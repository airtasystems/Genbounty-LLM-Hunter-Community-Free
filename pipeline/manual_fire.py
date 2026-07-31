"""Firing Range one-shot → timestamped logs/manual/<ts>/ attack_log helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pipeline.log_paths import STRATEGY_MANUAL, new_timestamped_run_dir


def _slug_token(text: str, *, fallback: str = "fire") -> str:
    raw = re.sub(r"[^a-zA-Z0-9]+", "-", str(text or "").strip().lower()).strip("-")
    return (raw[:40] or fallback).rstrip("-")


def build_manual_fire_attack_log(
    *,
    prompt: str,
    response: str,
    playbook_id: str,
    playbook: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Minimal single-entry attack_log for risk assessment of a Firing Range Q→A."""
    from pipeline.oracles import oracle_contract_metadata
    from playbooks.registry import load_playbook

    pid = str(playbook_id or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not pid:
        raise ValueError("playbook_id is required for Firing Range assess")

    pb = playbook if isinstance(playbook, dict) else load_playbook(pid)
    if not isinstance(pb, dict):
        raise ValueError(f"Playbook not found: {pid}")

    meta = oracle_contract_metadata(pb)
    cats = pb.get("categories") or pb.get("mandates") or []
    primary: dict[str, Any] = {}
    if isinstance(cats, list):
        for row in cats:
            if isinstance(row, dict) and (
                str(row.get("id") or "").strip() or str(row.get("name") or "").strip()
            ):
                primary = row
                break
    category_id = str(primary.get("id") or "").strip() or "CAT01"
    category_name = (
        str(primary.get("name") or primary.get("title") or "").strip()
        or category_id
    )
    play_label = str(pb.get("playbook") or pb.get("display_name") or pid).strip() or pid
    entry_id = f"manual-fire-{_slug_token(category_id)}"
    prompt_text = str(prompt or "")
    response_text = str(response or "")

    return {
        "playbook": play_label,
        "playbook_id": pid,
        **meta,
        "strategy": STRATEGY_MANUAL,
        "source_file": "firing_range",
        "results": [
            {
                "id": entry_id,
                "capture_id": entry_id,
                "prompt": prompt_text,
                "response": response_text,
                "ok": True,
                "status": "ok",
                "category": category_name,
                "category_id": category_id,
                "description": "Firing Range one-shot",
                "expected_behavior": "",
                "strategy": STRATEGY_MANUAL,
                "vector_type": "text_direct",
                "submission_outcome": "executed",
            }
        ],
    }


def write_manual_fire_attack_log(
    site: str,
    component: str,
    *,
    prompt: str,
    response: str,
    playbook_id: str,
    playbook: dict[str, Any] | None = None,
) -> Path:
    """Write attack_log.json under ``logs/manual/<timestamp>/`` and return its path."""
    attack_log = build_manual_fire_attack_log(
        prompt=prompt,
        response=response,
        playbook_id=playbook_id,
        playbook=playbook,
    )
    run_dir = new_timestamped_run_dir(site, component, "manual")
    out = run_dir / "attack_log.json"
    out.write_text(json.dumps(attack_log, indent=2, ensure_ascii=False), encoding="utf-8")
    return out
