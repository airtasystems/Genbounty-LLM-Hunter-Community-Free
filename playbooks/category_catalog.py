"""Strict loader for the declarative play-category semantic catalog."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playbooks.categories import PLAY_CATEGORY_IDS, PLAY_CATEGORY_TREE


CATALOG_PATH = Path(__file__).with_name("taxonomy") / "category_catalog.json"
TECHNIQUE_FAMILIES_PATH = (
    Path(__file__).with_name("taxonomy") / "technique_families.json"
)
_CAPABILITIES = frozenset({
    "file_upload",
    "multi_turn",
    "code_execution",
    "web_browse",
    "image_gen",
    "retrieval",
    "memory",
    "tool_use",
})
_TECHNIQUE_CHANNELS = frozenset({"text", "artifact"})
_STRATEGY_AFFINITIES = frozenset({
    "zero_shot",
    "adaptive",
    "multi_shot",
    "few_shot",
    "iterative",
    "chain_of_thought",
    "prompt_chaining",
    "tree_of_thoughts",
    "self_consistency",
    "self_reflection",
    "directional_stimulus",
    "jailbreak",
    "multimodal",
})
_LEAF_FIELDS = frozenset({
    "label",
    "hint",
    "objective",
    "success",
    "mitigation",
    "preset_family",
    "capability_family",
    "technique_family",
    "overrides",
})
_OVERRIDE_FIELDS = frozenset({
    "title_hint",
    "delivery_constraints",
    "required_capabilities",
    "optional_capabilities",
    "capability_profile",
    "category_vectors",
})


@dataclass(frozen=True)
class CapabilityFamily:
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    profile: str = ""
    vectors: tuple[str, ...] = ()


@dataclass(frozen=True)
class LeafCatalogEntry:
    label: str
    hint: str
    objective: str
    success: tuple[str, ...]
    mitigation: tuple[str, ...]
    preset_family: str
    capability_family: str
    technique_family: str
    overrides: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TechniqueDefinition:
    name: str
    summary: str
    example: str
    channels: tuple[str, ...]
    strategy_affinity: tuple[str, ...]


@dataclass(frozen=True)
class Catalog:
    preset_families: dict[str, dict[str, Any]]
    capability_families: dict[str, CapabilityFamily]
    technique_families: dict[str, tuple[TechniqueDefinition, ...]]
    leaves: dict[str, LeafCatalogEntry]


def _nonempty_string(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{location} must be a non-empty string")
    return value.strip()


def _string_tuple(value: Any, location: str, *, nonempty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise RuntimeError(f"{location} must be an array")
    result = tuple(_nonempty_string(item, f"{location}[{index}]") for index, item in enumerate(value))
    if nonempty and not result:
        raise RuntimeError(f"{location} must not be empty")
    if len(result) != len(set(result)):
        raise RuntimeError(f"{location} contains duplicates")
    return result


def _taxonomy_semantics() -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for root in PLAY_CATEGORY_TREE:
        for child in root.get("children") or ():
            path = f"{root['id']}.{child['id']}"
            result[path] = (
                str(child.get("label") or "").strip(),
                str(child.get("hint") or "").strip(),
            )
    return result


def _validate_capability_reference(reference: str, location: str) -> None:
    alternatives = reference.split("|")
    if not alternatives or any(item not in _CAPABILITIES for item in alternatives):
        raise RuntimeError(f"{location} references unknown capability: {reference}")


def _load_technique_families(
    path: str | Path,
) -> dict[str, tuple[TechniqueDefinition, ...]]:
    pack_path = Path(path)
    try:
        raw = json.loads(pack_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to load technique families {pack_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError("Technique-family catalog root must be an object")
    if set(raw) != {"schema_version", "technique_families"}:
        raise RuntimeError("Technique-family catalog fields mismatch")
    if raw["schema_version"] != 1:
        raise RuntimeError("Unsupported technique-family schema_version")

    families_raw = raw["technique_families"]
    if not isinstance(families_raw, dict) or not families_raw:
        raise RuntimeError("technique_families must be a non-empty object")
    families: dict[str, tuple[TechniqueDefinition, ...]] = {}
    technique_fields = {
        "name",
        "summary",
        "example",
        "channels",
        "strategy_affinity",
    }
    for raw_family, pack_raw in families_raw.items():
        family = _nonempty_string(raw_family, "technique family name")
        if family in families:
            raise RuntimeError(f"Duplicate technique family: {family}")
        if not isinstance(pack_raw, list) or not pack_raw:
            raise RuntimeError(f"technique_families.{family} must be a non-empty array")
        pack: list[TechniqueDefinition] = []
        names: set[str] = set()
        for index, values in enumerate(pack_raw):
            location = f"technique_families.{family}[{index}]"
            if not isinstance(values, dict) or set(values) != technique_fields:
                raise RuntimeError(f"{location} has invalid fields")
            name = _nonempty_string(values["name"], f"{location}.name")
            summary = _nonempty_string(values["summary"], f"{location}.summary")
            if name in names:
                raise RuntimeError(
                    f"technique_families.{family} contains duplicate name: {name}"
                )
            names.add(name)
            example = values["example"]
            if not isinstance(example, str):
                raise RuntimeError(f"{location}.example must be a string")
            channels = _string_tuple(
                values["channels"], f"{location}.channels", nonempty=True
            )
            invalid_channels = set(channels) - _TECHNIQUE_CHANNELS
            if invalid_channels:
                raise RuntimeError(
                    f"{location}.channels contains invalid values: "
                    f"{sorted(invalid_channels)}"
                )
            affinity = _string_tuple(
                values["strategy_affinity"], f"{location}.strategy_affinity"
            )
            invalid_affinity = set(affinity) - _STRATEGY_AFFINITIES
            if invalid_affinity:
                raise RuntimeError(
                    f"{location}.strategy_affinity contains invalid values: "
                    f"{sorted(invalid_affinity)}"
                )
            pack.append(
                TechniqueDefinition(
                    name=name,
                    summary=summary,
                    example=example.strip(),
                    channels=channels,
                    strategy_affinity=affinity,
                )
            )
        families[family] = tuple(pack)
    return families


def load_catalog(
    path: str | Path = CATALOG_PATH,
    technique_families_path: str | Path = TECHNIQUE_FAMILIES_PATH,
) -> Catalog:
    """Load and validate a complete catalog; malformed or partial data fails closed."""
    catalog_path = Path(path)
    try:
        raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to load semantic catalog {catalog_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError("Semantic catalog root must be an object")
    expected_root = {
        "schema_version",
        "preset_families",
        "capability_families",
        "leaves",
    }
    if set(raw) != expected_root:
        raise RuntimeError(
            f"Semantic catalog fields mismatch; missing={sorted(expected_root - set(raw))}, "
            f"extra={sorted(set(raw) - expected_root)}"
        )
    if raw["schema_version"] != 1:
        raise RuntimeError("Unsupported semantic catalog schema_version")

    preset_raw = raw["preset_families"]
    if not isinstance(preset_raw, dict) or not preset_raw:
        raise RuntimeError("preset_families must be a non-empty object")
    preset_families: dict[str, dict[str, Any]] = {}
    for name, values in preset_raw.items():
        family = _nonempty_string(name, "preset family name")
        if not isinstance(values, dict):
            raise RuntimeError(f"preset_families.{family} must be an object")
        unknown = set(values) - {"title_hint"}
        if unknown:
            raise RuntimeError(f"preset_families.{family} has unknown fields: {sorted(unknown)}")
        title_hint = str(values.get("title_hint") or "").strip()
        preset_families[family] = {
            "title_hint": title_hint,
        }

    capability_raw = raw["capability_families"]
    if not isinstance(capability_raw, dict) or not capability_raw:
        raise RuntimeError("capability_families must be a non-empty object")
    capability_families: dict[str, CapabilityFamily] = {}
    capability_fields = {
        "required_capabilities",
        "optional_capabilities",
        "capability_profile",
        "category_vectors",
    }
    for name, values in capability_raw.items():
        family = _nonempty_string(name, "capability family name")
        if not isinstance(values, dict) or set(values) != capability_fields:
            raise RuntimeError(f"capability_families.{family} has invalid fields")
        required = _string_tuple(
            values["required_capabilities"],
            f"capability_families.{family}.required_capabilities",
        )
        optional = _string_tuple(
            values["optional_capabilities"],
            f"capability_families.{family}.optional_capabilities",
        )
        for reference in (*required, *optional):
            _validate_capability_reference(
                reference, f"capability_families.{family}"
            )
        capability_families[family] = CapabilityFamily(
            required=required,
            optional=optional,
            profile=str(values["capability_profile"] or "").strip(),
            vectors=_string_tuple(
                values["category_vectors"],
                f"capability_families.{family}.category_vectors",
            ),
        )

    technique_families = _load_technique_families(technique_families_path)
    leaves_raw = raw["leaves"]
    if not isinstance(leaves_raw, dict):
        raise RuntimeError("leaves must be an object")
    missing = PLAY_CATEGORY_IDS - leaves_raw.keys()
    extra = leaves_raw.keys() - PLAY_CATEGORY_IDS
    if missing or extra:
        raise RuntimeError(
            f"Semantic catalog leaf mismatch; missing={sorted(missing)}, extra={sorted(extra)}"
        )

    taxonomy = _taxonomy_semantics()
    leaves: dict[str, LeafCatalogEntry] = {}
    semantic_boundaries: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    objectives: set[str] = set()
    for leaf_id in sorted(PLAY_CATEGORY_IDS):
        values = leaves_raw[leaf_id]
        if not isinstance(values, dict):
            raise RuntimeError(f"leaves.{leaf_id} must be an object")
        unknown = set(values) - _LEAF_FIELDS
        required = _LEAF_FIELDS - {"overrides"}
        missing_fields = required - set(values)
        if unknown or missing_fields:
            raise RuntimeError(
                f"leaves.{leaf_id} fields mismatch; missing={sorted(missing_fields)}, "
                f"extra={sorted(unknown)}"
            )
        label = _nonempty_string(values["label"], f"leaves.{leaf_id}.label")
        hint = _nonempty_string(values["hint"], f"leaves.{leaf_id}.hint")
        if (label, hint) != taxonomy[leaf_id]:
            raise RuntimeError(f"leaves.{leaf_id} label/hint do not match taxonomy")
        objective = _nonempty_string(values["objective"], f"leaves.{leaf_id}.objective")
        success = _string_tuple(values["success"], f"leaves.{leaf_id}.success", nonempty=True)
        mitigation = _string_tuple(
            values["mitigation"], f"leaves.{leaf_id}.mitigation", nonempty=True
        )
        if objective in objectives:
            raise RuntimeError(f"leaves.{leaf_id}.objective is not leaf-specific")
        objectives.add(objective)
        boundary = (success, mitigation)
        if boundary in semantic_boundaries:
            raise RuntimeError(f"leaves.{leaf_id} outcome boundary is not leaf-specific")
        semantic_boundaries.add(boundary)

        preset_family = _nonempty_string(
            values["preset_family"], f"leaves.{leaf_id}.preset_family"
        )
        capability_family = _nonempty_string(
            values["capability_family"], f"leaves.{leaf_id}.capability_family"
        )
        technique_family = _nonempty_string(
            values["technique_family"], f"leaves.{leaf_id}.technique_family"
        )
        if preset_family not in preset_families:
            raise RuntimeError(f"leaves.{leaf_id} references unknown preset family")
        if capability_family not in capability_families:
            raise RuntimeError(f"leaves.{leaf_id} references unknown capability family")
        if technique_family not in technique_families:
            raise RuntimeError(f"leaves.{leaf_id} references unknown technique family")

        overrides = values.get("overrides", {})
        if not isinstance(overrides, dict):
            raise RuntimeError(f"leaves.{leaf_id}.overrides must be an object")
        unknown_overrides = set(overrides) - _OVERRIDE_FIELDS
        if unknown_overrides:
            raise RuntimeError(
                f"leaves.{leaf_id}.overrides has unknown fields: {sorted(unknown_overrides)}"
            )
        for key in ("required_capabilities", "optional_capabilities", "category_vectors"):
            if key in overrides:
                overrides[key] = _string_tuple(
                    overrides[key], f"leaves.{leaf_id}.overrides.{key}"
                )
        for key in ("title_hint", "delivery_constraints", "capability_profile"):
            if key in overrides and not isinstance(overrides[key], str):
                raise RuntimeError(f"leaves.{leaf_id}.overrides.{key} must be a string")
        for reference in (
            *overrides.get("required_capabilities", ()),
            *overrides.get("optional_capabilities", ()),
        ):
            _validate_capability_reference(reference, f"leaves.{leaf_id}.overrides")

        leaves[leaf_id] = LeafCatalogEntry(
            label=label,
            hint=hint,
            objective=objective,
            success=success,
            mitigation=mitigation,
            preset_family=preset_family,
            capability_family=capability_family,
            technique_family=technique_family,
            overrides=dict(overrides),
        )
    referenced_families = {entry.technique_family for entry in leaves.values()}
    orphan_families = technique_families.keys() - referenced_families
    if orphan_families:
        raise RuntimeError(
            f"Technique families are not referenced by any leaf: {sorted(orphan_families)}"
        )
    return Catalog(
        preset_families=preset_families,
        capability_families=capability_families,
        technique_families=technique_families,
        leaves=leaves,
    )


CATALOG = load_catalog()
PRESET_FAMILIES = CATALOG.preset_families
CAPABILITY_FAMILIES = CATALOG.capability_families
TECHNIQUE_FAMILIES = CATALOG.technique_families
TECHNIQUE_FAMILY_NAMES = frozenset(TECHNIQUE_FAMILIES)
LEAF_CATALOG = CATALOG.leaves
