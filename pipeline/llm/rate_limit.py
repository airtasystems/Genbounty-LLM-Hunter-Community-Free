"""Optional token-bucket rate limiter for assistant LLM calls.

Two independent layers, both off unless configured in ``llm.yaml``:

* **Global** - ``defaults.rate_limit.capacity`` / ``refill_per_sec``. Applies
  to every call regardless of provider.
* **Per-provider RPM** - ``defaults.rate_limit.per_provider: {openai: 500, ...}``.
  Smooths bursts so parallel generation/assessment fan-out doesn't trip a
  provider's per-minute limit. A bucket starts full (burst of one minute's
  worth), then throttles sustained throughput to the configured RPM.

When neither layer is configured for a call it is a no-op.
"""

from __future__ import annotations

import threading
import time
from typing import Dict, Optional

from pipeline.llm.config import defaults, ensure_env_loaded


class _TokenBucket:
    def __init__(self, capacity: float, refill_per_sec: float) -> None:
        self.capacity = capacity
        self.refill_per_sec = refill_per_sec
        self._tokens = capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last
                self._last = now
                self._tokens = min(
                    self.capacity, self._tokens + elapsed * self.refill_per_sec
                )
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                needed = tokens - self._tokens
                wait = needed / self.refill_per_sec if self.refill_per_sec > 0 else 0.05
            time.sleep(min(wait, 5.0))


_LOCK = threading.Lock()
_GLOBAL: Optional[_TokenBucket] = None
_PROVIDER: Dict[str, Optional[_TokenBucket]] = {}
_INITIALIZED = False


def _rate_cfg() -> dict:
    ensure_env_loaded()
    cfg = defaults().get("rate_limit")
    return cfg if isinstance(cfg, dict) else {}


def _global_values(cfg: dict) -> tuple[float, float]:
    def _num(cfg_key: str) -> float:
        raw = cfg.get(cfg_key)
        try:
            return float(raw) if raw is not None and str(raw).strip() else 0.0
        except (TypeError, ValueError):
            return 0.0

    return _num("capacity"), _num("refill_per_sec")


def _provider_rpm(cfg: dict, provider: str) -> float:
    per = cfg.get("per_provider")
    raw = per.get(provider) if isinstance(per, dict) else None
    try:
        return float(raw) if raw is not None and str(raw).strip() else 0.0
    except (TypeError, ValueError):
        return 0.0


def _init() -> None:
    global _GLOBAL, _INITIALIZED
    with _LOCK:
        if _INITIALIZED:
            return
        cap, refill = _global_values(_rate_cfg())
        _GLOBAL = _TokenBucket(cap, refill) if cap > 0 and refill > 0 else None
        _INITIALIZED = True


def _provider_bucket(provider: str) -> Optional[_TokenBucket]:
    if provider in _PROVIDER:
        return _PROVIDER[provider]
    with _LOCK:
        if provider in _PROVIDER:
            return _PROVIDER[provider]
        rpm = _provider_rpm(_rate_cfg(), provider)
        bucket = (
            _TokenBucket(capacity=max(1.0, rpm), refill_per_sec=rpm / 60.0)
            if rpm > 0
            else None
        )
        _PROVIDER[provider] = bucket
        return bucket


def acquire(tokens: float = 1.0, provider: Optional[str] = None) -> None:
    """Block until a token is available (no-op when rate limiting is disabled)."""
    if not _INITIALIZED:
        _init()
    if _GLOBAL is not None:
        _GLOBAL.acquire(tokens)
    if provider:
        bucket = _provider_bucket(provider)
        if bucket is not None:
            bucket.acquire(tokens)


def reset() -> None:
    """Test hook: force re-reading rate-limit configuration."""
    global _GLOBAL, _INITIALIZED
    with _LOCK:
        _GLOBAL = None
        _PROVIDER.clear()
        _INITIALIZED = False
