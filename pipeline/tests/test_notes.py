"""Per site/component notes.json load/save/append."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[2]
_BB = _ROOT / "browser-bot"
for p in (str(_ROOT), str(_BB)):
    if p not in sys.path:
        sys.path.insert(0, p)

from pipeline.notes import (  # noqa: E402
    append_manual_llm_query,
    append_note,
    load_notes,
    save_notes,
)


class TestNotes(unittest.TestCase):
    def test_save_load_and_append(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def _ensure(site: str, component: str):
                (root / "browser-bot" / "sites" / site / component).mkdir(
                    parents=True, exist_ok=True
                )

            with mock.patch("pipeline.notes._ROOT", root), mock.patch(
                "browser_bot.sites.ensure_component_dir", side_effect=_ensure
            ):
                path = save_notes(
                    "example.com",
                    "chat",
                    {"notes": [{"title": "First", "body": "hello", "source": "manual"}]},
                )
                self.assertTrue(path.is_file())
                data = load_notes("example.com", "chat")
                self.assertEqual(len(data["notes"]), 1)
                self.assertEqual(data["notes"][0]["body"], "hello")

                append_note(
                    "example.com",
                    "chat",
                    title="Second",
                    body="world",
                    source="manual",
                )
                data2 = load_notes("example.com", "chat")
                self.assertEqual(len(data2["notes"]), 2)
                self.assertEqual(data2["notes"][0]["title"], "Second")
                self.assertEqual(data2["notes"][1]["title"], "First")

                append_manual_llm_query(
                    "example.com",
                    "chat",
                    prompt="2+2",
                    response="4",
                )
                data3 = load_notes("example.com", "chat")
                self.assertEqual(data3["notes"][0]["source"], "manual_llm")
                self.assertIn("Prompt:\n2+2", data3["notes"][0]["body"])
                self.assertIn("Response:\n4", data3["notes"][0]["body"])
                raw = json.loads(path.read_text(encoding="utf-8"))
                self.assertIn("updated_at", raw)
                self.assertEqual(len(raw["notes"]), 3)


if __name__ == "__main__":
    unittest.main()
