"""Canonical per-component log layout: probes / manual.

Under ``browser-bot/sites/<site>/<component>/logs/``:

- ``probes/<timestamp>/`` - suite Run Tests (timestamped)
- ``manual/<timestamp>/`` - Firing Range Fire+Assess (timestamped)
- ``manual/attack_log.json`` - legacy consolidated Firing Range assess (still listed)

No legacy top-level timestamp, ``manual_command/``, or ``logs/attack/`` paths.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

_ROOT = Path(__file__).resolve().parent.parent

LOG_KIND_PROBES = "probes"
LOG_KIND_MANUAL = "manual"
LOG_KINDS = (LOG_KIND_PROBES, LOG_KIND_MANUAL)

STRATEGY_MANUAL = "manual"


def component_logs_dir(site: str, component: str) -> Path:
    site = (site or "").strip()
    component = (component or "").strip()
    if not site or not component:
        raise ValueError("site and component are required")
    try:
        bb_dir = _ROOT / "browser-bot"
        import sys

        if str(bb_dir) not in sys.path:
            sys.path.insert(0, str(bb_dir))
        from browser_bot.sites import get_component_path

        return get_component_path(site, component) / "logs"
    except Exception:
        return _ROOT / "browser-bot" / "sites" / site / component / "logs"


def probes_logs_dir(site: str, component: str) -> Path:
    return component_logs_dir(site, component) / LOG_KIND_PROBES


def manual_logs_dir(site: str, component: str) -> Path:
    return component_logs_dir(site, component) / LOG_KIND_MANUAL


def _timestamp_slug() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def new_timestamped_run_dir(site: str, component: str, kind: str) -> Path:
    """Create and return ``logs/<probes|manual>/<timestamp>/``."""
    kind = (kind or "").strip().lower()
    if kind == LOG_KIND_PROBES:
        base = probes_logs_dir(site, component)
    elif kind == LOG_KIND_MANUAL:
        base = manual_logs_dir(site, component)
    else:
        raise ValueError(f"timestamped dirs only for probes|manual, not {kind!r}")
    run_dir = (base / _timestamp_slug()).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def is_hidden_log_path(path: Path, logs_dir: Path) -> bool:
    """True when a log path is under a private ``_*`` directory (e.g. ``_batch``)."""
    try:
        rel = path.resolve().relative_to(logs_dir.resolve())
    except ValueError:
        return False
    return any(part.startswith("_") for part in rel.parts)


def log_kind_for_path(path: Path, logs_dir: Path) -> str:
    """Return probes|manual when path is under that lane; else empty."""
    try:
        rel = path.resolve().relative_to(logs_dir.resolve())
    except ValueError:
        return ""
    parts = rel.parts
    if not parts:
        return ""
    kind = parts[0]
    return kind if kind in LOG_KINDS else ""


def label_log_path(logs_dir: Path, path: Path) -> str:
    """Human-friendly label relative to the component logs dir."""
    try:
        rel = path.resolve().relative_to(logs_dir.resolve())
        return str(rel).replace("\\", "/")
    except ValueError:
        if path.parent != logs_dir:
            return f"{path.parent.name} / {path.name}"
        return path.name


def _mtime_sorted(paths: Iterable[Path]) -> list[Path]:
    return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)


def list_run_logs(site: str, component: str) -> list[Path]:
    """Probe-lane run_log.json paths, newest first."""
    logs_dir = component_logs_dir(site, component)
    probes = logs_dir / LOG_KIND_PROBES
    if not probes.is_dir():
        return []
    paths = [p for p in probes.glob("*/run_log.json") if p.is_file()]
    paths = [p for p in paths if not is_hidden_log_path(p, logs_dir)]
    return _mtime_sorted(paths)


def _manual_lane_files(logs_dir: Path, filename: str) -> list[Path]:
    """Legacy ``manual/<file>`` plus timestamped ``manual/<ts>/<file>``."""
    manual = logs_dir / LOG_KIND_MANUAL
    if not manual.is_dir():
        return []
    found: list[Path] = []
    legacy = manual / filename
    if legacy.is_file():
        found.append(legacy)
    found.extend(manual.glob(f"*/{filename}"))
    return found


def list_attack_logs(
    site: str,
    component: str,
    *,
    kinds: Iterable[str] | None = None,
) -> list[Path]:
    """Attack log paths under selected lanes, newest first."""
    logs_dir = component_logs_dir(site, component)
    if not logs_dir.is_dir():
        return []
    wanted = {str(k).strip().lower() for k in (kinds or LOG_KINDS) if str(k).strip()}
    wanted &= set(LOG_KINDS)
    found: list[Path] = []
    if LOG_KIND_PROBES in wanted:
        probes = logs_dir / LOG_KIND_PROBES
        if probes.is_dir():
            found.extend(probes.glob("*/attack_log.json"))
    if LOG_KIND_MANUAL in wanted:
        found.extend(_manual_lane_files(logs_dir, "attack_log.json"))
    found = [p for p in found if p.is_file() and not is_hidden_log_path(p, logs_dir)]
    return _mtime_sorted(found)


def list_pipeline_reports(
    site: str,
    component: str,
    *,
    kinds: Iterable[str] | None = None,
) -> list[Path]:
    """Pipeline report paths under selected lanes, newest first."""
    logs_dir = component_logs_dir(site, component)
    if not logs_dir.is_dir():
        return []
    wanted = {str(k).strip().lower() for k in (kinds or LOG_KINDS) if str(k).strip()}
    wanted &= set(LOG_KINDS)
    found: list[Path] = []
    if LOG_KIND_PROBES in wanted:
        probes = logs_dir / LOG_KIND_PROBES
        if probes.is_dir():
            found.extend(probes.glob("*/pipeline_report.json"))
    if LOG_KIND_MANUAL in wanted:
        found.extend(_manual_lane_files(logs_dir, "pipeline_report.json"))
    found = [p for p in found if p.is_file() and not is_hidden_log_path(p, logs_dir)]
    return _mtime_sorted(found)


def is_probe_log_path(path: Path, site: str = "", component: str = "") -> bool:
    """True when path lives under ``logs/probes/``."""
    p = Path(path)
    if site and component:
        try:
            return log_kind_for_path(p, component_logs_dir(site, component)) == LOG_KIND_PROBES
        except ValueError:
            pass
    # …/logs/probes/<ts>/file
    try:
        idx = [x.lower() for x in p.parts].index("logs")
        return idx + 1 < len(p.parts) and p.parts[idx + 1].lower() == LOG_KIND_PROBES
    except ValueError:
        return LOG_KIND_PROBES in {x.lower() for x in p.parts}
