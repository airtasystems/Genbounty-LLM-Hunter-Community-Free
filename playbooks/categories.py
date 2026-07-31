"""Hierarchical play category taxonomy for UI grouping and generation context."""

from __future__ import annotations

from typing import Any

PLAY_CATEGORY_TREE: tuple[dict[str, Any], ...] = (
    {
        "id": "mission",
        "label": "Mission",
        "hint": "Name the hunt - every mission is identified by its hunt name.",
        "default_l2": "hunt",
        "children": (
            {
                "id": "hunt",
                "label": "Hunt",
                "hint": "Short hunt name required; it also becomes the default mission file id.",
            },
        ),
    },
)

# Default create/update selection: sole taxonomy leaf (mission.hunt).
DEFAULT_PLAY_CATEGORY_L1 = "mission"
DEFAULT_PLAY_CATEGORY_L2 = "hunt"
DEFAULT_PLAY_CATEGORY = f"{DEFAULT_PLAY_CATEGORY_L1}.{DEFAULT_PLAY_CATEGORY_L2}"

# Flat list for backward-compatible API consumers
PLAY_CATEGORIES: tuple[dict[str, str], ...] = tuple(
    {"id": node["id"], "label": node["label"]} for node in PLAY_CATEGORY_TREE
)

_LEAF_IDS: set[str] = set()
_NODE_BY_PATH: dict[tuple[str, ...], dict[str, Any]] = {}
_L1_BY_ID: dict[str, dict[str, Any]] = {n["id"]: n for n in PLAY_CATEGORY_TREE}

# Legacy storage ids rewritten to the current sole leaf.
_CATEGORY_ALIASES: dict[str, str] = {
    "other.custom": DEFAULT_PLAY_CATEGORY,
    "other": DEFAULT_PLAY_CATEGORY,
}


def _walk_tree(
    nodes: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    prefix: tuple[str, ...] = (),
) -> None:
    for node in nodes:
        nid = str(node["id"])
        path = prefix + (nid,)
        _NODE_BY_PATH[path] = node
        children = node.get("children") or ()
        dot = ".".join(path)
        if children:
            _walk_tree(children, path)
        else:
            _LEAF_IDS.add(dot)


_walk_tree(PLAY_CATEGORY_TREE)

PLAY_CATEGORY_IDS = frozenset(_LEAF_IDS)


def _clean_path(parts: list[str]) -> list[str]:
    return [str(p).strip() for p in (parts or []) if str(p).strip()]


def _alias_category_path(parts: list[str]) -> list[str]:
    """Rewrite deprecated L1.L2 paths to the current sole leaf."""
    cleaned = _clean_path(parts)
    if cleaned == ["other", "custom"]:
        return [DEFAULT_PLAY_CATEGORY_L1, DEFAULT_PLAY_CATEGORY_L2]
    if len(cleaned) == 2:
        aliased = _CATEGORY_ALIASES.get(path_to_dot_path(cleaned))
        if aliased and "." in aliased:
            return _clean_path(aliased.split("."))
    return cleaned


def list_play_category_tree() -> list[dict[str, Any]]:
    """Return full taxonomy tree for UI (JSON-serializable)."""

    def _serialize(node: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {"id": node["id"], "label": node["label"]}
        if node.get("hint"):
            out["hint"] = node["hint"]
        children = node.get("children") or ()
        if children:
            out["children"] = [_serialize(c) for c in children]
            if node.get("default_l2"):
                out["default_l2"] = node["default_l2"]
        return out

    return [_serialize(n) for n in PLAY_CATEGORY_TREE]


def default_play_category_path() -> list[str]:
    """Default L1/L2 path for new plays (sole leaf mission.hunt)."""
    return [DEFAULT_PLAY_CATEGORY_L1, DEFAULT_PLAY_CATEGORY_L2]


def default_play_category_l2(l1_id: str) -> str:
    """Return the broad catch-all L2 id for an L1 category (UI default when L1 changes)."""
    l1 = _L1_BY_ID.get(normalize_play_category(l1_id).split(".", 1)[0])
    if not l1:
        # Legacy L1 id other → mission tree
        if normalize_play_category(l1_id) in ("other", DEFAULT_PLAY_CATEGORY):
            return DEFAULT_PLAY_CATEGORY_L2
        return ""
    explicit = l1.get("default_l2")
    if explicit:
        return str(explicit)
    children = l1.get("children") or ()
    return str(children[0]["id"]) if children else ""


def list_play_categories() -> list[dict[str, str]]:
    """L1 categories only."""
    return [dict(c) for c in PLAY_CATEGORIES]


def normalize_play_category(category_id: str) -> str:
    cid = (category_id or "").strip().lower()
    return _CATEGORY_ALIASES.get(cid, cid)


def canonical_category_path(playbook: dict[str, Any]) -> list[str]:
    """Resolve stored play fields to L1.L2 path array."""
    raw_path = playbook.get("play_category_path")
    if isinstance(raw_path, list):
        parts = _alias_category_path(raw_path)
        if len(parts) == 2:
            return parts
    cid = normalize_play_category(str(playbook.get("play_category", "")))
    if "." in cid:
        parts = _alias_category_path(cid.split("."))
        if len(parts) == 2:
            return parts
    return []


def path_to_dot_path(path: list[str]) -> str:
    return ".".join(p.strip() for p in path if p.strip())


def resolve_play_category(
    path: list[str],
    *,
    play_category_label: str = "",
) -> dict[str, Any]:
    """Resolve UI path [l1, l2] to canonical storage fields."""
    parts = _alias_category_path(path)
    if len(parts) != 2:
        raise ValueError("play_category_path must be exactly L1 and L2")
    key = tuple(parts)
    if key not in _NODE_BY_PATH:
        raise ValueError(f"Invalid play_category_path: {'.'.join(parts)}")
    dot = path_to_dot_path(parts)
    if dot not in _LEAF_IDS:
        raise ValueError(f"Invalid play_category_path: {dot}")
    label = play_category_label.strip()
    if not label:
        raise ValueError("play_category_label (hunt name) is required")
    return {
        "play_category": dot,
        "play_category_path": parts,
        "play_category_label": label,
    }


def parse_play_category(
    play_category: str,
    play_category_path: list[str] | None = None,
) -> dict[str, Any]:
    """Parse stored category into UI dropdown state and display metadata."""
    if play_category_path is not None:
        parts = _alias_category_path(play_category_path)
    else:
        cid = normalize_play_category(play_category)
        parts = _alias_category_path(cid.split(".")) if "." in cid else []

    labels: list[str] = []
    for i in range(len(parts)):
        key = tuple(parts[: i + 1])
        node = _NODE_BY_PATH.get(key)
        if node:
            labels.append(str(node.get("label", parts[i])))

    result: dict[str, Any] = {
        "l1": parts[0] if len(parts) > 0 else "",
        "l2": parts[1] if len(parts) > 1 else "",
        "path": parts,
        "labels": labels,
        "dot_path": path_to_dot_path(parts) if parts else normalize_play_category(play_category),
    }
    if len(parts) >= 1:
        l1 = _L1_BY_ID.get(parts[0])
        result["l1_label"] = l1["label"] if l1 else parts[0]
    else:
        result["l1_label"] = "Uncategorized"
    return result


def category_breadcrumb(
    play_category: str,
    custom_label: str = "",
    play_category_path: list[str] | None = None,
) -> str:
    parsed = parse_play_category(play_category, play_category_path)
    # Sole leaf: surface the hunt name, not taxonomy path branding.
    if parsed.get("l1") == DEFAULT_PLAY_CATEGORY_L1 and custom_label.strip():
        return custom_label.strip()
    labels = list(parsed.get("labels") or [])
    return " › ".join(labels) if labels else custom_label.strip() or "Uncategorized"


def category_label(category_id: str, custom_label: str = "") -> str:
    """Display label - breadcrumb for dot-path."""
    cid = normalize_play_category(category_id)
    if cid == DEFAULT_PLAY_CATEGORY_L1 or cid.startswith(f"{DEFAULT_PLAY_CATEGORY_L1}."):
        custom = (custom_label or "").strip()
        if custom:
            return custom
    parsed = parse_play_category(category_id)
    labels = parsed.get("labels") or []
    if labels:
        return category_breadcrumb(category_id, custom_label, parsed.get("path"))
    return custom_label.strip() or cid or "Uncategorized"


def category_context_for_prompt(
    category_id: str,
    custom_label: str = "",
    play_category_path: list[str] | None = None,
) -> str:
    """Hunt name + brief authoring hint (storage leaf is fixed)."""
    hunt = (custom_label or "").strip()
    if not hunt:
        hunt = category_breadcrumb(category_id, custom_label, play_category_path)
    return (
        f"Hunt: {hunt}. Follow the user's play hypothesis closely; "
        "authored attack_techniques are the runtime source of truth."
    )


def is_valid_play_category(category_id: str) -> bool:
    return normalize_play_category(category_id) in _LEAF_IDS


def validate_play_category_fields(
    play_category: str,
    play_category_label: str = "",
    play_category_path: list[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    cid = normalize_play_category(play_category)
    if not cid and not play_category_path:
        errors.append("play_category is required")
        return errors
    if play_category_path:
        try:
            resolve_play_category(play_category_path, play_category_label=play_category_label)
        except ValueError as exc:
            errors.append(str(exc))
        return errors
    if not is_valid_play_category(cid):
        errors.append(f"Invalid play_category: {play_category}")
        return errors
    parsed = parse_play_category(cid)
    if (
        parsed.get("l1") == DEFAULT_PLAY_CATEGORY_L1
        and parsed.get("l2") == DEFAULT_PLAY_CATEGORY_L2
    ):
        if not (play_category_label or "").strip():
            errors.append("play_category_label (hunt name) is required")
    return errors


def play_group_key(playbook: dict[str, Any]) -> str:
    """Sort/group key: L1 id, or mission with hunt label."""
    parts = canonical_category_path(playbook)
    if parts and parts[0] == DEFAULT_PLAY_CATEGORY_L1:
        return (
            f"{DEFAULT_PLAY_CATEGORY_L1}:"
            f"{(playbook.get('play_category_label') or 'Hunt').strip().lower()}"
        )
    if parts:
        return parts[0]
    cid = normalize_play_category(str(playbook.get("play_category", "")))
    if cid == DEFAULT_PLAY_CATEGORY or cid.startswith(f"{DEFAULT_PLAY_CATEGORY_L1}."):
        return (
            f"{DEFAULT_PLAY_CATEGORY_L1}:"
            f"{(playbook.get('play_category_label') or 'Hunt').strip().lower()}"
        )
    return "uncategorized"
