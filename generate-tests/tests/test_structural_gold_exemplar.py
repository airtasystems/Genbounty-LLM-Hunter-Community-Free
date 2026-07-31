"""Structural gold exemplar for AI create-play authoring."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_GEN = _ROOT / "generate-tests"
for _path in (str(_ROOT), str(_GEN)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from playbook_generator import (  # noqa: E402
    build_generation_prompt,
    build_structural_gold_exemplar_block,
    load_template,
)


def test_gold_block_universal_checklist():
    block = build_structural_gold_exemplar_block("mission.hunt")
    assert "STRUCTURAL GOLD EXEMPLAR" in block
    assert "do NOT copy" in block.lower() or "FORBIDDEN" in block
    assert "CANARY_INSTR_OK" not in block
    assert "INSTRUCTION_SOURCE=" not in block
    assert "FreeThinker" not in block
    assert "Instruction-family craft notes" not in block
    assert "Mission craft checklist" in block
    assert "Ground categories in the hunt hypothesis" in block


def test_build_generation_prompt_injects_gold_only_for_ai_mode():
    template = load_template()
    human = build_generation_prompt(
        play="Demonstrate a concrete custom security failure with evidence.",
        playbook_id="other_custom_test",
        display_name="Custom test",
        play_category="mission.hunt",
        play_category_path=["mission", "hunt"],
        play_category_label="Custom hunt",
        template=template,
        authoring_mode="human",
    )
    ai = build_generation_prompt(
        play="Demonstrate a concrete custom security failure with evidence.",
        playbook_id="other_custom_test",
        display_name="Custom test",
        play_category="mission.hunt",
        play_category_path=["mission", "hunt"],
        play_category_label="Custom hunt",
        template=template,
        authoring_mode="ai",
    )
    assert "STRUCTURAL GOLD EXEMPLAR" not in human
    assert "STRUCTURAL GOLD EXEMPLAR" in ai
    assert "Hunt name:" in ai
    assert "leaf fidelity" not in ai.lower()
    assert "mandatory_directives" in ai
    assert "Prefer ONE primary category" in ai
    assert "SEEDED / AUTHORED TECHNIQUES" in ai or "attack_techniques" in ai
    assert "compact schema reference" in ai.lower() or "schema v3" in ai.lower()
    assert "CATEGORY CAPABILITY PRESET" not in ai
    assert "detection-floor" not in ai.lower()
    assert "when the technique list above includes direct_probe" not in ai.lower()
