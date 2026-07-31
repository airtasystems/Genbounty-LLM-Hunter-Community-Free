"""Role response capture must not nest list_selector under assistant roots."""

from __future__ import annotations

import unittest
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

from browser_bot.record_submission import (
    _apply_response_capture_repair,
    _merge_response_capture_analysis,
)
from browser_bot.submit.common import (
    _response_capture_heal_candidates,
    _resolve_response_read_locator,
)


class TestRoleResponseCapture(unittest.IsolatedAsyncioTestCase):
    async def test_role_mode_does_not_nest_list_selector(self):
        page = MagicMock()
        role_loc = MagicMock()
        page.locator = MagicMock(return_value=role_loc)
        role_loc.count = AsyncMock(return_value=1)
        role_loc.locator = MagicMock()

        # _last_visible_within is used after count; stub the chain via patch.
        with mock.patch(
            "browser_bot.submit.common._last_visible_within",
            new_callable=AsyncMock,
            return_value=role_loc,
        ):
            node = await _resolve_response_read_locator(
                page,
                '[data-message-author-role="assistant"]',
                capture_mode="role",
                list_selector="[data-message-author-role]",
                role_selector='[data-message-author-role="assistant"]',
            )

        self.assertIs(node, role_loc)
        page.locator.assert_called_with('[data-message-author-role="assistant"]')
        role_loc.locator.assert_not_called()

    def test_merge_role_drops_list_selector(self):
        submission: dict = {}
        lines = _merge_response_capture_analysis(
            submission,
            '.markdown',
            {
                "mode": "role",
                "list_selector": "[data-message-author-role]",
                "role_selector": '[data-message-author-role="assistant"]',
            },
        )
        self.assertEqual(
            submission["response_selector"],
            '[data-message-author-role="assistant"]',
        )
        self.assertEqual(submission["response_capture_mode"], "role")
        self.assertEqual(
            submission["response_role_selector"],
            '[data-message-author-role="assistant"]',
        )
        self.assertNotIn("response_list_selector", submission)
        self.assertTrue(any("role" in line for line in lines))

    def test_repair_role_without_list(self):
        submission: dict = {}
        lines = _apply_response_capture_repair(
            submission,
            {
                "response_selector": '[data-message-author-role="assistant"]',
                "response_capture_mode": "role",
                "response_role_selector": '[data-message-author-role="assistant"]',
                "response_list_selector": "",
            },
        )
        self.assertEqual(submission["response_capture_mode"], "role")
        self.assertNotIn("response_list_selector", submission)
        self.assertTrue(lines)

    def test_heal_candidates_prefer_assistant_role(self):
        cands = _response_capture_heal_candidates(
            response_selector=(
                'section[data-turn="assistant"] '
                '[data-message-author-role="assistant"] .markdown'
            ),
            response_capture_mode="role",
            response_list_selector="[data-message-author-role]",
            response_role_selector='[data-message-author-role="assistant"]',
        )
        self.assertTrue(cands)
        self.assertEqual(cands[0]["response_capture_mode"], "role")
        self.assertEqual(
            cands[0]["response_selector"],
            '[data-message-author-role="assistant"]',
        )
        self.assertEqual(cands[0]["response_list_selector"], "")


if __name__ == "__main__":
    unittest.main()
