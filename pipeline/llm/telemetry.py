"""Unified telemetry hook for assistant LLM calls.

Single place that records role, provider, model, latency, and output size for
every completion. Emits a structured ``[llm]`` log line and invokes an optional
observer callback so richer telemetry (token usage, tracing) can be layered on
without touching call sites.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, List, Optional

from pipeline.llm.base import LLMResponse

logger = logging.getLogger("pipeline.llm")

# Observers receive a dict describing the call. Kept intentionally simple.
_OBSERVERS: List[Callable[[dict], None]] = []


def add_observer(fn: Callable[[dict], None]) -> None:
    _OBSERVERS.append(fn)


def clear_observers() -> None:
    _OBSERVERS.clear()


def record(
    *,
    role: str,
    provider: str,
    model: str,
    latency_s: float,
    response: Optional[LLMResponse] = None,
    error: Optional[BaseException] = None,
) -> None:
    chars = len((response.text or "")) if response is not None else 0
    cache_hit = bool(response.cache_hit) if response is not None else False
    event: dict[str, Any] = {
        "role": role,
        "provider": provider,
        "model": model,
        "latency_s": round(latency_s, 3),
        "chars": chars,
        "cache_hit": cache_hit,
        "ok": error is None,
    }
    if error is not None:
        event["error"] = str(error)
        logger.warning(
            "[llm] role=%s provider=%s model=%s latency=%.2fs error=%s",
            role, provider, model, latency_s, error,
        )
    else:
        logger.info(
            "[llm] role=%s provider=%s model=%s latency=%.2fs chars=%d cache=%s",
            role, provider, model, latency_s, chars, "hit" if cache_hit else "miss",
        )
    for obs in list(_OBSERVERS):
        try:
            obs(event)
        except Exception:  # pragma: no cover - observers must never break calls
            logger.debug("LLM telemetry observer failed", exc_info=True)
