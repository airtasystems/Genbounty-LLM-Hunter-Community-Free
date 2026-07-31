"""Shared playbook loading and category metadata helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_PLAYBOOKS_DIR = Path(__file__).resolve().parent
_EXCLUDED_STEMS = frozenset({"company", "component"})

_PARENT_ID_FROM_CATEGORY = re.compile(
    r"^([A-Z]+\d+(?:-[A-Z]+)?)(?:-(?:T|A|NC))?$",
    re.IGNORECASE,
)

_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def playbooks_dir() -> Path:
    return _PLAYBOOKS_DIR


def normalize_playbook_id(playbook_id: str) -> str:
    return (playbook_id or "").strip().lower().replace("-", "_")


def list_playbook_stems() -> list[str]:
    if not _PLAYBOOKS_DIR.is_dir():
        return []
    stems: list[str] = []
    for path in sorted(_PLAYBOOKS_DIR.glob("*.json")):
        stem = path.stem
        if stem.startswith("_") or stem in _EXCLUDED_STEMS:
            continue
        stems.append(stem)
    return stems


def playbook_path(playbook_id: str) -> Path:
    pid = normalize_playbook_id(playbook_id)
    return _PLAYBOOKS_DIR / f"{pid}.json"


def load_playbook(playbook_id: str) -> dict[str, Any] | None:
    """Load playbook JSON with mtime-based cache. Returns None if missing or invalid."""
    pid = normalize_playbook_id(playbook_id)
    path = playbook_path(pid)
    if not path.is_file():
        return None
    mtime = path.stat().st_mtime
    cached = _cache.get(pid)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    _cache[pid] = (mtime, data)
    return data


def get_categories(playbook: dict[str, Any]) -> list[dict[str, Any]]:
    cats = playbook.get("categories")
    if isinstance(cats, list):
        return [c for c in cats if isinstance(c, dict)]
    mandates = playbook.get("mandates")
    if isinstance(mandates, list):
        return [c for c in mandates if isinstance(c, dict)]
    return []


def get_category(playbook_id: str, category_id: str) -> dict[str, Any] | None:
    playbook = load_playbook(playbook_id)
    if not playbook:
        return None
    cid = (category_id or "").strip()
    for cat in get_categories(playbook):
        if str(cat.get("id", "")).strip() == cid:
            return cat
        name = str(cat.get("name", cat.get("mandate", ""))).strip()
        if name and name == cid:
            return cat
    return None


def _infer_parent_from_category_id(category_id: str) -> str:
    cid = (category_id or "").strip().upper()
    if not cid:
        return ""
    m = _PARENT_ID_FROM_CATEGORY.match(cid)
    if not m:
        return ""
    parent = m.group(1).upper()
    if parent.endswith("-NC"):
        return parent[:-3]
    return parent


def resolve_parent_id(playbook_id: str, category_id: str) -> str:
    cat = get_category(playbook_id, category_id)
    if cat:
        parent = str(cat.get("parent_id", "")).strip()
        if parent:
            return parent
    inferred = _infer_parent_from_category_id(category_id)
    if inferred:
        return inferred
    return (category_id or "").strip()


def get_category_channel(category: dict[str, Any]) -> str:
    """Return the category's required explicit channel."""
    ch = category.get("channel")
    if ch in ("text", "artifact"):
        return str(ch)
    raise ValueError("Category requires explicit channel 'text' or 'artifact'")


def count_channels(playbook_id: str) -> dict[str, int]:
    playbook = load_playbook(playbook_id)
    if not playbook:
        return {"text": 0, "artifact": 0}
    counts = {"text": 0, "artifact": 0}
    for cat in get_categories(playbook):
        counts[get_category_channel(cat)] += 1
    return counts


def get_play_metadata(playbook_id: str) -> dict[str, Any] | None:
    playbook = load_playbook(playbook_id)
    if not playbook:
        return None
    from playbooks.categories import (
        canonical_category_path,
        category_breadcrumb,
        category_label,
        normalize_play_category,
        parse_play_category,
    )

    cid = normalize_play_category(str(playbook.get("play_category", "")))
    custom = str(playbook.get("play_category_label", "")).strip()
    path = canonical_category_path(playbook)
    parsed = parse_play_category(cid, path)
    return {
        "playbook_id": normalize_playbook_id(playbook_id),
        "playbook": str(playbook.get("playbook", "")).strip(),
        "play": str(playbook.get("play", "")).strip(),
        "play_category": cid,
        "play_category_path": path,
        "play_category_label": custom,
        "play_category_display": category_label(cid, custom),
        "play_category_breadcrumb": category_breadcrumb(cid, custom, path),
        "play_category_l1_label": parsed.get("l1_label", ""),
        "schema_version": playbook.get("schema_version"),
        "category_count": len(get_categories(playbook)),
    }


def list_plays_by_category() -> list[dict[str, Any]]:
    """All plays grouped metadata for UI catalog."""
    from playbooks.categories import play_group_key

    rows: list[dict[str, Any]] = []
    for stem in list_playbook_stems():
        meta = get_play_metadata(stem)
        if not meta:
            continue
        playbook = load_playbook(stem)
        if playbook and playbook.get("deprecated"):
            continue
        meta["id"] = stem.replace("-", "_")
        meta["group_key"] = play_group_key(playbook or {})
        meta["group_label"] = meta.get("play_category_l1_label") or meta.get("play_category_display") or "Uncategorized"
        rows.append(meta)
    return rows


def default_playbook_id() -> str:
    """First available play stem, or empty string."""
    stems = list_playbook_stems()
    return stems[0].replace("-", "_") if stems else ""
