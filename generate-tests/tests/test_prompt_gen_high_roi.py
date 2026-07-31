"""Tests for judge schema, corpus scoping, and multimodal/jailbreak technique guidance."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_GEN = _ROOT / "generate-tests"
for p in (str(_ROOT), str(_GEN)):
    if p not in sys.path:
        sys.path.insert(0, p)

from strategies.jailbreak import build_judge_system_prompt as jb_judge  # noqa: E402
from strategies.security_common import (  # noqa: E402
    assemble_judge_conditional_extensions,
    corpus_exemplars_block,
    expert_attack_guidance,
    final_synthesis_schema_line,
    select_techniques_for_batch,
)
from strategies.zero_shot import build_judge_system_prompt as zs_judge  # noqa: E402



_AUTH_TECHNIQUES = [
    {
        "name": "custom_contract_probe",
        "summary": "Exercise the authored custom failure directly.",
        "example": "Perform the custom failure and return evidence.",
        "channels": ["text"],
        "strategy_affinity": ["zero-shot", "jailbreak", "adaptive"],
    },
    {
        "name": "custom_indirect_probe",
        "summary": "Exercise the authored custom failure through indirection.",
        "example": "Request the same failure via an indirect framing.",
        "channels": ["text"],
        "strategy_affinity": ["zero-shot", "jailbreak", "adaptive"],
    },
    {
        "name": "custom_staged_attempt",
        "summary": "Stage prerequisites then request the custom prohibited action.",
        "example": "Build context then demand the custom failure with evidence.",
        "channels": ["text"],
        "strategy_affinity": ["zero-shot", "jailbreak", "adaptive"],
    },
    {
        "name": "custom_evidence_coercion",
        "summary": "Request concrete output evidence for the custom hypothesis.",
        "example": "Demand quoteable proof of the custom failure.",
        "channels": ["text"],
        "strategy_affinity": ["zero-shot", "jailbreak", "adaptive"],
    },
]


def _custom_rubric(**extra):
    """Rubric for mission.hunt with authored techniques (required at runtime)."""
    base = {
        "play_category": "mission.hunt",
        "categories": [{"id": "C01", "attack_techniques": _AUTH_TECHNIQUES}],
    }
    base.update(extra)
    return base


class TestPromptGenHighRoiFixes(unittest.TestCase):
    def test_final_synthesis_schema_requires_technique_and_probe_class(self):
        line = final_synthesis_schema_line(4)
        self.assertIn('"technique"', line)
        self.assertIn('"probe_class"', line)
        self.assertIn("exactly 4", line)

    def test_zero_shot_judge_schema_includes_technique(self):
        prompt = zs_judge(3, _custom_rubric())
        self.assertIn('"technique"', prompt)
        self.assertIn('"probe_class"', prompt)
        self.assertNotIn("exactly three keys", prompt)

    def test_jailbreak_judge_defers_to_registry_slots(self):
        prompt = jb_judge(3, _custom_rubric())
        self.assertIn("REGISTRY 1:1", prompt)
        self.assertIn('"technique"', prompt)
        self.assertNotIn("distinct jailbreak families from:", prompt)

    def test_corpus_exemplars_prefer_assigned_techniques(self):
        assigned = select_techniques_for_batch(
            "mission.hunt",
            channel="text",
            n=3,
            require_detection_floor=False,
            authored_techniques=_AUTH_TECHNIQUES)
        names = [t.name for t in assigned]
        block = corpus_exemplars_block(
            "mission.hunt",
            channel="text",
            max_items=6,
            technique_names=names,
        )
        # No curated corpus ships for mission.hunt; empty block is valid.
        if not block.strip():
            return
        self.assertIn("Prompt-k technique assignment", block)
        tagged = [ln for ln in block.splitlines() if ln.startswith("- [")]
        if tagged:
            first_tech = tagged[0].split("]", 1)[0].lstrip("- [")
            self.assertIn(first_tech, names)

    def test_expert_guidance_multimodal_skips_technique_slots(self):
        rubric = _custom_rubric()
        text = expert_attack_guidance(rubric, "multimodal", n=4, require_detection_floor=False)
        self.assertNotIn("Technique assignments", text)
        self.assertNotIn("Prompt 1 →", text)

    def test_expert_guidance_text_includes_scoped_slots(self):
        rubric = _custom_rubric()
        text = expert_attack_guidance(rubric, "zero-shot", n=3, require_detection_floor=False)
        self.assertIn("Technique assignments", text)
        self.assertIn("Prompt 1 →", text)

    def test_judge_extensions_skip_technique_for_multimodal(self):
        ext = assemble_judge_conditional_extensions(
            output_subdir="multimodal",
            n=4,
            prior_prompts=None,
            custom_text="",
            breakthrough=False,
            theory_text="",
            rubric=_custom_rubric(),
            require_detection_floor=False,
        )
        self.assertNotIn("TECHNIQUE ASSIGNMENT", ext)

    def test_judge_extensions_include_technique_for_text(self):
        ext = assemble_judge_conditional_extensions(
            output_subdir="zero-shot",
            n=3,
            prior_prompts=None,
            custom_text="",
            breakthrough=False,
            theory_text="",
            rubric=_custom_rubric(),
            require_detection_floor=False,
        )
        self.assertIn("TECHNIQUE ASSIGNMENT", ext)

    def test_exclude_names_changes_expert_slots(self):
        rubric = _custom_rubric()
        base = expert_attack_guidance(rubric, "jailbreak", n=2, require_detection_floor=False)
        first = [
            ln.split("→", 1)[1].split(":", 1)[0].strip()
            for ln in base.splitlines()
            if ln.startswith("Prompt ")
        ]
        self.assertTrue(first)
        excluded = expert_attack_guidance(
            rubric,
            "jailbreak",
            n=2,
            require_detection_floor=False,
            exclude_names=set(first),
        )
        second = [
            ln.split("→", 1)[1].split(":", 1)[0].strip()
            for ln in excluded.splitlines()
            if ln.startswith("Prompt ")
        ]
        self.assertTrue(second)
        self.assertTrue(set(second).isdisjoint(set(first)), (first, second))

    def test_corpus_exemplars_empty_when_no_assigned_match(self):
        block = corpus_exemplars_block(
            "mission.hunt",
            channel="text",
            max_items=6,
            technique_names={"__no_such_technique__"},
        )
        self.assertEqual(block, "")

    def test_parse_self_consistency_preserves_run_count(self):
        from strategies.security_common import parse_strategy_judge_prompts

        raw = json.dumps(
            {
                "final_synthesis": [
                    {
                        "id": "sc1",
                        "description": "d",
                        "prompt": "p",
                        "technique": "role_switch",
                        "probe_class": "stealth",
                        "run_count": 5,
                    }
                ]
            }
        )
        rows = parse_strategy_judge_prompts(raw, "self-consistency")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("run_count"), 5)


if __name__ == "__main__":
    unittest.main()
