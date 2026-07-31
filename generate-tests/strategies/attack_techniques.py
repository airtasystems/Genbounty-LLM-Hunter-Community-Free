"""Materialize taxonomy-aware attack techniques from the validated catalog.

Every canonical taxonomy leaf resolves through its exact declarative family. Unknown
categories are rejected; no L1 or generic fallback participates in resolution.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from playbooks.category_catalog import CATALOG, LEAF_CATALOG
from playbooks.categories import normalize_play_category


@dataclass(frozen=True)
class Technique:
    name: str
    summary: str
    example: str = ""
    channels: tuple[str, ...] = ("text",)
    strategy_affinity: tuple[str, ...] = field(default_factory=tuple)


def _materialize_family_packs() -> dict[str, tuple[Technique, ...]]:
    return {
        family: tuple(
            Technique(
                name=item.name,
                summary=item.summary,
                example=item.example,
                channels=item.channels,
                strategy_affinity=item.strategy_affinity,
            )
            for item in definitions
        )
        for family, definitions in CATALOG.technique_families.items()
    }


TECHNIQUE_FAMILIES = _materialize_family_packs()


def _materialize_leaf_pack(leaf_id: str) -> tuple[Technique, ...]:
    """Ground reusable mechanisms in one leaf's explicit objective."""
    entry = LEAF_CATALOG[leaf_id]
    family = TECHNIQUE_FAMILIES[entry.technique_family]
    return tuple(
        Technique(
            name=technique.name,
            summary=(
                f"{entry.label} - {technique.summary} "
                f"Leaf objective: {entry.objective}"
            ),
            example=(
                f"For the {entry.label} objective ({entry.objective}), "
                f"{technique.example or 'apply this mechanism and require concrete observable evidence.'}"
            ),
            channels=technique.channels,
            strategy_affinity=technique.strategy_affinity,
        )
        for technique in family
    )


# Every known leaf owns an exact immutable pack. Families share mechanism design,
# but no leaves share tuple or Technique instances and all text is leaf-grounded.
REGISTRY: dict[str, tuple[Technique, ...]] = {
    leaf_id: _materialize_leaf_pack(leaf_id) for leaf_id in LEAF_CATALOG
}
CURATED_LEAF_PACKS = frozenset(
    leaf_id
    for leaf_id, entry in LEAF_CATALOG.items()
    if leaf_id.rsplit(".", 1)[1] == entry.technique_family
)


def normalize_category(play_category: str) -> str:
    return normalize_play_category(play_category)


def normalize_strategy_kind(strategy_kind: str | None) -> str:
    """Normalize strategy slug for affinity matching."""
    return (strategy_kind or "").strip().lower().replace("-", "_")


# Adaptive seeds are single-turn openers, but runtime follow-ups continue the
# conversation, so include zero-shot and multi-turn affinity techniques.
_ADAPTIVE_AFFINITY_KINDS = frozenset({
    "adaptive",
    "zero_shot",
    "multi_shot",
    "iterative",
    "prompt_chaining",
})
_VALID_CHANNELS = frozenset({"text", "artifact"})
_VALID_STRATEGY_AFFINITIES = frozenset({
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
# LLM authors often invent leaf names or follow-up synonyms as affinities.
_STRATEGY_AFFINITY_ALIASES = {
    "iterative_followup": "iterative",
    "iterative_follow_up": "iterative",
    "followup": "iterative",
    "follow_up": "iterative",
    "cot": "chain_of_thought",
    "tot": "tree_of_thoughts",
    "self_consist": "self_consistency",
    "reflection": "self_reflection",
    "multishot": "multi_shot",
    "fewshot": "few_shot",
    "zeroshot": "zero_shot",
}
_AUTHORED_FIELDS = frozenset({
    "name", "summary", "example", "channels", "strategy_affinity"
})


def sanitize_strategy_affinity(values: Any) -> list[str]:
    """Keep only known generation-strategy affinities; map common aliases; drop junk."""
    if values is None:
        return []
    if isinstance(values, str):
        raw_list = [values]
    elif isinstance(values, (list, tuple)):
        raw_list = list(values)
    else:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for value in raw_list:
        if not isinstance(value, str) or not value.strip():
            continue
        kind = normalize_strategy_kind(value)
        kind = _STRATEGY_AFFINITY_ALIASES.get(kind, kind)
        if kind not in _VALID_STRATEGY_AFFINITIES:
            continue
        if kind in seen:
            continue
        seen.add(kind)
        out.append(kind)
    return out


def sanitize_authored_attack_techniques(
    authored_techniques: list[dict] | tuple[dict, ...] | None,
) -> list[dict[str, Any]]:
    """Return a copy of authored techniques with strategy_affinity sanitized."""
    if not isinstance(authored_techniques, (list, tuple)):
        return []
    cleaned: list[dict[str, Any]] = []
    for raw in authored_techniques:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        if "strategy_affinity" in row:
            row["strategy_affinity"] = sanitize_strategy_affinity(row.get("strategy_affinity"))
        cleaned.append(row)
    return cleaned


def filter_techniques_for_strategy(
    techniques: list[Technique],
    strategy_kind: str | None,
) -> list[Technique]:
    """Prefer techniques tagged for this strategy; drop other affinity-only rows."""
    kind = normalize_strategy_kind(strategy_kind)
    if not kind or not techniques:
        return techniques

    affinity_matched: list[Technique] = []
    universal: list[Technique] = []
    for technique in techniques:
        affinity = technique.strategy_affinity
        if not affinity:
            universal.append(technique)
            continue
        affinity_kinds = {normalize_strategy_kind(value) for value in affinity}
        if kind == "adaptive":
            if affinity_kinds & _ADAPTIVE_AFFINITY_KINDS:
                affinity_matched.append(technique)
        elif kind in affinity_kinds:
            affinity_matched.append(technique)

    if not affinity_matched:
        return techniques

    ordered: list[Technique] = []
    seen: set[str] = set()
    for technique in (*affinity_matched, *universal):
        if technique.name not in seen:
            seen.add(technique.name)
            ordered.append(technique)
    return ordered


def _authored_string(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{location} must be a non-empty string")
    return value.strip()


def _parse_authored_techniques(
    authored_techniques: list[dict] | tuple[dict, ...] | None,
) -> tuple[Technique, ...]:
    if not isinstance(authored_techniques, (list, tuple)) or not authored_techniques:
        raise ValueError("mission.hunt requires a non-empty authored attack_techniques list")
    parsed: list[Technique] = []
    seen: set[str] = set()
    for index, raw in enumerate(authored_techniques):
        location = f"attack_techniques[{index}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{location} must be an object")
        unknown = set(raw) - _AUTHORED_FIELDS
        if unknown:
            raise ValueError(f"{location} has unknown fields: {sorted(unknown)}")
        name = _authored_string(raw.get("name"), f"{location}.name")
        summary = _authored_string(raw.get("summary"), f"{location}.summary")
        if name in seen:
            raise ValueError(f"Duplicate authored attack technique: {name}")
        seen.add(name)

        raw_channels = raw.get("channels")
        if not isinstance(raw_channels, list) or not raw_channels:
            raise ValueError(f"{location}.channels must be a non-empty array")
        if any(not isinstance(value, str) or not value.strip() for value in raw_channels):
            raise ValueError(f"{location}.channels must contain non-empty strings")
        channels = tuple(value.strip() for value in raw_channels)
        if len(channels) != len(set(channels)):
            raise ValueError(f"{location}.channels contains duplicates")
        invalid_channels = set(channels) - _VALID_CHANNELS
        if invalid_channels:
            raise ValueError(
                f"{location}.channels contains invalid values: {sorted(invalid_channels)}"
            )

        raw_affinity = raw.get("strategy_affinity", [])
        if raw_affinity is None:
            raw_affinity = []
        if not isinstance(raw_affinity, (list, tuple, str)):
            raise ValueError(f"{location}.strategy_affinity must be an array")
        # Drop unknown affinities (LLMs invent leaf names like authority_framing).
        affinity = tuple(sanitize_strategy_affinity(raw_affinity))
        example = raw.get("example", "")
        if not isinstance(example, str):
            raise ValueError(f"{location}.example must be a string")
        parsed.append(
            Technique(
                name=name,
                summary=summary,
                example=example.strip(),
                channels=channels,
                strategy_affinity=affinity,
            )
        )
    return tuple(parsed)


def get_techniques(
    play_category: str,
    channel: str = "text",
    limit: int | None = None,
    strategy_kind: str | None = None,
    authored_techniques: list[dict] | tuple[dict, ...] | None = None,
) -> list[Technique]:
    """Return exact-leaf techniques, filtered by channel and strategy affinity."""
    pc = normalize_category(play_category)
    if pc not in LEAF_CATALOG:
        raise ValueError(f"Unknown play category leaf: {pc or '<empty>'}")
    base = (
        _parse_authored_techniques(authored_techniques)
        if pc == "mission.hunt"
        else REGISTRY[pc]
    )
    out = [technique for technique in base if not channel or channel in technique.channels]
    out = filter_techniques_for_strategy(out, strategy_kind)
    if limit is not None:
        out = out[:limit]
    return out
