"""Materialize multimodal suite payloads to disk and update suite JSON with payload.path."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from payloads._utils import prune_stale_artifacts, stable_materialize_args
from payloads.generators import generate_payload


def _slug_id(prompt_id: str) -> str:
    s = re.sub(r"[^\w\-]", "-", (prompt_id or "prompt").strip().lower())
    return re.sub(r"-+", "-", s).strip("-") or "prompt"


def _materialize_prompt_payload(
    prompt: dict[str, Any],
    suite_dir: Path,
) -> dict[str, Any]:
    """Generate artifact for one prompt; return updated payload dict."""
    payload = prompt.get("payload")
    if not isinstance(payload, dict):
        return prompt

    raw_gen = payload.get("generator")
    if not raw_gen:
        return prompt

    prompt_id = prompt.get("id") or "prompt"
    artifact_dir = suite_dir / "artifacts" / _slug_id(str(prompt_id))
    artifact_dir.mkdir(parents=True, exist_ok=True)

    args = dict(payload.get("args") or {})
    generator = str(raw_gen)
    try:
        _root = Path(__file__).resolve().parent.parent
        import sys as _sys

        if str(_root) not in _sys.path:
            _sys.path.insert(0, str(_root))
        from payloads.normalize import (
            normalize_generator_args,
            normalize_generator_name,
            normalize_multimodal_prompt,
        )

        row_norm = normalize_multimodal_prompt(
            {
                "id": prompt_id,
                "vector_type": prompt.get("vector_type", ""),
                "payload": {"generator": raw_gen, "args": args},
            }
        )
        payload_norm = row_norm.get("payload") or {}
        generator = str(payload_norm.get("generator") or raw_gen)
        args = dict(payload_norm.get("args") or {})
        generator = normalize_generator_name(generator, str(prompt.get("vector_type") or ""))
        args = normalize_generator_args(generator, args)
    except Exception:
        pass
    args = stable_materialize_args(args)
    try:
        abs_path = generate_payload(generator, args, out_dir=artifact_dir)
    except Exception as exc:
        import logging

        logging.warning(
            "Failed to materialize payload for %s (%s): %s",
            prompt_id,
            generator,
            exc,
        )
        existing = payload.get("path")
        if existing and (suite_dir / str(existing)).is_file():
            return prompt
        return prompt

    prune_stale_artifacts(artifact_dir, abs_path)
    rel_path = abs_path.resolve().relative_to(suite_dir.resolve())
    updated = dict(payload)
    updated["path"] = str(rel_path).replace("\\", "/")
    out = dict(prompt)
    out["payload"] = updated
    return out


def _materialize_turn_payloads(
    prompt: dict[str, Any],
    suite_dir: Path,
) -> tuple[dict[str, Any], int, int]:
    """Generate artifacts for per-turn payloads and update turns in place."""
    turns = prompt.get("turns")
    if not isinstance(turns, list):
        return prompt, 0, 0
    out_prompt = dict(prompt)
    new_turns: list[Any] = []
    mat = 0
    total = 0
    for i, turn in enumerate(turns):
        if not isinstance(turn, dict):
            new_turns.append(turn)
            continue
        row = dict(turn)
        payload = row.get("payload")
        if isinstance(payload, dict) and payload.get("generator"):
            total += 1
            turn_id = str(prompt.get("id") or "prompt")
            turn_prompt = {
                "id": f"{turn_id}--t{i+1}",
                "vector_type": prompt.get("vector_type", row.get("vector_type", "")),
                "payload": payload,
            }
            updated_turn = _materialize_prompt_payload(turn_prompt, suite_dir)
            updated_payload = (updated_turn.get("payload") or {})
            if isinstance(updated_payload, dict):
                row["payload"] = updated_payload
                rel = updated_payload.get("path")
                if rel and (suite_dir / str(rel)).is_file():
                    mat += 1
        new_turns.append(row)
    out_prompt["turns"] = new_turns
    return out_prompt, mat, total


def materialize_suite(suite_path: Path | str) -> tuple[Path, int, int]:
    """
    Generate files for all prompts with payload.generator in a suite JSON file.

    Returns (suite_path, materialized_count, total_with_generator).
    Rewrites the suite file in place.
    """
    path = Path(suite_path)
    if not path.is_file():
        raise FileNotFoundError(f"Suite not found: {path}")

    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    suite_dir = path.parent
    materialized = 0
    total = 0

    cats = raw.get("categories") or raw.get("mandates") or []
    if isinstance(cats, list):
        for cat in cats:
            if not isinstance(cat, dict):
                continue
            prompts = cat.get("prompts") or []
            new_prompts = []
            for p in prompts:
                if not isinstance(p, dict):
                    new_prompts.append(p)
                    continue
                payload = p.get("payload")
                if isinstance(payload, dict) and payload.get("generator"):
                    total += 1
                    updated = _materialize_prompt_payload(p, suite_dir)
                    rel = (updated.get("payload") or {}).get("path")
                    if rel and (suite_dir / str(rel)).is_file():
                        materialized += 1
                    new_prompts.append(updated)
                else:
                    new_prompts.append(p)
                latest = new_prompts[-1]
                if isinstance(latest, dict) and isinstance(latest.get("turns"), list):
                    updated_turns, turns_mat, turns_total = _materialize_turn_payloads(
                        latest, suite_dir
                    )
                    new_prompts[-1] = updated_turns
                    materialized += turns_mat
                    total += turns_total
            cat["prompts"] = new_prompts

    path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path, materialized, total


def artifact_status_for_suite(suite_path: Path | str) -> list[dict[str, Any]]:
    """Return per-prompt artifact status for run pre-flight UI."""
    path = Path(suite_path)
    if not path.is_file():
        return []
    suite_dir = path.parent
    rows: list[dict[str, Any]] = []
    for entry in _iter_suite_prompts(path):
        payload = entry.get("payload")
        status = "none"
        rel_path = ""
        if isinstance(payload, dict):
            rel = payload.get("path")
            if rel:
                rel_path = str(rel)
                candidate = suite_dir / rel_path
                status = "ready" if candidate.is_file() else "missing_path"
            elif payload.get("generator"):
                status = "lazy"
        rows.append({
            "id": entry.get("id", ""),
            "vector_type": entry.get("vector_type", ""),
            "status": status,
            "path": rel_path,
            "generator": (payload or {}).get("generator") if isinstance(payload, dict) else None,
        })
    return rows


def _iter_suite_prompts(suite_path: Path) -> list[dict[str, Any]]:
    raw = json.loads(suite_path.read_text(encoding="utf-8-sig"))
    out: list[dict[str, Any]] = []
    for cat in raw.get("categories") or raw.get("mandates") or []:
        if not isinstance(cat, dict):
            continue
        for p in cat.get("prompts") or []:
            if not isinstance(p, dict):
                continue
            if p.get("prompt") or p.get("payload") or p.get("turns"):
                out.append(p)
    return out
