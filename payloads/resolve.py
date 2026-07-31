"""Resolve suite payload specs to on-disk artifact paths."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from payloads.generators import generate_payload
from payloads.prompt_text import normalize_prompt_text
from payloads._utils import prune_stale_artifacts, stable_materialize_args

_PROBE_RUN_PRIORITY = {
    "stealth": 0,
    "escalation": 1,
    "detection_floor": 2,
}


def sort_test_cases_by_probe_class(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run stealth and escalation prompts before detection-floor probes."""
    return sorted(
        cases,
        key=lambda c: _PROBE_RUN_PRIORITY.get(str(c.get("probe_class") or "").strip().lower(), 1),
    )


def _suite_dir(suite_path: Path | str | None) -> Path | None:
    if not suite_path:
        return None
    p = Path(suite_path)
    return p.parent if p.is_file() else p


def resolve_test_artifact(
    entry: dict[str, Any],
    *,
    suite_path: Path | str | None = None,
    out_dir: Path | str | None = None,
) -> tuple[Path | None, str, bool]:
    """
    Resolve a test case entry to an artifact file.

    Returns (path, vector_type, upload_ok).
    upload_ok is True when a file path was resolved or no payload was required.
    """
    vector_type = entry.get("vector_type") or "text_direct"
    payload = entry.get("payload")
    if not payload:
        return None, vector_type, True

    if isinstance(payload, str):
        p = Path(payload)
        if not p.is_absolute() and suite_path:
            base = _suite_dir(suite_path)
            if base:
                candidate = base / p
                if candidate.is_file():
                    return candidate.resolve(), vector_type, True
        if p.is_file():
            return p.resolve(), vector_type, True
        return None, vector_type, False

    if not isinstance(payload, dict):
        return None, vector_type, False

    if payload.get("path"):
        rel = Path(str(payload["path"]))
        if not rel.is_absolute() and suite_path:
            base = _suite_dir(suite_path)
            if base and (base / rel).is_file():
                return (base / rel).resolve(), vector_type, True
        if rel.is_file():
            return rel.resolve(), vector_type, True
        # Stale path: fall through to generator+args when available.

    generator = payload.get("generator")
    if not generator:
        return None, vector_type, False

    args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
    if out_dir is None:
        run_id = entry.get("id") or uuid.uuid4().hex[:8]
        if suite_path:
            base = _suite_dir(suite_path)
            if base:
                out_dir = base / "artifacts" / str(run_id)
            else:
                out_dir = Path(__file__).resolve().parent / "generate" / run_id
        else:
            out_dir = Path(__file__).resolve().parent / "generate" / run_id
    out_path = Path(out_dir)
    try:
        path = generate_payload(generator, stable_materialize_args(args), out_dir=out_path)
        if suite_path and "artifacts" in out_path.parts:
            prune_stale_artifacts(out_path, path)
        return path.resolve(), vector_type, True
    except Exception:
        return None, vector_type, False


def infer_strategy_from_suite_path(suite_path: Path | str | None) -> str:
    """Infer generation strategy slug from suite path (e.g. tests/multi-shot/foo.json -> multi_shot)."""
    if not suite_path:
        return ""
    parts = Path(suite_path).parts
    if "tests" not in parts:
        return ""
    idx = parts.index("tests")
    if idx + 1 >= len(parts):
        return ""
    return parts[idx + 1].replace("-", "_")


def load_suite_multi_test_cases(suite_path: Path | str) -> list[dict[str, Any]]:
    """Load multi-turn test case dicts (prompts arrays) from a suite JSON file."""
    path = Path(suite_path)
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    out: list[dict[str, Any]] = []
    cats = raw.get("categories") or raw.get("mandates") or []
    if not isinstance(cats, list):
        return out
    for cat in cats:
        if not isinstance(cat, dict):
            continue
        cat_name = cat.get("name", cat.get("mandate", ""))
        cat_id = str(cat.get("id") or "").strip()
        for p in cat.get("prompts") or []:
            if not isinstance(p, dict):
                continue
            turn_rows: list[dict[str, Any]] = []
            turns = p.get("turns")
            if isinstance(turns, list) and turns:
                for t in turns:
                    if isinstance(t, dict):
                        prompt_text = ""
                        if "prompt" in t:
                            prompt_text = normalize_prompt_text(str(t.get("prompt") or ""))
                        row: dict[str, Any] = {"prompt": prompt_text}
                        if isinstance(t.get("payload"), dict):
                            row["payload"] = t["payload"]
                        turn_rows.append(row)
                    elif isinstance(t, str):
                        turn_rows.append({"prompt": normalize_prompt_text(t)})

            if not turn_rows:
                prompts = p.get("prompts")
                if not isinstance(prompts, list) or not prompts:
                    continue
                turn_prompts = [
                    normalize_prompt_text(s)
                    for s in prompts
                    if isinstance(s, str) and normalize_prompt_text(s)
                ]
                if not turn_prompts:
                    continue
                turn_rows = [{"prompt": s} for s in turn_prompts]

            out_row = {
                "id": p.get("id", ""),
                "category": cat_name,
                "category_id": cat_id,
                "description": p.get("description", ""),
                "prompts": [str(t.get("prompt") or "") for t in turn_rows],
                "vector_type": p.get("vector_type", "text_direct"),
                "payload": p.get("payload"),
                "turns": turn_rows,
                "context_mode": p.get("context_mode", "upload"),
                "control_type": p.get("control_type"),
            }
            out.append(out_row)
    return out


def load_suite_test_cases(suite_path: Path | str) -> list[dict[str, Any]]:
    """Load flat test case dicts from a suite JSON file."""
    path = Path(suite_path)
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    out: list[dict[str, Any]] = []
    cats = raw.get("categories") or raw.get("mandates") or []
    if isinstance(cats, list):
        for cat in cats:
            if not isinstance(cat, dict):
                continue
            cat_name = cat.get("name", cat.get("mandate", ""))
            cat_id = str(cat.get("id") or "").strip()
            for p in cat.get("prompts") or []:
                if not isinstance(p, dict):
                    continue
                if isinstance(p.get("prompts"), list):
                    continue
                prompt = normalize_prompt_text(str(p.get("prompt", "")))
                if not prompt:
                    continue
                out.append({
                    "id": p.get("id", ""),
                    "category": cat_name,
                    "category_id": cat_id,
                    "description": p.get("description", ""),
                    "prompt": prompt,
                    "vector_type": p.get("vector_type", "text_direct"),
                    "payload": p.get("payload"),
                    "context_mode": p.get("context_mode", "upload"),
                    "probe_class": p.get("probe_class", ""),
                })
    elif isinstance(raw, list):
        for i, item in enumerate(raw):
            if isinstance(item, str) and normalize_prompt_text(item):
                out.append({"id": f"entry-{i+1}", "prompt": normalize_prompt_text(item), "vector_type": "text_direct"})
            elif isinstance(item, dict) and item.get("prompt"):
                row = dict(item)
                row["prompt"] = normalize_prompt_text(str(row["prompt"]))
                out.append(row)
    return sort_test_cases_by_probe_class(out)
