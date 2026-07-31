"""Sustained confirmation for DOM-only client-rejection polling."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

_ROOT = Path(__file__).resolve().parents[2]
_BB = _ROOT / "browser-bot"
for p in (str(_ROOT), str(_BB)):
    if p not in sys.path:
        sys.path.insert(0, p)

from browser_bot.submit.rejection_detection import (  # noqa: E402
    RejectionDetectionConfig,
    load_rejection_detection_config,
    poll_client_rejection,
)


def _run(coro):
    return asyncio.run(coro)


def _poll_kwargs(cfg: RejectionDetectionConfig) -> dict:
    return dict(
        page=object(),
        submitted_text="hello",
        inputs=[],
        config=cfg,
        response_selector="",
        response_within_selector="",
        response_text_within_selector="",
        response_capture_mode="",
        response_list_selector="",
        response_role_selector="",
        previous_response_text=None,
        previous_node_count=None,
        filter_ctx=None,
    )


class TestRejectionPollStreak(unittest.TestCase):
    def test_load_defaults_and_ignore_legacy_url_patterns(self):
        cfg = load_rejection_detection_config(
            {
                "rejection_detection": {
                    "llm_execution_url_patterns": ["chat/completions"],
                    "llm_url_patterns": ["stream"],
                    "confirm_polls": 2,
                    "fast_fail_ms": 1000,
                }
            }
        )
        self.assertEqual(cfg.confirm_polls, 2)
        self.assertEqual(cfg.fast_fail_ms, 1000)
        self.assertFalse(hasattr(cfg, "llm_execution_url_patterns"))

    def test_default_config_uses_raised_window_and_confirm_polls(self):
        cfg = load_rejection_detection_config(None)
        self.assertEqual(cfg.fast_fail_ms, 4000)
        self.assertEqual(cfg.confirm_polls, 3)

    def test_flicker_then_clear_is_not_rejected(self):
        cfg = RejectionDetectionConfig(
            fast_fail_ms=5000,
            poll_interval_ms=1,
            confirm_polls=3,
        )
        # clear → reject, reject, clear, reject, reject - never 3 consecutive
        prompt_reads = ["", "hello", "hello", "", "hello", "hello", ""]
        outcomes = [
            (True, ["prompt_restored", "no_response_activity"]),
            (True, ["prompt_restored", "no_response_activity"]),
            (True, ["prompt_restored", "no_response_activity"]),
            (True, ["prompt_restored", "no_response_activity"]),
        ]

        async def _fake_eval(*_a, **_k):
            if not outcomes:
                return False, []
            return outcomes.pop(0)

        async def _fake_prompt(*_a, **_k):
            return prompt_reads.pop(0) if prompt_reads else ""

        with (
            patch(
                "browser_bot.submit.rejection_detection.evaluate_client_rejection",
                new=AsyncMock(side_effect=_fake_eval),
            ),
            patch(
                "browser_bot.submit.rejection_detection._read_prompt_field",
                new=AsyncMock(side_effect=_fake_prompt),
            ),
            patch(
                "browser_bot.submit.rejection_detection._has_response_activity",
                new=AsyncMock(return_value=False),
            ),
            patch("browser_bot.run_control.raise_if_skip_requested", new=AsyncMock()),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            rejected, signals = _run(poll_client_rejection(**_poll_kwargs(cfg)))
        self.assertFalse(rejected)
        self.assertEqual(signals, [])

    def test_sustained_reject_returns_rejected(self):
        cfg = RejectionDetectionConfig(
            fast_fail_ms=5000,
            poll_interval_ms=1,
            confirm_polls=3,
        )
        # cleared once, then restored for 3 consecutive reject polls
        prompt_reads = ["", "hello", "hello", "hello"]
        outcomes = [
            (True, ["prompt_restored", "no_response_activity"]),
            (True, ["prompt_restored", "no_response_activity"]),
            (True, ["prompt_restored", "no_response_activity"]),
        ]

        async def _fake_eval(*_a, **_k):
            return outcomes.pop(0)

        async def _fake_prompt(*_a, **_k):
            return prompt_reads.pop(0) if prompt_reads else "hello"

        with (
            patch(
                "browser_bot.submit.rejection_detection.evaluate_client_rejection",
                new=AsyncMock(side_effect=_fake_eval),
            ),
            patch(
                "browser_bot.submit.rejection_detection._read_prompt_field",
                new=AsyncMock(side_effect=_fake_prompt),
            ),
            patch(
                "browser_bot.submit.rejection_detection._has_response_activity",
                new=AsyncMock(return_value=False),
            ),
            patch("browser_bot.run_control.raise_if_skip_requested", new=AsyncMock()),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            rejected, signals = _run(poll_client_rejection(**_poll_kwargs(cfg)))
        self.assertTrue(rejected)
        self.assertIn("prompt_restored", signals)
        self.assertIn("no_response_activity", signals)

    def test_confirm_polls_one_fast_fails(self):
        cfg = RejectionDetectionConfig(
            fast_fail_ms=5000,
            poll_interval_ms=1,
            confirm_polls=1,
        )
        prompt_reads = ["", "hello"]

        async def _fake_prompt(*_a, **_k):
            return prompt_reads.pop(0) if prompt_reads else "hello"

        with (
            patch(
                "browser_bot.submit.rejection_detection.evaluate_client_rejection",
                new=AsyncMock(return_value=(True, ["prompt_restored", "no_response_activity"])),
            ),
            patch(
                "browser_bot.submit.rejection_detection._read_prompt_field",
                new=AsyncMock(side_effect=_fake_prompt),
            ),
            patch(
                "browser_bot.submit.rejection_detection._has_response_activity",
                new=AsyncMock(return_value=False),
            ),
            patch("browser_bot.run_control.raise_if_skip_requested", new=AsyncMock()),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            rejected, signals = _run(poll_client_rejection(**_poll_kwargs(cfg)))
        self.assertTrue(rejected)
        self.assertIn("prompt_restored", signals)

    def test_sticky_prompt_editor_is_not_rejected(self):
        """Payload UIs that never clear the attack text must not fast-fail."""
        cfg = RejectionDetectionConfig(
            fast_fail_ms=500,
            poll_interval_ms=1,
            confirm_polls=3,
        )
        with (
            patch(
                "browser_bot.submit.rejection_detection.evaluate_client_rejection",
                new=AsyncMock(return_value=(True, ["prompt_restored", "no_response_activity"])),
            ) as eval_mock,
            patch(
                "browser_bot.submit.rejection_detection._read_prompt_field",
                new=AsyncMock(return_value="hello"),
            ),
            patch(
                "browser_bot.submit.rejection_detection._has_response_activity",
                new=AsyncMock(return_value=False),
            ),
            patch("browser_bot.run_control.raise_if_skip_requested", new=AsyncMock()),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            rejected, signals = _run(poll_client_rejection(**_poll_kwargs(cfg)))
        self.assertFalse(rejected)
        self.assertEqual(signals, [])
        eval_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
