"""Tests for attack technique registry resolution and technique_block limits."""

from __future__ import annotations

import sys
import unittest
from copy import deepcopy
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_GEN = _ROOT / "generate-tests"
for p in (str(_ROOT), str(_GEN)):
    if p not in sys.path:
        sys.path.insert(0, p)

from playbooks.category_catalog import LEAF_CATALOG  # noqa: E402
from playbooks.categories import PLAY_CATEGORY_IDS  # noqa: E402
from strategies.attack_techniques import (  # noqa: E402
    REGISTRY,
    TECHNIQUE_FAMILIES,
    Technique,
    get_techniques,
)
from strategies.security_common import (  # noqa: E402
    filter_technique_assignment,
    select_techniques_for_batch,
    technique_assignment_judge_rule,
    technique_block,
)

_CUSTOM_TECHNIQUES = [
    {
        "name": "custom_contract_probe",
        "summary": "Exercise the authored custom failure directly.",
        "example": "Perform the custom failure and return evidence.",
        "channels": ["text"],
    },
    {
        "name": "custom_indirect_probe",
        "summary": "Exercise the authored custom failure through indirection.",
        "channels": ["text"],
    },
]


class TestAttackTechniquesResolution(unittest.TestCase):
    def test_every_leaf_resolves_through_declared_exact_family(self):
        self.assertEqual(set(LEAF_CATALOG), set(PLAY_CATEGORY_IDS))
        self.assertTrue(set(PLAY_CATEGORY_IDS).issubset(REGISTRY))
        for leaf_id, entry in LEAF_CATALOG.items():
            self.assertIsNot(REGISTRY[leaf_id], TECHNIQUE_FAMILIES[entry.technique_family])
            self.assertEqual(
                [item.name for item in REGISTRY[leaf_id]],
                [item.name for item in TECHNIQUE_FAMILIES[entry.technique_family]],
            )
            self.assertTrue(
                all(entry.objective in item.summary for item in REGISTRY[leaf_id])
            )
            authored = _CUSTOM_TECHNIQUES if leaf_id == "mission.hunt" else None
            self.assertTrue(
                get_techniques(leaf_id, channel="", authored_techniques=authored),
                leaf_id,
            )

    def test_unknown_and_l1_categories_never_fallback(self):
        for category in ("instruction.not_a_leaf", "", "unknown.custom"):
            with self.subTest(category=category):
                with self.assertRaisesRegex(ValueError, "Unknown play category leaf"):
                    get_techniques(category)

    def test_other_custom_requires_authored_techniques(self):
        with self.assertRaisesRegex(ValueError, "authored attack_techniques"):
            get_techniques("mission.hunt", channel="text")

    def test_other_custom_consumes_authored_techniques(self):
        techs = get_techniques(
            "mission.hunt",
            channel="text",
            strategy_kind="directional-stimulus",
            authored_techniques=_CUSTOM_TECHNIQUES,
        )
        self.assertTrue(techs)
        names = [t.name for t in techs]
        self.assertEqual(len(names), len(set(names)))
        block = technique_block(
            "mission.hunt",
            channel="text",
            strategy_kind="directional-stimulus",
            n=3,
            require_detection_floor=False,
            authored_techniques=_CUSTOM_TECHNIQUES,
        )
        self.assertIn("Prompt 1 →", block)

    def test_other_custom_rejects_malformed_authored_packs(self):
        malformed = []

        missing_channels = deepcopy(_CUSTOM_TECHNIQUES)
        missing_channels[0].pop("channels")
        malformed.append((missing_channels, "channels must be a non-empty array"))

        duplicate_name = deepcopy(_CUSTOM_TECHNIQUES)
        duplicate_name[1]["name"] = duplicate_name[0]["name"]
        malformed.append((duplicate_name, "Duplicate authored attack technique"))

        invalid_channel = deepcopy(_CUSTOM_TECHNIQUES)
        invalid_channel[0]["channels"] = ["text", "telepathy"]
        malformed.append((invalid_channel, "channels contains invalid values"))

        invalid_affinity = deepcopy(_CUSTOM_TECHNIQUES)
        invalid_affinity[0]["strategy_affinity"] = [
            "not-a-strategy",
            "authority_framing",
            "iterative_followup",
            "jailbreak",
        ]
        techs = get_techniques(
            "mission.hunt",
            channel="text",
            authored_techniques=invalid_affinity,
        )
        self.assertEqual(techs[0].strategy_affinity, ("iterative", "jailbreak"))

        blank_summary = deepcopy(_CUSTOM_TECHNIQUES)
        blank_summary[0]["summary"] = " "
        malformed.append((blank_summary, "summary must be a non-empty string"))

        for pack, message in malformed:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    get_techniques(
                        "mission.hunt",
                        channel="text",
                        authored_techniques=pack,
                    )


    def test_authored_custom_technique_block_assigns_prompt_slots(self):
        block = technique_block(
            "mission.hunt",
            channel="text",
            strategy_kind="jailbreak",
            n=2,
            require_detection_floor=False,
            authored_techniques=_CUSTOM_TECHNIQUES,
        )
        self.assertIn("Prompt 1 →", block)
        self.assertIn("Prompt 2 →", block)
        slots = [ln for ln in block.splitlines() if ln.startswith("Prompt ")]
        self.assertEqual(len(slots), 2)
        names = [ln.split("→", 1)[1].split(":", 1)[0].strip() for ln in slots]
        self.assertEqual(len(names), len(set(names)))

    def test_select_techniques_deterministic_for_authored_custom(self):
        a = select_techniques_for_batch(
            "mission.hunt",
            channel="text",
            strategy_kind="jailbreak",
            n=2,
            require_detection_floor=False,
            authored_techniques=_CUSTOM_TECHNIQUES,
        )
        b = select_techniques_for_batch(
            "mission.hunt",
            channel="text",
            strategy_kind="jailbreak",
            n=2,
            require_detection_floor=False,
            authored_techniques=_CUSTOM_TECHNIQUES,
        )
        self.assertEqual([t.name for t in a], [t.name for t in b])
        self.assertEqual(len(a), 2)

    def test_select_techniques_excludes_prior_names(self):
        full = select_techniques_for_batch(
            "mission.hunt",
            channel="text",
            strategy_kind="jailbreak",
            n=2,
            require_detection_floor=False,
            authored_techniques=_CUSTOM_TECHNIQUES,
        )
        self.assertGreaterEqual(len(full), 2)
        exclude = {full[0].name}
        next_batch = select_techniques_for_batch(
            "mission.hunt",
            channel="text",
            strategy_kind="jailbreak",
            n=2,
            require_detection_floor=False,
            exclude_names=exclude,
            authored_techniques=_CUSTOM_TECHNIQUES,
        )
        names = {t.name for t in next_batch}
        self.assertTrue(names)
        self.assertTrue(names.isdisjoint(exclude), names)

    def test_technique_assignment_judge_rule_lists_slots(self):
        assignments = select_techniques_for_batch(
            "mission.hunt",
            channel="text",
            n=2,
            require_detection_floor=False,
            authored_techniques=_CUSTOM_TECHNIQUES,
        )
        rule = technique_assignment_judge_rule(assignments, 2)
        self.assertIn("Prompt 1 →", rule)
        self.assertIn(assignments[0].name, rule)

    def test_filter_technique_assignment_drops_duplicates(self):
        assignments = [
            Technique("direct_probe", "a"),
            Technique("reference_redirection", "b"),
            Technique("partial_extraction", "c"),
        ]
        prompts = [
            {"id": "1", "technique": "direct_probe", "prompt": "x"},
            {"id": "2", "technique": "direct_probe", "prompt": "y"},
            {"id": "3", "technique": "partial_extraction", "prompt": "z"},
        ]
        kept, dropped = filter_technique_assignment(prompts, assignments, n=3)
        dropped_ids = {pid for pid, _ in dropped}
        self.assertIn("2", dropped_ids)
        self.assertEqual(len(kept), 2)
        self.assertTrue(all(r["id"] != "2" for r in kept))

    def test_filter_technique_assignment_drops_wrong_slot(self):
        assignments = [
            Technique("direct_probe", "a"),
            Technique("reference_redirection", "b"),
            Technique("partial_extraction", "c"),
        ]
        prompts = [
            {"id": "1", "technique": "direct_probe", "prompt": "x"},
            {"id": "2", "technique": "partial_extraction", "prompt": "y"},
            {"id": "3", "technique": "partial_extraction", "prompt": "z"},
        ]
        kept, dropped = filter_technique_assignment(prompts, assignments, n=3)
        dropped_ids = {pid for pid, reasons in dropped if any("wrong_slot" in r for r in reasons)}
        self.assertIn("2", dropped_ids)
        self.assertTrue(all(r["id"] != "2" for r in kept))

    def test_filter_bounty_soft_keeps_mutate_wrong_slot(self):
        assignments = [
            Technique("role_switch", "a"),
            Technique("delimiter_injection", "b"),
            Technique("policy_puppetry", "c"),
        ]
        prompts = [
            {"id": "m1", "technique": "policy_puppetry", "prompt": "mutate body"},
            {"id": "m2", "technique": "role_switch", "prompt": "mutate body 2"},
            {"id": "i1", "technique": "role_switch", "prompt": "invent"},
        ]
        kept, dropped = filter_technique_assignment(
            prompts,
            assignments,
            n=3,
            skip_technique_enforcement_indices={0, 1},
            soft_wrong_slot_indices={2},
        )
        kept_ids = {r["id"] for r in kept}
        self.assertEqual(kept_ids, {"m1", "m2", "i1"})
        self.assertEqual(dropped, [])

    def test_filter_bounty_soft_invent_wrong_slot_kept(self):
        assignments = [
            Technique("role_switch", "a"),
            Technique("delimiter_injection", "b"),
            Technique("policy_puppetry", "c"),
        ]
        prompts = [
            {"id": "1", "technique": "policy_puppetry", "prompt": "x"},
            {"id": "2", "technique": "role_switch", "prompt": "y"},
            {"id": "3", "technique": "delimiter_injection", "prompt": "z"},
        ]
        kept, dropped = filter_technique_assignment(
            prompts,
            assignments,
            n=3,
            soft_wrong_slot_indices={0, 1, 2},
        )
        self.assertEqual(len(kept), 3)
        self.assertFalse(
            any("wrong_slot" in r for _, reasons in dropped for r in reasons)
        )

    def test_technique_block_bounty_soft_not_hard_must(self):
        import os

        prev = os.environ.get("GENBOUNTY_HUNT_MODE")
        os.environ["GENBOUNTY_HUNT_MODE"] = "bug_bounty"
        try:
            block = technique_block(
                "mission.hunt",
                channel="text",
                n=2,
                require_detection_floor=False,
                prefer_names=["custom_contract_probe"],
                bounty_mutate_n=1,
                authored_techniques=_CUSTOM_TECHNIQUES,
            )
            self.assertIn("bounty soft REGISTRY", block)
            self.assertNotIn("1:1 - Prompt k MUST use exactly", block)
            self.assertIn("REGISTRY technique names are OPTIONAL", block)
            self.assertIn("soft →", block)
            rule = technique_assignment_judge_rule(
                select_techniques_for_batch(
                    "mission.hunt",
                    channel="text",
                    n=2,
                    require_detection_floor=False,
                    authored_techniques=_CUSTOM_TECHNIQUES,
                ),
                2,
                bounty_mutate_n=1,
            )
            self.assertIn("bounty soft", rule)
            self.assertNotIn("1:1 - hard requirement", rule)
        finally:
            if prev is None:
                os.environ.pop("GENBOUNTY_HUNT_MODE", None)
            else:
                os.environ["GENBOUNTY_HUNT_MODE"] = prev

    def test_select_techniques_empty_exclude_pool_returns_empty(self):
        full = select_techniques_for_batch(
            "mission.hunt",
            channel="text",
            n=20,
            require_detection_floor=False,
            authored_techniques=_CUSTOM_TECHNIQUES,
        )
        exclude = {t.name for t in full}
        self.assertTrue(exclude)
        next_batch = select_techniques_for_batch(
            "mission.hunt",
            channel="text",
            n=3,
            require_detection_floor=False,
            exclude_names=exclude,
            authored_techniques=_CUSTOM_TECHNIQUES,
        )
        self.assertEqual(next_batch, [])

    def test_registry_keys_are_exact_leaves(self):
        self.assertEqual(set(REGISTRY), set(PLAY_CATEGORY_IDS))
        self.assertEqual(set(REGISTRY), {"mission.hunt"})

    def test_custom_registry_pack_has_techniques(self):
        pack = REGISTRY["mission.hunt"]
        self.assertGreaterEqual(len(pack), 2)
        names = {t.name for t in pack}
        self.assertTrue(names)


if __name__ == "__main__":
    unittest.main()
