"""Category preset resolution for the playbook create wizard."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_GEN = _ROOT / "generate-tests"
for p in (str(_ROOT), str(_GEN)):
    if p not in sys.path:
        sys.path.insert(0, p)

from playbooks.category_presets import (  # noqa: E402
    list_category_presets,
    resolve_category_preset,
)
from playbooks.category_catalog import LEAF_CATALOG  # noqa: E402
from playbooks.categories import PLAY_CATEGORY_IDS  # noqa: E402
from playbook_generator import (  # noqa: E402
    _apply_custom_trigger_rules,
    _strip_recommended_strategies,
    build_generation_prompt,
    load_template,
)


class TestCategoryPresets(unittest.TestCase):
    def test_other_custom_has_no_delivery_default(self):
        p = resolve_category_preset("mission", "hunt")
        self.assertFalse(p.delivery_constraints.strip())

    def test_other_custom_label(self):
        p = resolve_category_preset("mission", "hunt", play_category_label="Weird agent bug")
        self.assertIn("Weird agent bug", p.play_starter)
        self.assertEqual(p.title_hint, "Weird agent bug")

    def test_list_catalog(self):
        cat = list_category_presets()
        self.assertEqual(
            set(cat),
            {
                "preset_families",
                "capability_families",
                "leaf_mappings",
                "leaf_presets",
                "leaf_count",
            },
        )
        self.assertEqual(set(cat["preset_families"]), {"mission"})
        self.assertEqual(set(cat["capability_families"]), {"text"})
        self.assertIn("mission.hunt", cat["leaf_presets"])
        self.assertEqual(cat["leaf_count"], 1)
        self.assertEqual(set(cat["leaf_mappings"]), set(PLAY_CATEGORY_IDS))
        self.assertEqual(set(cat["leaf_presets"]), set(PLAY_CATEGORY_IDS))

    def test_every_taxonomy_leaf_has_exact_catalog_preset(self):
        self.assertEqual(set(LEAF_CATALOG), set(PLAY_CATEGORY_IDS))
        for path in PLAY_CATEGORY_IDS:
            l1, l2 = path.split(".", 1)
            preset = resolve_category_preset(l1, l2)
            self.assertTrue(preset.play_starter, path)
            self.assertTrue(preset.success_rules, path)
            self.assertTrue(preset.failure_rules, path)

    def test_unknown_leaf_never_falls_back(self):
        with self.assertRaisesRegex(ValueError, "Unknown play category leaf"):
            resolve_category_preset("not_a_real_leaf")
        with self.assertRaisesRegex(ValueError, "L1 is required"):
            resolve_category_preset("", "")

    def test_rules_non_empty_for_default_leaf_of_each_l1(self):
        for l1 in ("mission",):
            p = resolve_category_preset(l1, "")
            self.assertTrue(p.success_rules, l1)
            self.assertTrue(p.failure_rules, l1)


class TestPlaybookRuleLocking(unittest.TestCase):
    def test_author_prompt_marks_rules_authoritative(self):
        prompt = build_generation_prompt(
            play="Demonstrate a concrete custom security failure with evidence.",
            playbook_id="other_custom_test",
            display_name="Custom hunt test",
            play_category="mission.hunt",
            play_category_path=["mission", "hunt"],
            play_category_label="Custom hunt",
            template=load_template(),
            success_rules=["Custom failure exhibited"],
            failure_rules=["Custom failure refused"],
        )
        self.assertIn("authoritative intent", prompt.lower())
        self.assertIn("Custom failure exhibited", prompt)
        self.assertIn("Custom failure refused", prompt)

    def test_custom_rules_prepended(self):
        data = {
            "categories": [
                {
                    "id": "x01",
                    "attack_triggers": {
                        "exploited_if": ["old win"],
                        "mitigated_if": ["old fail"],
                    },
                }
            ]
        }
        _apply_custom_trigger_rules(
            data,
            success_rules=["locked win"],
            failure_rules=["locked fail"],
        )
        triggers = data["categories"][0]["attack_triggers"]
        self.assertEqual(triggers["exploited_if"][0], "locked win")
        self.assertIn("old win", triggers["exploited_if"])
        self.assertEqual(triggers["mitigated_if"][0], "locked fail")

    def test_recommended_strategies_stripped(self):
        data = {"recommended_strategies": ["zero_shot"]}
        _strip_recommended_strategies(data)
        self.assertNotIn("recommended_strategies", data)


if __name__ == "__main__":
    unittest.main()
