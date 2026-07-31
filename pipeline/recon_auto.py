"""Persist playbook intel from a pipeline_report.json (shared by workers and job hooks)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent


def save_intel_from_pipeline_report(
    site: str,
    component: str,
    report_path: Path | str,
) -> Path:
    """Merge report intel into intel/{playbook_id}.json and write the updated file."""
    site = (site or "").strip()
    component = (component or "").strip()
    if not site or not component:
        raise ValueError("site and component are required for intel auto-update")

    if str(_ROOT) not in __import__("sys").path:
        __import__("sys").path.insert(0, str(_ROOT))
    bb_dir = _ROOT / "browser-bot"
    if str(bb_dir) not in __import__("sys").path:
        __import__("sys").path.insert(0, str(bb_dir))

    from browser_bot.sites import ensure_component_dir
    from pipeline.intel import save_playbook_intel
    from pipeline.recon_from_report import merge_intel_from_pipeline_report

    merged: dict[str, Any] = merge_intel_from_pipeline_report(site, component, report_path)
    ensure_component_dir(site, component)
    return save_playbook_intel(site, component, merged)


def save_recon_from_pipeline_report(
    site: str,
    component: str,
    report_path: Path | str,
) -> Path:
    """Backward-compatible alias - writes playbook intel, not recon.json."""
    return save_intel_from_pipeline_report(site, component, report_path)
