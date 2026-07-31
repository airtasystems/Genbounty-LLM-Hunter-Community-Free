"""Per site/component hunter notes at sites/{site}/{component}/notes.json."""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_NOTES_FILENAME = "notes.json"
_ALLOWED_SOURCES = frozenset({"manual", "manual_llm"})
_WS_RE = re.compile(r"\s+")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_note_id() -> str:
    return f"n_{secrets.token_hex(4)}"


def notes_path(site: str, component: str) -> Path:
    site = (site or "").strip()
    component = (component or "").strip()
    return _ROOT / "browser-bot" / "sites" / site / component / _NOTES_FILENAME


def empty_notes() -> dict[str, Any]:
    return {"updated_at": _iso_now(), "notes": []}


def _normalize_note(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    body = str(raw.get("body") or "").strip()
    title = str(raw.get("title") or "").strip()
    if not body and not title:
        return None
    source = str(raw.get("source") or "manual").strip().lower()
    if source not in _ALLOWED_SOURCES:
        source = "manual"
    note_id = str(raw.get("id") or "").strip() or _new_note_id()
    created = str(raw.get("created_at") or "").strip() or _iso_now()
    return {
        "id": note_id,
        "created_at": created,
        "source": source,
        "title": title,
        "body": body,
    }


def normalize_notes(data: dict[str, Any] | None) -> dict[str, Any]:
    base = empty_notes()
    if not isinstance(data, dict):
        return base
    notes_in = data.get("notes")
    out_notes: list[dict[str, Any]] = []
    seen: set[str] = set()
    if isinstance(notes_in, list):
        for raw in notes_in:
            note = _normalize_note(raw)
            if note is None:
                continue
            if note["id"] in seen:
                note["id"] = _new_note_id()
            seen.add(note["id"])
            out_notes.append(note)
    updated = str(data.get("updated_at") or "").strip() or _iso_now()
    return {"updated_at": updated, "notes": out_notes}


def load_notes(site: str, component: str) -> dict[str, Any] | None:
    """Return notes document, or None if missing/invalid."""
    site = (site or "").strip()
    component = (component or "").strip()
    if not site or not component:
        return None
    path = notes_path(site, component)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return normalize_notes(data)


def save_notes(site: str, component: str, data: dict[str, Any]) -> Path:
    """Write notes.json for the site/component."""
    site = (site or "").strip()
    component = (component or "").strip()
    if not site or not component:
        raise ValueError("site and component are required to save notes")
    if not isinstance(data, dict):
        raise ValueError("notes data must be a JSON object")

    payload = normalize_notes(data)
    payload["updated_at"] = _iso_now()

    if str(_ROOT) not in __import__("sys").path:
        __import__("sys").path.insert(0, str(_ROOT))
    bb_dir = _ROOT / "browser-bot"
    if str(bb_dir) not in __import__("sys").path:
        __import__("sys").path.insert(0, str(bb_dir))

    from browser_bot.sites import ensure_component_dir

    ensure_component_dir(site, component)
    target = notes_path(site, component)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def append_note(
    site: str,
    component: str,
    *,
    body: str,
    title: str = "",
    source: str = "manual",
) -> Path:
    """Prepend a note (newest first) and save."""
    text = str(body or "").strip()
    if not text and not str(title or "").strip():
        raise ValueError("note body or title is required")
    src = str(source or "manual").strip().lower()
    if src not in _ALLOWED_SOURCES:
        src = "manual"
    data = load_notes(site, component) or empty_notes()
    note = {
        "id": _new_note_id(),
        "created_at": _iso_now(),
        "source": src,
        "title": str(title or "").strip(),
        "body": text,
    }
    data["notes"] = [note] + list(data.get("notes") or [])
    return save_notes(site, component, data)


def append_manual_llm_query(
    site: str,
    component: str,
    *,
    prompt: str,
    response: str,
) -> Path:
    """Append a sidebar Manual LLM Q→A as a notes entry."""
    q = str(prompt or "").strip()
    a = str(response or "").strip()
    if not q:
        raise ValueError("prompt is required")
    title_snip = _WS_RE.sub(" ", q)
    if len(title_snip) > 48:
        title_snip = title_snip[:48].rstrip() + "…"
    title = f"Manual LLM · {title_snip}" if title_snip else "Manual LLM"
    body = f"Prompt:\n{q}\n\nResponse:\n{a or '(empty)'}"
    return append_note(
        site,
        component,
        title=title,
        body=body,
        source="manual_llm",
    )
