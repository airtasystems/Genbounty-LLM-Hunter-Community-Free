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

class CorpusStoresClearBody(BaseModel):
    stores: list[str] = []


@router.get("/api/corpus-stores")
async def api_get_corpus_stores():
    """Return file counts/sizes for curated + learned + breakthrough + history stores."""
    ensure_generate_tests_path()
    from strategies.corpus_loader import CORPUS_STORE_IDS, corpus_store_stats

    payload = corpus_store_stats()
    return {
        "ok": True,
        "store_ids": list(CORPUS_STORE_IDS),
        "stores": payload.get("stores") or {},
    }


@router.post("/api/corpus-stores/clear")
async def api_clear_corpus_stores(body: CorpusStoresClearBody):
    """Delete selected corpus stores (whitelist: learned, breakthrough, history, curated)."""
    ensure_generate_tests_path()
    from strategies.corpus_loader import CORPUS_STORE_IDS, clear_corpus_stores

    wanted = [str(s).strip().lower() for s in (body.stores or []) if str(s).strip()]
    allowed = set(CORPUS_STORE_IDS)
    selected = [s for s in wanted if s in allowed]
    if not selected:
        raise HTTPException(
            status_code=400,
            detail=f"Select at least one store: {', '.join(CORPUS_STORE_IDS)}",
        )
    result = clear_corpus_stores(selected)
    return {
        "ok": True,
        "removed": result.get("removed") or {},
        "skipped": result.get("skipped") or [],
        "stores": result.get("stores") or {},
    }


@router.get("/api/sites/{site}/{component}/theory-history")
async def api_get_theory_history(site: str, component: str):
    """List persisted enhancement-theory entries for a site/component."""
    gen_dir = ROOT / "generate-tests"
    if str(gen_dir) not in sys.path:
        sys.path.insert(0, str(gen_dir))
    from enhance_theory_history import load_theory_history_file, theory_history_path

    data = load_theory_history_file(site, component)
    entries = list(data.get("entries") or [])
    enriched: list[dict] = []
    for idx, row in enumerate(entries):
        if not isinstance(row, dict):
            continue
        theory = str(row.get("theory") or "").strip()
        enriched.append(
            {
                "index": idx,
                "playbook_id": row.get("playbook_id", ""),
                "strategy": row.get("strategy", ""),
                "status": row.get("status", ""),
                "theory": theory,
                "theory_preview": (theory[:240] + "…") if len(theory) > 240 else theory,
                "reason": row.get("reason", ""),
                "round": row.get("round", ""),
                "job_id": row.get("job_id", ""),
                "timestamp": row.get("timestamp", ""),
            }
        )
    path = theory_history_path(site, component)
    accepted = sum(1 for e in enriched if str(e.get("status")).lower() == "accepted")
    rejected = sum(1 for e in enriched if str(e.get("status")).lower() == "rejected")
    return {
        "path": str(path),
        "entries": list(reversed(enriched)),
        "total": len(enriched),
        "accepted": accepted,
        "rejected": rejected,
    }


@router.delete("/api/sites/{site}/{component}/theory-history")
async def api_clear_theory_history(
    site: str,
    component: str,
    playbook_id: str = "",
    strategy: str = "",
    clear_elite: str = "1",
):
    """Clear enhancement-theory history (all entries or filtered by play/strategy).

    When playbook_id and strategy are both set, also clears that lane's elite
    genomes unless ``clear_elite`` is a falsey value (0/false/no/off). Pipeline
    retries pass clear_elite=0 so mutate DNA survives no_stop_win retries.
    """
    gen_dir = ROOT / "generate-tests"
    if str(gen_dir) not in sys.path:
        sys.path.insert(0, str(gen_dir))
    from enhance_theory_history import clear_theory_history

    pid = playbook_id.strip() or None
    strat = strategy.strip() or None
    removed = clear_theory_history(site, component, playbook_id=pid, strategy=strat)
    elite_cleared = False
    clear_elite_flag = str(clear_elite or "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    if pid and strat and clear_elite_flag:
        try:
            from strategies.elite_genomes import clear_elite_genomes

            elite_cleared = bool(clear_elite_genomes(site, component, pid, strat))
        except Exception:
            elite_cleared = False
    return {
        "ok": True,
        "removed": removed,
        "elite_cleared": elite_cleared,
        "clear_elite": clear_elite_flag,
    }


@router.delete("/api/sites/{site}/{component}/theory-history/{entry_index}")
async def api_delete_theory_history_entry(site: str, component: str, entry_index: int):
    """Delete one theory-history entry by storage index (0 = oldest)."""
    gen_dir = ROOT / "generate-tests"
    if str(gen_dir) not in sys.path:
        sys.path.insert(0, str(gen_dir))
    from enhance_theory_history import delete_theory_history_entry

    if not delete_theory_history_entry(site, component, entry_index):
        raise HTTPException(404, "Entry not found")
    return {"ok": True}

