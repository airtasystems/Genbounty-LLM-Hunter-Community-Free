"""Build and update custom flagged test suites from parent playbook JSON."""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.convert_log import _category_name, _suite_categories, resolve_suite_match


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def strategy_dir_name(strategy: str | None) -> str:
    slug = (strategy or "zero_shot").strip().replace("_", "-")
    return slug or "zero-shot"


def playbook_id_to_stem(playbook_id: str) -> str:
    return (playbook_id or "").strip().replace("_", "-")


def flagged_suite_stem(parent_stem: str) -> str:
    parent = (parent_stem or "").strip()
    if not parent:
        return "flagged"
    if parent.endswith("-flagged"):
        return parent
    return f"{parent}-flagged"


def resolve_parent_suite_path(
    report: dict[str, Any],
    *,
    site: str,
    component: str,
    bb_root: Path,
) -> Path | None:
    """Resolve the parent test suite path from a pipeline report."""
    workspace = Path(__file__).resolve().parent.parent
    source = str(report.get("source_file") or "").strip()
    if source:
        path = Path(source)
        if path.is_file():
            return path
        for base in (workspace, bb_root.parent, bb_root):
            candidate = base / source.lstrip("/")
            if candidate.is_file():
                return candidate

    strategy = strategy_dir_name(report.get("strategy"))
    playbook_id = str(report.get("playbook_id") or "").strip()
    stem = playbook_id_to_stem(playbook_id) if playbook_id else ""
    if not stem:
        playbook = str(report.get("playbook") or "").strip()
        stem = re.sub(r"[^a-z0-9]+", "-", playbook.lower()).strip("-") if playbook else ""
    if not stem:
        return None

    direct = bb_root / "sites" / site / component / "tests" / strategy / f"{stem}.json"
    if direct.is_file():
        return direct
    return None


def _find_prompt_in_suite(
    suite: dict[str, Any],
    *,
    prompt_id: str,
    category_id: str = "",
    category_name: str = "",
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    prompt_id = (prompt_id or "").strip()
    category_id = (category_id or "").strip()
    category_name = (category_name or "").strip()

    def _matches_cat(cat: dict[str, Any]) -> bool:
        if category_id and str(cat.get("id") or "").strip() != category_id:
            return False
        if category_name and _category_name(cat) != category_name and not category_id:
            return False
        return True

    if prompt_id:
        for cat in _suite_categories(suite):
            if category_id or category_name:
                if not _matches_cat(cat):
                    continue
            for prompt in cat.get("prompts") or []:
                if isinstance(prompt, dict) and str(prompt.get("id") or "").strip() == prompt_id:
                    return cat, prompt
        for cat in _suite_categories(suite):
            for prompt in cat.get("prompts") or []:
                if isinstance(prompt, dict) and str(prompt.get("id") or "").strip() == prompt_id:
                    return cat, prompt
    return None


def _prompt_object_from_result(
    suite: dict[str, Any] | None,
    result: dict[str, Any],
    *,
    position: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (category_meta, prompt_object) for a flagged row."""
    prompt_id = str(result.get("id") or "").strip()
    category_id = str(result.get("category_id") or "").strip()
    category_name = str(result.get("category") or "").strip()

    if suite:
        found = _find_prompt_in_suite(
            suite,
            prompt_id=prompt_id,
            category_id=category_id,
            category_name=category_name,
        )
        if found:
            cat, prompt = found
            cat_meta = {
                "id": cat.get("id", ""),
                "name": _category_name(cat),
                "focus": cat.get("focus", cat.get("description", "")),
            }
            return cat_meta, copy.deepcopy(prompt)

        index = []
        try:
            from pipeline.convert_log import build_suite_prompt_index

            index = build_suite_prompt_index(suite)
        except Exception:
            index = []
        matched = resolve_suite_match(result, index, position=position)
        if matched:
            for cat in _suite_categories(suite):
                for prompt in cat.get("prompts") or []:
                    if str(prompt.get("id") or "") == str(matched.get("id") or ""):
                        cat_meta = {
                            "id": cat.get("id", ""),
                            "name": _category_name(cat),
                            "focus": cat.get("focus", cat.get("description", "")),
                        }
                        return cat_meta, copy.deepcopy(prompt)

    slug_base = re.sub(r"[^a-z0-9-]+", "-", prompt_id.lower()).strip("-") if prompt_id else "prompt"
    prompt_obj: dict[str, Any] = {
        "id": prompt_id or f"flagged-{slug_base or 'item'}",
        "description": str(result.get("description") or "").strip(),
        "prompt": str(result.get("prompt") or "").strip(),
    }
    for key in ("probe_class", "vector_type", "payload", "context_mode", "control_type"):
        if result.get(key) is not None:
            prompt_obj[key] = result[key]
    turns = result.get("turns") or result.get("prior_turns")
    if isinstance(turns, list) and turns:
        prompt_obj["prompts"] = [
            {"prompt": str(t.get("prompt") or t.get("input") or "").strip()}
            for t in turns
            if isinstance(t, dict)
        ]
    cat_meta = {
        "id": category_id,
        "name": category_name or "Flagged",
        "focus": category_name or "Prompts flagged during assessment review",
    }
    return cat_meta, prompt_obj


def _category_shell(cat_meta: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"prompts": []}
    if cat_meta.get("id"):
        out["id"] = cat_meta["id"]
    if cat_meta.get("name"):
        out["name"] = cat_meta["name"]
    if cat_meta.get("focus"):
        out["focus"] = cat_meta["focus"]
    return out


def _find_category_in_flagged(flagged: dict[str, Any], cat_meta: dict[str, Any]) -> dict[str, Any] | None:
    cat_id = str(cat_meta.get("id") or "").strip()
    cat_name = str(cat_meta.get("name") or "").strip()
    for cat in flagged.get("categories") or []:
        if not isinstance(cat, dict):
            continue
        if cat_id and str(cat.get("id") or "").strip() == cat_id:
            return cat
        if cat_name and _category_name(cat) == cat_name:
            return cat
    return None


def _flagged_suite_shell(parent: dict[str, Any], *, parent_stem: str) -> dict[str, Any]:
    return {
        "playbook": parent.get("playbook") or parent.get("framework") or "Flagged prompts",
        "playbook_id": parent.get("playbook_id") or playbook_id_to_stem(parent_stem).replace("-", "_"),
        "description": (
            f"Flagged prompts of interest from {parent.get('playbook') or parent_stem}. "
            "Curated during risk assessment review."
        ),
        "categories": [],
        "strategy": parent.get("strategy"),
        "flagged_suite": True,
        "parent_playbook": parent_stem,
        "generation_notes": "Custom flagged set - prompts marked during assessment review.",
        "target_context": copy.deepcopy(parent.get("target_context"))
        if isinstance(parent.get("target_context"), dict)
        else None,
    }


def _prompt_ids_in_suite(suite: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for cat in _suite_categories(suite):
        for prompt in cat.get("prompts") or []:
            if isinstance(prompt, dict):
                pid = str(prompt.get("id") or "").strip()
                if pid:
                    ids.add(pid)
    return ids


def list_flagged_prompt_ids(flagged_path: Path) -> list[str]:
    if not flagged_path.is_file():
        return []
    try:
        data = json.loads(flagged_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return sorted(_prompt_ids_in_suite(data))


def add_prompt_to_flagged_suite(
    *,
    site: str,
    component: str,
    parent_suite_path: Path,
    result: dict[str, Any],
    position: int | None = None,
    report_path: str = "",
    bb_root: Path | None = None,
) -> dict[str, Any]:
    """Add one assessment result to the parent's -flagged.json suite."""
    root = bb_root or Path(__file__).resolve().parent.parent / "browser-bot"
    parent_suite_path = Path(parent_suite_path)
    if not parent_suite_path.is_file():
        raise FileNotFoundError(f"Parent suite not found: {parent_suite_path}")

    parent = json.loads(parent_suite_path.read_text(encoding="utf-8"))
    parent_stem = parent_suite_path.stem
    strategy_dir = parent_suite_path.parent.name
    flagged_path = parent_suite_path.parent / f"{flagged_suite_stem(parent_stem)}.json"

    cat_meta, prompt_obj = _prompt_object_from_result(parent, result, position=position)
    prompt_id = str(prompt_obj.get("id") or "").strip()
    if not prompt_id:
        raise ValueError("Cannot flag prompt without an id")

    if flagged_path.is_file():
        flagged = json.loads(flagged_path.read_text(encoding="utf-8"))
    else:
        flagged = _flagged_suite_shell(parent, parent_stem=parent_stem)

    existing_ids = _prompt_ids_in_suite(flagged)
    if prompt_id in existing_ids:
        return {
            "ok": True,
            "already_flagged": True,
            "prompt_id": prompt_id,
            "path": str(flagged_path),
            "strategy": strategy_dir,
            "playbook": flagged_path.stem,
            "flagged_count": len(existing_ids),
            "flagged_ids": sorted(existing_ids),
        }

    flagged.setdefault("flagged_entries", [])
    if isinstance(flagged["flagged_entries"], list):
        flagged["flagged_entries"].append(
            {
                "prompt_id": prompt_id,
                "flagged_at": _iso_now(),
                "report_path": report_path,
                "risk_level": str(result.get("risk_level") or ""),
            }
        )

    cat = _find_category_in_flagged(flagged, cat_meta)
    if cat is None:
        cat = _category_shell(cat_meta)
        flagged.setdefault("categories", [])
        flagged["categories"].append(cat)
    cat.setdefault("prompts", [])
    cat["prompts"].append(prompt_obj)

    flagged_path.parent.mkdir(parents=True, exist_ok=True)
    flagged_path.write_text(json.dumps(flagged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    all_ids = sorted(_prompt_ids_in_suite(flagged))
    return {
        "ok": True,
        "already_flagged": False,
        "prompt_id": prompt_id,
        "path": str(flagged_path),
        "strategy": strategy_dir,
        "playbook": flagged_path.stem,
        "flagged_count": len(all_ids),
        "flagged_ids": all_ids,
    }
