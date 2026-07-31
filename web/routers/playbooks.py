from __future__ import annotations

import json
import os
import re as _re
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from web.paths import BB_DIR, ROOT, ensure_generate_tests_path
from web.services.playbook_authoring import (
    GeneratePlaybookBody,
    PlaybookConfigBody,
    generate_and_save,
    playbook_contract_detail as _playbook_contract_detail,
)

router = APIRouter()

__all__ = [
    "GeneratePlaybookBody",
    "PlaybookConfigBody",
    "api_generate_playbook",
    "router",
]

# Cache for playbook directory scans, keyed by the directory's file/mtime
# signature so writes, additions, and deletions invalidate automatically.
_playbook_scan_cache: dict[str, tuple[tuple, object]] = {}


def _playbooks_dir_signature() -> tuple:
    """Cheap signature of playbooks/*.json (name + mtime) to detect changes."""
    playbooks_dir = ROOT / "playbooks"
    if not playbooks_dir.is_dir():
        return ()
    sig: list[tuple[str, int]] = []
    for p in playbooks_dir.glob("*.json"):
        try:
            sig.append((p.name, p.stat().st_mtime_ns))
        except OSError:
            sig.append((p.name, 0))
    return tuple(sorted(sig))


def _playbook_scan_cached(key: str, builder):
    """Return builder() result, cached until the playbooks dir changes."""
    sig = _playbooks_dir_signature()
    cached = _playbook_scan_cache.get(key)
    if cached is not None and cached[0] == sig:
        return cached[1]
    value = builder()
    _playbook_scan_cache[key] = (sig, value)
    return value


def _security_playbook_stems() -> list[str]:
    """Playbook stems for generate/CLI - excludes context rubrics and deprecated playbooks."""
    def _build() -> list[str]:
        playbooks_dir = ROOT / "playbooks"
        if not playbooks_dir.is_dir():
            return []
        out: list[str] = []
        for p in sorted(playbooks_dir.glob("*.json")):
            if p.stem in ("company", "component") or p.stem.startswith("_"):
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8-sig"))
                if data.get("deprecated"):
                    continue
            except (json.JSONDecodeError, OSError):
                pass
            out.append(p.stem.replace("-", "_"))
        return out

    return list(_playbook_scan_cached("security_stems", _build))


@router.get("/api/playbooks")
def api_playbooks():
    return _security_playbook_stems()


_PLAYBOOKS_DIR = ROOT / "playbooks"


def _playbook_generator():
    ensure_generate_tests_path()
    from playbook_generator import save_playbook, slugify_playbook_id, validate_playbook

    return slugify_playbook_id, validate_playbook, save_playbook


def _playbook_file_path(playbook_id: str) -> Path:
    slugify_playbook_id, _, _ = _playbook_generator()
    raw = (playbook_id or "").strip()
    if raw.endswith(".json"):
        raw = Path(raw).stem
    pid = slugify_playbook_id(raw)
    if not pid:
        raise HTTPException(400, "Invalid playbook_id")
    if raw.replace("-", "_").lower().startswith("_") and not pid.startswith("_"):
        pid = f"_{pid}"
    return _PLAYBOOKS_DIR / f"{pid}.json"


def _load_playbook_file(path: Path) -> dict:
    if not path.is_file():
        raise HTTPException(404, "Playbook not found")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise HTTPException(422, f"Invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise HTTPException(422, "Playbook must be a JSON object")
    return data


def _playbook_summary(path: Path, data: dict | None = None) -> dict:
    stem = path.stem
    payload = data if data is not None else _load_playbook_file(path)
    categories = payload.get("categories") if isinstance(payload.get("categories"), list) else []
    from playbooks.categories import (
        canonical_category_path,
        category_breadcrumb,
        category_label,
        normalize_play_category,
        parse_play_category,
    )

    play_cat = normalize_play_category(str(payload.get("play_category", "")))
    play_cat_label = str(payload.get("play_category_label", "")).strip()
    play_cat_path = canonical_category_path(payload)
    parsed = parse_play_category(play_cat, play_cat_path)
    return {
        "id": stem.replace("-", "_"),
        "filename": path.name,
        "playbook": payload.get("playbook") or stem,
        "playbook_id": payload.get("playbook_id") or stem,
        "play": str(payload.get("play", "")).strip(),
        "play_category": play_cat,
        "play_category_path": play_cat_path,
        "play_category_label": play_cat_label,
        "play_category_display": category_label(play_cat, play_cat_label),
        "play_category_breadcrumb": category_breadcrumb(play_cat, play_cat_label, play_cat_path),
        "play_category_l1_label": parsed.get("l1_label", ""),
        "group_key": parsed.get("l1") or play_cat,
        "assessment_type": payload.get("assessment_type") or "",
        "category_count": len(categories),
        "schema_version": payload.get("schema_version"),
        "deprecated": bool(payload.get("deprecated")),
        "updated_at": path.stat().st_mtime,
    }


@router.get("/api/playbooks/manage")
def api_playbooks_manage():
    """Catalog of playbook JSON files for the Playbooks UI."""
    def _build() -> list[dict]:
        if not _PLAYBOOKS_DIR.is_dir():
            return []
        rows: list[dict] = []
        for path in sorted(_PLAYBOOKS_DIR.glob("*.json"), key=lambda p: p.name.lower()):
            if path.stem.startswith("_"):
                continue
            try:
                rows.append(_playbook_summary(path))
            except HTTPException:
                continue
        return rows

    return list(_playbook_scan_cached("manage", _build))


@router.get("/api/plays/categories")
async def api_play_categories():
    from playbooks.categories import list_play_category_tree

    return {"tree": list_play_category_tree()}


@router.get("/api/plays/category-presets")
async def api_play_category_presets():
    from playbooks.category_presets import list_category_presets

    return list_category_presets()


@router.get("/api/plays/category-presets/{l1}/{l2}")
async def api_play_category_preset(l1: str, l2: str, play_category_label: str = ""):
    from playbooks.category_presets import preset_to_api_dict, resolve_category_preset
    from playbooks.categories import default_play_category_l2, normalize_play_category

    l1_id = normalize_play_category(l1) or l1.strip()
    l2_id = (l2 or "").strip() or default_play_category_l2(l1_id)
    if not l1_id or not l2_id:
        raise HTTPException(400, "l1 and l2 are required")
    try:
        preset = resolve_category_preset(
            l1_id, l2_id, play_category_label=play_category_label.strip()
        )
    except ValueError as exc:
        raise HTTPException(
            422,
            _playbook_contract_detail([str(exc)]),
        ) from exc
    return preset_to_api_dict(preset, l1=l1_id, l2=l2_id)


@router.get("/api/playbooks/template")
async def api_playbook_template():
    ensure_generate_tests_path()
    from playbook_generator import load_template, template_path

    try:
        data = load_template()
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"path": str(template_path()), "template": data}


@router.post("/api/playbooks/generate")
async def api_generate_playbook(body: GeneratePlaybookBody, request: Request):
    return await generate_and_save(body, request)


@router.get("/api/playbooks/{playbook_id}")
async def api_get_playbook(playbook_id: str):
    path = _playbook_file_path(playbook_id)
    data = _load_playbook_file(path)
    summary = _playbook_summary(path, data)
    return {
        **summary,
        "path": str(path.relative_to(ROOT)),
        "data": data,
    }


class PlaybookSaveBody(BaseModel):
    data: dict


@router.post("/api/playbooks")
async def api_create_playbook(body: PlaybookSaveBody):
    slugify_playbook_id, validate_playbook, save_playbook = _playbook_generator()
    data = body.data
    if not isinstance(data, dict):
        raise HTTPException(400, "data must be a JSON object")

    playbook_id = slugify_playbook_id(str(data.get("playbook_id", "")))
    if not playbook_id:
        raise HTTPException(400, "playbook_id is required")

    data = json.loads(json.dumps(data))
    data.pop("_comment", None)
    data["playbook_id"] = playbook_id
    if not str(data.get("playbook", "")).strip():
        data["playbook"] = playbook_id.replace("_", " ").title()

    from playbooks.playbook_config import canonicalize_playbook_config_storage

    canonicalize_playbook_config_storage(data)

    errors = validate_playbook(data, playbook_id)
    if errors:
        raise HTTPException(422, _playbook_contract_detail(errors[:8]))

    dest = _PLAYBOOKS_DIR / f"{playbook_id}.json"
    if dest.exists():
        raise HTTPException(409, f"Playbook already exists: {playbook_id}")

    path = save_playbook(data, overwrite=False)
    loaded = _load_playbook_file(path)
    return {
        "ok": True,
        "playbook_id": playbook_id,
        "path": str(path.relative_to(ROOT)),
        "summary": _playbook_summary(path, loaded),
    }


@router.put("/api/playbooks/{playbook_id}")
async def api_update_playbook(playbook_id: str, body: PlaybookSaveBody):
    slugify_playbook_id, validate_playbook, _save_playbook = _playbook_generator()
    path = _playbook_file_path(playbook_id)
    if not path.is_file():
        raise HTTPException(404, "Playbook not found")

    data = body.data
    if not isinstance(data, dict):
        raise HTTPException(400, "data must be a JSON object")

    expected_id = slugify_playbook_id(playbook_id)
    is_reference = path.stem.startswith("_")

    if is_reference:
        validate_id = slugify_playbook_id(str(data.get("playbook_id", "")))
        if not validate_id:
            raise HTTPException(400, "playbook_id is required in JSON")
    else:
        new_id = slugify_playbook_id(str(data.get("playbook_id", expected_id)))
        if new_id != expected_id:
            raise HTTPException(400, "playbook_id cannot be changed; create a new playbook instead")
        validate_id = expected_id

    data = json.loads(json.dumps(data))
    if not is_reference:
        data.pop("_comment", None)
        data["playbook_id"] = expected_id

    from playbooks.playbook_config import canonicalize_playbook_config_storage

    canonicalize_playbook_config_storage(data)

    errors = validate_playbook(data, validate_id)
    if errors:
        raise HTTPException(422, _playbook_contract_detail(errors[:8]))

    _PLAYBOOKS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    loaded = _load_playbook_file(path)
    return {
        "ok": True,
        "playbook_id": path.stem.replace("-", "_"),
        "path": str(path.relative_to(ROOT)),
        "summary": _playbook_summary(path, loaded),
    }


@router.post("/api/playbooks/{playbook_id}/convert-text-channel")
async def api_convert_playbook_text_channel(playbook_id: str):
    """Rewrite artifact-channel categories to text for text-only CTF harnesses."""
    from playbooks.channel_convert import convert_playbook_to_text_channel, playbook_has_artifact_categories

    path = _playbook_file_path(playbook_id)
    if not path.is_file():
        raise HTTPException(404, "Playbook not found")
    if path.stem.startswith("_"):
        raise HTTPException(400, "Reference playbooks cannot be converted")

    data = _load_playbook_file(path)
    if not playbook_has_artifact_categories(data):
        raise HTTPException(
            400,
            "Playbook has no artifact-channel categories; nothing to convert.",
        )

    converted, changes = convert_playbook_to_text_channel(data)
    _, validate_playbook, _ = _playbook_generator()
    expected_id = path.stem.replace("-", "_")
    converted["playbook_id"] = expected_id
    errors = validate_playbook(converted, expected_id)
    if errors:
        raise HTTPException(422, "; ".join(errors[:8]))

    path.write_text(json.dumps(converted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    loaded = _load_playbook_file(path)
    return {
        "ok": True,
        "playbook_id": expected_id,
        "path": str(path.relative_to(ROOT)),
        "summary": _playbook_summary(path, loaded),
        "changes": changes,
        "message": (
            f"Converted {expected_id} to text-based channel "
            f"({len(changes)} update{'s' if len(changes) != 1 else ''}). "
            "Retry test generation with your text strategy."
        ),
    }


class PlaybookRenameBody(BaseModel):
    new_playbook_id: str
    data: dict | None = None


@router.post("/api/playbooks/{playbook_id}/rename")
async def api_rename_playbook(playbook_id: str, body: PlaybookRenameBody):
    """Rename a playbook id (file) and relink suites + intel across all targets."""
    from playbooks.rename import PlaybookRenameError, rename_playbook

    try:
        result = rename_playbook(
            playbook_id,
            body.new_playbook_id,
            ROOT,
            data=body.data,
        )
    except PlaybookRenameError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(404, msg) from exc
        if "already exists" in msg.lower() or "conflict" in msg.lower():
            raise HTTPException(409, msg) from exc
        if "validation" in msg.lower():
            raise HTTPException(422, _playbook_contract_detail([msg])) from exc
        raise HTTPException(400, msg) from exc
    return result


@router.delete("/api/playbooks/{playbook_id}")
async def api_delete_playbook(playbook_id: str):
    path = _playbook_file_path(playbook_id)
    if not path.is_file():
        raise HTTPException(404, "Playbook not found")
    path.unlink()
    return {"ok": True, "playbook_id": path.stem.replace("-", "_")}

