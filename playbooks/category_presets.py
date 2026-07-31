"""Strict, leaf-specific category presets backed by the semantic catalog."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any

from playbooks.category_catalog import (
    CAPABILITY_FAMILIES,
    LEAF_CATALOG,
    PRESET_FAMILIES,
)
from playbooks.categories import default_play_category_l2, normalize_play_category


@dataclass(frozen=True)
class CategoryPreset:
    play_starter: str
    success_rules: tuple[str, ...]
    failure_rules: tuple[str, ...]
    title_hint: str = ""
    delivery_constraints: str = ""
    required_capabilities: tuple[str, ...] = field(default_factory=tuple)
    optional_capabilities: tuple[str, ...] = field(default_factory=tuple)
    capability_profile: str = ""
    category_vectors: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in (
            "success_rules",
            "failure_rules",
            "required_capabilities",
            "optional_capabilities",
            "category_vectors",
        ):
            result[key] = list(result[key])
        return result


def _tuple_override(overrides: dict[str, Any], name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = overrides.get(name)
    return tuple(value) if value is not None else default


def _materialize_leaf_preset(path: str) -> CategoryPreset:
    """Materialize semantics directly from one validated catalog entry."""
    entry = LEAF_CATALOG[path]
    capability = CAPABILITY_FAMILIES[entry.capability_family]
    family = PRESET_FAMILIES[entry.preset_family]
    overrides = entry.overrides
    return CategoryPreset(
        play_starter=entry.objective,
        success_rules=entry.success,
        failure_rules=entry.mitigation,
        title_hint=str(overrides.get("title_hint") or entry.label or family["title_hint"]),
        delivery_constraints=str(overrides.get("delivery_constraints") or ""),
        required_capabilities=_tuple_override(
            overrides, "required_capabilities", capability.required
        ),
        optional_capabilities=_tuple_override(
            overrides, "optional_capabilities", capability.optional
        ),
        capability_profile=str(
            overrides.get("capability_profile", capability.profile)
        ),
        category_vectors=_tuple_override(
            overrides, "category_vectors", capability.vectors
        ),
    )


_LEAF_PRESETS: dict[str, CategoryPreset] = {
    path: _materialize_leaf_preset(path) for path in LEAF_CATALOG
}

# Family metadata for the catalog API. Resolved leaves never consume these
# outcome rules.
_PRESET_FAMILIES: dict[str, CategoryPreset] = {
    name: CategoryPreset(
        play_starter="",
        success_rules=(),
        failure_rules=(),
        title_hint=str(values["title_hint"]),
    )
    for name, values in PRESET_FAMILIES.items()
}


def resolve_category_preset(
    l1: str,
    l2: str = "",
    *,
    play_category_label: str = "",
    capabilities: dict[str, bool] | None = None,
) -> CategoryPreset:
    """Resolve one exact leaf; unknown references never fall back."""
    _ = capabilities  # reserved: capability-gated delivery is authored, not leaf-driven
    l1_id = normalize_play_category(l1)
    if not l1_id:
        raise ValueError("play category L1 is required")
    l2_id = (l2 or "").strip() or default_play_category_l2(l1_id)
    path = f"{l1_id}.{l2_id}" if l2_id else ""
    if path not in _LEAF_PRESETS:
        raise ValueError(f"Unknown play category leaf: {path or l1_id}")
    preset = _LEAF_PRESETS[path]
    label = (play_category_label or "").strip()
    if label:
        preset = replace(
            preset,
            play_starter=(
                f"Obtain reportable evidence that the target discloses a protected "
                f"asset for hunt '{label}' under an observable attack action a "
                f"bug-bounty program would accept."
            ),
            title_hint=label[:80],
        )
    return preset


def list_category_presets() -> dict[str, Any]:
    """Return complete serializable catalog metadata and exact leaf presets."""
    leaf_presets = {
        path: value.to_dict() for path, value in _LEAF_PRESETS.items()
    }
    leaf_mappings = {
        path: {
            "preset_family": entry.preset_family,
            "capability_family": entry.capability_family,
            "technique_family": entry.technique_family,
        }
        for path, entry in LEAF_CATALOG.items()
    }
    capability_families = {
        key: {
            "required_capabilities": list(value.required),
            "optional_capabilities": list(value.optional),
            "capability_profile": value.profile,
            "category_vectors": list(value.vectors),
        }
        for key, value in CAPABILITY_FAMILIES.items()
    }
    family_metadata = {
        key: value.to_dict() for key, value in _PRESET_FAMILIES.items()
    }
    return {
        "preset_families": family_metadata,
        "capability_families": capability_families,
        "leaf_mappings": leaf_mappings,
        "leaf_presets": leaf_presets,
        "leaf_count": len(leaf_presets),
    }


def preset_to_api_dict(preset: CategoryPreset, *, l1: str, l2: str) -> dict[str, Any]:
    result = preset.to_dict()
    result["play_category_path"] = [l1, l2] if l2 else [l1]
    path = f"{l1}.{l2}" if l2 else l1
    result["source"] = "leaf_catalog" if path in LEAF_CATALOG else "unknown"
    return result
