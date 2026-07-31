"""Detect client-side prompt rejection (e.g. Gemini restores prompt without executing)."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any

OUTCOME_EXECUTED = "executed"
OUTCOME_CLIENT_REJECTED = "client_rejected"
OUTCOME_TIMEOUT = "timeout"
OUTCOME_SUBMIT_FAILED = "submit_failed"
OUTCOME_SKIPPED = "skipped"


@dataclass
class RejectionDetectionConfig:
    enabled: bool = True
    fast_fail_ms: int = 4000
    poll_interval_ms: int = 300
    prompt_input_selector: str = ""
    min_prompt_match_ratio: float = 0.85
    confirm_polls: int = 3


def load_rejection_detection_config(submission: dict | None) -> RejectionDetectionConfig:
    """Parse ``submission.rejection_detection`` with sensible defaults.

    Honored keys: ``enabled``, ``fast_fail_ms``, ``poll_interval_ms``,
    ``prompt_input_selector``, ``min_prompt_match_ratio``, ``confirm_polls``.

    Legacy keys ``llm_execution_url_patterns`` / ``llm_url_patterns`` are ignored.
    """
    if not submission or not isinstance(submission, dict):
        return RejectionDetectionConfig()
    raw = submission.get("rejection_detection")
    if raw is False:
        return RejectionDetectionConfig(enabled=False)
    if not isinstance(raw, dict):
        return RejectionDetectionConfig()
    enabled = raw.get("enabled", True)
    if enabled is False:
        return RejectionDetectionConfig(enabled=False)
    return RejectionDetectionConfig(
        enabled=True,
        fast_fail_ms=max(500, int(raw.get("fast_fail_ms", 4000) or 4000)),
        poll_interval_ms=max(100, int(raw.get("poll_interval_ms", 300) or 300)),
        prompt_input_selector=str(raw.get("prompt_input_selector") or "").strip(),
        min_prompt_match_ratio=min(
            1.0,
            max(0.5, float(raw.get("min_prompt_match_ratio", 0.85) or 0.85)),
        ),
        confirm_polls=max(1, int(raw.get("confirm_polls", 3) or 3)),
    )


def normalize_prompt_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def prompt_match_ratio(submitted: str, current: str) -> float:
    """How closely *current* composer text matches the submitted prompt (0–1)."""
    a = normalize_prompt_text(submitted)
    b = normalize_prompt_text(current)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b:
        return len(a) / max(len(b), 1)
    if b in a:
        return len(b) / max(len(a), 1)
    try:
        from difflib import SequenceMatcher

        return SequenceMatcher(None, a, b).ratio()
    except Exception:
        return 0.0


def apply_submission_outcome(
    evidence: dict[str, Any],
    outcome: str,
    *,
    signals: list[str] | None = None,
) -> dict[str, Any]:
    out = dict(evidence or {})
    out["submission_outcome"] = outcome
    if signals:
        out["rejection_signals"] = list(signals)
    return out


def submission_outcome_label(outcome: str) -> str:
    labels = {
        OUTCOME_CLIENT_REJECTED: "Client rejected (prompt restored)",
        OUTCOME_TIMEOUT: "No response (timeout)",
        OUTCOME_SUBMIT_FAILED: "Submit failed",
        OUTCOME_SKIPPED: "Skipped by operator",
        OUTCOME_EXECUTED: "Executed",
    }
    return labels.get(outcome, outcome.replace("_", " ").title())


async def _read_prompt_field(
    page,
    inputs: list[dict],
    config: RejectionDetectionConfig,
) -> str:
    from browser_bot.submit.common import _first_visible_locator, _read_text_control

    if config.prompt_input_selector:
        try:
            loc = await _first_visible_locator(page, config.prompt_input_selector)
            return await _read_text_control(loc, "contenteditable")
        except Exception:
            pass
    for inp in inputs or []:
        if not isinstance(inp, dict):
            continue
        inp_type = (inp.get("type") or "text").lower()
        if inp_type not in ("text", "textarea", "contenteditable", "password", "email", "search"):
            continue
        sel = str(inp.get("selector") or "").strip()
        if not sel:
            continue
        try:
            loc = await _first_visible_locator(page, sel, prefer_enabled=True)
            return await _read_text_control(loc, inp_type)
        except Exception:
            continue
    return ""


async def _has_response_activity(
    page,
    *,
    response_selector: str,
    response_within_selector: str,
    response_text_within_selector: str,
    response_capture_mode: str,
    response_list_selector: str,
    response_role_selector: str,
    previous_response_text: str | None,
    previous_node_count: int | None,
    filter_ctx,
) -> bool:
    if not (response_selector or "").strip():
        return False
    from browser_bot.submit.common import (
        _response_capture_is_meaningful,
        _response_delta,
        _response_selector_text,
        _response_selector_visible_count,
        is_actionable_response,
    )

    try:
        current = await _response_selector_text(
            page,
            response_selector,
            within_selector=response_within_selector,
            text_within_selector=response_text_within_selector,
            capture_mode=response_capture_mode,
            list_selector=response_list_selector,
            role_selector=response_role_selector,
        )
    except Exception:
        current = ""
    try:
        current_count = await _response_selector_visible_count(
            page,
            response_selector,
            within_selector=response_within_selector,
            capture_mode=response_capture_mode,
            list_selector=response_list_selector,
            role_selector=response_role_selector,
        )
    except Exception:
        current_count = 0

    base = previous_response_text if previous_response_text is not None else ""
    count_increased = (
        previous_node_count is not None and current_count > previous_node_count
    )
    new_slice = _response_delta(base, current)
    if count_increased:
        return True
    if _response_capture_is_meaningful(
        new_slice=new_slice,
        current=current,
        base=base,
        count_increased=False,
        filter_ctx=filter_ctx,
        exclude_norm="",
        reject_last_mode_echo=False,
        post_submit_activity=True,
    ):
        return True
    if is_actionable_response(current, filter_ctx) and current.strip() != base.strip():
        return True
    return False


async def evaluate_client_rejection(
    page,
    *,
    submitted_text: str,
    inputs: list[dict],
    config: RejectionDetectionConfig,
    response_selector: str,
    response_within_selector: str,
    response_text_within_selector: str,
    response_capture_mode: str,
    response_list_selector: str,
    response_role_selector: str,
    previous_response_text: str | None,
    previous_node_count: int | None,
    filter_ctx,
) -> tuple[bool, list[str]]:
    """Return (is_rejected, signals). DOM/composer-only."""
    signals: list[str] = []
    current_prompt = await _read_prompt_field(page, inputs, config)
    ratio = prompt_match_ratio(submitted_text, current_prompt)
    if ratio < config.min_prompt_match_ratio:
        return False, signals
    signals.append("prompt_restored")

    if await _has_response_activity(
        page,
        response_selector=response_selector,
        response_within_selector=response_within_selector,
        response_text_within_selector=response_text_within_selector,
        response_capture_mode=response_capture_mode,
        response_list_selector=response_list_selector,
        response_role_selector=response_role_selector,
        previous_response_text=previous_response_text,
        previous_node_count=previous_node_count,
        filter_ctx=filter_ctx,
    ):
        return False, []

    signals.append("no_response_activity")
    return True, signals


async def poll_client_rejection(
    page,
    *,
    submitted_text: str,
    inputs: list[dict],
    config: RejectionDetectionConfig,
    response_selector: str,
    response_within_selector: str,
    response_text_within_selector: str,
    response_capture_mode: str,
    response_list_selector: str,
    response_role_selector: str,
    previous_response_text: str | None,
    previous_node_count: int | None,
    filter_ctx,
) -> tuple[bool, list[str]]:
    """Poll briefly after submit for client-side rejection (fast-fail).

    Requires ``config.confirm_polls`` consecutive rejected evaluations before
    returning rejected, to reduce false positives while a response is still
    appearing in the DOM.

    Also requires observing the prompt field clear (or diverge) at least once
    before a match counts as "restored". Payload editors that keep the attack
    text after submit (challenge score / status chrome) are not treated as
    client-side rejection.
    """
    from browser_bot.run_control import raise_if_skip_requested

    deadline = time.perf_counter() + config.fast_fail_ms / 1000.0
    poll_s = config.poll_interval_ms / 1000.0
    streak = 0
    last_signals: list[str] = []
    saw_prompt_cleared = False
    while time.perf_counter() < deadline:
        await raise_if_skip_requested()
        current_prompt = await _read_prompt_field(page, inputs, config)
        ratio = prompt_match_ratio(submitted_text, current_prompt)
        if ratio < config.min_prompt_match_ratio:
            saw_prompt_cleared = True
            streak = 0
            last_signals = []
            await asyncio.sleep(poll_s)
            continue
        if not saw_prompt_cleared:
            # Sticky composer/payload field - not a restore. Exit early once a
            # reply appears; otherwise keep waiting until the fast-fail window ends.
            if await _has_response_activity(
                page,
                response_selector=response_selector,
                response_within_selector=response_within_selector,
                response_text_within_selector=response_text_within_selector,
                response_capture_mode=response_capture_mode,
                response_list_selector=response_list_selector,
                response_role_selector=response_role_selector,
                previous_response_text=previous_response_text,
                previous_node_count=previous_node_count,
                filter_ctx=filter_ctx,
            ):
                return False, []
            await asyncio.sleep(poll_s)
            continue

        rejected, signals = await evaluate_client_rejection(
            page,
            submitted_text=submitted_text,
            inputs=inputs,
            config=config,
            response_selector=response_selector,
            response_within_selector=response_within_selector,
            response_text_within_selector=response_text_within_selector,
            response_capture_mode=response_capture_mode,
            response_list_selector=response_list_selector,
            response_role_selector=response_role_selector,
            previous_response_text=previous_response_text,
            previous_node_count=previous_node_count,
            filter_ctx=filter_ctx,
        )
        if rejected:
            streak += 1
            last_signals = signals
            if streak >= config.confirm_polls:
                return True, last_signals
        else:
            streak = 0
            last_signals = []
            if not signals:
                return False, []
        await asyncio.sleep(poll_s)
    return False, []
