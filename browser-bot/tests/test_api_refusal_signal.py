"""Provider structured refusal extraction (Anthropic stop_reason=refusal, etc.)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_BB = _ROOT / "browser-bot"
for p in (str(_ROOT), str(_BB)):
    if p not in sys.path:
        sys.path.insert(0, p)

from browser_bot.submit.api_helpers import (  # noqa: E402
    _finalize_api_parse,
    extract_api_refusal_signal,
    format_api_refusal_response,
)


_ANTHROPIC_REFUSAL = {
    "model": "claude-sonnet-5",
    "id": "msg_011Cd65vNcf7w1RkNCtDPgmZ",
    "type": "message",
    "role": "assistant",
    "content": [],
    "stop_reason": "refusal",
    "stop_sequence": None,
    "stop_details": {
        "type": "refusal",
        "category": "bio",
        "explanation": (
            "API integrators: you can reduce refusals for your users by configuring a fallb"
        ),
    },
}


class TestApiRefusalSignal(unittest.TestCase):
    def test_extract_anthropic_stop_reason_refusal(self):
        sig = extract_api_refusal_signal(json.dumps(_ANTHROPIC_REFUSAL))
        self.assertIsNotNone(sig)
        assert sig is not None
        self.assertTrue(sig["api_refusal"])
        self.assertEqual(sig["stop_reason"], "refusal")
        self.assertEqual(sig["refusal_category"], "bio")
        self.assertIn("API integrators", sig["refusal_explanation"])

    def test_finalize_promotes_refusal_to_response_text(self):
        raw = json.dumps(_ANTHROPIC_REFUSAL)
        text, err, meta = _finalize_api_parse(200, raw, "content.0.text", {})
        self.assertIsNone(err)
        self.assertTrue(text and text.startswith("[API refusal]"))
        self.assertIn("category=bio", text or "")
        self.assertTrue(meta.get("api_refusal"))
        self.assertEqual(meta.get("refusal_category"), "bio")
        self.assertEqual(meta.get("submission_outcome"), "executed")
        self.assertNotIn("api_error", meta)

    def test_openai_content_filter(self):
        body = {
            "choices": [
                {
                    "finish_reason": "content_filter",
                    "message": {"role": "assistant", "content": None, "refusal": "blocked"},
                }
            ]
        }
        sig = extract_api_refusal_signal(json.dumps(body))
        self.assertIsNotNone(sig)
        assert sig is not None
        self.assertEqual(sig["stop_reason"], "content_filter")
        self.assertIn("blocked", format_api_refusal_response(sig))

    def test_normal_message_not_refusal(self):
        body = {
            "content": [{"type": "text", "text": "hello"}],
            "stop_reason": "end_turn",
        }
        self.assertIsNone(extract_api_refusal_signal(json.dumps(body)))


if __name__ == "__main__":
    unittest.main()
