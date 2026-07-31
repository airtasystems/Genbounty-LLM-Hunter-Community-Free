"""Shared transient-error retry for all providers.

Generalizes the Gemini-only ``_gemini_call_with_retry`` from the risk agent so
every provider gets consistent backoff on 429 / 503 / rate-limit errors. Uses
``tenacity`` when available, otherwise a stdlib exponential-backoff loop.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Callable

from pipeline.llm.config import defaults

logger = logging.getLogger(__name__)

try:
    from tenacity import (
        retry as _tenacity_retry,
        retry_if_exception as _retry_if_exception,
        stop_after_attempt as _stop_after_attempt,
        wait_exponential as _wait_exponential,
        wait_random as _wait_random,
    )

    _TENACITY_AVAILABLE = True
except ImportError:  # pragma: no cover - tenacity is a listed dependency
    _TENACITY_AVAILABLE = False

_RETRYABLE_TOKENS = (
    "503",
    "unavailable",
    "429",
    "resource_exhausted",
    "rate limit",
    "rate_limit",
    "quota exceeded",
    "overloaded",
    "too many requests",
    "timeout",
    "temporarily",
)

# Short initial backoff with jitter so a single transient 429/503 doesn't stall a
# run for minutes; the high cap is retained only for sustained rate limiting.
_DEFAULT_ATTEMPTS = 4
_DEFAULT_MIN_SECS = 3.0
_DEFAULT_MAX_SECS = 90.0
_JITTER_SECS = 5.0


def is_transient(exc: BaseException) -> bool:
    """Best-effort detection of retryable transient API errors across providers."""
    err = str(exc).lower()
    if any(tok in err for tok in _RETRYABLE_TOKENS):
        return True
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status in (429, 500, 502, 503, 504):
        return True
    return False


def _retry_params() -> tuple[int, float, float]:
    cfg = defaults().get("retry") if isinstance(defaults().get("retry"), dict) else {}
    attempts = int(cfg.get("attempts", _DEFAULT_ATTEMPTS) or _DEFAULT_ATTEMPTS)
    backoff_min = float(cfg.get("backoff_min", _DEFAULT_MIN_SECS) or _DEFAULT_MIN_SECS)
    backoff_max = float(cfg.get("backoff_max", _DEFAULT_MAX_SECS) or _DEFAULT_MAX_SECS)
    return max(1, attempts), backoff_min, backoff_max


def call_with_retry(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call ``fn`` with exponential backoff on transient errors."""
    attempts, backoff_min, backoff_max = _retry_params()

    if _TENACITY_AVAILABLE:
        def _before_sleep(retry_state: Any) -> None:
            exc = retry_state.outcome.exception()
            logger.warning(
                "LLM transient error (attempt %d/%d): %s - retrying...",
                retry_state.attempt_number,
                attempts,
                exc,
            )

        decorated = _tenacity_retry(
            stop=_stop_after_attempt(attempts),
            retry=_retry_if_exception(is_transient),
            wait=_wait_exponential(min=backoff_min, max=backoff_max)
            + _wait_random(0, _JITTER_SECS),
            before_sleep=_before_sleep,
            reraise=True,
        )(lambda: fn(*args, **kwargs))
        return decorated()

    delay = backoff_min
    for attempt in range(1, attempts + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - re-raised below when not transient
            if attempt == attempts or not is_transient(exc):
                raise
            jitter = random.uniform(-_JITTER_SECS, _JITTER_SECS)
            wait = min(max(0.0, delay + jitter), backoff_max)
            logger.warning(
                "LLM transient error (attempt %d/%d): %s - retrying in %.0fs...",
                attempt,
                attempts,
                exc,
                wait,
            )
            time.sleep(wait)
            delay = min(delay * 2, backoff_max)
