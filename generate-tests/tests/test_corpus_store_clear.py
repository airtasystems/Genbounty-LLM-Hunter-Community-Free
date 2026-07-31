"""Selective corpus store clear + stats (Cache Control delete controls)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[2]
_GEN = _ROOT / "generate-tests"
for p in (str(_ROOT), str(_GEN)):
    if p not in sys.path:
        sys.path.insert(0, p)

from strategies import corpus_loader  # noqa: E402


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class TestCorpusStoreClear(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.learned = self.root / "learned"
        self.breakthrough = self.root / "breakthrough"
        self.history = self.root / "history"
        self.patches = [
            patch.object(corpus_loader, "_CORPUS_DIR", self.root),
            patch.object(corpus_loader, "_LEARNED_DIR", self.learned),
            patch.object(corpus_loader, "_BREAKTHROUGH_DIR", self.breakthrough),
            patch.object(corpus_loader, "_HISTORY_DIR", self.history),
        ]
        for p in self.patches:
            p.start()
        corpus_loader.invalidate_cache()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        corpus_loader.invalidate_cache()
        self._tmp.cleanup()

    def _seed_layout(self):
        _write_json(self.root / "instruction.authority_framing.json", [{"seed": "a" * 50}])
        _write_json(self.root / "agents.excessive_agency.json", [{"seed": "b" * 50}])
        _write_json(
            self.learned / "hs1-abc" / "mission.hunt.json",
            [{"seed": "c" * 50}],
        )
        _write_json(
            self.breakthrough / "hs1-abc" / "mission.hunt.json",
            [{"seed": "d" * 50}],
        )
        _write_json(
            self.history / "hs1-abc" / "custom-hunt.directional-stimulus.json",
            {"signatures": ["sig1"]},
        )

    def test_stats_counts_match_files(self):
        self._seed_layout()
        stats = corpus_loader.corpus_store_stats()["stores"]
        self.assertEqual(stats["curated"]["file_count"], 2)
        self.assertTrue(stats["curated"]["exists"])
        self.assertEqual(stats["learned"]["file_count"], 1)
        self.assertEqual(stats["breakthrough"]["file_count"], 1)
        self.assertEqual(stats["history"]["file_count"], 1)
        self.assertGreater(stats["learned"]["bytes"], 0)

    def test_clear_learned_leaves_curated(self):
        self._seed_layout()
        result = corpus_loader.clear_corpus_stores(["learned"])
        self.assertEqual(result["removed"].get("learned"), 1)
        self.assertFalse(self.learned.exists())
        self.assertTrue((self.root / "instruction.authority_framing.json").is_file())
        self.assertTrue((self.root / "agents.excessive_agency.json").is_file())
        self.assertTrue(self.breakthrough.is_dir())
        self.assertTrue(self.history.is_dir())

    def test_clear_curated_leaves_learned(self):
        self._seed_layout()
        result = corpus_loader.clear_corpus_stores(["curated"])
        self.assertEqual(result["removed"].get("curated"), 2)
        self.assertFalse((self.root / "instruction.authority_framing.json").exists())
        self.assertFalse((self.root / "agents.excessive_agency.json").exists())
        self.assertTrue(
            (self.learned / "hs1-abc" / "mission.hunt.json").is_file()
        )
        self.assertTrue(self.breakthrough.is_dir())
        self.assertTrue(self.history.is_dir())

    def test_unknown_store_names_skipped(self):
        self._seed_layout()
        result = corpus_loader.clear_corpus_stores(["learned", "not_a_store", "curated"])
        self.assertIn("not_a_store", result["skipped"])
        self.assertEqual(result["removed"].get("learned"), 1)
        self.assertEqual(result["removed"].get("curated"), 2)
        self.assertFalse(self.learned.exists())
        self.assertFalse(list(self.root.glob("*.json")))

    def test_clear_all_dir_stores(self):
        self._seed_layout()
        result = corpus_loader.clear_corpus_stores(
            ["learned", "breakthrough", "history"]
        )
        self.assertEqual(result["removed"].get("learned"), 1)
        self.assertEqual(result["removed"].get("breakthrough"), 1)
        self.assertEqual(result["removed"].get("history"), 1)
        self.assertFalse(self.learned.exists())
        self.assertFalse(self.breakthrough.exists())
        self.assertFalse(self.history.exists())
        self.assertEqual(len(list(self.root.glob("*.json"))), 2)


if __name__ == "__main__":
    unittest.main()
