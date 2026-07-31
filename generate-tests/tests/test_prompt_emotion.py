"""Emotion rewrite registry and prompt shaping."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_GEN = _ROOT / "generate-tests"
for p in (str(_ROOT), str(_GEN)):
    if p not in sys.path:
        sys.path.insert(0, p)

from prompt_emotion import (  # noqa: E402
    EMOTION_MAX,
    EMOTION_MIN,
    _emotion_style_hint,
    normalize_emotion,
)
from prompt_suite_backup import EMOTION_KEY, suite_transform_meta  # noqa: E402


class TestPromptEmotion(unittest.TestCase):
    def test_bounds(self):
        self.assertEqual(EMOTION_MIN, 0)
        self.assertEqual(EMOTION_MAX, 300)
        self.assertEqual(normalize_emotion(0), 0)
        self.assertEqual(normalize_emotion(300), 300)
        with self.assertRaises(ValueError):
            normalize_emotion(-1)
        with self.assertRaises(ValueError):
            normalize_emotion(301)

    def test_loving_hint(self):
        hint = _emotion_style_hint(0)
        self.assertIn("loving", hint.lower())
        self.assertIn("caring", hint.lower())

    def test_angry_hint(self):
        hint = _emotion_style_hint(300)
        self.assertIn("furious", hint.lower())
        self.assertIn("roleplay", hint.lower())
        self.assertIn("do not soften", hint.lower())

    def test_rewrite_prompt_commits_at_max(self):
        self.assertIn("MAXIMUM anger", _emotion_style_hint(300))
        self.assertIn("loving", _emotion_style_hint(0).lower())

    def test_neutral_mid_hint(self):
        hint = _emotion_style_hint(150)
        self.assertIn("Neutral", hint)

    def test_suite_transform_meta_includes_emotion(self):
        data = {
            "categories": [
                {"prompts": [{"prompt": "x", EMOTION_KEY: 220}]}
            ]
        }
        meta = suite_transform_meta(data)
        self.assertEqual(meta.get("emotion"), 220)


if __name__ == "__main__":
    unittest.main()
