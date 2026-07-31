"""Persist and load accepted/rejected enhancement theories per target + play."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent


def _norm_strategy(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _norm_playbook(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def theory_history_path(site: str, component: str) -> Path:
    return _ROOT / "browser-bot" / "sites" / site / component / "enhance_theory_history.json"


_GENBOUNTY_THEORY_HISTORY = 40
_GENBOUNTY_THEORY_CONTEXT_ENTRIES = 5


def _history_cap() -> int:
    return max(5, _GENBOUNTY_THEORY_HISTORY)


def _context_history_limit() -> int:
    return max(1, _GENBOUNTY_THEORY_CONTEXT_ENTRIES)


def _truncate(text: str, limit: int = 1200) -> str:
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def load_theory_history_file(site: str, component: str) -> dict[str, Any]:
    path = theory_history_path(site, component)
    if not path.is_file():
        return {"entries": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"entries": []}
    if not isinstance(data, dict):
        return {"entries": []}
    entries = data.get("entries")
    if not isinstance(entries, list):
        data["entries"] = []
    return data


def load_theory_history(
    site: str,
    component: str,
    playbook_id: str,
    strategy: str,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Newest-first history entries for one play + strategy."""
    if not site or not component:
        return []
    pid = _norm_playbook(playbook_id)
    strat = _norm_strategy(strategy)
    entries = load_theory_history_file(site, component).get("entries") or []
    out: list[dict[str, Any]] = []
    for row in reversed(entries):
        if not isinstance(row, dict):
            continue
        if _norm_playbook(row.get("playbook_id", "")) != pid:
            continue
        if _norm_strategy(row.get("strategy", "")) != strat:
            continue
        out.append(row)
        if limit is not None and len(out) >= limit:
            break
    return out


def clear_theory_history(
    site: str,
    component: str,
    *,
    playbook_id: str | None = None,
    strategy: str | None = None,
) -> int:
    """Remove history entries; optional playbook/strategy filter. Returns count removed."""
    if not site or not component:
        return 0
    data = load_theory_history_file(site, component)
    entries = list(data.get("entries") or [])
    if not entries:
        return 0
    pid = _norm_playbook(playbook_id) if playbook_id else ""
    strat = _norm_strategy(strategy) if strategy else ""
    if not pid and not strat:
        removed = len(entries)
        data["entries"] = []
    else:
        kept: list[dict[str, Any]] = []
        removed = 0
        for row in entries:
            if not isinstance(row, dict):
                removed += 1
                continue
            if pid and _norm_playbook(row.get("playbook_id", "")) != pid:
                kept.append(row)
                continue
            if strat and _norm_strategy(row.get("strategy", "")) != strat:
                kept.append(row)
                continue
            removed += 1
        data["entries"] = kept
    if removed:
        path = theory_history_path(site, component)
        path.parent.mkdir(parents=True, exist_ok=True)
        if data["entries"]:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        elif path.is_file():
            path.unlink()
    return removed


def delete_theory_history_entry(
    site: str,
    component: str,
    entry_index: int,
) -> bool:
    """Delete one entry by index in chronological storage order (0 = oldest)."""
    if not site or not component:
        return False
    data = load_theory_history_file(site, component)
    entries = list(data.get("entries") or [])
    if entry_index < 0 or entry_index >= len(entries):
        return False
    entries.pop(entry_index)
    data["entries"] = entries
    path = theory_history_path(site, component)
    path.parent.mkdir(parents=True, exist_ok=True)
    if entries:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif path.is_file():
        path.unlink()
    return True


def append_theory_history_entry(
    site: str,
    component: str,
    entry: dict[str, Any],
) -> Path | None:
    if not site or not component:
        return None
    path = theory_history_path(site, component)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = load_theory_history_file(site, component)
    entries = list(data.get("entries") or [])
    row = dict(entry)
    row.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    entries.append(row)
    cap = _history_cap()
    if len(entries) > cap:
        entries = entries[-cap:]
    data["entries"] = entries
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def summarize_history_for_context(
    history: list[dict[str, Any]],
    *,
    session_rejections: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compact history for LLM context."""
    limit = _context_history_limit()
    accepted: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    for row in history:
        status = str(row.get("status") or "").strip().lower()
        theory = _truncate(row.get("theory") or "")
        if not theory:
            continue
        item = {
            "theory": theory,
            "timestamp": str(row.get("timestamp") or "")[:32],
            "round": str(row.get("round") or ""),
        }
        if status == "accepted":
            if len(accepted) >= limit:
                continue
            accepted.append(item)
        elif status == "rejected":
            if len(rejected) >= limit:
                continue
            rejected.append({**item, "reason": _truncate(row.get("reason") or "", 400)})

    session: list[dict[str, str]] = []
    for row in session_rejections or []:
        theory = _truncate(row.get("theory") or "")
        if not theory:
            continue
        session.append(
            {
                "theory": theory,
                "reason": _truncate(row.get("reason") or "", 400),
            }
        )

    return {
        "past_accepted_theories": accepted,
        "past_rejected_theories": rejected,
        "session_rejections": session,
    }
