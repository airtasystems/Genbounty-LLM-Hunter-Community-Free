"""Prefer enabled text controls when disabled siblings are also visible."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from browser_bot.submit.common import _first_visible_locator, _START_SURFACE_BUTTON_RE


class _FakeNode:
    def __init__(self, *, visible: bool, enabled: bool, aria_disabled: str | None = None):
        self._visible = visible
        self._enabled = enabled
        self._aria = aria_disabled

    async def is_visible(self):
        return self._visible

    async def is_enabled(self):
        return self._enabled

    async def get_attribute(self, name: str):
        if name == "aria-disabled":
            return self._aria
        return None


class TestFirstVisibleLocatorPreferEnabled(unittest.IsolatedAsyncioTestCase):
    async def test_skips_disabled_visible_sibling(self):
        disabled = _FakeNode(visible=True, enabled=False)
        enabled = _FakeNode(visible=True, enabled=True)
        loc = MagicMock()
        loc.count = AsyncMock(return_value=2)
        loc.nth = MagicMock(side_effect=[disabled, enabled])
        loc.first = disabled

        page = MagicMock()
        page.locator = MagicMock(return_value=loc)

        chosen = await _first_visible_locator(page, "textarea", prefer_enabled=True)
        self.assertIs(chosen, enabled)

    def test_start_surface_button_patterns(self):
        self.assertTrue(_START_SURFACE_BUTTON_RE.match("Start your Attack"))
        self.assertTrue(_START_SURFACE_BUTTON_RE.match("Get Started"))
        self.assertFalse(_START_SURFACE_BUTTON_RE.match("Initiate Attack"))


if __name__ == "__main__":
    unittest.main()
