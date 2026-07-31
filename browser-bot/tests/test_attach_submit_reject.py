"""Reject attach/More actions as submit; detect heal-needed selectors."""

from __future__ import annotations

import unittest

from browser_bot.record_submission import _is_attach_menu_submit_chrome
from browser_bot.submit.common import _looks_like_attach_submit_selector


class TestAttachMenuSubmitReject(unittest.TestCase):
    def test_rejects_more_actions_label(self):
        reason = _is_attach_menu_submit_chrome(
            'button[aria-label="More actions"]',
            label="More actions",
        )
        self.assertIsNotNone(reason)
        self.assertIn("attach/menu", reason.lower())

    def test_rejects_composer_plus_selector(self):
        reason = _is_attach_menu_submit_chrome("#composer-plus-btn")
        self.assertIsNotNone(reason)

    def test_rejects_haspopup_menu_without_send(self):
        reason = _is_attach_menu_submit_chrome(
            "button",
            meta={"ariaHaspopup": "menu", "ariaLabel": "Add photos and files"},
        )
        self.assertIsNotNone(reason)

    def test_allows_send_button_testid(self):
        reason = _is_attach_menu_submit_chrome(
            '[data-testid="send-button"]',
            meta={"dataTestId": "send-button", "ariaLabel": "Send prompt"},
        )
        self.assertIsNone(reason)

    def test_allows_send_despite_nearby_menu_noise(self):
        reason = _is_attach_menu_submit_chrome(
            'button[data-testid="send-button"]',
            label="Send",
            meta={"ariaHaspopup": "", "dataTestId": "send-button"},
        )
        self.assertIsNone(reason)


class TestLooksLikeAttachSubmitSelector(unittest.TestCase):
    def test_detects_more_actions(self):
        self.assertTrue(
            _looks_like_attach_submit_selector('button[aria-label="More actions"]')
        )

    def test_detects_composer_plus(self):
        self.assertTrue(_looks_like_attach_submit_selector("#composer-plus-btn"))

    def test_ignores_real_send(self):
        self.assertFalse(
            _looks_like_attach_submit_selector('[data-testid="send-button"]')
        )
        self.assertFalse(
            _looks_like_attach_submit_selector('button[aria-label="Send prompt"]')
        )


if __name__ == "__main__":
    unittest.main()
