"""Shared helpers for UI submission (single and multi)."""

import asyncio
import json
import os
import random
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine

import tenacity

from browser_bot.config import EVASION_MAX_RETRIES, EVASION_RETRY_WAIT_S
from browser_bot.sites import ensure_component_dir, get_component_path
from browser_bot.submit.response_filters import (
    ResponseFilterContext,
    filter_context_from_submission,
    is_actionable_delta,
    is_actionable_response,
    is_empty_response_text as _is_empty_response_text,
    line_looks_like_skeleton_loader as _line_looks_like_skeleton_loader,
    log_response_filter_rejection,
    looks_like_skeleton_progress_line as _looks_like_skeleton_progress_line,
    looks_like_welcome_or_redacted_response as _looks_like_welcome_or_redacted_response,
    non_actionable_reason,
    normalize_dom_text,
    register_pre_submit_chrome,
    response_delta as _response_delta,
    sanitize_captured_response,
)

_fetcher_policy_logged = False


def reset_resilience_run_banners() -> None:
    """Reset one-shot resilience banners at the start of each UI submission run."""
    global _fetcher_policy_logged
    _fetcher_policy_logged = False


def _log_fetcher_strategy_once(strategies: list[tuple[Any, bool, str]]) -> None:
    """Log fetcher tier order once per run (not once per prompt)."""
    global _fetcher_policy_logged
    if _fetcher_policy_logged or not strategies:
        return
    _fetcher_policy_logged = True
    tiers = " → ".join(tier for _, _, tier in strategies)
    log_resilience(
        "fetcher_policy",
        f"UI submit via {tiers}",
        detail=(
            "First tier pre-warmed; additional tiers used only on cloudflare/captcha blocks "
            "(rate limits backoff then next prompt; empty captures are logged as-is)"
        ),
    )


def log_resilience(
    category: str,
    message: str,
    *,
    attempt: int | None = None,
    max_attempts: int | None = None,
    wait_sec: float | None = None,
    detail: str = "",
) -> None:
    """Emit a human-readable resilience attempt line for the web UI console."""
    parts = [message]
    if attempt is not None and max_attempts is not None:
        parts.append(f"(attempt {attempt}/{max_attempts})")
    elif attempt is not None:
        parts.append(f"(attempt {attempt})")
    if wait_sec is not None:
        parts.append(f"- waiting {wait_sec:.0f}s")
    if detail:
        parts.append(f"- {detail}")
    line = " ".join(parts)
    print(f"[resilience] {line}", flush=True)


def log_evasion(reason: str, *, sleep_s: float | None = None, detail: str = "") -> None:
    """Emit a line for web UI / logs when an evasion delay or retry is applied."""
    log_resilience(
        reason,
        detail or reason.replace("_", " "),
        wait_sec=sleep_s,
    )


def log_genbounty_progress(payload: dict) -> None:
    """Structured progress for the Genbounty Hunter web UI (parsed from job stream)."""
    print(f"[genbounty_progress] {json.dumps(payload, ensure_ascii=False)}", flush=True)


TEST_PROMPT_DELIMITER = "" # \n[TEXT ONLY. NO HTML OR MARKUP. MAX 600 CHARS]


def append_test_prompt_delimiter(text: str) -> str:
    """Append test delimiter if not already present."""
    if TEST_PROMPT_DELIMITER in text:
        return text
    return text + TEST_PROMPT_DELIMITER


class SubmissionProgressTracker:
    """Live ETA via throughput: elapsed/done * remaining."""

    def __init__(self, mode: str, total_prompts: int) -> None:
        self.mode = mode
        self.total = max(0, int(total_prompts))
        self.done = 0
        self._start = time.perf_counter()

    def emit_run_start(self) -> None:
        reset_resilience_run_banners()
        log_genbounty_progress(
            {
                "type": "run_start",
                "mode": self.mode,
                "total": self.total,
                "label": "UI submission",
            }
        )

    def record_completed(
        self,
        count: int = 1,
        *,
        input_text: str | None = None,
        response: str | None = None,
        submission_outcome: str = "",
        rejection_signals: list | None = None,
        label: str | None = None,
    ) -> None:
        """Advance progress; optionally emit a live probe_result for the Run table."""
        self.done = min(self.total, self.done + max(0, count))
        self._emit()
        if input_text is None and response is None and not label:
            return
        payload: dict[str, Any] = {
            "type": "probe_result",
            "mode": self.mode,
            "current": self.done,
            "total": self.total,
            "input": "" if input_text is None else str(input_text),
            "response": "" if response is None else str(response),
            "submission_outcome": str(submission_outcome or ""),
            "rejection_signals": list(rejection_signals or []),
        }
        if label:
            payload["label"] = str(label)
        log_genbounty_progress(payload)

    def _emit(self) -> None:
        elapsed = time.perf_counter() - self._start
        rem = max(0, self.total - self.done)
        eta_sec = None
        if self.done > 0 and rem > 0:
            eta_sec = (elapsed / self.done) * rem
        elif rem == 0:
            eta_sec = 0.0
        log_genbounty_progress(
            {
                "type": "progress",
                "mode": self.mode,
                "current": self.done,
                "total": self.total,
                "elapsed_sec": round(elapsed, 1),
                "eta_sec": round(eta_sec, 1) if eta_sec is not None else None,
            }
        )

    def emit_run_done(self) -> None:
        log_genbounty_progress(
            {
                "type": "run_done",
                "mode": self.mode,
                "total": self.total,
                "elapsed_sec": round(time.perf_counter() - self._start, 1),
            }
        )

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page

_TEXT_TYPES = {"text", "textarea", "contenteditable", "password", "email", "search"}
_PROMPT_TYPES = {"textarea", "contenteditable"}

# Set .value through the native prototype setter so React/Vue controlled fields update.
_SET_NATIVE_TEXT_VALUE_JS = """
(el, value) => {
  const tag = (el.tagName || '').toLowerCase();
  const proto = tag === 'textarea'
    ? window.HTMLTextAreaElement.prototype
    : tag === 'input'
      ? window.HTMLInputElement.prototype
      : null;
  if (proto) {
    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
    if (desc && desc.set) desc.set.call(el, value);
    else el.value = value;
  } else if ('value' in el) {
    el.value = value;
  }
  el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
}
"""

_CLEAR_NATIVE_TEXT_VALUE_JS = """
(el) => {
  const tag = (el.tagName || '').toLowerCase();
  const proto = tag === 'textarea'
    ? window.HTMLTextAreaElement.prototype
    : tag === 'input'
      ? window.HTMLInputElement.prototype
      : null;
  if (proto) {
    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
    if (desc && desc.set) desc.set.call(el, '');
    else el.value = '';
  } else if ('value' in el) {
    el.value = '';
  }
  el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'deleteContentBackward' }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
}
"""


def is_unstable_selector(selector: str, *, for_prompt: bool = True) -> bool:
    """True for selectors that are risky as prompt fields (not upload-prep clicks)."""
    sel = (selector or "").strip()
    if not sel:
        return True
    if ":nth-of-type(" in sel:
        return True
    if re.search(r"\.[\w-]+--[A-Za-z0-9_]{4,}\b", sel):
        return True
    if re.search(r"#radix-_R_", sel, re.I):
        return True
    if not for_prompt:
        return False
    return False


def submission_needs_file_payload(
    test_case: dict | None,
    *,
    suite_path: Path | str | None = None,
) -> bool:
    """True when the active test case resolves to a file artifact for upload."""
    if not test_case:
        return False
    try:
        from browser_bot.artifacts import resolve_test_artifact

        turns = test_case.get("turns")
        if isinstance(turns, list):
            for turn in turns:
                if not isinstance(turn, dict):
                    continue
                artifact_path, _vector_type, upload_ok = resolve_test_artifact(
                    turn, suite_path=suite_path
                )
                if bool(upload_ok and artifact_path and artifact_path.is_file()):
                    return True

        artifact_path, _vector_type, upload_ok = resolve_test_artifact(
            test_case, suite_path=suite_path
        )
        return bool(upload_ok and artifact_path and artifact_path.is_file())
    except Exception:
        return False


def inputs_for_submission(
    inputs: list[dict],
    *,
    test_case: dict | None = None,
    suite_path: Path | str | None = None,
) -> list[dict]:
    """
    Return the input steps that apply to this submission.

    Text-only runs skip file-upload prep clicks and hidden menu items so readiness
    checks and sample requests do not require controls that only exist after
    opening an upload menu. Surface pre-steps (``surface_prep: true``) always run -
    challenge level / Start / notice gates must replay on every reload.
    """
    if not inputs:
        return []

    needs_file = submission_needs_file_payload(test_case, suite_path=suite_path)
    if needs_file:
        return [inp for inp in inputs if isinstance(inp, dict)]

    surface_rows: list[dict] = []
    candidates: list[dict] = []
    for inp in inputs:
        if not isinstance(inp, dict):
            continue
        sel = str(inp.get("selector") or "")
        inp_type = (inp.get("type") or "text").lower()
        if inp.get("surface_prep"):
            surface_rows.append(inp)
            continue
        if inp.get("upload_prep"):
            continue
        if inp_type == "file" or inp.get("path_from") == "payload":
            continue
        if inp_type == "click":
            continue
        if is_unstable_selector(sel):
            continue
        candidates.append(inp)

    if not candidates:
        # Prefer surface gates + whatever remains rather than dropping gates.
        leftover = [
            inp
            for inp in inputs
            if isinstance(inp, dict)
            and (
                inp.get("surface_prep")
                or (
                    (inp.get("type") or "text").lower()
                    not in ("file", "click")
                    and not inp.get("upload_prep")
                    and inp.get("path_from") != "payload"
                )
            )
        ]
        return leftover or list(inputs)

    prompt_like = [
        inp
        for inp in candidates
        if (inp.get("type") or "text").lower() in _PROMPT_TYPES
    ]
    if len(prompt_like) == 1:
        return surface_rows + prompt_like
    if len(prompt_like) > 1:
        return surface_rows + [prompt_like[-1]]
    if len(candidates) == 1:
        return surface_rows + [candidates[0]]
    return surface_rows + [candidates[-1]]


def configured_prompt_selectors(
    site: str,
    component: str,
    *,
    test_case: dict | None = None,
    suite_path: Path | str | None = None,
) -> list[str]:
    """Prompt input selectors from component config (no hardcoded fallbacks)."""
    from browser_bot.sites import get_submission_config

    sub = get_submission_config(site, component)
    if not sub:
        return []
    selectors: list[str] = []
    seen: set[str] = set()
    for inp in inputs_for_submission(
        sub.get("inputs") or [],
        test_case=test_case,
        suite_path=suite_path,
    ):
        sel = str(inp.get("selector") or "").strip()
        if sel and sel not in seen:
            selectors.append(sel)
            seen.add(sel)
    return selectors


def fetcher_with_page_kwargs(site: str, component: str, *, start_url: str | None = None) -> dict:
    """Extra kwargs for Fetcher.with_page when settings require a visible browser."""
    out: dict = {"site": site, "component": component}
    if start_url:
        out["start_url"] = start_url
    try:
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent.parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from pipeline.component_settings import playwright_headless_kwarg

        resolved = playwright_headless_kwarg(site=site, component=component)
        if resolved is False:
            out["headless"] = False
    except Exception:
        pass
    return out


def effective_fetch_method(site: str, component: str) -> str:
    """Resolved FETCH_METHOD for a site/component."""
    try:
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent.parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from pipeline.component_settings import get_effective_settings

        return str(get_effective_settings(site=site, component=component).get("FETCH_METHOD") or "auto").lower()
    except Exception:
        from browser_bot.config import FETCH_METHOD

        return str(FETCH_METHOD or "auto").lower()


def ui_fetchers_to_try(
    site: str,
    component: str,
    *,
    pool_fetcher,
    cluster_fetcher,
    human_fetcher,
) -> list[tuple]:
    """Ordered UI fetchers for submission (pool/cluster/human per effective FETCH_METHOD)."""
    method = effective_fetch_method(site, component)
    fetchers: list[tuple] = []
    if method in ("auto", "pool") and pool_fetcher:
        fetchers.append((pool_fetcher, False))
    if method in ("auto", "cluster") and cluster_fetcher:
        fetchers.append((cluster_fetcher, False))
    if method in ("auto", "human") and human_fetcher:
        fetchers.append((human_fetcher, True))
    return fetchers


class NonSuccessResponseError(Exception):
    """Raised when a same-origin POST/PUT/PATCH request returns a non-2xx status."""

    def __init__(self, status: int, url: str = "") -> None:
        self.status = status
        self.url = url
        super().__init__(f"Non-2xx response: HTTP {status}" + (f" from {url}" if url else ""))


def parallel_fetcher_for_ui(method: str, pool_fetcher, cluster_fetcher):
    """When FETCH_METHOD is auto, prefer pool then cluster (same order as HTTP post_url)."""
    fetchers = parallel_fetchers_for_ui(method, pool_fetcher, cluster_fetcher)
    return fetchers[0] if fetchers else None


def parallel_fetchers_for_ui(method: str, pool_fetcher, cluster_fetcher) -> list:
    """Return eligible fast UI fetchers in retry order for parallel submission."""
    if pool_fetcher is None and cluster_fetcher is None:
        return []
    m = method.lower()
    if m == "pool" and pool_fetcher is not None:
        return [pool_fetcher]
    if m == "cluster" and cluster_fetcher is not None:
        return [cluster_fetcher]
    if m == "auto":
        fetchers = []
        if pool_fetcher is not None:
            fetchers.append(pool_fetcher)
        if cluster_fetcher is not None:
            fetchers.append(cluster_fetcher)
        return fetchers
    return []


def _first_parallel_tier_workers(
    strategies: list[tuple[Any, bool, str]],
    *,
    prompt_count: int,
    fetcher_bundle: Any | None = None,
) -> int:
    """Worker slots for the first pool/cluster tier in the strategy ladder."""
    for _, _, tier_key in strategies:
        base = str(tier_key or "").split("_")[0]
        if base == "pool":
            if fetcher_bundle is not None:
                return max(0, int(fetcher_bundle._pool_size or 0))
            from browser_bot.config import POOL_SIZE

            return min(max(1, int(POOL_SIZE or 1)), prompt_count)
        if base == "cluster":
            if fetcher_bundle is not None:
                return max(0, int(fetcher_bundle._cluster_workers or 0))
            from browser_bot.config import CONTEXT_COUNT, PAGES_PER_CONTEXT

            workers = max(1, int(CONTEXT_COUNT or 1)) * max(1, int(PAGES_PER_CONTEXT or 1))
            return min(workers, prompt_count)
    return 0


def resolve_ui_parallel_concurrency(
    *,
    site: str,
    component: str,
    strategies: list[tuple[Any, bool, str]],
    work_count: int,
    stop_words: list[str] | None = None,
    fetcher_bundle: Any | None = None,
) -> int:
    """How many UI prompts/batches may run concurrently on pool/cluster pages.

    ``stop_words`` is accepted for call-site compatibility but does not reduce
    concurrency — pool/cluster throughput takes priority; markers are still
    checked on completed responses.
    """
    _ = stop_words
    if work_count <= 1:
        return 1
    workers = _first_parallel_tier_workers(
        strategies,
        prompt_count=work_count,
        fetcher_bundle=fetcher_bundle,
    )
    if workers <= 1:
        return 1
    if fetcher_bundle is not None:
        if fetcher_bundle._use_cdp:
            return 1
        if fetcher_bundle._launch_headless is False:
            return 1
    else:
        try:
            import sys
            from pathlib import Path

            root = Path(__file__).resolve().parent.parent.parent.parent
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            from pipeline.component_settings import playwright_headless_kwarg

            if playwright_headless_kwarg(site=site, component=component) is False:
                return 1
        except Exception:
            pass
    return max(1, min(workers, work_count))


def normalize_ui_submit_result(
    result: Any,
    fallback_text: str,
) -> tuple[str, str | None, dict[str, Any]]:
    """Map strategy fallback output to (text, response, submission_meta)."""
    if result is None:
        return fallback_text, None, {}
    if len(result) >= 3:
        return result[0], result[1], result[2] if isinstance(result[2], dict) else {}
    return result[0], result[1], {}


def _before_sleep_evasion(retry_state: Any) -> None:
    exc = retry_state.outcome.exception()
    status = getattr(exc, "status", None) if exc else None
    attempt = retry_state.attempt_number
    log_resilience(
        "http_retry",
        f"HTTP error (status={status}) - retrying after backoff",
        attempt=attempt,
        max_attempts=EVASION_MAX_RETRIES,
        wait_sec=EVASION_RETRY_WAIT_S,
    )


async def run_with_evasion_retry(
    coro_fn: Callable[[], Coroutine[Any, Any, Any]],
) -> Any:
    """Run *coro_fn* (a zero-arg async callable) with tenacity retry on NonSuccessResponseError.

    On non-2xx: waits EVASION_RETRY_WAIT_S seconds then retries, up to EVASION_MAX_RETRIES times.
    If all retries are exhausted, returns None.
    """
    try:
        async for attempt in tenacity.AsyncRetrying(
            retry=tenacity.retry_if_exception_type(NonSuccessResponseError),
            wait=tenacity.wait_fixed(EVASION_RETRY_WAIT_S),
            stop=tenacity.stop_after_attempt(EVASION_MAX_RETRIES),
            reraise=False,
            before_sleep=_before_sleep_evasion,
        ):
            with attempt:
                return await coro_fn()
    except tenacity.RetryError:
        pass
    return None


# Block kinds where the next fetcher tier may succeed (e.g. headless pool → stealth → human).
# Rate limits are site-wide - switching pool/cluster/human does not help.
TIER_FALLTHROUGH_BLOCK_KINDS = frozenset({"cloudflare", "captcha"})

DEFAULT_STRATEGY_FALLBACK_BACKOFF_SEC = 10.0


def block_kind_should_fallthrough(kind: str) -> bool:
    return kind in TIER_FALLTHROUGH_BLOCK_KINDS


async def _wait_before_next_fetcher_strategy(*, reason: str, wait_sec: float) -> None:
    log_resilience(
        "fetcher_fallback_backoff",
        f"Backing off after fetcher failure ({reason})",
        wait_sec=wait_sec,
    )
    from browser_bot.run_control import sleep_or_skip

    await sleep_or_skip(wait_sec)


async def _backoff_before_next_prompt(*, reason: str, wait_sec: float) -> None:
    """Wait after all fetcher tiers failed for this prompt; outer loop moves to the next prompt."""
    await _wait_before_next_fetcher_strategy(reason=reason, wait_sec=wait_sec)
    log_resilience(
        "fetcher_fallback_skip_prompt",
        "All browser strategies failed for this prompt after backoff - moving to next prompt",
    )


async def run_ui_submit_with_strategy_fallback(
    strategies: list[tuple[Any, bool, str]],
    run_once: Callable[[Any, bool, str], Coroutine[Any, Any, Any]],
    *,
    is_success: Callable[[Any], bool] | None = None,
    strategy_fallback_backoff_sec: float = DEFAULT_STRATEGY_FALLBACK_BACKOFF_SEC,
) -> Any:
    """
    Try each fetcher strategy in order for one prompt. Only cloudflare/captcha blocks fall through
    to the next browser tier (pool → cluster → human). Rate limits backoff once then skip to the
    next prompt. An empty capture after a completed submit is recorded as-is and moves on - it is
    not retried on other tiers and does not trigger resilience backoff.
    run_once(fetcher, human_behavior, tier_label) performs one submission attempt.
    """
    from browser_bot.page_blockers import PageBlockedError
    from browser_bot.run_control import SkipCurrentPromptError

    if not strategies:
        return None

    def _ok(result: Any) -> bool:
        if is_success is not None:
            return is_success(result)
        return result is not None and bool(result[1])

    first_tier = strategies[0][2]
    last_block: PageBlockedError | None = None
    last_result: Any = None

    _log_fetcher_strategy_once(strategies)

    for index, (fetcher, human_behavior, tier) in enumerate(strategies):
        try:
            result = await run_once(fetcher, human_behavior, tier)
            last_result = result
            if _ok(result):
                if tier != first_tier:
                    log_resilience(
                        "fetcher_fallback_ok",
                        f"Submission succeeded after falling back to {tier}",
                    )
                return result
            if result is not None:
                log_resilience(
                    "capture",
                    f"{tier}: no captured response for this prompt - continuing to next prompt",
                )
                return result
            log_resilience(
                "fetcher_fallback",
                f"{tier} submit failed with no result",
            )
            if strategy_fallback_backoff_sec > 0:
                await _backoff_before_next_prompt(
                    reason=f"{tier} submit failed",
                    wait_sec=strategy_fallback_backoff_sec,
                )
            return last_result
        except SkipCurrentPromptError:
            raise
        except PageBlockedError as exc:
            last_block = exc
            if exc.kind == "rate_limited":
                log_resilience(
                    "fetcher_fallback",
                    f"{tier} rate limited - skipping remaining browser tiers for this prompt",
                    detail=exc.message or exc.kind,
                )
                if strategy_fallback_backoff_sec > 0:
                    await _backoff_before_next_prompt(
                        reason=f"{tier} rate limited",
                        wait_sec=strategy_fallback_backoff_sec,
                    )
                return last_result
            if block_kind_should_fallthrough(exc.kind):
                log_resilience(
                    "fetcher_fallback",
                    f"{tier} blocked ({exc.kind}) - trying next browser strategy",
                    detail=exc.message or exc.kind,
                )
                continue
            raise

    if last_block is not None and block_kind_should_fallthrough(last_block.kind):
        if strategy_fallback_backoff_sec > 0:
            await _backoff_before_next_prompt(
                reason=f"all tiers blocked ({last_block.kind})",
                wait_sec=strategy_fallback_backoff_sec,
            )
            return last_result
        raise last_block

    return last_result


async def _first_visible_locator(page, selector: str, *, prefer_enabled: bool = False):
    """Return locator for first visible element matching selector. Avoids hidden elements.

    When ``prefer_enabled`` is True (text fields / editable controls), skip disabled
    matches so a visible but disabled sibling (common in challenge UIs) is not chosen.
    Also skips ``aria-hidden`` nodes (often still "visible" under a modal overlay).
    """
    loc = page.locator(selector)
    count = await loc.count()
    first_visible = None
    for i in range(count):
        node = loc.nth(i)
        try:
            if not await node.is_visible():
                continue
            aria_hidden = (await node.get_attribute("aria-hidden") or "").strip().lower()
            if aria_hidden in ("true", "1"):
                continue
            data_hidden = (await node.get_attribute("data-aria-hidden") or "").strip().lower()
            if data_hidden in ("true", "1"):
                continue
        except Exception:
            continue
        if first_visible is None:
            first_visible = node
        if not prefer_enabled:
            return node
        try:
            if await node.is_enabled():
                aria = (await node.get_attribute("aria-disabled") or "").strip().lower()
                if aria not in ("true", "1"):
                    return node
        except Exception:
            continue
    if first_visible is not None:
        return first_visible
    return loc.first


# Generic start/begin CTAs (any product). Keep short so Send/Submit are excluded.
_START_SURFACE_BUTTON_RE = re.compile(
    r"^\s*(?:start(?:\s+[\w']+){0,3}|begin(?:\s+[\w']+){0,3}|get\s+started|"
    r"try\s+it(?:\s+now)?|launch(?:\s+[\w']+){0,2})\s*$",
    re.IGNORECASE,
)

# Tabs that usually host the prompt composer (Info/Attack/Preview style UIs).
_COMPOSER_TAB_RE = re.compile(
    r"^\s*(?:attack|chat|prompt|compose|playground|try|write|message)\s*$",
    re.IGNORECASE,
)

_DISMISS_OVERLAY_LABEL_RE = re.compile(
    r"^\s*(accept(?:\s+all)?|agree|got\s+it|ok|okay|close|dismiss|continue|"
    r"i\s+understand|allow(?:\s+all)?|consent|i\s+agree|[×x✕✖])\s*$",
    re.IGNORECASE,
)

_BLOCKING_OVERLAY_SELECTOR = (
    'div[data-state="open"].fixed.inset-0, '
    'div[data-state="open"][class*="inset-0"][class*="z-50"], '
    '[data-radix-dialog-overlay][data-state="open"], '
    '[role="dialog"][data-state="open"]'
)


async def _page_has_blocking_overlay(page) -> bool:
    """True when a full-screen modal/backdrop is open and would intercept clicks."""
    try:
        loc = page.locator(_BLOCKING_OVERLAY_SELECTOR)
        count = await loc.count()
    except Exception:
        return False
    for i in range(min(count, 8)):
        node = loc.nth(i)
        try:
            if await node.is_visible():
                return True
        except Exception:
            continue
    return False


async def dismiss_blocking_overlays(page, *, max_rounds: int = 3) -> bool:
    """Dismiss cookie/consent/dialog overlays that intercept pointer events.

    Returns True if an overlay was present and we attempted dismissal.
    """
    dismissed_any = False
    for _ in range(max(1, max_rounds)):
        if not await _page_has_blocking_overlay(page):
            return dismissed_any
        dismissed_any = True

        # Prefer an explicit Accept/Close control inside the open dialog.
        clicked = False
        try:
            buttons = page.locator(
                '[role="dialog"][data-state="open"] button, '
                '[role="dialog"][data-state="open"] [role="button"], '
                '[data-state="open"] button, '
                '[data-radix-dialog-content] button'
            )
            count = await buttons.count()
        except Exception:
            count = 0
        for i in range(min(count, 24)):
            node = buttons.nth(i)
            try:
                if not await node.is_visible() or not await node.is_enabled():
                    continue
                label = _normalize_menu_label(await node.inner_text())
                aria = _normalize_menu_label(
                    (await node.get_attribute("aria-label") or "")
                )
                if label and _DISMISS_OVERLAY_LABEL_RE.match(label):
                    pass
                elif aria and _DISMISS_OVERLAY_LABEL_RE.match(aria):
                    pass
                else:
                    continue
                await node.click(timeout=3000)
                clicked = True
                await asyncio.sleep(0.35)
                break
            except Exception:
                continue

        if not clicked:
            # Icon-only close controls (common on success/score dialogs).
            try:
                close_loc = page.locator(
                    '[role="dialog"][data-state="open"] button[aria-label="Close"], '
                    '[role="dialog"][data-state="open"] button[aria-label="close"], '
                    '[data-radix-dialog-content] button[aria-label="Close"], '
                    '[data-state="open"] button[aria-label="Close"]'
                )
                if await close_loc.count() > 0:
                    node = close_loc.first
                    if await node.is_visible() and await node.is_enabled():
                        await node.click(timeout=3000)
                        clicked = True
                        await asyncio.sleep(0.35)
            except Exception:
                pass

        if not clicked:
            try:
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.2)
            except Exception:
                pass

        if not await _page_has_blocking_overlay(page):
            return True
    return dismissed_any


async def _text_inputs_usable(page, inputs: list[dict] | None) -> bool:
    """True when every configured text-like input has a visible, enabled match."""
    if await _page_has_blocking_overlay(page):
        return False
    for inp in inputs or []:
        if not isinstance(inp, dict):
            continue
        inp_type = (inp.get("type") or "text").lower()
        if inp_type in ("file", "click", "select", "combobox", "checkbox", "radio"):
            continue
        if inp.get("upload_prep") or inp.get("surface_prep"):
            continue
        if inp_type not in _TEXT_TYPES:
            continue
        sel = (inp.get("selector") or "").strip()
        if not sel:
            continue
        try:
            loc = await _first_visible_locator(page, sel, prefer_enabled=True)
            if not await loc.is_visible() or not await loc.is_enabled():
                return False
            aria_hidden = (await loc.get_attribute("aria-hidden") or "").strip().lower()
            if aria_hidden in ("true", "1"):
                return False
        except Exception:
            return False
    return True


async def _surface_prep_target_visible(page, inp: dict) -> bool:
    """True when a surface_prep click target can be resolved and is visible."""
    try:
        loc = await _resolve_click_locator(page, inp)
        if loc is None:
            return False
        return bool(await loc.is_visible())
    except Exception:
        return False


async def _wait_for_surface_prep_settle(
    page,
    inputs: list[dict] | None,
    *,
    next_gate: dict | None,
    timeout_s: float = 4.0,
) -> bool:
    """After a gate click, wait for the composer or the next gate (SPA expand).

    Fixed 0.2s sleeps are too short in headless: e.g. View all Levels → MASTER
    needs the level list to paint before the next click can land.
    """
    deadline = time.perf_counter() + max(0.2, float(timeout_s or 0))
    while time.perf_counter() < deadline:
        if await _text_inputs_usable(page, inputs):
            return True
        if next_gate is not None and await _surface_prep_target_visible(page, next_gate):
            return True
        await asyncio.sleep(0.15)
    return await _text_inputs_usable(page, inputs)


async def ensure_submission_surface_ready(
    page,
    inputs: list[dict] | None,
    *,
    timeout_ms: int = 12_000,
) -> bool:
    """Open gated UIs (start CTAs / recorded surface_prep clicks) so text inputs appear.

    Dismisses blocking modals first, then always replays ``surface_prep`` clicks
    (popup / level / Start). Then, when text fields are still not usable, runs other
    ``type: click`` / ``upload_prep`` rows and a one-shot Start/Begin heuristic.

    Callers that use this (``_do_one_submit_step``) should not re-click surface_prep
    rows while filling inputs — that doubles latency.
    """
    try:
        await dismiss_blocking_overlays(page)
    except Exception:
        pass

    surface_gates = [
        inp for inp in (inputs or [])
        if isinstance(inp, dict) and inp.get("surface_prep")
    ]

    # Surface gates must run on every reload even if a leftover composer is visible.
    for idx, inp in enumerate(surface_gates):
        next_gate = surface_gates[idx + 1] if idx + 1 < len(surface_gates) else None
        # Only re-scan overlays when one is actually open (skip CDP work otherwise).
        try:
            if await _page_has_blocking_overlay(page):
                await dismiss_blocking_overlays(page)
        except Exception:
            pass

        ok = False
        last_exc: BaseException | None = None
        # Retry briefly: next gate may not exist until the previous expand finishes.
        for attempt in range(4):
            if attempt and not await _surface_prep_target_visible(page, inp):
                await asyncio.sleep(0.25)
                continue
            try:
                ok = await _fill_input(page, inp, "")
            except Exception as exc:
                last_exc = exc
                ok = False
            if ok:
                break
            await asyncio.sleep(0.25)

        if ok:
            print(
                f"  [surface_prep] clicked {inp.get('selector')!r}",
                flush=True,
            )
        elif last_exc is not None:
            print(
                f"  [surface_prep] click failed {inp.get('selector')!r}: {last_exc!r}",
                flush=True,
            )
        else:
            print(
                f"  [surface_prep] click missed {inp.get('selector')!r}"
                + (f" name={inp.get('name')!r}" if inp.get("name") else ""),
                flush=True,
            )

        # Last gate → wait for composer; earlier gates → wait for next target.
        settle_s = 5.0 if next_gate is None else 4.0
        await _wait_for_surface_prep_settle(
            page, inputs, next_gate=next_gate, timeout_s=settle_s
        )
        if await _text_inputs_usable(page, inputs):
            return True

    if await _text_inputs_usable(page, inputs):
        return True

    # Explicit prep clicks from config (upload_prep / type click) that are not surface gates.
    for inp in inputs or []:
        if not isinstance(inp, dict):
            continue
        if inp.get("surface_prep"):
            continue
        inp_type = (inp.get("type") or "text").lower()
        if inp_type != "click" and not inp.get("upload_prep"):
            continue
        try:
            await _fill_input(page, inp, "")
        except Exception:
            continue
        await asyncio.sleep(0.35)
        if await _text_inputs_usable(page, inputs):
            return True

    # Heuristic gate button (challenge / landing CTAs).
    try:
        await dismiss_blocking_overlays(page)
    except Exception:
        pass
    try:
        buttons = page.locator("button, a[role='button'], [role='button']")
        count = await buttons.count()
    except Exception:
        count = 0
    for i in range(count):
        node = buttons.nth(i)
        try:
            if not await node.is_visible():
                continue
            label = _normalize_menu_label(await node.inner_text())
            if not label or not _START_SURFACE_BUTTON_RE.match(label):
                continue
            await node.click(timeout=5000)
            await asyncio.sleep(0.5)
            break
        except Exception:
            continue

    if await _text_inputs_usable(page, inputs):
        return True

    # Composer often lives under a sibling tab (Info selected, Attack has the textarea).
    # Headed CDP profiles may already be on Attack; headless cold starts land on Info.
    if await _click_composer_tab_if_needed(page, inputs):
        return True

    deadline = time.perf_counter() + max(int(timeout_ms or 0), 500) / 1000.0
    while time.perf_counter() < deadline:
        try:
            await dismiss_blocking_overlays(page)
        except Exception:
            pass
        if await _text_inputs_usable(page, inputs):
            return True
        if await _click_composer_tab_if_needed(page, inputs):
            return True
        await asyncio.sleep(0.25)
    return await _text_inputs_usable(page, inputs)


async def _click_composer_tab_if_needed(page, inputs: list[dict] | None) -> bool:
    """Click Attack/Chat-style tabs when the composer is still hidden."""
    if await _text_inputs_usable(page, inputs):
        return True
    try:
        tabs = page.locator(
            '[role="tab"], button[role="tab"], a[role="tab"], '
            'button, [role="button"]'
        )
        count = await tabs.count()
    except Exception:
        return False
    for i in range(min(count, 40)):
        node = tabs.nth(i)
        try:
            if not await node.is_visible():
                continue
            label = _normalize_menu_label(await node.inner_text())
            if not label or not _COMPOSER_TAB_RE.match(label):
                continue
            selected = (await node.get_attribute("aria-selected") or "").strip().lower()
            if selected in ("true", "1"):
                continue
            await node.click(timeout=5000)
            print(f"  [surface_prep] clicked composer tab {label!r}", flush=True)
            await _wait_for_surface_prep_settle(
                page, inputs, next_gate=None, timeout_s=4.0
            )
            if await _text_inputs_usable(page, inputs):
                return True
        except Exception:
            continue
    return False


_UPLOAD_MENU_LABEL_PATTERNS = (
    re.compile(r"add photos?\s*(?:&|and)\s*files?", re.I),
    re.compile(r"^upload(?:\s+a)?\s+file", re.I),
    re.compile(r"^add files\b", re.I),
    re.compile(r"^attach(?:\s+a)?\s+file", re.I),
)

_UPLOAD_MENU_EXCLUDE_PATTERNS = (
    re.compile(r"create\s+image", re.I),
    re.compile(r"^web search", re.I),
    re.compile(r"^deep research", re.I),
    re.compile(r"visualize anything", re.I),
    re.compile(r"search plugins", re.I),
)


def _normalize_menu_label(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _is_upload_menu_label(text: str) -> bool:
    label = _normalize_menu_label(text)
    if not label:
        return False
    if any(p.search(label) for p in _UPLOAD_MENU_EXCLUDE_PATTERNS):
        return False
    return any(p.search(label) for p in _UPLOAD_MENU_LABEL_PATTERNS)


async def _click_upload_menu_target(page, target, artifact_path: Path | None = None) -> bool:
    """Click an upload menu target; attach immediately if it opens a chooser."""
    if artifact_path and artifact_path.is_file():
        uploaded = await _click_and_maybe_set_file_chooser(
            page,
            target,
            artifact_path,
            timeout_ms=2500,
        )
        if uploaded:
            return True
        # The menu row may reveal an input instead of opening a native chooser.
        # If the first click timed out, it has still usually activated the row.
        return False
    await target.click()
    await asyncio.sleep(0.3)
    return False


async def _click_upload_menu_item(
    page,
    artifact_path: Path | None = None,
) -> tuple[bool, bool]:
    """
    Click the file-upload row in an attachment menu (not Create image / Web search).
    Matches ChatGPT's current 'Add photos & files' label and similar variants.

    Returns (clicked, uploaded). Some UIs open a chooser directly; others reveal
    an input[type=file] for the later file step.
    """
    roles = ("menuitem", "option", "menuitemradio", "menuitemcheckbox")
    for role in roles:
        loc = page.get_by_role(role)
        count = await loc.count()
        for i in range(count):
            item = loc.nth(i)
            try:
                if not await item.is_visible():
                    continue
            except Exception:
                continue
            try:
                label = _normalize_menu_label(await item.inner_text())
            except Exception:
                label = ""
            if not _is_upload_menu_label(label):
                continue
            uploaded = await _click_upload_menu_target(page, item, artifact_path)
            return True, uploaded

    exact_labels = (
        "Add photos & files",
        "Add photos and files",
        "Upload file",
        "Upload a file",
        "Add files",
        "Attach file",
        "Attach a file",
    )
    for label in exact_labels:
        loc = page.get_by_text(label, exact=True)
        count = await loc.count()
        for i in range(count):
            item = loc.nth(i)
            try:
                if not await item.is_visible():
                    continue
            except Exception:
                continue
            uploaded = await _click_upload_menu_target(page, item, artifact_path)
            return True, uploaded

    text_selectors = (
        r'text=/^\s*Add photos?\s*(?:&|and)\s*files?\s*$/i',
        r'text=/^\s*Upload(?:\s+a)?\s+file\s*$/i',
        r'text=/^\s*Add files?\s*$/i',
        r'text=/^\s*Attach(?:\s+a)?\s+file\s*$/i',
    )
    for selector in text_selectors:
        loc = page.locator(selector)
        count = await loc.count()
        for i in range(count):
            item = loc.nth(i)
            try:
                if not await item.is_visible():
                    continue
            except Exception:
                continue
            uploaded = await _click_upload_menu_target(page, item, artifact_path)
            return True, uploaded

    return False, False


def _input_wants_upload_menu(inp: dict) -> bool:
    return bool(inp.get("upload_menu"))


_PROMOTE_INTERACTIVE_CLICK_JS = """(el) => {
  if (!el || el.nodeType !== 1) return el;
  const interactive = (node) => {
    if (!node || node.nodeType !== 1) return false;
    const tag = (node.tagName || "").toLowerCase();
    const role = (node.getAttribute("role") || "").toLowerCase();
    if (tag === "button" || tag === "a" || tag === "summary") return true;
    if (["button", "link", "tab", "menuitem", "option", "radio", "checkbox"].includes(role)) {
      return true;
    }
    if (node.getAttribute("onclick") != null) return true;
    try {
      if (window.getComputedStyle(node).cursor === "pointer") return true;
    } catch (_) {}
    try {
      if (typeof node.tabIndex === "number" && node.tabIndex >= 0 && tag !== "span") {
        return true;
      }
    } catch (_) {}
    return false;
  };
  let cur = el;
  for (let i = 0; i < 14 && cur && cur !== document.documentElement; i++) {
    if (interactive(cur)) return cur;
    cur = cur.parentElement;
  }
  return el;
}"""


def _selector_matches_by_contained_text(selector: str) -> bool:
    """True when a selector can match a large ancestor that merely contains the label."""
    s = (selector or "").strip().lower()
    if not s:
        return False
    return (
        s.startswith("text=")
        or s.startswith("text/")
        or ":text-is(" in s
        or ":text(" in s
        or "has-text(" in s
        or s.startswith(":has-text(")
    )


def _split_selector_alternates(selector: str) -> list[str]:
    """Split comma-separated Playwright alternates without breaking quoted has-text() args."""
    raw = (selector or "").strip()
    if not raw:
        return []
    parts: list[str] = []
    buf: list[str] = []
    quote = ""
    depth = 0
    for ch in raw:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in ('"', "'"):
            quote = ch
            buf.append(ch)
            continue
        if ch == "(":
            depth += 1
            buf.append(ch)
            continue
        if ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
            continue
        if ch == "," and depth == 0:
            part = "".join(buf).strip()
            if part:
                parts.append(part)
            buf = []
            continue
        buf.append(ch)
    part = "".join(buf).strip()
    if part:
        parts.append(part)
    return parts or [raw]


async def _best_click_candidate_from_loc(loc: "Locator", *, max_scan: int = 40):
    """Prefer deepest / smallest visible match (avoids clicking a label's ancestor panel).

    Broad ``has-text`` / ``text=`` sets can be huge — walk from the end (leaves tend to
    be last in DOM order) instead of scoring every ancestor over CDP. Small sets use a
    single ``evaluate_all`` pass for depth/area ranking.
    """
    try:
        count = await loc.count()
    except Exception:
        return None
    if count <= 0:
        return None
    if count == 1:
        try:
            if await loc.first.is_visible():
                return loc.first
        except Exception:
            pass
        return loc.first

    limit = max(1, min(int(max_scan or 40), count))

    # Large match sets: last visible node is usually the text leaf, not the panel.
    if count > limit:
        checked = 0
        for i in range(count - 1, -1, -1):
            if checked >= limit:
                break
            checked += 1
            node = loc.nth(i)
            try:
                if not await node.is_visible():
                    continue
                aria_hidden = (await node.get_attribute("aria-hidden") or "").strip().lower()
                if aria_hidden in ("true", "1"):
                    continue
                return node
            except Exception:
                continue
        return loc.nth(count - 1)

    try:
        metas = await loc.evaluate_all(
            """(els) => {
              const out = [];
              for (let i = 0; i < els.length; i++) {
                const el = els[i];
                if (!el || el.nodeType !== 1) continue;
                const aria = (el.getAttribute("aria-hidden") || "").trim().toLowerCase();
                if (aria === "true" || aria === "1") continue;
                const style = window.getComputedStyle(el);
                const r = el.getBoundingClientRect();
                if (
                  !style
                  || style.visibility === "hidden"
                  || style.display === "none"
                  || r.width <= 0
                  || r.height <= 0
                ) {
                  continue;
                }
                let depth = 0;
                for (let n = el; n; n = n.parentElement) depth += 1;
                out.push({
                  i,
                  depth,
                  area: Math.max(1, (r.width || 0) * (r.height || 0)),
                });
              }
              return out;
            }"""
        )
    except Exception:
        metas = None

    if isinstance(metas, list) and metas:
        best_meta = max(
            metas,
            key=lambda m: (int(m.get("depth") or 0), -float(m.get("area") or 1)),
        )
        try:
            return loc.nth(int(best_meta.get("i")))
        except Exception:
            pass

    for i in range(count - 1, -1, -1):
        node = loc.nth(i)
        try:
            if await node.is_visible():
                return node
        except Exception:
            continue
    return loc.first


async def _promote_interactive_click_host(loc: "Locator"):
    """Climb from a text leaf (span) to the nearest pointer/button host before clicking."""
    try:
        handle = await loc.evaluate_handle(_PROMOTE_INTERACTIVE_CLICK_JS)
        element = handle.as_element() if handle is not None else None
        if element is None:
            return loc
        # Stamp a unique marker so we can re-locate after promotion.
        marker = f"gbclick_{uuid.uuid4().hex[:12]}"
        await element.evaluate(
            """(el, marker) => { el.setAttribute('data-genbounty-click', marker); }""",
            marker,
        )
        page = loc.page
        promoted = page.locator(f'[data-genbounty-click="{marker}"]')
        if await promoted.count() > 0:
            return promoted.first
    except Exception:
        pass
    return loc


def _is_generic_click_selector(selector: str) -> bool:
    """True for selectors that match many unrelated controls (header icons, etc.)."""
    try:
        from browser_bot.record_submission import is_generic_click_selector
    except Exception:
        sel = (selector or "").strip().lower()
        return sel in ("button", "a", "div", "span") or sel.startswith(
            "button[type=button]"
        ) or sel.startswith('button[type="button"]')
    return is_generic_click_selector(selector)


def _selector_part_priority(part: str) -> tuple[int, int]:
    """Lower = try first. Prefer exact text / button labels over broad has-text."""
    s = (part or "").strip().lower()
    if ":text-is(" in s:
        return (0, len(s))
    if s.startswith("button:has-text") or s.startswith('[role="button"]:has-text'):
        return (1, len(s))
    if s.startswith("a:has-text") or s.startswith('[role="link"]:has-text'):
        return (2, len(s))
    if "has-text(" in s:
        return (3, len(s))
    if s.startswith("text=") or s.startswith("text/"):
        return (4, len(s))
    return (5, len(s))


def _click_name_candidates(name: str) -> list[str]:
    """Name variants to try when resolving a labeled click (title before badge noise)."""
    n = " ".join((name or "").split()).strip()
    if not n:
        return []
    out: list[str] = [n]
    words = n.split()
    if len(words) >= 2:
        short = " ".join(words[:2])
        if short not in out:
            out.append(short)
    return out


async def _resolve_named_click_locator(page, name: str):
    """Resolve by visible text / accessible name (cards are often not <button>)."""
    for candidate in _click_name_candidates(name):
        # Exact leaf text first (few matches); avoid broad get_by_text until needed.
        try:
            loc = page.locator(f':text-is("{candidate}")')
            if await loc.count() > 0:
                found = await _best_click_candidate_from_loc(loc, max_scan=12)
                if found is not None:
                    return found
        except Exception:
            pass
        try:
            loc = page.get_by_text(candidate, exact=True)
            if await loc.count() > 0:
                found = await _best_click_candidate_from_loc(loc, max_scan=12)
                if found is not None:
                    return found
        except Exception:
            pass
        try:
            loc = page.locator(f"text={candidate}")
            if await loc.count() > 0:
                found = await _best_click_candidate_from_loc(loc, max_scan=40)
                if found is not None:
                    return found
        except Exception:
            pass
        try:
            loc = page.get_by_text(candidate, exact=False)
            if await loc.count() > 0:
                found = await _best_click_candidate_from_loc(loc, max_scan=40)
                if found is not None:
                    return found
        except Exception:
            pass
    return None


async def _resolve_click_locator(page, inp: dict):
    """Resolve a click target from selector and/or role+name.

    Text/has-text selectors often match a large ancestor that *contains* the label.
    Prefer the deepest visible match, then promote to the nearest interactive host.

    Generic selectors like ``button[type=button]`` are skipped when a name is
    available — otherwise Run clicks the first header icon.
    """
    selector = str(inp.get("selector") or "").strip()
    name = str(inp.get("name") or inp.get("menu_match") or "").strip()
    role = str(inp.get("role") or "").strip()
    found = None
    if role and name:
        try:
            loc = page.get_by_role(role, name=re.compile(re.escape(name), re.I))
            if await loc.count() > 0:
                found = await _best_click_candidate_from_loc(loc)
        except Exception:
            pass
        # Role+name with a long label ("Level 2 ADEPT") may miss; try short title.
        if found is None:
            for candidate in _click_name_candidates(name)[1:]:
                try:
                    loc = page.get_by_role(
                        role, name=re.compile(re.escape(candidate), re.I)
                    )
                    if await loc.count() > 0:
                        found = await _best_click_candidate_from_loc(loc)
                        if found is not None:
                            break
                except Exception:
                    continue

    parts = _split_selector_alternates(selector) if selector else []
    specific_parts = sorted(
        [p for p in parts if not _is_generic_click_selector(p)],
        key=_selector_part_priority,
    )
    generic_parts = [p for p in parts if _is_generic_click_selector(p)]

    if found is None:
        for part in specific_parts:
            try:
                loc = page.locator(part)
                if await loc.count() <= 0:
                    continue
                # Exact text / role+text: take deepest quickly; skip huge has-text scans when
                # a tight :text-is / button:has-text already matched.
                if _selector_matches_by_contained_text(part):
                    max_scan = 12 if ":text-is(" in part.lower() else 40
                    cand = await _best_click_candidate_from_loc(loc, max_scan=max_scan)
                else:
                    cand = await _first_visible_locator(page, part)
                if cand is not None:
                    found = cand
                    break
            except Exception:
                continue

    # Named resolution before generic tag selectors (button[type=button] → header grid).
    if found is None and name:
        found = await _resolve_named_click_locator(page, name)

    if found is None and generic_parts and not name:
        for part in generic_parts:
            try:
                cand = await _first_visible_locator(page, part)
                if cand is not None:
                    found = cand
                    break
            except Exception:
                continue

    if found is None and selector and not specific_parts and not name:
        try:
            if not _is_generic_click_selector(selector):
                if _selector_matches_by_contained_text(selector):
                    found = await _best_click_candidate_from_loc(page.locator(selector))
                else:
                    found = await _first_visible_locator(page, selector)
        except Exception:
            pass

    if found is None:
        return None
    return await _promote_interactive_click_host(found)


async def _first_visible_locator_from_loc(loc: "Locator"):
    count = await loc.count()
    for i in range(count):
        node = loc.nth(i)
        if await node.is_visible():
            return node
    return loc.first


async def _resolve_file_input_locator(page, selector: str):
    """Return a file-input locator; hidden inputs are allowed."""
    loc = page.locator(selector)
    if await loc.count() == 0:
        return None
    first = loc.first
    try:
        meta = await first.evaluate(
            """(el) => ({
              tag: (el.tagName || '').toLowerCase(),
              type: (el.type || '').toLowerCase(),
            })"""
        )
        if meta.get("tag") == "input" and meta.get("type") == "file":
            return first
    except Exception:
        pass
    return None


async def _find_page_file_input(page):
    for _ in range(6):
        loc = page.locator('input[type="file"]')
        if await loc.count() > 0:
            return loc.first
        await asyncio.sleep(0.15)
    return None


def _selector_suggests_upload_trigger(selector: str) -> bool:
    sel = (selector or "").lower()
    tokens = (
        "button",
        "composer-plus",
        "menuitem",
        "attach",
        "upload",
        "aria-haspopup",
        '[role="button"]',
        "plus-btn",
    )
    return any(token in sel for token in tokens)


async def _click_and_maybe_set_file_chooser(
    page,
    loc: "Locator",
    artifact_path: Path,
    *,
    timeout_ms: int = 1000,
) -> bool:
    """Click an upload control and attach the artifact if it opens a file chooser."""
    if not artifact_path or not artifact_path.is_file():
        return False
    try:
        async with page.expect_file_chooser(timeout=timeout_ms) as chooser_info:
            await loc.click()
        chooser = await chooser_info.value
        await chooser.set_files(str(artifact_path))
        await asyncio.sleep(0.3)
        return True
    except Exception:
        return False


async def _set_input_files_artifact(
    page,
    artifact_path: Path,
    *,
    selector: str = "",
    inp: dict | None = None,
) -> bool:
    """Attach artifact to a file input, clicking upload triggers when needed."""
    if not artifact_path or not artifact_path.is_file():
        return False
    path_str = str(artifact_path)

    if selector:
        file_loc = await _resolve_file_input_locator(page, selector)
        if file_loc is not None:
            await file_loc.set_input_files(path_str)
            await asyncio.sleep(0.3)
            return True

    if selector and _selector_suggests_upload_trigger(selector):
        try:
            trigger = await _first_visible_locator(page, selector)
            if await _click_and_maybe_set_file_chooser(page, trigger, artifact_path):
                return True
            await asyncio.sleep(0.35)
        except Exception:
            pass
        menu_sel = str((inp or {}).get("menu_selector") or "").strip()
        if menu_sel:
            try:
                menu_loc = await _first_visible_locator(page, menu_sel)
                if await _click_and_maybe_set_file_chooser(page, menu_loc, artifact_path):
                    return True
                await asyncio.sleep(0.25)
            except Exception:
                pass

    file_loc = await _find_page_file_input(page)
    if file_loc is not None:
        await file_loc.set_input_files(path_str)
        await asyncio.sleep(0.3)
        return True
    return False


async def _last_visible_locator(page, selector: str):
    """Return locator for last visible element matching selector (latest chat bubble, etc.)."""
    loc = page.locator(selector)
    count = await loc.count()
    for i in range(count - 1, -1, -1):
        node = loc.nth(i)
        if await node.is_visible():
            return node
    return loc.last


async def _last_visible_within(loc: "Locator"):
    """Like _last_visible_locator but scoped to an existing locator (narrowed descendant chain)."""
    count = await loc.count()
    for i in range(count - 1, -1, -1):
        node = loc.nth(i)
        try:
            if await node.is_visible():
                return node
        except Exception:
            continue
    return loc.last


async def _last_visible_with_visible_parity(loc: "Locator", parity: int):
    """Last visible match whose index among visible siblings has ``parity`` (0=even, 1=odd)."""
    count = await loc.count()
    last: "Locator | None" = None
    vis_idx = 0
    for i in range(count):
        node = loc.nth(i)
        try:
            if not await node.is_visible():
                continue
        except Exception:
            continue
        if vis_idx % 2 == parity:
            last = node
        vis_idx += 1
    return last


async def _visible_locator_count(loc: "Locator") -> int:
    """Count visible nodes under an existing locator."""
    try:
        count = await loc.count()
    except Exception:
        return 0
    visible = 0
    for i in range(count):
        try:
            if await loc.nth(i).is_visible():
                visible += 1
        except Exception:
            continue
    return visible


async def _resolve_response_target_locator(
    page: "Page",
    selector: str,
    *,
    within_selector: str = "",
    capture_mode: str = "last",
    list_selector: str = "",
    role_selector: str = "",
):
    """Locator for all candidate response nodes (before picking last/parity/role)."""
    mode = (capture_mode or "last").strip().lower()
    inner = within_selector.strip()
    list_sel = list_selector.strip()
    role_sel = role_selector.strip()
    root_sel = selector.strip()

    if list_sel:
        return page.locator(list_sel)

    if mode == "role":
        rs = role_sel or root_sel
        if not rs:
            return None
        target = page.locator(rs)
        if inner:
            target = target.locator(inner)
        return target

    if not root_sel:
        return None
    roots = page.locator(root_sel)
    if await roots.count() == 0:
        return None
    return roots.locator(inner) if inner else roots


async def _response_selector_visible_count(
    page: "Page",
    selector: str,
    *,
    within_selector: str = "",
    capture_mode: str = "last",
    list_selector: str = "",
    role_selector: str = "",
) -> int:
    """Visible node count for the configured response capture scope."""
    target = await _resolve_response_target_locator(
        page,
        selector,
        within_selector=within_selector,
        capture_mode=capture_mode,
        list_selector=list_selector,
        role_selector=role_selector,
    )
    if target is None:
        return 0
    return await _visible_locator_count(target)


async def _response_selector_surface_texts(
    page: "Page",
    selector: str,
    *,
    within_selector: str = "",
    text_within_selector: str = "",
    capture_mode: str = "last",
    list_selector: str = "",
    role_selector: str = "",
    max_len: int = 240,
    cap: int = 40,
) -> tuple[str, ...]:
    """Short visible texts under the response surface (welcome/chrome candidates)."""
    target = await _resolve_response_target_locator(
        page,
        selector,
        within_selector=within_selector,
        capture_mode=capture_mode,
        list_selector=list_selector,
        role_selector=role_selector,
    )
    if target is None:
        return ()
    try:
        count = await target.count()
    except Exception:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    txt_in = (text_within_selector or "").strip()
    for i in range(min(count, cap)):
        node = target.nth(i)
        try:
            if not await node.is_visible():
                continue
        except Exception:
            continue
        extract = node
        if txt_in:
            leaf = await _first_visible_under(node, txt_in)
            if leaf is not None:
                extract = leaf
        try:
            text = normalize_dom_text(await extract.inner_text()).strip()
        except Exception:
            continue
        if not text or len(text) > max_len:
            continue
        key = re.sub(r"\s+", " ", text).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return tuple(out)


def _response_capture_is_meaningful(
    *,
    new_slice: str,
    current: str,
    base: str,
    count_increased: bool,
    filter_ctx: ResponseFilterContext | None,
    exclude_norm: str,
    reject_last_mode_echo: bool,
    post_submit_activity: bool = False,
) -> bool:
    """True when polled DOM state represents a newly arrived assistant reply."""
    # Node remounts of the same pre-submit chrome (welcome bubble) bump the count
    # without changing text - that is not a new model reply.
    if (
        count_increased
        and current.strip() != base.strip()
        and is_actionable_response(current, filter_ctx)
    ):
        return True
    # Same visible text as pre-submit baseline but the bubble cycled (loader → reply) or
    # a new identical assistant message appeared - common when sequential tests reuse
    # session state and the model repeats the same refusal.
    if (
        post_submit_activity
        and is_actionable_response(current, filter_ctx)
        and current.strip() == base.strip()
    ):
        return True
    return (
        bool(new_slice.strip())
        and new_slice.strip() != base.strip()
        and is_actionable_delta(new_slice, filter_ctx)
        and is_actionable_response(current, filter_ctx)
        and not (reject_last_mode_echo and new_slice.strip() == exclude_norm)
    )


def response_capture_kwargs(submission: dict | None) -> dict[str, str]:
    """Extract optional response capture strategy fields from a submission config dict."""
    sub = submission or {}
    return {
        "response_capture_mode": str(sub.get("response_capture_mode") or "last").strip().lower(),
        "response_list_selector": str(sub.get("response_list_selector") or "").strip(),
        "response_role_selector": str(sub.get("response_role_selector") or "").strip(),
    }


async def _resolve_response_read_locator(
    page: "Page",
    selector: str,
    *,
    within_selector: str = "",
    capture_mode: str = "last",
    list_selector: str = "",
    role_selector: str = "",
):
    """Resolve the DOM node Genbounty Hunter reads for assistant output under the configured capture mode."""
    mode = (capture_mode or "last").strip().lower()
    inner = within_selector.strip()
    list_sel = list_selector.strip()
    role_sel = role_selector.strip()
    root_sel = selector.strip()

    if mode in ("parity_odd", "parity_even"):
        parity = 1 if mode == "parity_odd" else 0
        if list_sel:
            target = page.locator(list_sel)
        elif root_sel:
            roots = page.locator(root_sel)
            if await roots.count() == 0:
                return None
            target = roots.locator(inner) if inner else roots
            if inner and await target.count() == 0:
                return None
        else:
            return None
        node = await _last_visible_with_visible_parity(target, parity)
        if node is not None:
            return node
        return await _last_visible_within(target)

    if mode == "role":
        rs = role_sel or root_sel
        if not rs:
            return None
        target = page.locator(rs)
        if inner:
            target = target.locator(inner)
        elif list_sel:
            target = target.locator(list_sel)
        if await target.count() == 0:
            return None
        return await _last_visible_within(target)

    if list_sel:
        target = page.locator(list_sel)
        if await target.count() == 0:
            return None
        return await _last_visible_within(target)

    if not root_sel:
        return None
    roots = page.locator(root_sel)
    if await roots.count() == 0:
        return None
    target = roots.locator(inner) if inner else roots
    if inner and await target.count() == 0:
        return None
    return await _last_visible_within(target)


def _is_actionable_response_text(text: str) -> bool:
    """Backward-compatible alias for wait-gate checks without submission context."""
    return is_actionable_response(text)


async def _first_visible_under(main_loc: "Locator", relative: str) -> "Locator | None":
    """First visible node under ``main_loc`` matching Playwright-relative ``relative``."""
    rel = (relative or "").strip()
    if not rel:
        return None
    sub = main_loc.locator(rel)
    count = await sub.count()
    for i in range(count):
        node = sub.nth(i)
        try:
            if await node.is_visible():
                return node
        except Exception:
            continue
    return None


async def _response_selector_text(
    page: "Page",
    selector: str,
    *,
    within_selector: str = "",
    text_within_selector: str = "",
    capture_mode: str = "last",
    list_selector: str = "",
    role_selector: str = "",
) -> str:
    """Read inner_text: scope to bubble/container, optionally read from a narrower leaf only.

    Use ``text_within_selector`` when the container includes labels or footer widgets - for
    example a Playwright-relative ``> p`` on the bubble picks the assistant body paragraph
    while the bubble itself stays the visibility anchor during streaming.
    When the leaf is missing (spinner-only phase), falls back to the container's inner_text.

    ``capture_mode`` controls how the target node is chosen from a message list:
    ``last`` (default), ``role`` (assistant-only roots), ``parity_odd`` / ``parity_even``
    (alternating chat threads where user and assistant share the same leaf selector).
    """
    main_loc = await _resolve_response_read_locator(
        page,
        selector,
        within_selector=within_selector,
        capture_mode=capture_mode,
        list_selector=list_selector,
        role_selector=role_selector,
    )
    if main_loc is None:
        return ""
    await main_loc.wait_for(state="visible", timeout=3000)
    txt_in = text_within_selector.strip() if text_within_selector else ""
    extract_loc = main_loc
    if txt_in:
        leaf = await _first_visible_under(main_loc, txt_in)
        if leaf is not None:
            extract_loc = leaf
    return normalize_dom_text(await extract_loc.inner_text()).strip()


async def _wait_for_response_selector_text(
    page,
    selector: str,
    *,
    previous_text: str | None,
    timeout_ms: int,
    stable_ms: int = 900,
    within_selector: str = "",
    text_within_selector: str = "",
    capture_mode: str = "last",
    list_selector: str = "",
    role_selector: str = "",
    exclude_text: str = "",
    previous_node_count: int | None = None,
    human_behavior: bool = False,
    filter_ctx: ResponseFilterContext | None = None,
    completion_status: dict[str, Any] | None = None,
) -> str:
    """Poll until inner text differs from baseline and stays stable (`stable_ms`), or deadline.

    `timeout_ms` is the maximum time to poll - not a minimum sleep before returning.
    If `previous_text` is ``None`` (baseline could not be read before submit), the first sample
    after waiting starts establishes the baseline so existing DOM copy is not mistaken for the
    new model reply (previously any non‑empty node satisfied `current != ""` and exited in ~1s).
    """
    from browser_bot.run_control import raise_if_skip_requested

    deadline = time.perf_counter() + max(int(timeout_ms or 0), 1000) / 1000.0
    stable_for = max(int(stable_ms or 0), 500) / 1000.0
    candidate = ""
    last_seen = ""
    last_changed = time.perf_counter()
    baseline_unknown = previous_text is None
    effective_baseline: str | None = previous_text if not baseline_unknown else None
    seeded_post_submit = False
    poll_count = 0
    saw_post_submit_activity = False
    mode = (capture_mode or "last").strip().lower()
    exclude_norm = (exclude_text or "").strip()
    reject_submitted = bool(exclude_norm) and mode.startswith("parity_")
    reject_last_mode_echo = bool(exclude_norm) and mode == "last"

    while time.perf_counter() < deadline:
        await raise_if_skip_requested()
        try:
            current = await _response_selector_text(
                page,
                selector,
                within_selector=within_selector,
                text_within_selector=text_within_selector,
                capture_mode=capture_mode,
                list_selector=list_selector,
                role_selector=role_selector,
            )
        except Exception:
            current = ""

        try:
            current_count = await _response_selector_visible_count(
                page,
                selector,
                within_selector=within_selector,
                capture_mode=capture_mode,
                list_selector=list_selector,
                role_selector=role_selector,
            )
        except Exception:
            current_count = 0

        if baseline_unknown and not seeded_post_submit:
            effective_baseline = current
            seeded_post_submit = True
            # First post-submit sample is often still the welcome bubble - treat short
            # copy as chrome so we keep waiting for a real reply on any app.
            register_pre_submit_chrome(filter_ctx, current, persist=True)
            await asyncio.sleep(0.2)
            continue

        base = effective_baseline if effective_baseline is not None else ""
        new_slice = _response_delta(base, current)
        count_increased = (
            previous_node_count is not None and current_count > previous_node_count
        )
        if seeded_post_submit:
            if count_increased or current.strip() != base.strip():
                saw_post_submit_activity = True
            elif non_actionable_reason(current, filter_ctx) is not None:
                saw_post_submit_activity = True
            if saw_post_submit_activity and completion_status is not None:
                completion_status["saw_activity"] = True
        meaningful = _response_capture_is_meaningful(
            new_slice=new_slice,
            current=current,
            base=base,
            count_increased=count_increased,
            filter_ctx=filter_ctx,
            exclude_norm=exclude_norm,
            reject_last_mode_echo=reject_last_mode_echo,
            post_submit_activity=saw_post_submit_activity,
        ) and not (reject_submitted and current.strip() == exclude_norm)
        if meaningful:
            if current != last_seen:
                last_seen = current
                last_changed = time.perf_counter()
            candidate = current
            if time.perf_counter() - last_changed >= stable_for:
                if is_actionable_response(candidate, filter_ctx):
                    if completion_status is not None:
                        completion_status["stable"] = True
                    return candidate
                candidate = ""
        elif candidate and non_actionable_reason(current, filter_ctx) is not None:
            candidate = ""
            last_seen = ""

        poll_count += 1
        if human_behavior and poll_count % 6 == 0:
            try:
                from browser_bot.browser.human_behavior import human_mouse_wander, human_scroll

                await human_mouse_wander(page, count=1)
                if poll_count % 12 == 0:
                    await human_scroll(page)
            except Exception:
                pass

        await asyncio.sleep(0.25)

    if candidate and is_actionable_response(candidate, filter_ctx):
        return candidate

    # Primary deadline passed with only loader text - allow a short grace window.
    grace_deadline = time.perf_counter() + min(max(stable_for * 6, 2.0), 6.0)
    base = effective_baseline if effective_baseline is not None else ""
    while time.perf_counter() < grace_deadline:
        try:
            current = await _response_selector_text(
                page,
                selector,
                within_selector=within_selector,
                text_within_selector=text_within_selector,
                capture_mode=capture_mode,
                list_selector=list_selector,
                role_selector=role_selector,
            )
        except Exception:
            current = ""
        try:
            current_count = await _response_selector_visible_count(
                page,
                selector,
                within_selector=within_selector,
                capture_mode=capture_mode,
                list_selector=list_selector,
                role_selector=role_selector,
            )
        except Exception:
            current_count = 0
        new_slice = _response_delta(base, current)
        count_increased = (
            previous_node_count is not None and current_count > previous_node_count
        )
        if _response_capture_is_meaningful(
            new_slice=new_slice,
            current=current,
            base=base,
            count_increased=count_increased,
            filter_ctx=filter_ctx,
            exclude_norm=exclude_norm,
            reject_last_mode_echo=reject_last_mode_echo,
            post_submit_activity=saw_post_submit_activity,
        ):
            await asyncio.sleep(stable_for)
            try:
                settled = await _response_selector_text(
                    page,
                    selector,
                    within_selector=within_selector,
                    text_within_selector=text_within_selector,
                    capture_mode=capture_mode,
                    list_selector=list_selector,
                    role_selector=role_selector,
                )
            except Exception:
                settled = current
            if is_actionable_response(settled, filter_ctx):
                if completion_status is not None:
                    completion_status["stable"] = True
                return settled
        await asyncio.sleep(0.25)

    if saw_post_submit_activity:
        try:
            final = await _response_selector_text(
                page,
                selector,
                within_selector=within_selector,
                text_within_selector=text_within_selector,
                capture_mode=capture_mode,
                list_selector=list_selector,
                role_selector=role_selector,
            )
        except Exception:
            final = ""
        if is_actionable_response(final, filter_ctx):
            return final

    return ""


async def _read_text_control(loc: "Locator", inp_type: str) -> str:
    """Read the current value from a text-like control (input, textarea, contenteditable)."""
    if inp_type == "contenteditable":
        return (
            await loc.evaluate("(el) => (el.innerText || el.textContent || '').trim()")
        ) or ""
    try:
        value = await loc.input_value()
        if value is not None:
            return value.strip()
    except Exception:
        pass
    tag = await loc.evaluate("(el) => (el.tagName || '').toLowerCase()")
    if tag in ("textarea", "input"):
        return (
            await loc.evaluate("(el) => String(el.value != null ? el.value : '').trim()")
        ) or ""
    return (await loc.inner_text()).strip()


async def _keyboard_fill_text_control(page, loc: "Locator", inp_type: str, value: str) -> None:
    """Type like a user when programmatic fills do not hydrate framework state."""
    await loc.click()
    await asyncio.sleep(0.1)
    await page.keyboard.press("Control+A")
    await page.keyboard.press("Backspace")
    await asyncio.sleep(0.05)
    await page.keyboard.type(value, delay=20)


async def _sync_native_text_value(loc: "Locator", value: str) -> None:
    await loc.evaluate(_SET_NATIVE_TEXT_VALUE_JS, value)


async def _fill_text_control(page, loc: "Locator", inp_type: str, value: str) -> None:
    """Fill input/textarea/contenteditable with strategies that work on hydrated UIs."""
    try:
        await dismiss_blocking_overlays(page)
    except Exception:
        pass
    try:
        await loc.click(timeout=5000)
    except Exception:
        # Modal may still be settling; force focus as a last resort.
        try:
            await dismiss_blocking_overlays(page)
            await loc.click(timeout=3000, force=True)
        except Exception:
            await loc.focus()
    await asyncio.sleep(0.1)

    if inp_type == "contenteditable":
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Backspace")
        await asyncio.sleep(0.05)
        await page.keyboard.type(value, delay=15)
        return

    tag = await loc.evaluate("(el) => (el.tagName || '').toLowerCase()")
    if tag in ("textarea", "input"):
        await _sync_native_text_value(loc, value)
        read_back = await _read_text_control(loc, "textarea" if tag == "textarea" else "text")
        if value not in read_back:
            await loc.fill(value)
            read_back = await _read_text_control(loc, "textarea" if tag == "textarea" else "text")
        if value not in read_back:
            await _keyboard_fill_text_control(page, loc, inp_type, value)
        return

    await loc.fill(value)


async def _clear_text_control(page, loc: "Locator", inp_type: str) -> None:
    if inp_type == "contenteditable":
        await loc.click()
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Backspace")
        await asyncio.sleep(0.1)
        return
    tag = await loc.evaluate("(el) => (el.tagName || '').toLowerCase()")
    if tag in ("textarea", "input"):
        await loc.click()
        await loc.evaluate(_CLEAR_NATIVE_TEXT_VALUE_JS)
        return
    try:
        await loc.fill("")
    except Exception:
        pass


async def _fill_input(
    page,
    inp: dict,
    value: str,
    *,
    artifact_path: Path | None = None,
) -> bool:
    """Fill a single input based on its type."""
    selector = inp["selector"]
    inp_type = inp.get("type", "text")

    if inp_type == "file":
        if artifact_path is None:
            path_str = inp.get("path") or inp.get("value")
            if path_str:
                artifact_path = Path(str(path_str))
        if artifact_path and artifact_path.is_file():
            ok = await _set_input_files_artifact(
                page, artifact_path, selector=selector, inp=inp
            )
            if not ok:
                log_resilience(
                    "artifact_upload",
                    detail=(
                        f"Could not attach file to {selector!r} "
                        f"({artifact_path.name}); continuing without upload"
                    ),
                )
                return False
            return ok
        return False

    if inp_type == "click":
        uploaded = False
        if _input_wants_upload_menu(inp):
            clicked, uploaded = await _click_upload_menu_item(page, artifact_path)
            if not clicked:
                log_resilience(
                    "artifact_upload",
                    detail="Could not find an upload menu item after opening dropdown",
                )
            return uploaded
        else:
            loc = await _resolve_click_locator(page, inp)
            if loc is None:
                return False
            try:
                if not await loc.is_visible():
                    return False
            except Exception:
                return False
            if (
                artifact_path
                and artifact_path.is_file()
                and inp.get("attach_on_click")
            ):
                return await _click_and_maybe_set_file_chooser(page, loc, artifact_path)
            await loc.click()
            await asyncio.sleep(
                0.2 if inp.get("surface_prep") else (0.25 if inp.get("upload_prep") else 0.15)
            )
            return True

    if inp_type in _TEXT_TYPES:
        loc = await _first_visible_locator(page, selector, prefer_enabled=True)
        await _fill_text_control(page, loc, inp_type, value)
    elif inp_type == "select":
        sel_loc = await _first_visible_locator(page, selector)
        options = await sel_loc.evaluate(
            """
            (el) => {
              if (!el || el.tagName !== 'SELECT') return [];
              return Array.from(el.options).map(o => o.value).filter(v => v !== '');
            }
            """
        )
        configured = inp.get("value")
        if configured and configured in options:
            chosen = configured
        else:
            chosen = random.choice(options) if options else (configured or "")
        await sel_loc.select_option(value=chosen)
    elif inp_type == "combobox":
        combo_loc = await _first_visible_locator(page, selector)
        await combo_loc.click()
        await asyncio.sleep(0.2)
        listbox = page.get_by_role("listbox")
        options = await listbox.locator('[role="option"]').all_text_contents()
        if not options:
            options = await page.locator('[role="option"]').all_text_contents()
        options = [o.strip() for o in options if o.strip()]
        chosen = random.choice(options) if options else (value or inp.get("value", ""))
        try:
            await page.get_by_role("option", name=chosen).first.click()
        except Exception:
            await page.locator(f'[role="option"]:has-text("{chosen}")').first.click()
    elif inp_type == "checkbox":
        loc = await _first_visible_locator(page, selector)
        if inp.get("value"):
            await loc.check()
        else:
            await loc.uncheck()
    elif inp_type == "radio":
        radio_loc = await _first_visible_locator(page, selector)
        if inp.get("value"):
            await radio_loc.check()
        else:
            await radio_loc.uncheck()
    else:
        loc = await _first_visible_locator(page, selector)
        await loc.fill(value)
    return False


async def _refire_text_input_events(page, inputs: list[dict]) -> None:
    """Nudge hydrated frontends that missed Playwright's first fill event."""
    for inp in inputs:
        if inp.get("type", "text") not in _TEXT_TYPES:
            continue
        selector = inp.get("selector")
        if not selector:
            continue
        try:
            loc = await _first_visible_locator(page, inp["selector"], prefer_enabled=True)
            current = await _read_text_control(loc, inp.get("type", "text"))
            if current:
                await _sync_native_text_value(loc, current)
        except Exception:
            continue


async def wait_for_composer_idle_before_submit(
    page,
    *,
    submit_selector: str,
    inputs: list[dict] | None = None,
    response_selector: str = "",
    response_within_selector: str = "",
    response_text_within_selector: str = "",
    response_capture_mode: str = "last",
    response_list_selector: str = "",
    response_role_selector: str = "",
    timeout_ms: int = 120_000,
    stable_ms: int = 750,
    require_submit_ready: bool = False,
) -> bool:
    """
    Wait until a chat UI is ready for another send.

    Before fill: waits for the latest assistant reply to stop changing and for prompt
    inputs to be enabled. Send/submit is often disabled until text is entered, so it is
    not required unless ``require_submit_ready`` is True.
    """
    from browser_bot.run_control import raise_if_skip_requested

    submit_sel = (submit_selector or "").strip()
    if not submit_sel and not (response_selector or "").strip() and not inputs:
        return True

    deadline = time.perf_counter() + max(int(timeout_ms or 0), 1000) / 1000.0
    stable_for = max(int(stable_ms or 0), 250) / 1000.0
    response_sel = (response_selector or "").strip()
    last_response_text: str | None = None
    last_response_change = time.perf_counter()
    last_log = 0.0

    while time.perf_counter() < deadline:
        await raise_if_skip_requested()
        submit_ready = await _submit_control_active(page, submit_sel) if submit_sel else True

        response_stable = True
        if response_sel:
            try:
                current = await _response_selector_text(
                    page,
                    response_sel,
                    within_selector=response_within_selector,
                    text_within_selector=response_text_within_selector,
                    capture_mode=response_capture_mode,
                    list_selector=response_list_selector,
                    role_selector=response_role_selector,
                )
            except Exception:
                current = ""
            if last_response_text is None:
                last_response_text = current
                last_response_change = time.perf_counter()
            elif current != last_response_text:
                last_response_text = current
                last_response_change = time.perf_counter()
                response_stable = False
            else:
                response_stable = (time.perf_counter() - last_response_change) >= stable_for

        inputs_ready = True
        for inp in inputs or []:
            if not isinstance(inp, dict):
                continue
            inp_type = (inp.get("type") or "text").lower()
            if inp_type in ("file", "click") or inp.get("upload_prep"):
                continue
            sel = (inp.get("selector") or "").strip()
            if not sel:
                continue
            try:
                loc = await _first_visible_locator(page, sel, prefer_enabled=True)
                if not await loc.is_visible() or not await loc.is_enabled():
                    inputs_ready = False
                    break
            except Exception:
                inputs_ready = False
                break

        if response_sel:
            ready = response_stable and inputs_ready
            if require_submit_ready:
                ready = ready and submit_ready
        elif submit_sel:
            ready = submit_ready and inputs_ready
        else:
            ready = inputs_ready

        if ready:
            return True

        now = time.perf_counter()
        if now - last_log >= 8.0:
            last_log = now
            detail = []
            if require_submit_ready and not submit_ready:
                detail.append("send disabled")
            if response_sel and not response_stable:
                detail.append("reply still updating")
            if not inputs_ready:
                detail.append("prompt input disabled")
            log_resilience(
                "composer_idle",
                "Waiting for chat composer to become ready",
                detail=", ".join(detail) or "polling",
            )

        await asyncio.sleep(0.25)

    return False


async def _ensure_submit_ready(
    page,
    inputs: list[dict],
    submit_selector: str,
    text: str,
    *,
    timeout_ms: int = 5000,
) -> None:
    """Wait for submit to enable; re-sync or keyboard-type prompt fields if needed."""
    if await _wait_for_submit_enabled(page, submit_selector, timeout_ms=1500):
        return

    await _refire_text_input_events(page, inputs)
    if await _wait_for_submit_enabled(page, submit_selector, timeout_ms=1500):
        return

    for inp in inputs:
        inp_type = (inp.get("type") or "text").lower()
        if inp_type not in _TEXT_TYPES or inp.get("upload_prep"):
            continue
        try:
            loc = await _first_visible_locator(page, inp["selector"], prefer_enabled=True)
            await _keyboard_fill_text_control(page, loc, inp_type, text)
        except Exception:
            continue

    await _refire_text_input_events(page, inputs)
    await _wait_for_submit_enabled(page, submit_selector, timeout_ms=timeout_ms)


async def _submit_control_active(page, submit_selector: str) -> bool:
    try:
        loc = await _first_visible_locator(page, submit_selector)
        if not await loc.is_visible():
            return False
        if not await loc.is_enabled():
            return False
        aria = (await loc.get_attribute("aria-disabled") or "").strip().lower()
        if aria in ("true", "1"):
            return False
        return True
    except Exception:
        return False


async def _wait_for_submit_enabled(page, submit_selector: str, timeout_ms: int = 3000) -> bool:
    deadline = time.perf_counter() + max(timeout_ms, 250) / 1000.0
    while time.perf_counter() < deadline:
        if await _submit_control_active(page, submit_selector):
            return True
        await asyncio.sleep(0.1)
    return False


async def _do_one_submit_step(
    page: "Page",
    inputs: list[dict],
    submit_selector: str,
    text: str,
    *,
    response_selector: str = "",
    response_within_selector: str = "",
    response_text_within_selector: str = "",
    response_capture_mode: str = "last",
    response_list_selector: str = "",
    response_role_selector: str = "",
    submit_via: str = "click",
    response_wait_ms: int = 5000,
    baseline_text: str | None = None,
    test_case: dict | None = None,
    suite_path: Path | str | None = None,
    human_behavior: bool = False,
    submission: dict | None = None,
    filter_ctx: ResponseFilterContext | None = None,
    site: str = "",
    component: str = "",
    capture_id: str = "",
    composer_idle_timeout_ms: int = 0,
) -> tuple[str, str | None, str, dict[str, Any]]:
    """Fill inputs, submit, wait for response. No goto.
    Returns (text, response_text, full_content, submission_meta). When baseline_text is provided (multi mode),
    response_text is only the newly added content; full_content is for the next step's baseline."""
    from browser_bot.run_control import SkipCurrentPromptError

    ctx = filter_ctx or filter_context_from_submission(
        submission, text, site=site, component=component
    )
    resolved_capture_id = (
        str(capture_id or "").strip()
        or str((test_case or {}).get("id") or "").strip()
        or "entry"
    )
    try:
        cfg_stable_ms = int((submission or {}).get("response_stable_ms") or 0)
    except (TypeError, ValueError):
        cfg_stable_ms = 0
    effective_stable_ms = cfg_stable_ms if cfg_stable_ms > 0 else 1200
    capture_status: dict[str, Any] = {}
    artifact_path: Path | None = None
    if test_case:
        try:
            from browser_bot.artifacts import resolve_test_artifact

            artifact_path, _vt, _ok = resolve_test_artifact(
                test_case, suite_path=suite_path
            )
        except Exception:
            artifact_path = None

    artifact_uploaded = False

    submit_sel = (submit_selector or "").strip()
    idle_timeout = max(int(composer_idle_timeout_ms or 0), 0)

    # Challenge UIs often hide the composer behind a Start/Begin CTA until clicked.
    # ensure_page_ready_for_submit may already have run surface_prep (avoids double-click
    # and the old 8s readiness stall before the first gate). Keep the page mark so
    # same-page multi-turn does not re-click gates.
    try:
        from browser_bot.page_blockers import _SURFACE_PREP_DONE_ATTR

        surface_already_done = bool(getattr(page, _SURFACE_PREP_DONE_ATTR, False))
    except Exception:
        surface_already_done = False
    if not surface_already_done:
        try:
            await ensure_submission_surface_ready(page, inputs)
        except Exception:
            pass

    if submit_sel or (response_selector or "").strip():
        submit_disabled = bool(submit_sel) and not await _submit_control_active(page, submit_sel)
        if submit_disabled or idle_timeout > 0:
            ready = await wait_for_composer_idle_before_submit(
                page,
                submit_selector=submit_sel,
                inputs=inputs,
                response_selector=response_selector,
                response_within_selector=response_within_selector,
                response_text_within_selector=response_text_within_selector,
                response_capture_mode=response_capture_mode,
                response_list_selector=response_list_selector,
                response_role_selector=response_role_selector,
                timeout_ms=idle_timeout if idle_timeout > 0 else 120_000,
            )
            if not ready:
                log_resilience(
                    "composer_idle",
                    "Composer still busy after wait - submit may fail",
                    detail=f"timeout={idle_timeout or 120_000}ms",
                )

    for inp in inputs:
        inp_type = inp.get("type", "text")
        path_from = inp.get("path_from", "")
        use_artifact = (
            inp_type == "file"
            or path_from == "payload"
            or inp.get("artifact") is True
        )
        use_artifact_menu = inp_type == "click" and inp.get("upload_menu")
        if artifact_path and use_artifact:
            uploaded = await _fill_input(page, inp, text, artifact_path=artifact_path)
            artifact_uploaded = artifact_uploaded or uploaded
        elif artifact_path and use_artifact_menu:
            uploaded = await _fill_input(page, inp, text, artifact_path=artifact_path)
            artifact_uploaded = artifact_uploaded or uploaded
        elif inp_type == "click" or inp.get("upload_prep") or inp.get("surface_prep"):
            # Surface gates already ran in ensure_submission_surface_ready — do not
            # click them again (was ~2× latency for every pre-step).
            if inp.get("surface_prep"):
                continue
            # File-upload prep clicks are optional once the composer is usable
            # (attachment menus disappear).
            if inp.get("upload_prep") and await _text_inputs_usable(page, inputs):
                continue
            try:
                await _fill_input(page, inp, text)
            except Exception:
                continue
        elif inp_type in _TEXT_TYPES:
            await _fill_input(page, inp, text)
        elif inp_type in ("select", "combobox"):
            await _fill_input(page, inp, "")
        else:
            default = inp.get("value", "")
            await _fill_input(page, inp, default if isinstance(default, str) else str(default))

    if artifact_path and not artifact_uploaded:
        artifact_uploaded = await _set_input_files_artifact(page, artifact_path)
        if not artifact_uploaded:
            log_resilience(
                "artifact_upload",
                detail=(
                    f"Could not attach artifact {artifact_path.name}; "
                    "no usable file input or chooser was found"
                ),
            )

    await _refire_text_input_events(page, inputs)
    submit_ready_timeout = 20_000 if (idle_timeout > 0 or submit_sel) else 5000
    await _ensure_submit_ready(
        page, inputs, submit_selector, text, timeout_ms=submit_ready_timeout
    )

    previous_response_text = None
    previous_node_count: int | None = None
    if response_selector and str(response_selector).strip():
        probe_sel = (
            response_list_selector.strip()
            or response_role_selector.strip()
            or response_selector.strip()
        )
        sel = probe_sel
        try:
            has_nodes = await page.locator(sel).count() > 0
        except Exception:
            has_nodes = False
        if has_nodes:
            for _attempt in range(4):
                try:
                    previous_response_text = await _response_selector_text(
                        page,
                        response_selector,
                        within_selector=response_within_selector,
                        text_within_selector=response_text_within_selector,
                        capture_mode=response_capture_mode,
                        list_selector=response_list_selector,
                        role_selector=response_role_selector,
                    )
                    previous_node_count = await _response_selector_visible_count(
                        page,
                        response_selector,
                        within_selector=response_within_selector,
                        capture_mode=response_capture_mode,
                        list_selector=response_list_selector,
                        role_selector=response_role_selector,
                    )
                    chrome_texts = await _response_selector_surface_texts(
                        page,
                        response_selector,
                        within_selector=response_within_selector,
                        text_within_selector=response_text_within_selector,
                        capture_mode=response_capture_mode,
                        list_selector=response_list_selector,
                        role_selector=response_role_selector,
                    )
                    register_pre_submit_chrome(
                        ctx,
                        previous_response_text or "",
                        *chrome_texts,
                        persist=True,
                    )
                    break
                except Exception:
                    if _attempt >= 3:
                        break
                    await asyncio.sleep(0.15)
        else:
            previous_response_text = ""
            previous_node_count = 0

    await asyncio.sleep(0.1)

    submit_loc = await _first_visible_locator(page, submit_selector)
    if not await _wait_for_submit_enabled(page, submit_selector, timeout_ms=8000):
        log_resilience(
            "submit_disabled",
            "Send/submit still disabled after fill - skipping click",
            detail=f"prompt={text[:80]!r}",
        )
        from browser_bot.submit.rejection_detection import (
            OUTCOME_SUBMIT_FAILED,
            apply_submission_outcome,
        )

        return text, None, "", apply_submission_outcome({}, OUTCOME_SUBMIT_FAILED)
    if human_behavior:
        try:
            from browser_bot.browser.human_behavior import human_mouse_wander, human_mouse_move
            import random

            await human_mouse_wander(page, count=1)
            box = await submit_loc.bounding_box()
            if box:
                cx = box["x"] + box["width"] / 2
                cy = box["y"] + box["height"] / 2
                await human_mouse_move(page, cx, cy)
                await asyncio.sleep(random.uniform(0.05, 0.2))
        except Exception:
            pass

    captured = []

    def on_response(response):
        if response.request.method in ("POST", "PUT", "PATCH"):
            captured.append(response)

    page.on("response", on_response)
    try:
        if submit_via == "enter":
            await page.keyboard.press("Enter")
        else:
            await submit_loc.click()

        from browser_bot.submit.rejection_detection import (
            OUTCOME_CLIENT_REJECTED,
            apply_submission_outcome,
            load_rejection_detection_config,
            poll_client_rejection,
            submission_outcome_label,
        )

        rej_cfg = load_rejection_detection_config(submission)
        if rej_cfg.enabled:
            rejected, rej_signals = await poll_client_rejection(
                page,
                submitted_text=text,
                inputs=inputs,
                config=rej_cfg,
                response_selector=response_selector,
                response_within_selector=response_within_selector,
                response_text_within_selector=response_text_within_selector,
                response_capture_mode=response_capture_mode,
                response_list_selector=response_list_selector,
                response_role_selector=response_role_selector,
                previous_response_text=previous_response_text,
                previous_node_count=previous_node_count,
                filter_ctx=ctx,
            )
            if rejected:
                log_resilience(
                    "client_rejected",
                    submission_outcome_label(OUTCOME_CLIENT_REJECTED),
                    detail=", ".join(rej_signals),
                )
                log_genbounty_progress(
                    {
                        "type": "client_rejected",
                        "status": "applied",
                        "signals": rej_signals,
                        "message": submission_outcome_label(OUTCOME_CLIENT_REJECTED),
                    }
                )
                evidence = apply_submission_outcome(
                    {"capture_id": resolved_capture_id},
                    OUTCOME_CLIENT_REJECTED,
                    signals=rej_signals,
                )
                return text, None, "", evidence

        full_content = None
        if response_selector and str(response_selector).strip():
            try:
                full_content = await _wait_for_response_selector_text(
                    page,
                    response_selector,
                    previous_text=previous_response_text,
                    timeout_ms=response_wait_ms,
                    stable_ms=effective_stable_ms,
                    within_selector=response_within_selector,
                    text_within_selector=response_text_within_selector,
                    capture_mode=response_capture_mode,
                    list_selector=response_list_selector,
                    role_selector=response_role_selector,
                    exclude_text=text,
                    previous_node_count=previous_node_count,
                    human_behavior=human_behavior,
                    filter_ctx=ctx,
                    completion_status=capture_status,
                )
            except SkipCurrentPromptError:
                raise
            except Exception:
                pass
        else:
            from browser_bot.run_control import sleep_or_skip

            await sleep_or_skip(response_wait_ms / 1000.0)
            page_origin = page.url.split("/", 3)[:3]
            page_origin_str = "/".join(page_origin) if len(page_origin) >= 3 else ""

            for resp in captured:
                try:
                    req_url = resp.request.url
                    if page_origin_str and not req_url.startswith(page_origin_str):
                        continue
                    body = await resp.text()
                    if body and body.strip():
                        full_content = body
                        break
                except Exception:
                    continue

            if full_content is None:
                for resp in captured:
                    try:
                        body = await resp.text()
                        if body and body.strip():
                            full_content = body
                            break
                    except Exception:
                        continue
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass

    # Only retry on genuine server-side transient failures (rate-limit or 5xx).
    # Ignore 4xx from background app calls (analytics, polling, etc.) that happen
    # to fire during response_wait_ms - those are not submission failures.
    # Also skip if we already captured content: the submit succeeded.
    if full_content is None:
        page_origin = page.url.split("/", 3)[:3]
        page_origin_str = "/".join(page_origin) if len(page_origin) >= 3 else ""
        for resp in captured:
            try:
                status = resp.status
                if not (status == 429 or status >= 500):
                    continue
                req_url = resp.request.url
                if page_origin_str and not req_url.startswith(page_origin_str):
                    continue
                raise NonSuccessResponseError(status, req_url)
            except NonSuccessResponseError:
                raise
            except Exception:
                continue

    full_content = full_content or ""
    if baseline_text is not None and full_content.startswith(baseline_text):
        response_text = full_content[len(baseline_text) :].strip()
    else:
        response_text = full_content if full_content else None

    if (
        response_selector
        and str(response_selector).strip()
        and (not response_text or not is_actionable_response(response_text, ctx))
    ):
        extra_ms = max(int(response_wait_ms * 0.75), 6000)
        try:
            retry_content = await _wait_for_response_selector_text(
                page,
                response_selector,
                previous_text=previous_response_text,
                timeout_ms=extra_ms,
                stable_ms=effective_stable_ms,
                within_selector=response_within_selector,
                text_within_selector=response_text_within_selector,
                capture_mode=response_capture_mode,
                list_selector=response_list_selector,
                role_selector=response_role_selector,
                exclude_text=text,
                previous_node_count=previous_node_count,
                human_behavior=human_behavior,
                filter_ctx=ctx,
                completion_status=capture_status,
            )
        except Exception:
            retry_content = ""
        if retry_content and is_actionable_response(retry_content, ctx):
            full_content = retry_content
            if baseline_text is not None and full_content.startswith(baseline_text):
                response_text = full_content[len(baseline_text) :].strip()
            else:
                response_text = full_content

    raw_response = response_text
    response_text = sanitize_captured_response(response_text, ctx)
    if raw_response and not response_text:
        reason = non_actionable_reason(raw_response, ctx) or "non_actionable"
        log_response_filter_rejection(reason, preview=raw_response)
        # Keep captured DOM text for run logs when post-capture filters reject it - the UI may
        # still have shown this content; dropping to null breaks assessment on later prompts.
        response_text = str(raw_response).strip() or None
    elif not response_text and full_content and str(full_content).strip():
        fallback = sanitize_captured_response(full_content, ctx)
        response_text = fallback or str(full_content).strip() or None

    from browser_bot.submit.rejection_detection import (
        OUTCOME_CLIENT_REJECTED,
        OUTCOME_EXECUTED,
        OUTCOME_TIMEOUT,
        apply_submission_outcome,
        evaluate_client_rejection,
        load_rejection_detection_config,
    )

    rej_cfg = load_rejection_detection_config(submission)
    outcome = OUTCOME_EXECUTED if (response_text and str(response_text).strip()) else OUTCOME_TIMEOUT
    rejection_signals: list[str] = []
    if outcome == OUTCOME_TIMEOUT and rej_cfg.enabled:
        rejected, rejection_signals = await evaluate_client_rejection(
            page,
            submitted_text=text,
            inputs=inputs,
            config=rej_cfg,
            response_selector=response_selector,
            response_within_selector=response_within_selector,
            response_text_within_selector=response_text_within_selector,
            response_capture_mode=response_capture_mode,
            response_list_selector=response_list_selector,
            response_role_selector=response_role_selector,
            previous_response_text=previous_response_text,
            previous_node_count=previous_node_count,
            filter_ctx=ctx,
        )
        if rejected:
            outcome = OUTCOME_CLIENT_REJECTED
            log_resilience(
                "client_rejected",
                "Client-side safety gate rejected prompt (prompt restored)",
                detail=", ".join(rejection_signals),
            )

    submission_meta = apply_submission_outcome(
        {"capture_id": resolved_capture_id},
        outcome,
        signals=rejection_signals if outcome == OUTCOME_CLIENT_REJECTED else None,
    )
    final_text = response_text if (response_text and str(response_text).strip()) else full_content
    if (
        final_text
        and str(final_text).strip()
        and not capture_status.get("stable")
        and capture_status.get("saw_activity")
    ):
        submission_meta["capture_incomplete"] = True
    if artifact_path is not None:
        submission_meta["artifact_delivered"] = bool(artifact_uploaded)
    return (text, response_text, full_content, submission_meta)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def load_run_stop_words(
    suite_path: Path | str | None,
    *,
    category: str | None = None,
) -> list[str]:
    """Load runtime success markers: playbook stop_words plus exploit patterns when enabled."""
    import sys

    root = _project_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from playbooks.stop_words import load_stop_terms_for_run

    return load_stop_terms_for_run(suite_path, category=category)


def response_stop_word_match(
    response: str | None,
    stop_words: list[str],
) -> str | None:
    """Return matched success marker in response, if any."""
    if not stop_words:
        return None
    import sys

    root = _project_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from playbooks.stop_words import find_stop_word_match

    return find_stop_word_match(response or "", stop_words)


RUN_LOG_DIR_ENV = "GENBOUNTY_RUN_LOG_DIR"


def prepare_run_log_dir(site: str, component: str, *, reuse_env: bool = True) -> Path:
    """Create sites/.../logs/probes/{timestamp}/ and set GENBOUNTY_RUN_LOG_DIR."""
    if reuse_env:
        existing = os.environ.get(RUN_LOG_DIR_ENV, "").strip()
        if existing:
            run_dir = Path(existing).expanduser().resolve()
            run_dir.mkdir(parents=True, exist_ok=True)
            os.environ[RUN_LOG_DIR_ENV] = str(run_dir)
            return run_dir

    ensure_component_dir(site, component)
    import sys

    root = _project_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from pipeline.log_paths import new_timestamped_run_dir

    run_dir = new_timestamped_run_dir(site, component, "probes")
    os.environ[RUN_LOG_DIR_ENV] = str(run_dir)
    return run_dir


def run_log_screenshots_dir() -> Path | None:
    """Return sites/.../logs/probes/{timestamp}/screenshots/ when a run log dir is active."""
    raw = os.environ.get(RUN_LOG_DIR_ENV, "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve() / "screenshots"


def resolve_run_log_path(site: str, component: str) -> Path | None:
    """Prefer run_log.json under GENBOUNTY_RUN_LOG_DIR, else newest under logs/probes/."""
    prepared = os.environ.get(RUN_LOG_DIR_ENV, "").strip()
    if prepared:
        candidate = Path(prepared).expanduser().resolve() / "run_log.json"
        if candidate.is_file():
            return candidate
        # A prepared run dir without run_log.json means this run did not execute tests -
        # do not fall back to an older log (that would re-assess stale results).
        return None

    root = _project_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from pipeline.log_paths import list_run_logs

    candidates = list_run_logs(site, component)
    return candidates[0] if candidates else None


def _compact_submission_meta(submission_meta: dict[str, Any] | None) -> dict[str, Any]:
    """Compact submission fields for logs (outcome, rejection, API meta, capture_id)."""
    if not submission_meta or not isinstance(submission_meta, dict):
        return {}
    meta: dict[str, Any] = {}
    outcome = submission_meta.get("submission_outcome")
    if outcome:
        meta["submission_outcome"] = outcome
    signals = submission_meta.get("rejection_signals")
    if signals:
        meta["rejection_signals"] = signals
    if submission_meta.get("capture_incomplete"):
        meta["capture_incomplete"] = True
    if "artifact_delivered" in submission_meta:
        meta["artifact_delivered"] = bool(submission_meta["artifact_delivered"])
    capture_id = str(submission_meta.get("capture_id") or "").strip()
    if capture_id:
        meta["capture_id"] = capture_id
    if submission_meta.get("http_status") is not None:
        try:
            meta["http_status"] = int(submission_meta["http_status"])
        except (TypeError, ValueError):
            pass
    api_error = str(submission_meta.get("api_error") or "").strip()
    if api_error:
        meta["api_error"] = api_error[:800]
    if submission_meta.get("api_refusal"):
        meta["api_refusal"] = True
        for key in ("stop_reason", "refusal_category", "refusal_explanation", "provider_signal"):
            val = str(submission_meta.get(key) or "").strip()
            if val:
                meta[key] = val[:600] if key == "refusal_explanation" else val
    return meta


def _write_run_log(
    site: str,
    component: str,
    results: list[tuple[str, str | None]],
    *,
    multi_batches: list[list[str]] | None = None,
    test_cases: list[dict] | None = None,
    multi_test_cases: list[dict] | None = None,
    suite_path: Path | str | None = None,
    stopped_early: bool = False,
    stop_word_matched: str = "",
    submission_metas: list[dict[str, Any] | None] | None = None,
) -> Path | None:
    """Write run log to sites/.../logs/probes/{timestamp}/run_log.json.

    Uses GENBOUNTY_RUN_LOG_DIR when set (same directory as live run screenshots).
    Otherwise creates a fresh timestamped subdirectory under ``logs/probes/`` so
    attack_log.json and pipeline_report.json written into the same directory are
    naturally scoped to that test run.

    When multi_batches is set (same structure as get_posts_batches), results are grouped
    one batch per multi-shot conversation. Otherwise flat entries (single-shot).
    """
    try:
        from browser_bot.config import infer_strategy_from_suite_path

        ensure_component_dir(site, component)
        prepared = os.environ.get(RUN_LOG_DIR_ENV, "").strip()
        if prepared:
            run_dir = Path(prepared).expanduser().resolve()
            run_dir.mkdir(parents=True, exist_ok=True)
            timestamp = run_dir.name
        else:
            import sys

            root = _project_root()
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            from pipeline.log_paths import new_timestamped_run_dir

            run_dir = new_timestamped_run_dir(site, component, "probes")
            timestamp = run_dir.name
        log_path = run_dir / "run_log.json"

        strategy = infer_strategy_from_suite_path(suite_path)
        source_file = str(suite_path) if suite_path else ""

        from pipeline.response_echo import strip_echoed_prompt_from_response

        entries = []
        for i, (inp, resp) in enumerate(results):
            cleaned = strip_echoed_prompt_from_response(resp, inp)
            row: dict[str, Any] = {
                "input": inp,
                "response": cleaned if cleaned is not None else resp,
            }
            if submission_metas and i < len(submission_metas) and submission_metas[i]:
                row.update(_compact_submission_meta(submission_metas[i]))
            if test_cases and i < len(test_cases):
                tc = test_cases[i]
                if tc.get("id"):
                    row["id"] = tc["id"]
                if tc.get("vector_type"):
                    row["vector_type"] = tc["vector_type"]
                if tc.get("payload"):
                    row["payload"] = tc["payload"]
                try:
                    from browser_bot.artifacts import resolve_test_artifact

                    ap, _, upload_ok = resolve_test_artifact(tc, suite_path=suite_path)
                    if ap:
                        row["artifact_path"] = str(ap)
                    row["upload_ok"] = upload_ok
                except Exception:
                    pass
            entries.append(row)

        use_grouped = (
            multi_batches is not None
            and results
            and sum(len(b) for b in multi_batches) == len(results)
        )

        if use_grouped:
            batches_out: list[dict] = []
            offset = 0
            for batch_index, batch_prompts in enumerate(multi_batches):
                n = len(batch_prompts)
                chunk = results[offset : offset + n]
                batch_start = offset
                offset += n
                turns = []
                for turn_index, (inp, resp) in enumerate(chunk):
                    turn_row: dict[str, Any] = {
                        "turn": turn_index,
                        "input": inp,
                        "response": strip_echoed_prompt_from_response(resp, inp),
                    }
                    meta_idx = batch_start + turn_index
                    if submission_metas and meta_idx < len(submission_metas) and submission_metas[meta_idx]:
                        turn_row.update(_compact_submission_meta(submission_metas[meta_idx]))
                    turns.append(turn_row)
                batch_row: dict[str, Any] = {
                    "batch_index": batch_index,
                    "turn_count": n,
                    "turns": turns,
                }
                if multi_test_cases and batch_index < len(multi_test_cases):
                    tc = multi_test_cases[batch_index]
                    if tc.get("id"):
                        batch_row["id"] = tc["id"]
                    if tc.get("description"):
                        batch_row["description"] = tc["description"]
                    if tc.get("vector_type"):
                        batch_row["vector_type"] = tc["vector_type"]
                    if tc.get("category"):
                        batch_row["category"] = tc["category"]
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
                    turn_cases = tc.get("turns")
                    if isinstance(turn_cases, list):
                        for turn_i, turn in enumerate(turns):
                            if turn_i >= len(turn_cases):
                                break
                            turn_case = turn_cases[turn_i]
                            if not isinstance(turn_case, dict):
                                continue
                            turn_payload = turn_case.get("payload")
                            if isinstance(turn_payload, dict):
                                turn["payload"] = turn_payload
                            try:
                                from browser_bot.artifacts import resolve_test_artifact

                                ap, _, upload_ok = resolve_test_artifact(
                                    turn_case, suite_path=suite_path
                                )
                                if ap:
                                    turn["artifact_path"] = str(ap)
                                turn["upload_ok"] = upload_ok
                            except Exception:
                                pass
                batches_out.append(batch_row)
            log_data: dict[str, Any] = {
                "site": site,
                "component": component,
                "timestamp": timestamp,
                "mode": "multi",
                "batches": batches_out,
            }
        else:
            log_data = {
                "site": site,
                "component": component,
                "timestamp": timestamp,
                "mode": "single",
                "entries": entries,
            }

        if strategy:
            log_data["strategy"] = strategy
        if source_file:
            log_data["source_file"] = source_file
        if stopped_early:
            log_data["stopped_early"] = True
            if stop_word_matched:
                log_data["stop_word_matched"] = stop_word_matched

        with open(log_path, "w") as f:
            json.dump(log_data, f, indent=2)
        return log_path
    except Exception as exc:
        print(f"[-] Failed to write run log: {exc}", flush=True)
        return None


def _write_adaptive_run_log(
    site: str,
    component: str,
    batches: list[dict[str, Any]],
    *,
    suite_path: Path | str | None = None,
    stopped_early: bool = False,
    stop_word_matched: str = "",
) -> Path | None:
    """Write adaptive run log under ``logs/probes/{timestamp}/``."""
    try:
        ensure_component_dir(site, component)
        prepared = os.environ.get(RUN_LOG_DIR_ENV, "").strip()
        if prepared:
            run_dir = Path(prepared).expanduser().resolve()
            run_dir.mkdir(parents=True, exist_ok=True)
            timestamp = run_dir.name
        else:
            import sys

            root = _project_root()
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            from pipeline.log_paths import new_timestamped_run_dir

            run_dir = new_timestamped_run_dir(site, component, "probes")
            timestamp = run_dir.name
        log_path = run_dir / "run_log.json"

        source_file = str(suite_path) if suite_path else ""
        log_data: dict[str, Any] = {
            "site": site,
            "component": component,
            "timestamp": timestamp,
            "mode": "adaptive",
            "strategy": "adaptive",
            "batches": batches,
        }
        if source_file:
            log_data["source_file"] = source_file
        if stopped_early:
            log_data["stopped_early"] = True
            if stop_word_matched:
                log_data["stop_word_matched"] = stop_word_matched

        from pipeline.response_echo import sanitize_run_log

        log_data = sanitize_run_log(log_data)

        with open(log_path, "w") as f:
            json.dump(log_data, f, indent=2)
        return log_path
    except Exception as exc:
        print(f"[-] Failed to write adaptive run log: {exc}", flush=True)
        return None
