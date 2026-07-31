"""Per-playbook hunt learning stored at sites/{site}/{component}/intel/{playbook_id}.json."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_INTEL_DIR_NAME = "intel"

# Component baseline (recon.json) - browser probe only; not updated by report merges.
BASE_RECON_KEYS = frozenset(
    {
        "probed_at",
        "source_mode",
        "target_url",
        "transport",
        "host",
        "product_name",
        "vendor",
        "description",
        "provider",
        "model_hints",
        "inference_type",
        "capabilities",
        "tools",
        "integrations",
        "api_endpoints",
        "auth_mechanisms",
        "tech_stack",
        "ui_features",
        "security_observations",
        "attack_surface_notes",
        "evidence",
        "analyst_notes",
        "confirmation_status",
        "ui_capability_response",
        "har_path",
        "network_log_path",
        "grounding_passed",
        "grounding_issues",
        "judge_reasoning",
    }
)

# Playbook intel file - evolves after assessed runs and recon rounds.
INTEL_KEYS = frozenset(
    {
        "playbook_id",
        "play_category",
        "updated_at",
        "last_strategy",
        "last_report",
        "capabilities",
        "tools",
        "integrations",
        "model_hints",
        "security_observations",
        "attack_surface_notes",
        "recon_findings",
        "recon_rounds",
        "recon_round_at",
        "grounding_issues",
        "ui_capability_response",
        "credentials_and_paths",
    }
)

# Fields where component baseline wins over intel when merging effective recon.
_BASE_WINS_KEYS = frozenset(
    {
        "product_name",
        "vendor",
        "provider",
        "target_url",
        "transport",
        "host",
        "api_endpoints",
        "auth_mechanisms",
        "tech_stack",
        "ui_features",
        "har_path",
        "network_log_path",
        "confirmation_status",
        "probed_at",
        "source_mode",
        "inference_type",
        "grounding_passed",
        "judge_reasoning",
    }
)

# Intel-only fields (not unioned with base lists).
_INTEL_ONLY_KEYS = frozenset(
    {
        "recon_findings",
        "recon_rounds",
        "recon_round_at",
        "playbook_id",
        "play_category",
        "updated_at",
        "last_strategy",
        "last_report",
        "credentials_and_paths",
    }
)

_LIST_UNION_KEYS = frozenset(
    {
        "capabilities",
        "integrations",
        "security_observations",
        "attack_surface_notes",
        "model_hints",
        "grounding_issues",
    }
)

# Fields stored as lean, capped entries (dedup + MRU ranking + hard caps)
# instead of unbounded bare-string lists. Text fields persist as {"text": "..."};
# tools persist as {name, type, description}. No provenance metadata - intel is
# fed to LLMs so every token counts. `capabilities` is deliberately excluded: it's
# a small controlled vocabulary shared with recon.json and drives capability-gating.
_ENTRY_FIELDS = frozenset(
    {
        "recon_findings",
        "security_observations",
        "attack_surface_notes",
        "model_hints",
        "integrations",
        "grounding_issues",
        "tools",
    }
)

# Deterministic backstop: enforced on every merge regardless of whether the
# optional LLM consolidation pass (recon_consolidate.py) runs or succeeds.
MAX_ENTRIES_BY_FIELD: dict[str, int] = {
    "recon_findings": 80,
    "security_observations": 60,
    "attack_surface_notes": 40,
    "model_hints": 20,
    "integrations": 20,
    "grounding_issues": 30,
    "tools": 40,
}

_WS_RE = re.compile(r"\s+")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_entry_text(text: Any) -> str:
    return _WS_RE.sub(" ", str(text or "").strip()).lower()


def _entry_dedup_key(field: str, entry: dict[str, Any]) -> str:
    if field == "tools":
        return str(entry.get("name") or "").strip().lower()
    return _norm_entry_text(entry.get("text"))[:160]


def _coerce_entry(item: Any, *, field: str) -> dict[str, Any] | None:
    """Coerce bare strings / legacy provenance-wrapped dicts into lean entries.

    Text fields -> {"text": "..."}. Tools -> {name, type, description}.
    """
    if field == "tools":
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            if not name:
                return None
            return {
                "name": name,
                "type": str(item.get("type") or "unknown").strip() or "unknown",
                "description": str(item.get("description") or "").strip()[:500],
            }
        name = str(item or "").strip()
        if not name:
            return None
        return {"name": name, "type": "unknown", "description": ""}

    if isinstance(item, dict):
        text = str(item.get("text") or "").strip()
        if not text:
            return None
        return {"text": text}
    text = str(item or "").strip()
    if not text:
        return None
    return {"text": text}


def merge_entry_list(
    existing: list[Any] | None,
    new_items: list[Any] | None,
    *,
    field: str,
    source_report: str = "",
) -> list[dict[str, Any]]:
    """Dedup + MRU reaffirm + hard-cap lean entries for one intel field.

    ``source_report`` is accepted for call-site compatibility but never stored.
    On reaffirmation the entry moves to the front (most useful for LLM truncation).
    Existing order is preserved when seeding; only new/reaffirmed items jump front.
    """
    del source_report  # intentionally unused - never persist provenance
    by_key: dict[str, dict[str, Any]] = {}
    # Most-recently-reaffirmed / newest first.
    order: list[str] = []

    for item in existing or []:
        coerced = _coerce_entry(item, field=field)
        if coerced is None:
            continue
        key = _entry_dedup_key(field, coerced)
        if not key or key in by_key:
            continue
        by_key[key] = coerced
        order.append(key)

    for item in new_items or []:
        coerced = _coerce_entry(item, field=field)
        if coerced is None:
            continue
        key = _entry_dedup_key(field, coerced)
        if not key:
            continue
        if key not in by_key:
            by_key[key] = coerced
            order.insert(0, key)
            continue
        cur = by_key[key]
        if field == "tools":
            if len(str(coerced.get("description") or "")) > len(str(cur.get("description") or "")):
                cur["description"] = coerced["description"]
            if str(cur.get("type") or "unknown") == "unknown" and coerced.get("type"):
                cur["type"] = coerced["type"]
        else:
            # Prefer the newer / more specific wording on reaffirmation.
            cur["text"] = coerced["text"]
        order.remove(key)
        order.insert(0, key)

    ranked = [by_key[k] for k in order]
    cap = MAX_ENTRIES_BY_FIELD.get(field)
    if cap is not None and len(ranked) > cap:
        ranked = ranked[:cap]
    return ranked


def flatten_entries(entries: list[Any] | None) -> list[str]:
    """Plain-text view of a lean entry list (consumer contract)."""
    if not entries:
        return []
    out: list[str] = []
    for item in entries:
        if isinstance(item, dict):
            text = str(item.get("text") or "").strip()
        else:
            text = str(item or "").strip()
        if text:
            out.append(text)
    return out


def flatten_tools(entries: list[Any] | None) -> list[dict[str, str]]:
    """{name,type,description} view of tool entries (strips any legacy metadata)."""
    if not entries:
        return []
    out: list[dict[str, str]] = []
    for item in entries:
        coerced = _coerce_entry(item, field="tools")
        if coerced is None:
            continue
        out.append(coerced)
    return out


def normalize_intel_entries(intel: dict[str, Any]) -> dict[str, Any]:
    """Strip provenance metadata and coerce entry fields to the lean shape."""
    out = dict(intel)
    for field in _ENTRY_FIELDS:
        vals = out.get(field)
        if not isinstance(vals, list) or not vals:
            continue
        out[field] = merge_entry_list(vals, [], field=field)
    return out


def _norm_playbook_id(playbook_id: str) -> str:
    if str(_ROOT) not in __import__("sys").path:
        __import__("sys").path.insert(0, str(_ROOT))
    from playbooks.registry import normalize_playbook_id

    return normalize_playbook_id(playbook_id)


def intel_dir(site: str, component: str) -> Path:
    """Path to sites/{site}/{component}/intel/."""
    site = (site or "").strip()
    component = (component or "").strip()
    return _ROOT / "browser-bot" / "sites" / site / component / _INTEL_DIR_NAME


def intel_path(site: str, component: str, playbook_id: str) -> Path:
    """Path to sites/{site}/{component}/intel/{playbook_id}.json."""
    pid = _norm_playbook_id(playbook_id)
    if not pid:
        raise ValueError("playbook_id is required for intel path")
    return intel_dir(site, component) / f"{pid}.json"


def empty_intel(playbook_id: str, *, play_category: str = "") -> dict[str, Any]:
    """Fresh intel document for a playbook."""
    pid = _norm_playbook_id(playbook_id)
    return {
        "playbook_id": pid,
        "play_category": (play_category or "").strip(),
        "updated_at": _iso_now(),
        "last_strategy": "",
        "last_report": "",
        "capabilities": [],
        "tools": [],
        "integrations": [],
        "model_hints": [],
        "security_observations": [],
        "attack_surface_notes": [],
        "recon_findings": [],
        "recon_rounds": [],
        "grounding_issues": [],
        "by_strategy": {},
    }


# List/entry fields mirrored into by_strategy[<strat>] for clean-lane reads.
_STRATEGY_SLICE_KEYS = frozenset(
    {
        "capabilities",
        "tools",
        "integrations",
        "model_hints",
        "security_observations",
        "attack_surface_notes",
        "recon_findings",
        "grounding_issues",
        "ui_capability_response",
    }
)


def _norm_strategy_key(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def resolve_intel_for_strategy(
    intel: dict[str, Any] | None,
    strategy: str | None,
) -> dict[str, Any] | None:
    """Prefer ``by_strategy[strat]`` list fields; fall back to top-level intel."""
    if not isinstance(intel, dict):
        return intel
    strat = _norm_strategy_key(strategy)
    if not strat:
        return intel
    by = intel.get("by_strategy")
    if not isinstance(by, dict):
        return intel
    slice_doc = by.get(strat)
    if not isinstance(slice_doc, dict) or not slice_doc:
        return intel
    out = dict(intel)
    for key in _STRATEGY_SLICE_KEYS:
        if key in slice_doc:
            out[key] = slice_doc[key]
    return out


def mirror_intel_delta_into_strategy_slice(
    intel: dict[str, Any],
    merge_delta: dict[str, Any],
    ctx: dict[str, Any],
    *,
    merge_fn,
) -> dict[str, Any]:
    """Apply the same merge delta into ``by_strategy[last_strategy]``."""
    strat = _norm_strategy_key(ctx.get("last_strategy") or intel.get("last_strategy"))
    if not strat:
        return intel
    out = dict(intel)
    by = out.get("by_strategy")
    if not isinstance(by, dict):
        by = {}
    prev = by.get(strat) if isinstance(by.get(strat), dict) else {}
    sliced = merge_fn(dict(prev), merge_delta, {**ctx, "_slice_only": True})
    # Keep slice lean - drop nested by_strategy if merge copied it.
    if isinstance(sliced, dict):
        sliced.pop("by_strategy", None)
        by[strat] = sliced
    out["by_strategy"] = by
    return out


def load_playbook_intel(site: str, component: str, playbook_id: str) -> dict[str, Any] | None:
    """Parse intel/{playbook_id}.json; return None if missing or invalid."""
    site = (site or "").strip()
    component = (component or "").strip()
    pid = _norm_playbook_id(playbook_id)
    if not site or not component or not pid:
        return None
    path = intel_path(site, component, pid)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    # Legacy field: no longer generated or consumed.
    data.pop("verbatim_responses", None)
    return normalize_intel_entries(data)


def save_playbook_intel(site: str, component: str, intel: dict[str, Any]) -> Path:
    """Write intel/{playbook_id}.json."""
    site = (site or "").strip()
    component = (component or "").strip()
    if not site or not component:
        raise ValueError("site and component are required to save playbook intel")
    if not isinstance(intel, dict) or not intel:
        raise ValueError("intel must be a non-empty dict")

    pid = _norm_playbook_id(str(intel.get("playbook_id") or ""))
    if not pid:
        raise ValueError("intel.playbook_id is required")

    intel = normalize_intel_entries(dict(intel))
    intel["playbook_id"] = pid
    intel.setdefault("updated_at", _iso_now())
    # Legacy field: no longer generated or persisted.
    intel.pop("verbatim_responses", None)

    if str(_ROOT) not in __import__("sys").path:
        __import__("sys").path.insert(0, str(_ROOT))
    bb_dir = _ROOT / "browser-bot"
    if str(bb_dir) not in __import__("sys").path:
        __import__("sys").path.insert(0, str(bb_dir))

    from browser_bot.sites import ensure_component_dir

    ensure_component_dir(site, component)
    target = intel_path(site, component, pid)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(intel, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def list_intel_files(site: str, component: str) -> list[dict[str, Any]]:
    """List intel files with lightweight metadata."""
    site = (site or "").strip()
    component = (component or "").strip()
    if not site or not component:
        return []
    directory = intel_dir(site, component)
    if not directory.is_dir():
        return []
    # Reserved component inventory - not a playbook intel file.
    try:
        from pipeline.credentials_and_paths import CREDENTIALS_AND_PATHS_STEM
    except Exception:
        CREDENTIALS_AND_PATHS_STEM = "credentials_and_paths"
    out: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        if not path.is_file():
            continue
        if path.stem == CREDENTIALS_AND_PATHS_STEM:
            continue
        entry: dict[str, Any] = {
            "playbook_id": path.stem,
            "path": str(path),
        }
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                entry["updated_at"] = str(data.get("updated_at") or "")
                entry["play_category"] = str(data.get("play_category") or "")
                entry["findings_count"] = len(data.get("recon_findings") or [])
                round_at = str(data.get("recon_round_at") or "").strip()
                if round_at:
                    entry["recon_round_at"] = round_at
        except (OSError, json.JSONDecodeError):
            pass
        out.append(entry)
    return out


def _merge_list_unique(existing: list, new_items: list, *, key=None) -> list:
    out = list(existing) if isinstance(existing, list) else []
    seen = set()
    for item in out:
        marker = key(item) if key else json.dumps(item, sort_keys=True, default=str)
        seen.add(marker)
    for item in new_items or []:
        if item is None:
            continue
        marker = key(item) if key else json.dumps(item, sort_keys=True, default=str)
        if marker in seen:
            continue
        seen.add(marker)
        out.append(item)
    return out


def _merge_tools(existing: list, new_items: list) -> list:
    def _tool_key(t: Any) -> str:
        if isinstance(t, dict):
            return str(t.get("name") or "").strip().lower()
        return str(t).strip().lower()

    return _merge_list_unique(existing or [], new_items or [], key=_tool_key)


def merge_effective_recon(
    base: dict[str, Any] | None,
    intel: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Merge component baseline recon with playbook intel for downstream consumers."""
    if not base and not intel:
        return None
    if not base:
        return dict(intel) if intel else None
    if not intel:
        return dict(base)

    out = dict(base)

    for key in _BASE_WINS_KEYS:
        if base.get(key) is not None and base.get(key) != "":
            out[key] = base[key]

    for key in _INTEL_ONLY_KEYS:
        val = intel.get(key)
        if key in _ENTRY_FIELDS and isinstance(val, list):
            val = flatten_entries(val)
        if val is not None and val != "" and val != []:
            out[key] = val

    for key in _LIST_UNION_KEYS:
        base_vals = base.get(key) or []
        intel_vals = intel.get(key) or []
        if key in _ENTRY_FIELDS and isinstance(intel_vals, list):
            intel_vals = flatten_entries(intel_vals)
        if isinstance(base_vals, list) or isinstance(intel_vals, list):
            merged = _merge_list_unique(
                base_vals if isinstance(base_vals, list) else [],
                intel_vals if isinstance(intel_vals, list) else [],
                key=lambda x: str(x).strip().lower(),
            )
            if merged:
                out[key] = merged

    out["tools"] = _merge_tools(base.get("tools") or [], flatten_tools(intel.get("tools") or []))

    base_ui = str(base.get("ui_capability_response") or "").strip()
    intel_ui = str(intel.get("ui_capability_response") or "").strip()
    if base_ui and intel_ui:
        if intel_ui not in base_ui:
            out["ui_capability_response"] = (base_ui + "\n\n--- Playbook intel ---\n" + intel_ui).strip()[:8000]
        else:
            out["ui_capability_response"] = base_ui[:8000]
    elif intel_ui:
        out["ui_capability_response"] = intel_ui[:8000]
    elif base_ui:
        out["ui_capability_response"] = base_ui[:8000]

    out["_intel_playbook_id"] = intel.get("playbook_id")
    out["_intel_updated_at"] = intel.get("updated_at")
    return out


def load_effective_recon(
    site: str,
    component: str,
    playbook_id: str = "",
    strategy: str | None = None,
) -> dict[str, Any] | None:
    """Load merged component recon + playbook intel when playbook_id is set.

    When ``strategy`` is set, prefer ``intel.by_strategy[strategy]`` list fields
    (fall back to top-level if the slice is missing).
    """
    from pipeline.recon_context import load_component_recon

    base = load_component_recon(site, component)
    pid = _norm_playbook_id(playbook_id)
    if not pid:
        return dict(base) if base else None
    intel = load_playbook_intel(site, component, pid)
    intel = resolve_intel_for_strategy(intel, strategy)
    return merge_effective_recon(base, intel)


def strip_intel_only_fields_from_base(recon: dict[str, Any]) -> dict[str, Any]:
    """Remove hunt-learning fields that belong in intel/, not recon.json."""
    out = dict(recon)
    for key in (
        "verbatim_responses",
        "recon_rounds",
        "recon_round_at",
        "recon_findings",
        "_intel_playbook_id",
        "_intel_updated_at",
    ):
        out.pop(key, None)
    return out
