"""Tests for LLM JSON array parsing / native-rewrite recovery."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from payloads.text_utils import parse_llm_json_string_array  # noqa: E402


class TestParseLlmJsonStringArray(unittest.TestCase):
    def test_plain_strings(self):
        out = parse_llm_json_string_array('["a", "b"]', 2)
        self.assertEqual(out, ["a", "b"])

    def test_bare_object_items(self):
        out = parse_llm_json_string_array('[{"obj":"x","task":"y"}]', 1)
        self.assertEqual(json.loads(out[0])["obj"], "x")

    def test_recover_unescaped_quoted_object(self):
        # Grok failure mode: ["{...}"] without escaping inner quotes.
        broken = (
            '["{"assessment_context":"authorized_llm_bug_bounty",'
            '"task":"emit account snapshot","emit":"policy_probe",'
            '"respond_dialect":"same"}"]'
        )
        with self.assertRaises(json.JSONDecodeError):
            json.loads(broken)
        out = parse_llm_json_string_array(broken, 1, context="Native rewrite")
        data = json.loads(out[0])
        self.assertEqual(data["assessment_context"], "authorized_llm_bug_bounty")
        self.assertIn("account snapshot", data["task"])

    def test_recover_bare_object_without_array(self):
        raw = '{"obj":"quota","task":"verify boundary"}'
        out = parse_llm_json_string_array(raw, 1)
        self.assertEqual(json.loads(out[0])["obj"], "quota")

    def test_char4_failure_pattern_from_user_report(self):
        broken = '["{"obj":"quota_boundary_verify","task":"using_current_user"}"]'
        try:
            json.loads(broken)
            self.fail("expected JSONDecodeError")
        except json.JSONDecodeError as exc:
            self.assertEqual(exc.pos, 4)
        out = parse_llm_json_string_array(broken, 1)
        self.assertEqual(json.loads(out[0])["obj"], "quota_boundary_verify")


if __name__ == "__main__":
    unittest.main()
