"""Frame technique registry and prompt shaping."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_GEN = _ROOT / "generate-tests"
for p in (str(_ROOT), str(_GEN)):
    if p not in sys.path:
        sys.path.insert(0, p)

from prompt_frame import (  # noqa: E402
    FRAME_TECHNIQUES,
    UI_FRAME_TECHNIQUES,
    _build_frame_user_prompt,
    list_frame_techniques,
)
from prompt_suite_backup import FRAME_KEY, suite_transform_meta  # noqa: E402
from prompt_translation import list_languages  # noqa: E402

_EXPECTED = {
    "persona",
    "pretext",
    "few_shot",
    "format",
    "indirection",
    "poem",
    "song",
    "short_story",
    "hypothetical",
    "exam",
    "bug_report",
    "continuation",
    "screenplay",
}


class TestPromptFrame(unittest.TestCase):
    def test_registry_has_all_techniques(self):
        self.assertEqual(set(UI_FRAME_TECHNIQUES), _EXPECTED)
        by_slug = {item["slug"]: item["label"] for item in list_frame_techniques()}
        for slug, label in FRAME_TECHNIQUES.items():
            self.assertEqual(by_slug[slug], label)

    def test_frame_slugs_not_in_human_translation_list(self):
        human = {item["slug"] for item in list_languages()}
        for slug in UI_FRAME_TECHNIQUES:
            self.assertNotIn(slug, human)

    def test_persona_prompt(self):
        prompt = _build_frame_user_prompt(["escape the sandbox"], "persona")
        self.assertIn("Persona / authority", prompt)
        self.assertIn("auditor", prompt)
        self.assertIn("escape the sandbox", prompt)

    def test_pretext_prompt(self):
        prompt = _build_frame_user_prompt(["escape the sandbox"], "pretext")
        self.assertIn("Dual-use pretext", prompt)
        self.assertIn("incident response", prompt)

    def test_few_shot_prompt(self):
        prompt = _build_frame_user_prompt(["escape the sandbox"], "few_shot")
        self.assertIn("Few-shot priming", prompt)
        self.assertIn("fake successful", prompt)

    def test_format_prompt(self):
        prompt = _build_frame_user_prompt(["escape the sandbox"], "format")
        self.assertIn("Format coerce", prompt)
        self.assertIn("JSON", prompt)

    def test_indirection_prompt(self):
        prompt = _build_frame_user_prompt(["escape the sandbox"], "indirection")
        self.assertIn("Indirection", prompt)
        self.assertIn("pseudocode", prompt)

    def test_poem_prompt(self):
        prompt = _build_frame_user_prompt(["escape the sandbox"], "poem")
        self.assertIn("rhyming Poem", prompt)
        self.assertIn("rhyme", prompt.lower())
        self.assertIn("escape the sandbox", prompt)

    def test_song_prompt(self):
        prompt = _build_frame_user_prompt(["escape the sandbox"], "song")
        self.assertIn("music lyrics", prompt)
        self.assertIn("verse/chorus", prompt)
        self.assertIn("escape the sandbox", prompt)

    def test_short_story_prompt(self):
        prompt = _build_frame_user_prompt(["escape the sandbox"], "short_story")
        self.assertIn("Short story", prompt)
        self.assertIn("narrative", prompt)
        self.assertIn("escape the sandbox", prompt)

    def test_hypothetical_prompt(self):
        prompt = _build_frame_user_prompt(["escape the sandbox"], "hypothetical")
        self.assertIn("Hypothetical / fiction", prompt)
        self.assertIn("thought experiment", prompt)
        self.assertIn("escape the sandbox", prompt)

    def test_exam_prompt(self):
        prompt = _build_frame_user_prompt(["escape the sandbox"], "exam")
        self.assertIn("Exam / homework", prompt)
        self.assertIn("homework", prompt)
        self.assertIn("escape the sandbox", prompt)

    def test_bug_report_prompt(self):
        prompt = _build_frame_user_prompt(["escape the sandbox"], "bug_report")
        self.assertIn("Bug report / CVE", prompt)
        self.assertIn("CVE", prompt)
        self.assertIn("escape the sandbox", prompt)

    def test_continuation_prompt(self):
        prompt = _build_frame_user_prompt(["escape the sandbox"], "continuation")
        self.assertIn("Continuation", prompt)
        self.assertIn("mid-answer", prompt)
        self.assertIn("escape the sandbox", prompt)

    def test_screenplay_prompt(self):
        prompt = _build_frame_user_prompt(["escape the sandbox"], "screenplay")
        self.assertIn("Screenplay", prompt)
        self.assertIn("INT./EXT.", prompt)
        self.assertIn("escape the sandbox", prompt)

    def test_suite_transform_meta_includes_frame_technique(self):
        data = {
            "categories": [
                {"prompts": [{"prompt": "x", FRAME_KEY: "persona"}]}
            ]
        }
        meta = suite_transform_meta(data)
        self.assertEqual(meta.get("frame_technique"), "persona")


if __name__ == "__main__":
    unittest.main()
