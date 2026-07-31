"""Operator controls during Run Tests (skip in-flight prompt via stdin).

The stdin reader runs on a dedicated **daemon** thread rather than the asyncio
default executor. A blocking ``sys.stdin.readline()`` on a default-executor
thread would make ``asyncio.run()`` hang on shutdown (``shutdown_default_executor``
waits for that thread), because the web job keeps the stdin pipe open and never
sends EOF. Daemon threads are never awaited at interpreter/loop shutdown, so the
run subprocess can finish, convert its run log, and continue to assessment.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from typing import Any

_skip_event = threading.Event()
_armed = threading.Event()
_reader_thread: threading.Thread | None = None
_reader_lock = threading.Lock()


class SkipCurrentPromptError(Exception):
    """Raised when the operator requests skipping the in-flight prompt."""


def clear_skip_request() -> None:
    _skip_event.clear()


def skip_requested() -> bool:
    return _skip_event.is_set()


def _parse_line(line: str) -> dict[str, Any]:
    stripped = (line or "").strip()
    if not stripped:
        return {"type": "continue"}
    try:
        data = json.loads(stripped)
        return data if isinstance(data, dict) else {"type": "unknown", "raw": stripped}
    except json.JSONDecodeError:
        return {"type": "unknown", "raw": stripped}


def _is_skip_current_message(msg: dict[str, Any]) -> bool:
    mtype = str(msg.get("type") or "").strip().lower().replace("-", "_")
    if mtype in ("skip_current", "skip_prompt"):
        return True
    if mtype == "unknown":
        raw = str(msg.get("raw") or "").strip().lower().replace("-", " ")
        return raw in ("skip_current", "skip current", "skip prompt")
    return False


def log_skip_current_requested() -> None:
    from browser_bot.submit.common import log_genbounty_progress, log_resilience

    log_resilience("skip_current", "Operator requested skip - aborting current prompt")
    log_genbounty_progress({"type": "skip_current", "status": "requested"})


def log_skip_current_applied() -> None:
    from browser_bot.submit.common import log_genbounty_progress, log_resilience

    log_resilience("skip_current", "Skipped current prompt with null response - continuing")
    log_genbounty_progress({"type": "skip_current", "status": "applied"})


def _reader_loop() -> None:
    """Read stdin for the process lifetime; act on skip requests only while armed."""
    while True:
        try:
            line = sys.stdin.readline()
        except Exception:
            return
        if not line:  # EOF - stdin closed, nothing more to read
            return
        if not _armed.is_set():
            continue
        msg = _parse_line(line)
        if _is_skip_current_message(msg):
            _skip_event.set()
            try:
                log_skip_current_requested()
            except Exception:
                pass


def _ensure_reader_thread() -> None:
    global _reader_thread
    with _reader_lock:
        if _reader_thread is not None and _reader_thread.is_alive():
            return
        _reader_thread = threading.Thread(
            target=_reader_loop, name="run-control-stdin", daemon=True
        )
        _reader_thread.start()


async def raise_if_skip_requested() -> None:
    if skip_requested():
        raise SkipCurrentPromptError()


async def sleep_or_skip(seconds: float) -> None:
    """Sleep in short slices so skip can interrupt."""
    if seconds <= 0:
        await raise_if_skip_requested()
        return
    loop = asyncio.get_running_loop()
    end = loop.time() + seconds
    while loop.time() < end:
        await raise_if_skip_requested()
        remaining = end - loop.time()
        await asyncio.sleep(min(0.25, remaining))


async def arm_run_control() -> None:
    clear_skip_request()
    _armed.set()
    _ensure_reader_thread()


def disarm_run_control() -> None:
    _armed.clear()
    clear_skip_request()


async def await_with_skip(awaitable: Any) -> Any:
    """Run *awaitable*; raise SkipCurrentPromptError if skip is requested while waiting."""
    task = asyncio.ensure_future(awaitable)
    try:
        while not task.done():
            await raise_if_skip_requested()
            await asyncio.wait({task}, timeout=0.25)
        return task.result()
    except SkipCurrentPromptError:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        raise
