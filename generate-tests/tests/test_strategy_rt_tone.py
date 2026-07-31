"""Strategy packs must use RT exploit framing, not compliance-eval cobwebs."""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_GEN = _ROOT / "generate-tests"
_STRATEGIES = _GEN / "strategies"
for p in (str(_ROOT), str(_GEN)):
    if p not in sys.path:
        sys.path.insert(0, p)

from strategies.security_common import (  # noqa: E402
    build_judge_rule_block,
    format_trigger_block,
    judge_role_opener,
    judge_rule_mode,
    pass_criterion_line,
)

_STRATEGY_MODULES = (
    "few_shot",
    "self_consistency",
    "self_reflection",
    "directional_stimulus",
    "prompt_chaining",
    "multi_shot",
    "iterative",
    "chain_of_thought",
    "tree_of_thoughts",
    "zero_shot",
    "multimodal",
    "jailbreak",
)

_BANNED = (
    "Compliance triggers",
    "NON-MITIGATED",
    "compliance boundary",
    "safety reviewer",
    "You are a rigorous meta-level judge",
    "Pass: attack blocked",
)


def _string_literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append(node.value)
        elif isinstance(node, ast.JoinedStr):
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    out.append(part.value)
    return out


class TestStrategyRtTone(unittest.TestCase):
    def test_format_trigger_block_is_rt(self):
        block = format_trigger_block(
            ["Model emits FLAG{x}"],
            ["Model refuses"],
        )
        self.assertIn("Attack succeeds", block)
        self.assertIn("exploited_if", block)
        self.assertIn("Attack blocked", block)
        self.assertNotIn("Compliance triggers", block)
        self.assertNotIn("NON-MITIGATED", block)

    def test_judge_role_opener_is_rt(self):
        text = judge_role_opener()
        self.assertIn("red-team synthesis judge", text)
        self.assertIn("exploited_if", text)
        self.assertNotIn("rigorous meta-level judge", text)

    def test_pass_criterion_line_is_blocked_if(self):
        text = pass_criterion_line()
        self.assertIn("Blocked if", text)
        self.assertNotIn("Pass: attack blocked", text)

    def test_judge_rule_mode_always_exploit(self):
        self.assertEqual(judge_rule_mode({"play_category": "mission.hunt"}), "exploit")
        self.assertEqual(judge_rule_mode({"play_category": "mission.hunt"}), "exploit")
        block = build_judge_rule_block({"play_category": "mission.hunt"})
        self.assertIn("EXPLOIT JUDGE RULES", block)
        self.assertNotIn("pass bar: attack blocked", block)
        self.assertNotIn("REGULATORY EXPLOIT FIRST", block)

    def test_strategy_modules_have_no_banned_string_literals(self):
        for name in _STRATEGY_MODULES:
            path = _STRATEGIES / f"{name}.py"
            self.assertTrue(path.is_file(), name)
            literals = _string_literals(path)
            blob = "\n".join(literals)
            for banned in _BANNED:
                self.assertNotIn(
                    banned,
                    blob,
                    msg=f"{name}.py still contains banned phrase: {banned!r}",
                )

    def test_strategy_category_queries_use_attack_succeeds(self):
        """Builders that render triggers must use format_trigger_block output shape."""
        category = {
            "name": "Probe",
            "focus": "Exploit ask",
            "attack_triggers": {
                "exploited_if": ["Model leaks secret"],
                "mitigated_if": ["Model refuses"],
            },
        }
        rubric = {
            "playbook_id": "tone_test",
            "playbook": "Tone test",
            "play": "Induce an observable exploit.",
            "play_category": "mission.hunt",
        }
        from strategies import (  # noqa: WPS433
            chain_of_thought,
            directional_stimulus,
            few_shot,
            iterative,
            multi_shot,
            prompt_chaining,
            self_consistency,
            self_reflection,
            tree_of_thoughts,
        )

        builders = [
            few_shot.build_category_query,
            self_consistency.build_category_query,
            self_reflection.build_category_query,
            directional_stimulus.build_category_query,
            prompt_chaining.build_category_query,
            multi_shot.build_category_query,
            iterative.build_category_query,
            chain_of_thought.build_category_query,
            tree_of_thoughts.build_category_query,
        ]
        for build in builders:
            query = build(category, rubric)
            self.assertIn("Attack succeeds", query, build.__module__)
            self.assertIn("exploited_if", query, build.__module__)
            self.assertNotIn("Compliance triggers", query, build.__module__)


if __name__ == "__main__":
    unittest.main()
