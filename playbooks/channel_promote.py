"""Ensure text-channel playbooks can run multimodal when the target supports upload."""
from __future__ import annotations

import copy
from typing import Any, Sequence

from playbooks.artifact_delivery import ARTIFACT_VECTOR_SPECS
from playbooks.channel_convert import playbook_has_artifact_categories
from playbooks.registry import get_category_channel

# Matches Forge “file, image, and audio probes”.
DEFAULT_MULTIMODAL_VECTORS: tuple[str, ...] = (
    "text",
    "pdf_hidden",
    "image_text",
    "audio_tts",
)

_V3_MAX_CATEGORIES = 3


def _delivery_for_vectors(vectors: Sequence[str]) -> list[str]:
    methods: list[str] = []
    for vector in vectors:
        spec = ARTIFACT_VECTOR_SPECS.get(str(vector).strip())
        if not spec:
            continue
        method = spec[1]
        if method and method not in methods:
            methods.append(method)
    return methods or ["text_file"]


def _normalize_vectors(vectors: Sequence[str] | None) -> list[str]:
    out: list[str] = []
    for value in vectors or DEFAULT_MULTIMODAL_VECTORS:
        vector = str(value or "").strip()
        if vector in ARTIFACT_VECTOR_SPECS and vector not in out:
            out.append(vector)
    return out or list(DEFAULT_MULTIMODAL_VECTORS)


def _existing_ids(categories: list[Any]) -> set[str]:
    ids: set[str] = set()
    for cat in categories:
        if not isinstance(cat, dict):
            continue
        cid = str(cat.get("id") or "").strip()
        if cid:
            ids.add(cid)
    return ids


def _artifact_sibling_id(base_id: str, used: set[str]) -> str:
    stem = (base_id or "CAT").strip() or "CAT"
    candidates = [
        f"{stem}-A",
        f"{stem}A",
        f"{stem}_A",
        f"{stem}02",
        f"{stem}A01",
    ]
    for cand in candidates:
        if cand not in used:
            return cand
    n = 1
    while True:
        cand = f"{stem}-A{n}"
        if cand not in used:
            return cand
        n += 1


def _has_artifact_sibling(categories: list[Any], text_id: str) -> bool:
    """True when an artifact category already covers this text id as sibling/parent."""
    tid = (text_id or "").strip()
    if not tid:
        return False
    for cat in categories:
        if not isinstance(cat, dict):
            continue
        try:
            if get_category_channel(cat) != "artifact":
                continue
        except ValueError:
            continue
        cid = str(cat.get("id") or "").strip()
        parent = str(cat.get("parent_id") or "").strip()
        if cid in {f"{tid}-A", f"{tid}A", f"{tid}_A"} or parent == tid:
            return True
        if cid.startswith(f"{tid}-A") or cid.startswith(f"{tid}_A"):
            return True
    return False


def _enrich_techniques_for_artifact(techniques: Any) -> list[dict[str, Any]]:
    if not isinstance(techniques, list):
        return []
    out: list[dict[str, Any]] = []
    for row in techniques:
        if not isinstance(row, dict):
            continue
        tech = copy.deepcopy(row)
        channels = tech.get("channels")
        if isinstance(channels, list):
            merged = [str(c).strip() for c in channels if str(c).strip()]
            if "artifact" not in merged:
                merged.append("artifact")
            tech["channels"] = merged
        else:
            tech["channels"] = ["text", "artifact"]
        affinity = tech.get("strategy_affinity")
        if isinstance(affinity, list):
            merged_aff = [str(a).strip() for a in affinity if str(a).strip()]
            if "multimodal" not in merged_aff:
                merged_aff.append("multimodal")
            tech["strategy_affinity"] = merged_aff
        out.append(tech)
    return out


def _apply_artifact_fields(
    cat: dict[str, Any],
    *,
    vectors: list[str],
    name_suffix: str = " (file upload)",
) -> None:
    cat["channel"] = "artifact"
    cat["category_vectors"] = list(vectors)
    cat["delivery_methods"] = _delivery_for_vectors(vectors)
    required = cat.get("required_capabilities")
    caps: list[str] = []
    if isinstance(required, list):
        caps = [str(c).strip() for c in required if str(c).strip()]
    if "file_upload" not in caps:
        caps.append("file_upload")
    cat["required_capabilities"] = caps
    if isinstance(cat.get("attack_techniques"), list):
        cat["attack_techniques"] = _enrich_techniques_for_artifact(
            cat.get("attack_techniques")
        )
    name = str(cat.get("name") or "").strip()
    if name and "file upload" not in name.lower() and "artifact" not in name.lower():
        cat["name"] = f"{name}{name_suffix}"


def _clone_text_as_artifact(
    text_cat: dict[str, Any],
    *,
    new_id: str,
    vectors: list[str],
) -> dict[str, Any]:
    sibling = copy.deepcopy(text_cat)
    sibling["id"] = new_id
    sibling["parent_id"] = str(text_cat.get("id") or new_id).strip() or new_id
    _apply_artifact_fields(sibling, vectors=vectors)
    return sibling


def _extend_oracles_for_category(
    data: dict[str, Any],
    *,
    source_id: str,
    new_id: str,
) -> list[str]:
    """Add new_id to semantic_rubric scopes that already cover source_id, or synthesize."""
    changes: list[str] = []
    cfg = data.get("playbook_config")
    if not isinstance(cfg, dict):
        return changes
    assessment = cfg.get("assessment")
    if not isinstance(assessment, dict):
        return changes
    oracles = assessment.get("oracles")
    if not isinstance(oracles, list):
        return changes

    covered = False
    for oracle in oracles:
        if not isinstance(oracle, dict):
            continue
        if str(oracle.get("type") or "").strip() != "semantic_rubric":
            continue
        scope = oracle.get("category_ids")
        if not isinstance(scope, list):
            continue
        ids = [str(x).strip() for x in scope if str(x).strip()]
        if source_id in ids and new_id not in ids:
            ids.append(new_id)
            oracle["category_ids"] = ids
            covered = True
            changes.append(f"oracle {oracle.get('id') or '?'}: category_ids += {new_id}")
        elif new_id in ids:
            covered = True

    if covered:
        return changes

    # Clone first semantic rubric that mentions source_id, or synthesize from triggers.
    for oracle in oracles:
        if not isinstance(oracle, dict):
            continue
        if str(oracle.get("type") or "").strip() != "semantic_rubric":
            continue
        scope = oracle.get("category_ids")
        if not isinstance(scope, list) or source_id not in [
            str(x).strip() for x in scope
        ]:
            continue
        clone = copy.deepcopy(oracle)
        clone["id"] = f"{new_id.lower()}_semantic_success"
        clone["category_ids"] = [new_id]
        oracles.append(clone)
        changes.append(f"oracle: synthesized {clone['id']} for {new_id}")
        return changes

    categories = data.get("categories") or []
    for cat in categories:
        if not isinstance(cat, dict):
            continue
        if str(cat.get("id") or "").strip() != new_id:
            continue
        triggers = cat.get("attack_triggers")
        if not isinstance(triggers, dict):
            break
        exploited = [
            str(item).strip()
            for item in (triggers.get("exploited_if") or [])
            if str(item).strip()
        ]
        if not exploited:
            break
        oracles.append(
            {
                "id": f"{new_id.lower()}_semantic_success",
                "type": "semantic_rubric",
                "category_ids": [new_id],
                "rubric": (
                    f"The response satisfies at least one concrete {new_id} exploited_if "
                    f"condition: {exploited[0]}"
                ),
            }
        )
        changes.append(f"oracle: synthesized {new_id.lower()}_semantic_success")
        break
    return changes


def ensure_artifact_channel_potential(
    data: dict[str, Any],
    *,
    vectors: Sequence[str] | None = None,
    max_categories: int = _V3_MAX_CATEGORIES,
) -> tuple[dict[str, Any], list[str]]:
    """Ensure the playbook has artifact categories for multimodal delivery.

    Leaves existing text categories intact when room allows (schema v3 max 3).
    When already at the category cap with no artifact channel, converts the last
    text category in place so multimodal can still run.
    """
    out = copy.deepcopy(data) if isinstance(data, dict) else {}
    changes: list[str] = []
    categories = out.get("categories")
    if not isinstance(categories, list) or not categories:
        return out, changes

    if playbook_has_artifact_categories(out):
        # Still add missing siblings for text cats when space remains.
        pass

    chosen = _normalize_vectors(vectors)
    used_ids = _existing_ids(categories)

    text_cats = [
        cat
        for cat in categories
        if isinstance(cat, dict) and get_category_channel(cat) == "text"
    ]
    if not text_cats and playbook_has_artifact_categories(out):
        return out, changes

    for text_cat in list(text_cats):
        tid = str(text_cat.get("id") or "").strip()
        if not tid:
            continue
        if _has_artifact_sibling(categories, tid):
            continue
        if playbook_has_artifact_categories(out) and len(categories) >= max_categories:
            break
        if len(categories) < max_categories:
            new_id = _artifact_sibling_id(tid, used_ids)
            sibling = _clone_text_as_artifact(
                text_cat, new_id=new_id, vectors=chosen
            )
            categories.append(sibling)
            used_ids.add(new_id)
            changes.append(f"{tid}: added artifact sibling {new_id}")
            changes.extend(
                _extend_oracles_for_category(out, source_id=tid, new_id=new_id)
            )
            continue

        # At category cap with no artifact yet: convert last text category in place.
        if playbook_has_artifact_categories(out):
            break
        # Prefer converting a non-primary text category when possible.
        convert_target = text_cats[-1]
        convert_id = str(convert_target.get("id") or "").strip()
        if len(text_cats) > 1 and convert_id == str(text_cats[0].get("id") or "").strip():
            convert_target = text_cats[-1]
        _apply_artifact_fields(convert_target, vectors=chosen)
        changes.append(
            f"{convert_id or '?'}: converted text → artifact (category cap {max_categories})"
        )
        break

    out["categories"] = categories
    return out, changes


__all__ = [
    "DEFAULT_MULTIMODAL_VECTORS",
    "ensure_artifact_channel_potential",
    "playbook_has_artifact_categories",
]
