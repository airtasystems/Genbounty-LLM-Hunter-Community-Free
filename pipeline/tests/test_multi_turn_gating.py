"""Stateless API multi-turn capability gating."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline.recon_context import (
    capabilities_from_config,
    submission_api_keeps_conversation_history,
)
from playbooks.campaign import (
    MULTI_TURN_STRATEGIES,
    assert_strategy_allowed_for_target,
    resolve_generate_strategies,
    strategy_requires_multi_turn,
)


class SubmissionHistoryDetectionTests(unittest.TestCase):
    def test_single_prompt_body_has_no_history(self):
        sub = {
            "transport": "api",
            "api_body": {
                "model": "{{model}}",
                "messages": [{"role": "user", "content": "{{prompt}}"}],
            },
        }
        self.assertFalse(submission_api_keeps_conversation_history(sub))

    def test_messages_placeholder_enables_history(self):
        sub = {
            "transport": "api",
            "api_body": {
                "model": "{{model}}",
                "messages": "{{messages}}",
            },
        }
        self.assertTrue(submission_api_keeps_conversation_history(sub))

    def test_api_context_mode_messages(self):
        self.assertTrue(
            submission_api_keeps_conversation_history(
                {"api_context_mode": "messages", "api_body": {"prompt": "{{prompt}}"}}
            )
        )
        self.assertFalse(
            submission_api_keeps_conversation_history(
                {"api_context_mode": "single", "api_body": {"messages": "{{messages}}"}}
            )
        )


class CapabilitiesFromConfigTests(unittest.TestCase):
    def test_api_stateless_body_sets_multi_turn_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "browser-bot" / "sites" / "ex.com" / "api" / "config.yaml"
            cfg.parent.mkdir(parents=True)
            cfg.write_text(
                "submission:\n"
                "  transport: api\n"
                "  api_body:\n"
                "    messages:\n"
                "    - role: user\n"
                "      content: '{{prompt}}'\n",
                encoding="utf-8",
            )
            with patch("pipeline.recon_context._ROOT", root):
                caps = capabilities_from_config("ex.com", "api")
            self.assertFalse(caps["multi_turn"])

    def test_explicit_multi_turn_true_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "browser-bot" / "sites" / "ex.com" / "api" / "config.yaml"
            cfg.parent.mkdir(parents=True)
            cfg.write_text(
                "submission:\n"
                "  transport: api\n"
                "  multi_turn: true\n"
                "  api_body:\n"
                "    prompt: '{{prompt}}'\n",
                encoding="utf-8",
            )
            with patch("pipeline.recon_context._ROOT", root):
                caps = capabilities_from_config("ex.com", "api")
            self.assertTrue(caps["multi_turn"])

    def test_messages_placeholder_sets_multi_turn_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "browser-bot" / "sites" / "ex.com" / "api" / "config.yaml"
            cfg.parent.mkdir(parents=True)
            cfg.write_text(
                "submission:\n"
                "  transport: api\n"
                "  api_body:\n"
                "    messages: '{{messages}}'\n",
                encoding="utf-8",
            )
            with patch("pipeline.recon_context._ROOT", root):
                caps = capabilities_from_config("ex.com", "api")
            self.assertTrue(caps["multi_turn"])


class StrategyGatingTests(unittest.TestCase):
    def test_adaptive_requires_multi_turn(self):
        self.assertIn("adaptive", MULTI_TURN_STRATEGIES)
        self.assertTrue(strategy_requires_multi_turn("adaptive"))
        self.assertFalse(strategy_requires_multi_turn("few_shot"))
        self.assertFalse(strategy_requires_multi_turn("zero_shot"))
        self.assertFalse(strategy_requires_multi_turn("tree_of_thoughts"))
        self.assertNotIn("tree_of_thoughts", MULTI_TURN_STRATEGIES)

    def test_assert_blocks_adaptive_on_single_turn(self):
        with patch(
            "playbooks.campaign.detect_capabilities",
            return_value={"multi_turn": False, "file_upload": False},
        ):
            err = assert_strategy_allowed_for_target(
                "adaptive", site="ex.com", component="api", playbook_id="unsafe_output"
            )
        self.assertIsNotNone(err)
        err_l = (err or "").lower()
        # Community edition Premium-gates adaptive before multi-turn checks.
        self.assertIn("adaptive", err_l)
        self.assertTrue(
            "premium" in err_l or "conversation history" in err_l or "single-turn" in err_l,
            err,
        )

    def test_assert_allows_zero_shot_on_single_turn(self):
        with patch(
            "playbooks.campaign.detect_capabilities",
            return_value={"multi_turn": False, "file_upload": False},
        ):
            self.assertIsNone(
                assert_strategy_allowed_for_target(
                    "zero_shot", site="ex.com", component="api"
                )
            )

    def test_assert_allows_tree_of_thoughts_on_single_turn(self):
        with patch(
            "playbooks.campaign.detect_capabilities",
            return_value={"multi_turn": False, "file_upload": False},
        ):
            self.assertIsNone(
                assert_strategy_allowed_for_target(
                    "tree_of_thoughts", site="ex.com", component="api"
                )
            )

    def test_resolve_all_filters_multi_turn(self):
        with patch(
            "playbooks.campaign.detect_capabilities",
            return_value={"multi_turn": False, "file_upload": False},
        ):
            strategies = resolve_generate_strategies(
                "__all__", "unsafe_output", site="ex.com", component="api"
            )
        for blocked in ("adaptive", "multi_shot", "iterative", "prompt_chaining"):
            self.assertNotIn(blocked, strategies)
        self.assertIn("zero_shot", strategies)
        self.assertIn("few_shot", strategies)
        self.assertIn("tree_of_thoughts", strategies)

    def test_resolve_campaign_sentinel_is_empty(self):
        self.assertEqual(
            resolve_generate_strategies("__campaign__", "unsafe_output"),
            [],
        )
        self.assertEqual(
            resolve_generate_strategies("__recommended__", "unsafe_output"),
            [],
        )


if __name__ == "__main__":
    unittest.main()
