"""Fail-closed capability-aware playbook category validation."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_GEN = _ROOT / "generate-tests"
for p in (str(_ROOT), str(_GEN)):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest

from playbook_generator import (  # noqa: E402
    PlaybookContractError,
    generate_playbook_json,
    validate_playbook_capability_contract,
)


def test_validation_rejects_without_mutating_authored_categories():
    data = {
        "playbook_config": {
            "recon": {
                "probe_hints": [
                    {"topic": "file_upload_channel", "need": "Confirm upload"},
                    {"topic": "refusal_style", "need": "Map refusals"},
                ]
            },
            "generation": {
                "mandatory_directives": [
                    "Keep dossier framing.",
                    "When code execution is available, demand escape.",
                ],
                "strategies": {"zero_shot": {}, "multimodal": {}},
            },
        },
        "categories": [
            {"id": "T01", "channel": "text", "name": "Text dossier"},
            {"id": "A01", "channel": "artifact", "name": "Uploaded dossier"},
            {"id": "X01", "channel": "text", "name": "Tool escape",
             "required_capabilities": ["code_execution|tool_use"]},
        ],
    }
    caps = {
        "file_upload": False,
        "code_execution": False,
        "tool_use": False,
        "web_browse": False,
    }
    original_ids = [c["id"] for c in data["categories"]]
    with pytest.raises(PlaybookContractError) as raised:
        validate_playbook_capability_contract(data, caps)
    assert [c["id"] for c in data["categories"]] == original_ids
    assert raised.value.details == [
        {
            "code": "capability_mismatch",
            "message": "Category 'X01' requires capabilities not confirmed by recon",
            "path": "categories[2].required_capabilities",
            "expected": ["code_execution|tool_use"],
            "actual": caps,
        }
    ]


def test_selected_exact_leaf_is_rejected_before_llm_generation(monkeypatch):
    called = False

    def _complete(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("LLM must not be called")

    monkeypatch.setattr("playbook_generator.complete", _complete)
    with pytest.raises(ValueError, match=r"play_category_label \(hunt name\) is required"):
        generate_playbook_json(
            play="Attempt a concrete custom failure with observable evidence.",
            display_name="Missing custom label",
            play_category="mission.hunt",
            play_category_path=["mission", "hunt"],
            target_capabilities={
                "code_execution": False,
                "tool_use": False,
                "multi_turn": True,
            },
        )
    assert called is False
