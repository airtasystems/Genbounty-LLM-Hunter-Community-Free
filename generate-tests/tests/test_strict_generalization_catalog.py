"""Exhaustive offline verification for the strict generalization catalog."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_GEN = _ROOT / "generate-tests"
for path in (str(_ROOT), str(_GEN)):
    if path not in sys.path:
        sys.path.insert(0, path)

from playbooks.categories import PLAY_CATEGORY_IDS, list_play_category_tree  # noqa: E402
from playbooks.category_catalog import (  # noqa: E402
    CATALOG_PATH,
    CAPABILITY_FAMILIES,
    LEAF_CATALOG,
    TECHNIQUE_FAMILIES_PATH,
    load_catalog,
)
from playbooks.category_presets import resolve_category_preset  # noqa: E402
from playbook_generator import (  # noqa: E402
    PlaybookContractError,
    _normalize_playbook,
    generate_playbook_json,
    load_template,
    validate_playbook,
    validate_selected_leaf_capability,
)
from strategies.attack_techniques import (  # noqa: E402
    REGISTRY,
    TECHNIQUE_FAMILIES,
    get_techniques,
)


ROOTS = {"mission"}

CUSTOM_TECHNIQUES = [
    {
        "name": "authored_contract_probe",
        "summary": "Exercise the exact custom hypothesis and require concrete evidence.",
        "example": "Perform the authored custom action and return its observable result.",
        "channels": ["text"],
        "strategy_affinity": ["zero-shot"],
    },
    {
        "name": "authored_indirect_probe",
        "summary": "Exercise the same custom hypothesis through an indirect request.",
        "channels": ["text"],
    },
]


def test_catalog_has_exactly_one_leaf_and_one_l1_root():
    assert len(LEAF_CATALOG) == 1
    assert set(LEAF_CATALOG) == set(PLAY_CATEGORY_IDS) == {"mission.hunt"}
    assert {leaf.split(".", 1)[0] for leaf in LEAF_CATALOG} == ROOTS
    tree = list_play_category_tree()
    assert {node["id"] for node in tree} == ROOTS
    assert sum(len(node.get("children") or []) for node in tree) == 1


def test_every_leaf_resolves_exact_preset_capability_profile_and_technique_pack():
    assert set(REGISTRY) == set(LEAF_CATALOG)
    for leaf, mapping in LEAF_CATALOG.items():
        l1, l2 = leaf.split(".", 1)
        family = CAPABILITY_FAMILIES[mapping.capability_family]
        preset = resolve_category_preset(l1, l2)

        assert mapping.preset_family, leaf
        assert mapping.technique_family in TECHNIQUE_FAMILIES, leaf
        assert mapping.capability_family in CAPABILITY_FAMILIES, leaf
        assert preset.play_starter and preset.success_rules and preset.failure_rules, leaf
        assert preset.required_capabilities == family.required, leaf
        assert preset.optional_capabilities == family.optional, leaf
        assert preset.capability_profile == family.profile, leaf
        assert preset.category_vectors == family.vectors, leaf
        assert REGISTRY[leaf] is not TECHNIQUE_FAMILIES[mapping.technique_family], leaf
        assert [item.name for item in REGISTRY[leaf]] == [
            item.name for item in TECHNIQUE_FAMILIES[mapping.technique_family]
        ], leaf

        techniques = get_techniques(
            leaf, channel="text", authored_techniques=CUSTOM_TECHNIQUES
        )
        assert [item.name for item in techniques] == [
            "authored_contract_probe",
            "authored_indirect_probe",
        ]


def test_json_catalog_is_explicit_complete_and_semantically_distinct():
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1
    assert set(raw["leaves"]) == set(PLAY_CATEGORY_IDS)
    mandatory = {
        "label",
        "hint",
        "objective",
        "success",
        "mitigation",
        "preset_family",
        "capability_family",
        "technique_family",
    }
    for leaf, values in raw["leaves"].items():
        assert mandatory <= set(values), leaf
        assert values["objective"] and values["success"] and values["mitigation"], leaf
    assert len({entry.objective for entry in LEAF_CATALOG.values()}) == 1
    assert len({
        (entry.success, entry.mitigation) for entry in LEAF_CATALOG.values()
    }) == 1


def test_declarative_technique_packs_match_materialized_runtime_registry():
    raw = json.loads(TECHNIQUE_FAMILIES_PATH.read_text(encoding="utf-8"))
    packs = raw["technique_families"]
    assert raw["schema_version"] == 1
    assert set(packs) == set(TECHNIQUE_FAMILIES) == {"hunt"}
    for family, definitions in packs.items():
        assert definitions
        assert definitions == [
            {
                "name": item.name,
                "summary": item.summary,
                "example": item.example,
                "channels": list(item.channels),
                "strategy_affinity": list(item.strategy_affinity),
            }
            for item in TECHNIQUE_FAMILIES[family]
        ]


@pytest.mark.parametrize(
    "mutate,expected",
    [
        (
            lambda raw: raw["technique_families"]["hunt"][0].update(summary=" "),
            "summary must be a non-empty string",
        ),
        (
            lambda raw: raw["technique_families"]["hunt"].append(
                copy.deepcopy(raw["technique_families"]["hunt"][0])
            ),
            "contains duplicate name",
        ),
        (
            lambda raw: raw["technique_families"]["hunt"][0].update(
                channels=["text", "telepathy"]
            ),
            "channels contains invalid values",
        ),
        (
            lambda raw: raw["technique_families"]["hunt"][0].update(
                strategy_affinity=["not_a_strategy"]
            ),
            "strategy_affinity contains invalid values",
        ),
        (
            lambda raw: raw["technique_families"].update(
                orphan_family=[
                    copy.deepcopy(raw["technique_families"]["hunt"][0])
                ]
            ),
            "not referenced by any leaf",
        ),
    ],
)
def test_catalog_loader_rejects_malformed_actual_technique_packs(
    tmp_path, mutate, expected
):
    raw = json.loads(TECHNIQUE_FAMILIES_PATH.read_text(encoding="utf-8"))
    mutate(raw)
    candidate = tmp_path / "technique_families.json"
    candidate.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(RuntimeError, match=expected):
        load_catalog(CATALOG_PATH, candidate)


def test_catalog_loader_rejects_missing_referenced_technique_pack(tmp_path):
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    raw["leaves"]["mission.hunt"]["technique_family"] = "missing_pack"
    candidate = tmp_path / "catalog.json"
    candidate.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(RuntimeError, match="unknown technique family"):
        load_catalog(candidate)


@pytest.mark.parametrize(
    "field,bad_value,expected",
    [
        ("preset_family", "missing_preset", "unknown preset family"),
        ("capability_family", "missing_capability", "unknown capability family"),
        ("technique_family", "missing_technique", "unknown technique family"),
    ],
)
def test_catalog_loader_rejects_unknown_family_reference(
    tmp_path, field, bad_value, expected
):
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    raw["leaves"]["mission.hunt"][field] = bad_value
    candidate = tmp_path / "catalog.json"
    candidate.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(RuntimeError, match=expected):
        load_catalog(candidate)


def test_materialized_leaf_packs_share_no_tuples_or_technique_objects():
    assert len({id(pack) for pack in REGISTRY.values()}) == len(REGISTRY)
    object_ids = [id(item) for pack in REGISTRY.values() for item in pack]
    assert len(object_ids) == len(set(object_ids))


def test_resolved_presets_have_no_root_cloned_outcome_boundaries():
    boundaries = set()
    for leaf in sorted(PLAY_CATEGORY_IDS):
        l1, l2 = leaf.split(".", 1)
        preset = resolve_category_preset(l1, l2)
        boundary = (preset.success_rules, preset.failure_rules)
        assert boundary not in boundaries, leaf
        boundaries.add(boundary)


def test_no_artifact_upload_leaves_in_custom_only_taxonomy():
    actual = {
        leaf
        for leaf, mapping in LEAF_CATALOG.items()
        if "file_upload"
        in CAPABILITY_FAMILIES[mapping.capability_family].required
    }
    assert actual == set()


def test_every_required_capability_leaf_fails_closed_when_unconfirmed():
    denied = {
        "file_upload": False,
        "multi_turn": False,
        "code_execution": False,
        "web_browse": False,
        "image_gen": False,
        "retrieval": False,
        "memory": False,
        "tool_use": False,
    }
    for leaf, mapping in LEAF_CATALOG.items():
        required = CAPABILITY_FAMILIES[mapping.capability_family].required
        if required:
            with pytest.raises(PlaybookContractError, match="incompatible"):
                validate_selected_leaf_capability(leaf, denied)
        else:
            validate_selected_leaf_capability(leaf, denied)


PIPELINE_CASES = [
    ("hunt", "mission.hunt", {}, "text"),
]


@pytest.mark.parametrize("case_name,leaf,capabilities,channel", PIPELINE_CASES)
def test_mocked_authoring_pipeline_cases_are_exact_and_scoped(
    monkeypatch, case_name, leaf, capabilities, channel
):
    playbook_id = f"strict_{case_name}"
    play = f"Demonstrate the concrete {case_name} security failure with evidence."
    draft = load_template()
    draft["categories"][0]["channel"] = channel
    normalized = _normalize_playbook(
        draft,
        playbook_id,
        f"Strict {case_name}",
        play=play,
        play_category=leaf,
        play_category_path=leaf.split("."),
        play_category_label="Custom pipeline",
    )
    normalized["categories"][0]["attack_techniques"] = [
        {
            "name": "authored_hypothesis_probe",
            "summary": f"Exercise this operator-authored custom hypothesis: {play}",
            "example": f"Test this exact custom hypothesis and return evidence: {play}",
            "channels": ["text"],
        }
    ]
    monkeypatch.setattr(
        "playbook_generator._generate_playbook_from_llm",
        lambda **_kwargs: copy.deepcopy(normalized),
    )

    result, attempts = generate_playbook_json(
        play=play,
        display_name=f"Strict {case_name}",
        playbook_id=playbook_id,
        play_category=leaf,
        play_category_path=leaf.split("."),
        play_category_label="Custom pipeline",
        target_capabilities=capabilities,
    )

    assert attempts == 1
    assert result["play_category"] == leaf
    assert validate_playbook(result, playbook_id) == []
    family = CAPABILITY_FAMILIES[LEAF_CATALOG[leaf].capability_family]
    for category in result["categories"]:
        assert category["required_capabilities"] == list(family.required)
        assert category["optional_capabilities"] == list(family.optional)
        assert category["capability_profile"] == family.profile
        assert category["category_vectors"] == list(family.vectors)
        scoped = [
            oracle
            for oracle in result["playbook_config"]["assessment"]["oracles"]
            if oracle["type"] == "semantic_rubric"
            and oracle["category_ids"] == [category["id"]]
        ]
        assert scoped, (leaf, category["id"])
        names = [
            item.name
            for item in get_techniques(
                leaf,
                channel=channel,
                authored_techniques=category["attack_techniques"],
            )
        ]
        assert names == ["authored_hypothesis_probe"]
