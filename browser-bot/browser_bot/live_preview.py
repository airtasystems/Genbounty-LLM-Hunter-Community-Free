"""Periodic browser screenshots for live Run Tests preview in the web UI."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator

from typing import TYPE_CHECKING, AsyncIterator

if TYPE_CHECKING:
    from playwright.async_api import Page

_DEFAULT_INTERVAL_S = 0.0
_MIN_INTERVAL_S = 1.0

_slot_lock = asyncio.Lock()
_active_job_id: str | None = None
_page_slots: dict[int, int] = {}
_next_slot = 0
_slot_sequences: dict[int, int] = {}


def _log_progress(payload: dict) -> None:
    from browser_bot.submit.common import log_genbounty_progress

    log_genbounty_progress(payload)


def _shots_dir() -> Path | None:
    from browser_bot.submit.common import run_log_screenshots_dir

    raw = run_log_screenshots_dir()
    return raw.resolve() if raw else None


def preview_filename(job_id: str, slot: int, sequence: int | None = None) -> str:
    if sequence is None:
        return f"{job_id}_{slot}.png"
    return f"{job_id}_{slot}_{sequence:04d}.png"


def preview_filename_glob(job_id: str, slot: int) -> str:
    """Glob pattern matching all archived frames for a job slot."""
    return f"{job_id}_{slot}_*.png"


def preview_path(
    job_id: str,
    slot: int = 0,
    *,
    run_log_dir: str | None = None,
    sequence: int | None = None,
) -> Path:
    """Filesystem path for a job preview screenshot."""
    shots_dir: Path | None = None
    if run_log_dir:
        shots_dir = Path(run_log_dir).expanduser().resolve() / "screenshots"
    else:
        raw = _shots_dir()
        shots_dir = raw
    if not shots_dir:
        return Path("")
    return shots_dir / preview_filename(job_id, slot, sequence)


def _latest_preview_in_dir(shots_dir: Path, job_id: str, slot: int) -> Path | None:
    if not shots_dir.is_dir():
        return None
    matches = sorted(
        shots_dir.glob(preview_filename_glob(job_id, slot)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if matches:
        return matches[0]
    legacy = shots_dir / preview_filename(job_id, slot)
    return legacy if legacy.is_file() else None


def find_preview_path(
    job_id: str,
    slot: int,
    *,
    run_log_dir: str | None = None,
    site: str | None = None,
    component: str | None = None,
) -> Path | None:
    """Resolve the newest preview PNG for a job slot (live UI + archived frames)."""
    if run_log_dir:
        found = _latest_preview_in_dir(
            Path(run_log_dir).expanduser().resolve() / "screenshots",
            job_id,
            slot,
        )
        if found:
            return found

    raw = _shots_dir()
    if raw:
        found = _latest_preview_in_dir(raw, job_id, slot)
        if found:
            return found

    if not (site and component):
        return None

    from browser_bot.sites import get_component_path

    logs_dir = get_component_path(site, component) / "logs"
    glob_pattern = preview_filename_glob(job_id, slot)
    matches = sorted(
        logs_dir.glob(f"probes/*/screenshots/{glob_pattern}"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if matches:
        return matches[0]

    legacy_matches = sorted(
        logs_dir.glob(f"probes/*/screenshots/{preview_filename(job_id, slot)}"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return legacy_matches[0] if legacy_matches else None


def screenshot_interval_s(
    *,
    site: str | None = None,
    component: str | None = None,
) -> float:
    """Resolved seconds between run-test preview captures. ``0`` means disabled."""
    site = (site or os.getenv("GENBOUNTY_SITE") or "").strip() or None
    component = (component or os.getenv("GENBOUNTY_COMPONENT") or "").strip() or None
    try:
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from pipeline.component_settings import get_effective_setting

        val = get_effective_setting(
            "RUN_SCREENSHOT_INTERVAL_S",
            site=site,
            component=component,
        )
        if val is not None:
            interval = float(val)
            if interval <= 0:
                return 0.0
            return max(_MIN_INTERVAL_S, interval)
    except Exception:
        pass
    try:
        from browser_bot.config import RUN_SCREENSHOT_INTERVAL_S

        interval = float(RUN_SCREENSHOT_INTERVAL_S)
        if interval <= 0:
            return 0.0
        return max(_MIN_INTERVAL_S, interval)
    except Exception:
        return _DEFAULT_INTERVAL_S


def screenshots_enabled(
    *,
    site: str | None = None,
    component: str | None = None,
) -> bool:
    """True when run-preview screenshots should be captured."""
    return screenshot_interval_s(site=site, component=component) > 0


async def _allocate_slot(page: "Page", job_id: str) -> int:
    global _active_job_id, _page_slots, _next_slot, _slot_sequences
    async with _slot_lock:
        if job_id != _active_job_id:
            _active_job_id = job_id
            _page_slots.clear()
            _slot_sequences.clear()
            _next_slot = 0
        page_id = id(page)
        if page_id not in _page_slots:
            _page_slots[page_id] = _next_slot
            _next_slot += 1
        return _page_slots[page_id]


def _next_sequence_locked(job_id: str, slot: int) -> int:
    global _active_job_id, _slot_sequences
    if job_id != _active_job_id:
        _active_job_id = job_id
        _slot_sequences.clear()
    seq = _slot_sequences.get(slot, 0)
    _slot_sequences[slot] = seq + 1
    return seq


async def _next_sequence(job_id: str, slot: int) -> int:
    async with _slot_lock:
        return _next_sequence_locked(job_id, slot)


async def capture_preview_screenshot(page: "Page", *, job_id: str | None = None) -> int | None:
    """Capture one live-preview frame immediately. Returns sequence when saved, else None."""
    if not screenshots_enabled():
        return None
    jid = (job_id or os.environ.get("GENBOUNTY_JOB_ID", "")).strip()
    shots_dir = _shots_dir()
    if not jid or not shots_dir:
        return None
    shots_dir.mkdir(parents=True, exist_ok=True)
    slot = await _allocate_slot(page, jid)
    seq = await _next_sequence(jid, slot)
    path = shots_dir / preview_filename(jid, slot, seq)
    try:
        await page.screenshot(path=str(path), full_page=False, timeout=10000)
    except Exception as exc:
        print(
            f"[warn] Live preview screenshot failed (job={jid}, slot={slot}): {exc}",
            flush=True,
        )
        return None
    try:
        if not path.is_file() or path.stat().st_size < 64:
            print(
                f"[warn] Live preview screenshot empty (job={jid}, slot={slot}, path={path})",
                flush=True,
            )
            return None
    except OSError as exc:
        print(f"[warn] Live preview screenshot unreadable: {exc}", flush=True)
        return None
    _log_progress(
        {"type": "screenshot", "job_id": jid, "slot": slot, "sequence": seq}
    )
    return seq


async def _screenshot_loop(page: "Page", job_id: str, slot: int, stop: asyncio.Event) -> None:
    shots_dir = _shots_dir()
    if not shots_dir:
        return
    interval_s = screenshot_interval_s()
    if interval_s <= 0:
        return
    shots_dir.mkdir(parents=True, exist_ok=True)
    while not stop.is_set():
        await capture_preview_screenshot(page, job_id=job_id)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
        except asyncio.TimeoutError:
            continue


@asynccontextmanager
async def live_preview_context(page: "Page") -> AsyncIterator[None]:
    """Capture screenshots on an interval while the page session is active."""
    job_id = os.environ.get("GENBOUNTY_JOB_ID", "").strip()
    if not job_id or not _shots_dir() or not screenshots_enabled():
        yield
        return

    slot = await _allocate_slot(page, job_id)
    stop = asyncio.Event()
    task = asyncio.create_task(_screenshot_loop(page, job_id, slot, stop))
    try:
        yield
    finally:
        stop.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        _log_progress({"type": "screenshot_closed", "job_id": job_id, "slot": slot})
