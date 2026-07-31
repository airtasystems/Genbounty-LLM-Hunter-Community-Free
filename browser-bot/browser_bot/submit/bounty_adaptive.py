"""Bug Bounty hybrid: DNA-locked adaptive follow-ups on mutate/elite single-turn seeds.

Does not flip suite strategy to ``adaptive``. Full adaptive suites skip this path.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _ensure_root_on_path() -> None:
    root = _project_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def is_full_adaptive_suite(suite_path) -> bool:
    try:
        from browser_bot.submit import is_adaptive_suite

        return bool(is_adaptive_suite(suite_path))
    except Exception:
        return False


def bounty_hybrid_should_attempt(suite_path, test_case: dict | None) -> bool:
    """Gate: bounty hunt + eligible seed + not already full adaptive suite."""
    if is_full_adaptive_suite(suite_path):
        return False
    _ensure_root_on_path()
    try:
        from pipeline.adaptive_attacker import (
            bounty_adaptive_followups_enabled,
            seed_eligible_for_bounty_adaptive,
        )
    except Exception:
        return False
    if not bounty_adaptive_followups_enabled():
        return False
    return seed_eligible_for_bounty_adaptive(test_case)


def bounty_hybrid_should_continue_after_first(
    response: str | None,
    meta: dict | None,
    *,
    stop_words: list[str] | None = None,
) -> bool:
    """Continue only on refuse/partial; never after success markers."""
    from browser_bot.submit.common import response_stop_word_match

    if response_stop_word_match(response, stop_words or []):
        return False
    _ensure_root_on_path()
    try:
        from pipeline.adaptive_attacker import response_signals_refusal_or_partial
    except Exception:
        return False
    return response_signals_refusal_or_partial(response or "", meta)


def _load_playbook(suite_path) -> dict | None:
    _ensure_root_on_path()
    from pipeline.adaptive_attacker import load_playbook_for_suite

    return load_playbook_for_suite(suite_path)


def _limits(suite_path) -> tuple[int, int]:
    _ensure_root_on_path()
    from pipeline.adaptive_attacker import load_bounty_adaptive_limits

    return load_bounty_adaptive_limits(suite_path)


def _generate_followup_sync(
    *,
    playbook: dict | None,
    test_case: dict,
    turns: list[dict[str, Any]],
    turns_remaining: int,
    llm_calls_remaining: int,
) -> dict[str, Any] | None:
    _ensure_root_on_path()
    from pipeline.adaptive_attacker import generate_validated_followup

    return generate_validated_followup(
        playbook=playbook,
        test_case=test_case,
        turns=turns,
        turns_remaining=turns_remaining,
        llm_calls_remaining=llm_calls_remaining,
    )


async def run_bounty_hybrid_followups_api(
    *,
    sub: dict,
    site: str,
    component: str,
    seed_prompt: str,
    first_response: str | None,
    first_meta: dict | None,
    test_case: dict,
    suite_path,
    stop_words: list[str] | None = None,
) -> tuple[str, str | None, dict]:
    """After first API turn: optional DNA-locked follow-ups. Returns final (prompt, response, meta).

    Fail-safe: any error keeps the first-turn result.
    """
    from browser_bot.config import EVASION_REQUEST_DELAY_S
    from browser_bot.submit.api_helpers import do_api_request, uses_messages_context
    from browser_bot.submit.common import (
        append_test_prompt_delimiter,
        log_resilience,
        response_stop_word_match,
    )
    from browser_bot.run_control import sleep_or_skip

    final_prompt = seed_prompt
    final_response = first_response
    final_meta = dict(first_meta or {})
    if not bounty_hybrid_should_continue_after_first(
        first_response, first_meta, stop_words=stop_words
    ):
        return final_prompt, final_response, final_meta

    try:
        max_fu, max_llm = _limits(suite_path)
        playbook = _load_playbook(suite_path)
        turns: list[dict[str, Any]] = [
            {
                "turn": 0,
                "input": seed_prompt,
                "response": first_response,
                "generated": False,
            }
        ]
        history: list[tuple[str, str | None]] = []
        accumulate = uses_messages_context(sub)
        if accumulate:
            history.append(
                (append_test_prompt_delimiter(seed_prompt), first_response or "")
            )
        llm_calls = 0
        for fu_i in range(max_fu):
            if llm_calls >= max_llm:
                break
            turns_remaining = max_fu - fu_i
            llm_budget = max_llm - llm_calls
            log_resilience(
                "bounty_adaptive",
                f"Generating DNA-locked follow-up {llm_calls + 1}/{max_llm}",
            )
            followup = await asyncio.to_thread(
                _generate_followup_sync,
                playbook=playbook,
                test_case=test_case,
                turns=turns,
                turns_remaining=turns_remaining,
                llm_calls_remaining=llm_budget,
            )
            llm_calls += 1
            if not followup or not followup.get("next_prompt"):
                break
            user_prompt = str(followup["next_prompt"])
            await sleep_or_skip(EVASION_REQUEST_DELAY_S)
            prompt = append_test_prompt_delimiter(user_prompt)
            _status, response_text, _err, submission_meta = await asyncio.to_thread(
                do_api_request,
                sub,
                prompt,
                site=site,
                component=component,
                test_case=test_case,
                suite_path=suite_path,
                conversation_history=list(history) if accumulate else None,
            )
            from pipeline.response_echo import strip_echoed_prompt_from_response

            clean = strip_echoed_prompt_from_response(response_text, user_prompt)
            turns.append(
                {
                    "turn": len(turns),
                    "input": user_prompt,
                    "response": clean,
                    "generated": True,
                    "attacker_reasoning": followup.get("attacker_reasoning", ""),
                    "judge_reasoning": followup.get("judge_reasoning", ""),
                }
            )
            if accumulate:
                history.append((prompt, clean or ""))
            final_prompt = user_prompt
            final_response = clean
            final_meta = dict(submission_meta or {})
            final_meta["bounty_adaptive_followups"] = llm_calls
            if response_stop_word_match(clean, stop_words or []):
                break
    except Exception as exc:
        log_resilience(
            "bounty_adaptive",
            f"Hybrid follow-up skipped (fail-safe keep first turn): {exc}",
        )
        return seed_prompt, first_response, dict(first_meta or {})
    return final_prompt, final_response, final_meta


async def run_bounty_hybrid_followups_ui(
    *,
    page,
    site: str,
    component: str,
    start_url: str,
    inputs: list[dict],
    submit_selector: str,
    seed_prompt: str,
    first_response: str | None,
    first_full_content: str | None,
    first_meta: dict | None,
    test_case: dict,
    page_kwargs: dict,
    human_behavior: bool,
    stop_words: list[str] | None = None,
) -> tuple[str, str | None, dict]:
    """Same-page UI follow-ups after first turn. Fail-safe keeps first-turn result."""
    from browser_bot.page_blockers import (
        check_login_wall_before_submit,
        check_rate_limit_before_submit,
    )
    from browser_bot.submit.common import (
        _do_one_submit_step,
        append_test_prompt_delimiter,
        inputs_for_submission,
        log_resilience,
        response_stop_word_match,
    )

    final_prompt = seed_prompt
    final_response = first_response
    final_meta = dict(first_meta or {})
    if not bounty_hybrid_should_continue_after_first(
        first_response, first_meta, stop_words=stop_words
    ):
        return final_prompt, final_response, final_meta

    suite_path = page_kwargs.get("suite_path")
    try:
        max_fu, max_llm = _limits(suite_path)
        playbook = _load_playbook(suite_path)
        turns: list[dict[str, Any]] = [
            {
                "turn": 0,
                "input": seed_prompt,
                "response": first_response,
                "generated": False,
            }
        ]
        active_inputs = inputs_for_submission(
            inputs, test_case=test_case, suite_path=suite_path
        )
        baseline = first_full_content or ""
        llm_calls = 0
        for fu_i in range(max_fu):
            if llm_calls >= max_llm:
                break
            followup = await asyncio.to_thread(
                _generate_followup_sync,
                playbook=playbook,
                test_case=test_case,
                turns=turns,
                turns_remaining=max_fu - fu_i,
                llm_calls_remaining=max_llm - llm_calls,
            )
            llm_calls += 1
            if not followup or not followup.get("next_prompt"):
                break
            user_input = str(followup["next_prompt"])
            prompt = append_test_prompt_delimiter(user_input)
            await check_login_wall_before_submit(
                page, site=site, component=component, start_url=start_url
            )
            await check_rate_limit_before_submit(
                page, site=site, component=component, blockers=page_kwargs.get("blockers")
            )
            log_resilience(
                "bounty_adaptive",
                f"UI DNA-locked follow-up {llm_calls}/{max_llm}",
            )
            _text_out, response_out, full_content, submission_meta = await _do_one_submit_step(
                page,
                active_inputs,
                submit_selector,
                prompt,
                response_selector=page_kwargs.get("response_selector", ""),
                response_within_selector=page_kwargs.get("response_within_selector", ""),
                response_text_within_selector=page_kwargs.get(
                    "response_text_within_selector", ""
                ),
                response_capture_mode=page_kwargs.get("response_capture_mode", "last"),
                response_list_selector=page_kwargs.get("response_list_selector", ""),
                response_role_selector=page_kwargs.get("response_role_selector", ""),
                submit_via=page_kwargs.get("submit_via", "click"),
                response_wait_ms=int(page_kwargs.get("response_wait_ms", 5000) or 5000),
                baseline_text=baseline or None,
                human_behavior=human_behavior,
                test_case=test_case,
                suite_path=suite_path,
                submission=page_kwargs.get("submission"),
                site=site,
                component=component,
                capture_id=str(test_case.get("id") or f"bounty-adaptive-{llm_calls}"),
            )
            from pipeline.response_echo import strip_echoed_prompt_from_response

            clean = strip_echoed_prompt_from_response(response_out, user_input)
            turns.append(
                {
                    "turn": len(turns),
                    "input": user_input,
                    "response": clean,
                    "generated": True,
                }
            )
            baseline = full_content or baseline
            final_prompt = user_input
            final_response = clean
            final_meta = dict(submission_meta or {})
            final_meta["bounty_adaptive_followups"] = llm_calls
            if response_stop_word_match(clean, stop_words or []):
                break
    except Exception as exc:
        log_resilience(
            "bounty_adaptive",
            f"UI hybrid follow-up skipped (fail-safe): {exc}",
        )
        # Prefer last successful follow-up over first turn when the page already advanced.
        if llm_calls > 0 and final_response is not None:
            return final_prompt, final_response, final_meta
        return seed_prompt, first_response, dict(first_meta or {})
    return final_prompt, final_response, final_meta
