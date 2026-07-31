from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from web.paths import ROOT

router = APIRouter()


@router.get("/api/sites/{site}/{component}/logs")
async def api_component_logs(site: str, component: str):
    from pipeline.log_paths import (
        component_logs_dir,
        label_log_path,
        list_attack_logs,
        list_pipeline_reports,
        list_run_logs,
    )

    try:
        logs_dir = component_logs_dir(site, component)
    except ValueError:
        return {"runs": [], "attacks": [], "reports": []}
    if not logs_dir.is_dir():
        return {"runs": [], "attacks": [], "reports": []}

    # probes/<ts>/run_log.json; probes/<ts>/ + manual/ + manual/<ts>/ for attack_log & reports.
    runs = list_run_logs(site, component)
    attacks = list_attack_logs(site, component)
    reports = list_pipeline_reports(site, component)

    def _entry(p: Path) -> dict:
        return {
            "name": label_log_path(logs_dir, p),
            "path": str(p),
            "mtime": p.stat().st_mtime,
        }

    return {
        "runs": [_entry(p) for p in runs],
        "attacks": [_entry(p) for p in attacks],
        "reports": [_entry(p) for p in reports],
    }


@router.get("/api/files")
async def api_read_file(path: str):
    """Read a JSON file by absolute path (scoped to project root for safety)."""
    p = Path(path)
    if not str(p).startswith(str(ROOT)):
        raise HTTPException(403, "Path outside project root")
    if not p.exists():
        raise HTTPException(404, "File not found")
    data = json.loads(p.read_text(encoding="utf-8"))
    if p.name == "run_log.json":
        from pipeline.response_echo import sanitize_run_log

        data = sanitize_run_log(data)
    return data


@router.get("/api/log")
async def api_serve_log(path: str):
    """Return the raw JSON contents of a log file by absolute path."""
    p = Path(path)
    if not p.is_absolute():
        raise HTTPException(400, "Path must be absolute")
    if not p.exists():
        raise HTTPException(404, "File not found")
    # Safety: only allow files under the workspace root
    try:
        p.resolve().relative_to(ROOT.resolve())
    except ValueError:
        raise HTTPException(403, "Access denied")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(500, str(exc))
