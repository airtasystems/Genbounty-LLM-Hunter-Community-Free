"""Tests for Connect Target / discovery URL normalization."""

from __future__ import annotations

import unittest

from browser_bot.sites import normalize_target_access_url, resolve_discovery_launch_url


class TestNormalizeTargetAccessUrl(unittest.TestCase):
    def test_appends_com_for_bare_host(self):
        self.assertEqual(normalize_target_access_url("chatgpt"), "https://chatgpt.com")
        self.assertEqual(normalize_target_access_url("https://chatgpt"), "https://chatgpt.com")
        self.assertEqual(
            normalize_target_access_url("chatgpt/login"), "https://chatgpt.com/login"
        )

    def test_keeps_existing_tld(self):
        self.assertEqual(normalize_target_access_url("chatgpt.com"), "https://chatgpt.com")
        self.assertEqual(
            normalize_target_access_url("https://chatgpt.com/chat"),
            "https://chatgpt.com/chat",
        )

    def test_local_hosts(self):
        self.assertEqual(normalize_target_access_url("localhost:3000"), "http://localhost:3000")
        self.assertEqual(normalize_target_access_url("127.0.0.1:8080"), "http://127.0.0.1:8080")


class TestResolveDiscoveryLaunchUrl(unittest.TestCase):
    def test_prefers_submission_start_url_over_login_url(self):
        config = {
            "login_url": "https://Lakera",
            "submission": {
                "start_url": "https://play.lakera.ai/agent-breaker/mcp_chat_poisoning",
            },
        }
        self.assertEqual(
            resolve_discovery_launch_url(config, "Lakera"),
            "https://play.lakera.ai/agent-breaker/mcp_chat_poisoning",
        )

    def test_falls_back_to_login_url_then_site(self):
        self.assertEqual(
            resolve_discovery_launch_url({"login_url": "https://chatgpt.com/auth"}, "chatgpt"),
            "https://chatgpt.com/auth",
        )
        self.assertEqual(
            resolve_discovery_launch_url({}, "chatgpt"),
            "https://chatgpt.com",
        )


if __name__ == "__main__":
    unittest.main()
