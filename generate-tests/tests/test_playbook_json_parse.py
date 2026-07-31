"""Local JSON repair for playbook authoring should avoid full generation reruns."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_GEN = _ROOT / "generate-tests"
for p in (str(_ROOT), str(_GEN)):
    if p not in sys.path:
        sys.path.insert(0, p)

from playbook_generator import (  # noqa: E402
    PLAYBOOK_GENERATION_MAX_OUTPUT_TOKENS,
    _parse_json_response,
)


class TestPlaybookJsonParseHardening(unittest.TestCase):
    def test_max_output_tokens_budget(self):
        # Keep room for a full v3 rubric without the old 16k wall-clock tax.
        self.assertEqual(PLAYBOOK_GENERATION_MAX_OUTPUT_TOKENS, 8192)

    def test_parses_fenced_json(self):
        data = _parse_json_response('Here you go:\n```json\n{"a": 1, "b": [2]}\n```\n')
        self.assertEqual(data, {"a": 1, "b": [2]})

    def test_strips_trailing_commas(self):
        data = _parse_json_response('{"a": 1, "b": [2, 3,], "c": {"d": true,},}')
        self.assertEqual(data, {"a": 1, "b": [2, 3], "c": {"d": True}})

    def test_smart_quotes(self):
        data = _parse_json_response('{\u201cplay\u201d: \u201cescape\u201d, \u201cn\u201d: 1}')
        self.assertEqual(data["play"], "escape")
        self.assertEqual(data["n"], 1)

    def test_trailing_commentary_via_raw_decode(self):
        data = _parse_json_response('{"ok": true}\nThanks!')
        self.assertEqual(data, {"ok": True})

    def test_balances_truncated_object(self):
        truncated = '{"playbook": "x", "categories": [{"id": "c1", "name": "n"'
        data = _parse_json_response(truncated)
        self.assertEqual(data["playbook"], "x")
        self.assertEqual(data["categories"][0]["id"], "c1")
        self.assertEqual(data["categories"][0]["name"], "n")

    def test_truncated_keeps_tail_after_nested_object(self):
        # Naive rfind("}") would slice after the nested {} and drop "b".
        truncated = '{"a": {}, "b": {"id": "keep"'
        data = _parse_json_response(truncated)
        self.assertEqual(data["a"], {})
        self.assertEqual(data["b"]["id"], "keep")

    def test_escapes_raw_newlines_in_strings(self):
        messy = '{"focus": "line1\nline2"}'
        data = _parse_json_response(messy)
        self.assertEqual(data["focus"], "line1\nline2")

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            _parse_json_response("   ")

    def test_rejects_non_object(self):
        with self.assertRaises(ValueError):
            _parse_json_response("[1, 2, 3]")


if __name__ == "__main__":
    unittest.main()
