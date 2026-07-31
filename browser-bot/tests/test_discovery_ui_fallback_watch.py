"""Regression: run_with_ui_fallback_watch must return the coroutine result."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from browser_bot.discovery_ui_bridge import run_with_ui_fallback_watch


class TestRunWithUiFallbackWatch(unittest.IsolatedAsyncioTestCase):
    async def test_returns_result_when_task_finishes_between_polls(self):
        page = SimpleNamespace(context=object())

        async def _slow():
            await asyncio.sleep(0.35)
            return ("prompt", "reply", "full", {"ok": True})

        with patch(
            "browser_bot.discovery_ui_bridge.resolve_discovery_page",
            side_effect=lambda p: p,
        ), patch(
            "browser_bot.discovery_ui_bridge.check_ui_discovery_restart",
            return_value=None,
        ):
            result = await run_with_ui_fallback_watch(page, _slow())
        self.assertEqual(result, ("prompt", "reply", "full", {"ok": True}))


if __name__ == "__main__":
    unittest.main()
