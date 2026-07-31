"""Curated corpus alignment with attack_techniques REGISTRY."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[2]
_GEN = _ROOT / "generate-tests"
for p in (str(_ROOT), str(_GEN)):
    if p not in sys.path:
        sys.path.insert(0, p)

from strategies.attack_techniques import CURATED_LEAF_PACKS, REGISTRY  # noqa: E402
from strategies.corpus_loader import corpus_dir, invalidate_cache, load_corpus  # noqa: E402


class TestCorpusAlignment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        invalidate_cache()

    def test_registry_is_other_custom_only(self):
        self.assertEqual(set(REGISTRY), {"mission.hunt"})
        self.assertEqual(set(CURATED_LEAF_PACKS), {"mission.hunt"})

    def test_load_corpus_unknown_leaf_empty(self):
        self.assertEqual(load_corpus("data.system_prompt_leak", channel="text"), [])
        self.assertEqual(load_corpus("execution", channel="text"), [])

    def test_obsolete_l1_corpus_files_are_not_required(self):
        for l1 in (
            "execution",
            "data",
            "agents",
            "context",
            "output",
            "session",
            "supply_chain",
            "availability",
            "trust",
            "governance",
        ):
            self.assertFalse(
                (corpus_dir() / f"{l1}.json").exists(),
                f"obsolete broad corpus file: {l1}.json",
            )
            self.assertEqual(load_corpus(l1, channel="text"), [])

    def test_prompt_count_uses_pipeline_settings(self):
        from strategies.generation_mode import prompt_count_for_route

        with mock.patch(
            "pipeline.pipeline_settings.open_loop_prompts", return_value=4
        ), mock.patch(
            "pipeline.pipeline_settings.closed_loop_prompts", return_value=4
        ):
            self.assertEqual(prompt_count_for_route("open_loop"), 4)
            self.assertEqual(prompt_count_for_route("advance"), 4)


if __name__ == "__main__":
    unittest.main()
