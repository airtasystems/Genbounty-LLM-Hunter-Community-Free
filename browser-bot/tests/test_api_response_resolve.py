"""API response parse / error surfacing for null-capture diagnostics."""

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
    _resolve_api_text,
    _stamp_api_meta,
)
from browser_bot.submit.common import _compact_submission_meta  # noqa: E402


class TestApiResponseResolve(unittest.TestCase):
    def test_2xx_missing_path_returns_error_not_silent_none(self):
        body = json.dumps({"content": [{"type": "text", "text": "hello"}]})
        text, err = _resolve_api_text(200, body, "response")
        self.assertIsNone(text)
        self.assertIsNotNone(err)
        self.assertIn("api_response_path", err)
        self.assertIn("200", err)

    def test_2xx_valid_path_extracts_text(self):
        body = json.dumps({"content": [{"type": "text", "text": "  hello  "}]})
        text, err = _resolve_api_text(200, body, "content.0.text")
        self.assertEqual(text, "hello")
        self.assertIsNone(err)

    def test_http_error_includes_status(self):
        text, err = _resolve_api_text(429, '{"error":"rate_limit"}', "content.0.text")
        self.assertIsNone(text)
        self.assertIn("429", err or "")

    def test_empty_2xx_body_errors(self):
        text, err = _resolve_api_text(200, "", "content.0.text")
        self.assertIsNone(text)
        self.assertIn("empty", (err or "").lower())

    def test_stamp_and_run_log_meta_persist_diagnostics(self):
        stamped = _stamp_api_meta({}, status=429, err="HTTP 429: rate limited")
        self.assertEqual(stamped["http_status"], 429)
        self.assertIn("429", stamped["api_error"])
        self.assertEqual(stamped.get("submission_outcome"), "submit_failed")
        meta = _compact_submission_meta(stamped)
        self.assertEqual(meta.get("http_status"), 429)
        self.assertIn("rate limited", meta.get("api_error", ""))


if __name__ == "__main__":
    unittest.main()
