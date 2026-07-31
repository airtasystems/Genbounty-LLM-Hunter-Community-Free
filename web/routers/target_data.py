from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re as _re
import sys
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from web.paths import BB_DIR, ROOT, ensure_generate_tests_path

router = APIRouter()

STRATEGIES = [
    "zero_shot", "adaptive", "multi_shot", "few_shot", "iterative", "chain_of_thought",
    "prompt_chaining", "tree_of_thoughts", "self_consistency", "self_reflection",
    "directional_stimulus", "jailbreak", "multimodal",
]

from browser_bot.sites import (
    get_component_path,
    load_component_config,
)

@router.get("/api/sites/{site}/{component}/recon")
def api_get_recon(site: str, component: str):
    from browser_bot.sites import get_recon_path

    path = get_recon_path(site, component)
    if not path.is_file():
        return {"exists": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise HTTPException(500, f"Failed to read recon.json: {exc}") from exc
    return {"exists": True, "data": data, "path": str(path)}


class SaveReconBody(BaseModel):
    data: dict


@router.put("/api/sites/{site}/{component}/recon")
async def api_save_recon(site: str, component: str, body: SaveReconBody):
    if not isinstance(body.data, dict):
        raise HTTPException(400, "data must be a JSON object")
    from browser_bot.sites import ensure_component_dir, get_recon_path

    ensure_component_dir(site, component)
    path = get_recon_path(site, component)
    path.write_text(json.dumps(body.data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"ok": True, "path": str(path)}


@router.delete("/api/sites/{site}/{component}/recon")
async def api_delete_recon(site: str, component: str):
    from browser_bot.sites import get_recon_path

    path = get_recon_path(site, component)
    if path.is_file():
        path.unlink()
    return {"ok": True}


@router.get("/api/sites/{site}/{component}/capabilities")
async def api_get_capabilities(site: str, component: str, playbook: str = ""):
    from pipeline.recon_context import detect_capabilities, load_component_recon, load_effective_recon
    from playbooks.registry import normalize_playbook_id

    pid = normalize_playbook_id(playbook) if playbook else ""
    recon = load_effective_recon(site, component, pid) if pid else load_component_recon(site, component)
    return {
        "capabilities": detect_capabilities(site, component, playbook_id=pid),
        "recon_loaded": recon is not None,
        "recon_confirmation_status": str(recon.get("confirmation_status") or "") if recon else "",
        "intel_playbook_id": pid or None,
    }


class SaveIntelBody(BaseModel):
    data: dict


class SaveNotesBody(BaseModel):
    data: dict


class AppendNoteBody(BaseModel):
    body: str = ""
    title: str = ""
    source: str = "manual"


class AppendManualQueryBody(BaseModel):
    prompt: str
    response: str = ""


class CredentialsAndPathsBody(BaseModel):
    entries: list | None = None
    enabled: bool | None = None


class CredentialsExtractBody(BaseModel):
    aggregate_all: bool = True
    pipeline_report: str | None = None
    force: bool = True


@router.get("/api/sites/{site}/{component}/credentials-and-paths")
async def api_get_credentials_and_paths(site: str, component: str):
    from pipeline.credentials_and_paths import (
        credentials_and_paths_path,
        is_credentials_and_paths_enabled,
        load_credentials_and_paths,
    )

    data = load_credentials_and_paths(site, component)
    return {
        "path": str(credentials_and_paths_path(site, component)),
        "enabled": is_credentials_and_paths_enabled(site, component),
        "data": data,
    }


@router.put("/api/sites/{site}/{component}/credentials-and-paths")
async def api_put_credentials_and_paths(
    site: str, component: str, body: CredentialsAndPathsBody
):
    from pipeline.edition import raise_premium

    raise_premium("intel")


@router.post("/api/sites/{site}/{component}/credentials-and-paths/extract")
async def api_extract_credentials_and_paths(
    site: str, component: str, body: CredentialsExtractBody | None = None
):
    from pipeline.edition import raise_premium

    raise_premium("intel")


@router.get("/api/sites/{site}/{component}/intel")
async def api_list_intel(site: str, component: str):
    from pipeline.intel import list_intel_files

    return {"items": list_intel_files(site, component)}


@router.get("/api/sites/{site}/{component}/intel/{playbook_id}")
async def api_get_intel(site: str, component: str, playbook_id: str):
    from pipeline.intel import intel_path, load_playbook_intel
    from playbooks.registry import normalize_playbook_id

    pid = normalize_playbook_id(playbook_id)
    path = intel_path(site, component, pid)
    data = load_playbook_intel(site, component, pid)
    if not data:
        return {"exists": False, "playbook_id": pid, "path": str(path)}
    return {"exists": True, "playbook_id": pid, "data": data, "path": str(path)}


@router.put("/api/sites/{site}/{component}/intel/{playbook_id}")
async def api_save_intel(site: str, component: str, playbook_id: str, body: SaveIntelBody):
    from pipeline.edition import raise_premium

    raise_premium("intel")


@router.delete("/api/sites/{site}/{component}/intel/{playbook_id}")
async def api_delete_intel(site: str, component: str, playbook_id: str):
    from pipeline.edition import raise_premium

    raise_premium("intel")


@router.get("/api/sites/{site}/{component}/notes")
async def api_get_notes(site: str, component: str):
    from pipeline.notes import load_notes, notes_path

    path = notes_path(site, component)
    data = load_notes(site, component)
    if not data:
        return {"exists": False, "path": str(path), "data": {"updated_at": "", "notes": []}}
    return {"exists": True, "path": str(path), "data": data}


@router.put("/api/sites/{site}/{component}/notes")
async def api_save_notes(site: str, component: str, body: SaveNotesBody):
    if not isinstance(body.data, dict):
        raise HTTPException(400, "data must be a JSON object")
    from pipeline.notes import save_notes

    try:
        path = save_notes(site, component, dict(body.data))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    from pipeline.notes import load_notes

    return {"ok": True, "path": str(path), "data": load_notes(site, component)}


@router.post("/api/sites/{site}/{component}/notes/append")
async def api_append_note(site: str, component: str, body: AppendNoteBody):
    from pipeline.notes import append_note, load_notes

    try:
        path = append_note(
            site,
            component,
            body=str(body.body or ""),
            title=str(body.title or ""),
            source=str(body.source or "manual"),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "path": str(path), "data": load_notes(site, component)}


@router.post("/api/sites/{site}/{component}/notes/append-manual-query")
async def api_append_notes_manual_query(site: str, component: str, body: AppendManualQueryBody):
    """Append a sidebar Manual LLM query Q→A into site/component notes."""
    from pipeline.notes import append_manual_llm_query, load_notes

    prompt = str(body.prompt or "").strip()
    if not prompt:
        raise HTTPException(400, "prompt is required")
    try:
        path = append_manual_llm_query(
            site,
            component,
            prompt=prompt,
            response=str(body.response or ""),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "path": str(path), "data": load_notes(site, component)}


@router.get("/api/strategies")
async def api_strategies():
    try:
        from pipeline.edition import filter_community_strategies

        return filter_community_strategies(STRATEGIES)
    except ImportError:
        return [s for s in STRATEGIES if str(s).lower().replace("-", "_") != "adaptive"]