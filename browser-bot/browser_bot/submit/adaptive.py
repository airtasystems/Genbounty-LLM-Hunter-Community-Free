"""Adaptive submission: zero-shot seed + runtime LLM follow-ups (UI and API)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from browser_bot.config import EVASION_REQUEST_DELAY_S, get_suite_test_cases
from browser_bot.live_preview import capture_preview_screenshot, live_preview_context
from browser_bot.page_blockers import (
    PageBlockedError,
    check_login_wall_before_submit,
    check_rate_limit_before_submit,
    ensure_page_ready_for_submit,
)
from browser_bot.sites import (
    browser_ui_session_ready,
    get_browser_storage_state_path,
    get_submission_config,
)

from browser_bot.submit.common import (
    NonSuccessResponseError,
    SubmissionProgressTracker,
    _do_one_submit_step,
    _write_adaptive_run_log,
    append_test_prompt_delimiter,
    fetcher_with_page_kwargs,
    inputs_for_submission,
    load_run_stop_words,
    log_evasion,
    log_resilience,
    response_capture_kwargs,
    response_stop_word_match,
    run_ui_submit_with_strategy_fallback,
    run_with_evasion_retry,
    ui_fetchers_to_try,
)
from browser_bot.submit.api_helpers import do_api_request, uses_messages_context
from browser_bot.run_control import (
    SkipCurrentPromptError,
    clear_skip_request,
    log_skip_current_applied,
    sleep_or_skip,
)
from browser_bot.submit.rejection_detection import (
    OUTCOME_CLIENT_REJECTED,
    OUTCOME_SKIPPED,
    apply_submission_outcome,
)

if TYPE_CHECKING:
    from playwright.async_api import Page

    from browser_bot.fetchers.ui_bundle import UIFetcherBundle


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _record_adaptive_turns(
    tracker: SubmissionProgressTracker,
    turns: list[dict[str, Any]] | None,
) -> None:
    """Advance progress one row per adaptive turn for the live results table."""
    rows = list(turns or [])
    if not rows:
        tracker.record_completed(1, input_text="", response=None)
        return
    for turn in rows:
        if not isinstance(turn, dict):
            tracker.record_completed(1)
            continue
        tracker.record_completed(
            1,
            input_text=str(turn.get("input") or ""),
            response=turn.get("response"),
            submission_outcome=str(turn.get("submission_outcome") or ""),
            rejection_signals=list(turn.get("rejection_signals") or []),
        )


def _load_adaptive_context(suite_path) -> tuple[int, int, dict | None]:
    import sys

    root = _project_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from pipeline.adaptive_attacker import load_adaptive_suite_config, load_playbook_for_suite

    max_turns, max_llm = load_adaptive_suite_config(suite_path)
    playbook = load_playbook_for_suite(suite_path)
    return max_turns, max_llm, playbook


def _generate_followup_sync(
    *,
    playbook: dict | None,
    test_case: dict,
    turns: list[dict[str, Any]],
    turns_remaining: int,
    llm_calls_remaining: int,
) -> dict[str, Any] | None:
    import sys

    root = _project_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from pipeline.adaptive_attacker import generate_validated_followup

    return generate_validated_followup(
        playbook=playbook,
        test_case=test_case,
        turns=turns,
        turns_remaining=turns_remaining,
        llm_calls_remaining=llm_calls_remaining,
    )


async def _generate_followup(**kwargs) -> dict[str, Any] | None:
    return await asyncio.to_thread(_generate_followup_sync, **kwargs)


async def _run_adaptive_conversation_ui(
    page: "Page",
    *,
    site: str,
    component: str,
    start_url: str,
    inputs: list[dict],
    submit_selector: str,
    seed_prompt: str,
    test_case: dict,
    playbook: dict | None,
    max_turns: int,
    max_llm_calls: int,
    stop_words: list[str],
    page_kwargs: dict,
    human_behavior: bool,
) -> list[dict[str, Any]]:
    await page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
    # DCL is enough; waiting for "load" stalls SPAs that keep network activity.
    await asyncio.sleep(0.15)
    await capture_preview_screenshot(page)

    active_inputs = inputs_for_submission(
        inputs, test_case=test_case, suite_path=page_kwargs.get("suite_path")
    )
    await ensure_page_ready_for_submit(
        page,
        site=site,
        component=component,
        inputs=active_inputs,
        submit_selector=submit_selector,
        start_url=start_url,
        blockers=page_kwargs.get("blockers"),
    )

    turns: list[dict[str, Any]] = []
    user_input = seed_prompt
    prompt = append_test_prompt_delimiter(seed_prompt)
    baseline = ""
    llm_calls_made = 0
    stopped_early = False
    stop_word_matched = ""

    for turn_idx in range(max_turns):
        await check_login_wall_before_submit(
            page, site=site, component=component, start_url=start_url
        )
        await check_rate_limit_before_submit(
            page, site=site, component=component, blockers=page_kwargs.get("blockers")
        )

        try:
            text_out, response_out, full_content, submission_meta = await _do_one_submit_step(
                page,
                active_inputs,
                submit_selector,
                prompt,
                response_selector=page_kwargs.get("response_selector", ""),
                response_within_selector=page_kwargs.get("response_within_selector", ""),
                response_text_within_selector=page_kwargs.get("response_text_within_selector", ""),
                response_capture_mode=page_kwargs.get("response_capture_mode", "last"),
                response_list_selector=page_kwargs.get("response_list_selector", ""),
                response_role_selector=page_kwargs.get("response_role_selector", ""),
                submit_via=page_kwargs.get("submit_via", "click"),
                response_wait_ms=int(page_kwargs.get("response_wait_ms", 5000) or 5000),
                baseline_text=baseline if turn_idx > 0 else None,
                human_behavior=human_behavior,
                test_case=test_case,
                suite_path=page_kwargs.get("suite_path"),
                submission=page_kwargs.get("submission"),
                site=site,
                component=component,
                capture_id=str(test_case.get("id") or f"adaptive-turn-{turn_idx + 1}"),
            )
        except SkipCurrentPromptError:
            clear_skip_request()
            log_skip_current_applied()
            turns.append(
                {
                    "turn": turn_idx,
                    "input": user_input,
                    "response": None,
                    "generated": turn_idx > 0,
                    "skipped": True,
                    "submission_outcome": OUTCOME_SKIPPED,
                }
            )
            break
        from pipeline.response_echo import strip_echoed_prompt_from_response

        clean_response = strip_echoed_prompt_from_response(response_out, user_input)
        turn_row: dict[str, Any] = {
            "turn": turn_idx,
            "input": user_input,
            "response": clean_response,
            "generated": turn_idx > 0,
        }
        if submission_meta:
            from browser_bot.submit.common import _compact_submission_meta

            turn_row.update(_compact_submission_meta(submission_meta))
        if turn_idx > 0 and test_case.get("_last_followup_meta"):
            turn_row.update(test_case.pop("_last_followup_meta"))
        turns.append(turn_row)
        if submission_meta and submission_meta.get("submission_outcome") == OUTCOME_CLIENT_REJECTED:
            log_resilience(
                "client_rejected",
                "Adaptive conversation stopped after client-side prompt rejection",
            )
            break
        baseline = full_content or baseline

        matched = response_stop_word_match(clean_response, stop_words)
        if matched:
            stop_word_matched = matched
            stopped_early = True
            log_resilience(
                "success_markers",
                f"Success marker '{matched}' found - ending adaptive conversation",
            )
            break

        if turn_idx >= max_turns - 1:
            break
        if llm_calls_made >= max_llm_calls:
            break

        turns_remaining = max_turns - turn_idx - 1
        llm_budget = max_llm_calls - llm_calls_made
        log_resilience(
            "adaptive_llm",
            f"Generating follow-up {llm_calls_made + 1}/{max_llm_calls} "
            f"(turn {turn_idx + 2}/{max_turns})",
        )
        followup = await _generate_followup(
            playbook=playbook,
            test_case=test_case,
            turns=turns,
            turns_remaining=turns_remaining,
            llm_calls_remaining=llm_budget,
        )
        llm_calls_made += 1
        if not followup or not followup.get("next_prompt"):
            log_resilience("adaptive_llm", "No follow-up generated - stopping conversation")
            break

        test_case["_last_followup_meta"] = {
            "attacker_reasoning": followup.get("attacker_reasoning", ""),
            "judge_reasoning": followup.get("judge_reasoning", ""),
        }
        user_input = str(followup["next_prompt"])
        prompt = append_test_prompt_delimiter(user_input)

    if stop_word_matched:
        test_case["_stop_word_matched"] = stop_word_matched
    if stopped_early:
        test_case["_stopped_early"] = True
    return turns


async def _run_adaptive_conversation_api(
    sub: dict,
    *,
    site: str,
    component: str,
    seed_prompt: str,
    test_case: dict,
    playbook: dict | None,
    max_turns: int,
    max_llm_calls: int,
    stop_words: list[str],
    suite_path,
) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    history: list[tuple[str, str | None]] = []
    accumulate = uses_messages_context(sub)
    user_prompt = seed_prompt
    llm_calls_made = 0

    for turn_idx in range(max_turns):
        if turn_idx > 0:
            await asyncio.sleep(EVASION_REQUEST_DELAY_S)

        prompt = append_test_prompt_delimiter(user_prompt)
        status, response_text, err, submission_meta = await asyncio.to_thread(
            do_api_request,
            sub,
            prompt,
            site=site,
            component=component,
            test_case=test_case,
            suite_path=suite_path,
            conversation_history=list(history) if accumulate else None,
        )
        if err and not response_text:
            print(f"  [adaptive/api] turn {turn_idx + 1} failed ({status}): {err}", flush=True)

        from pipeline.response_echo import strip_echoed_prompt_from_response

        clean_response = strip_echoed_prompt_from_response(response_text, user_prompt)
        turn_row: dict[str, Any] = {
            "turn": turn_idx,
            "input": user_prompt,
            "response": clean_response,
            "generated": turn_idx > 0,
        }
        if turn_idx > 0 and test_case.get("_last_followup_meta"):
            turn_row.update(test_case.pop("_last_followup_meta"))
        if submission_meta:
            from browser_bot.submit.common import _compact_submission_meta

            turn_row.update(_compact_submission_meta(submission_meta))
        turns.append(turn_row)

        if accumulate:
            history.append((prompt, clean_response or ""))

        matched = response_stop_word_match(clean_response, stop_words)
        if matched:
            test_case["_stop_word_matched"] = matched
            test_case["_stopped_early"] = True
            break

        if turn_idx >= max_turns - 1:
            break
        if llm_calls_made >= max_llm_calls:
            break

        followup = await _generate_followup(
            playbook=playbook,
            test_case=test_case,
            turns=turns,
            turns_remaining=max_turns - turn_idx - 1,
            llm_calls_remaining=max_llm_calls - llm_calls_made,
        )
        llm_calls_made += 1
        if not followup or not followup.get("next_prompt"):
            break
        test_case["_last_followup_meta"] = {
            "attacker_reasoning": followup.get("attacker_reasoning", ""),
            "judge_reasoning": followup.get("judge_reasoning", ""),
        }
        user_prompt = str(followup["next_prompt"])

    return turns


async def run_adaptive_submission(
    site: str,
    component: str,
    *,
    fetcher_bundle: "UIFetcherBundle | None" = None,
    pool_fetcher=None,
    cluster_fetcher=None,
    human_fetcher=None,
    suite_path=None,
) -> tuple[list[dict[str, Any]], Path | None]:
    """Run adaptive tests: one conversation batch per seed test case."""
    sub = get_submission_config(site, component)
    if not sub:
        return [], None

    test_cases = get_suite_test_cases(suite_path) if suite_path else []
    if not test_cases:
        return [], None

    max_turns, max_llm_calls, playbook = _load_adaptive_context(suite_path)
    stop_words = load_run_stop_words(suite_path)
    transport = (sub.get("transport") or "ui").lower()

    tracker = SubmissionProgressTracker("adaptive", len(test_cases) * max_turns)
    tracker.emit_run_start()

    batches: list[dict[str, Any]] = []
    global_stop = ""
    global_stopped = False

    if transport in ("api", "api_document", "api_multipart"):
        for i, tc in enumerate(test_cases):
            if i > 0:
                log_evasion(
                    "sequential_burst_pause",
                    sleep_s=EVASION_REQUEST_DELAY_S,
                    detail="Pause between adaptive API cases",
                )
                await asyncio.sleep(EVASION_REQUEST_DELAY_S)
            tc_copy = dict(tc)
            turns = await _run_adaptive_conversation_api(
                sub,
                site=site,
                component=component,
                seed_prompt=tc["prompt"],
                test_case=tc_copy,
                playbook=playbook,
                max_turns=max_turns,
                max_llm_calls=max_llm_calls,
                stop_words=stop_words,
                suite_path=suite_path,
            )
            _record_adaptive_turns(tracker, turns)
            batch_row = {
                "id": tc.get("id", ""),
                "description": tc.get("description", ""),
                "category": tc.get("category", ""),
                "vector_type": tc.get("vector_type", "text_direct"),
                "turn_count": len(turns),
                "turns": turns,
            }
            if tc.get("category_id"):
                batch_row["category_id"] = tc["category_id"]
            for key in (
                "bounty_slot",
                "mutate_of",
                "mechanism_family",
                "enhance_phase",
                "broadened_ask",
            ):
                if tc.get(key) is not None and str(tc.get(key) or "").strip():
                    batch_row[key] = tc[key]
            if tc_copy.get("_stopped_early"):
                batch_row["stopped_early"] = True
                global_stopped = True
            if tc_copy.get("_stop_word_matched"):
                batch_row["stop_word_matched"] = tc_copy["_stop_word_matched"]
                global_stop = tc_copy["_stop_word_matched"]
            batches.append(batch_row)
            if tc_copy.get("_stopped_early"):
                break
    else:
        start_url = sub["start_url"]
        inputs = sub["inputs"]
        submit_selector = sub["submit_selector"]
        blockers = sub.get("blockers") if isinstance(sub.get("blockers"), list) else None
        capture = response_capture_kwargs(sub)
        if not browser_ui_session_ready(site, component):
            return [], None
        storage_path = get_browser_storage_state_path(site, component)
        storage_str = str(storage_path) if storage_path else None

        if fetcher_bundle and fetcher_bundle.strategies:
            strategies = fetcher_bundle.strategies
        else:
            legacy = ui_fetchers_to_try(
                site,
                component,
                pool_fetcher=pool_fetcher,
                cluster_fetcher=cluster_fetcher,
                human_fetcher=human_fetcher,
            )
            tier_labels = iter(("pool", "cluster", "human"))
            strategies = [(f, hb, next(tier_labels, "fetcher")) for f, hb in legacy]

        page_kw = fetcher_with_page_kwargs(site, component, start_url=start_url)

        page_kwargs = dict(
            site=site,
            component=component,
            blockers=blockers,
            response_selector=sub.get("response_selector") or "",
            response_within_selector=sub.get("response_within_selector") or "",
            response_text_within_selector=sub.get("response_text_within_selector") or "",
            response_capture_mode=capture["response_capture_mode"],
            response_list_selector=capture["response_list_selector"],
            response_role_selector=capture["response_role_selector"],
            submit_via=sub.get("submit_via", "click"),
            response_wait_ms=int(sub.get("response_wait_ms", 5000) or 5000),
            suite_path=suite_path,
            submission=sub,
        )

        for i, tc in enumerate(test_cases):
            clear_skip_request()
            if i > 0:
                log_evasion(
                    "sequential_burst_pause",
                    sleep_s=EVASION_REQUEST_DELAY_S,
                    detail="Pause between adaptive UI cases",
                )
                await sleep_or_skip(EVASION_REQUEST_DELAY_S)

            tc_copy = dict(tc)

            async def _run_once(fetcher, human_behavior, tier, *, case=tc_copy):
                async def _cb(page, hb=human_behavior, c=case):
                    async with live_preview_context(page):
                        await asyncio.sleep(0.1 + time.perf_counter() % 0.15)
                        return await _run_adaptive_conversation_ui(
                            page,
                            site=site,
                            component=component,
                            start_url=start_url,
                            inputs=inputs,
                            submit_selector=submit_selector,
                            seed_prompt=c["prompt"],
                            test_case=c,
                            playbook=playbook,
                            max_turns=max_turns,
                            max_llm_calls=max_llm_calls,
                            stop_words=stop_words,
                            page_kwargs=page_kwargs,
                            human_behavior=hb,
                        )

                try:
                    return await run_with_evasion_retry(
                        lambda f=_cb, fet=fetcher: fet.with_page(
                            f, storage_path=storage_str, **page_kw
                        )
                    )
                except PageBlockedError:
                    raise
                except NonSuccessResponseError:
                    return None
                except SkipCurrentPromptError:
                    raise

            try:
                turns = await run_ui_submit_with_strategy_fallback(
                    strategies,
                    _run_once,
                    is_success=lambda r: r is not None and len(r) > 0,
                )
            except PageBlockedError:
                raise
            except SkipCurrentPromptError:
                clear_skip_request()
                log_skip_current_applied()
                turns = [
                    {
                        "turn": 0,
                        "input": tc_copy.get("prompt", ""),
                        "response": None,
                        "generated": False,
                        "skipped": True,
                        "submission_outcome": OUTCOME_SKIPPED,
                    }
                ]

            if turns is None:
                turns = []

            _record_adaptive_turns(tracker, turns)
            batch_row = {
                "id": tc.get("id", ""),
                "description": tc.get("description", ""),
                "category": tc.get("category", ""),
                "vector_type": tc.get("vector_type", "text_direct"),
                "turn_count": len(turns),
                "turns": turns,
            }
            if tc.get("category_id"):
                batch_row["category_id"] = tc["category_id"]
            for key in (
                "bounty_slot",
                "mutate_of",
                "mechanism_family",
                "enhance_phase",
                "broadened_ask",
            ):
                if tc.get(key) is not None and str(tc.get(key) or "").strip():
                    batch_row[key] = tc[key]
            if tc_copy.get("_stopped_early"):
                batch_row["stopped_early"] = True
                global_stopped = True
            if tc_copy.get("_stop_word_matched"):
                batch_row["stop_word_matched"] = tc_copy["_stop_word_matched"]
                global_stop = tc_copy["_stop_word_matched"]
            batches.append(batch_row)
            if tc_copy.get("_stopped_early"):
                break

    tracker.emit_run_done()
    log_path = (
        _write_adaptive_run_log(
            site,
            component,
            batches,
            suite_path=suite_path,
            stopped_early=global_stopped,
            stop_word_matched=global_stop,
        )
        if batches
        else None
    )
    return batches, log_path
