"""LazyTierFetcher.with_page accepts fetcher_with_page_kwargs (site/component/start_url)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from browser_bot.fetchers.human import HumanFetcher
from browser_bot.fetchers.ui_bundle import LazyTierFetcher


class TestLazyTierFetcherWithPageKwargs(unittest.IsolatedAsyncioTestCase):
    async def test_forwards_site_kwargs_to_human(self):
        human = MagicMock(spec=HumanFetcher)
        human.with_page = AsyncMock(return_value=("ok",))
        bundle = MagicMock()
        bundle.ensure_tier = AsyncMock(return_value=human)
        proxy = LazyTierFetcher(bundle, "human")

        result = await proxy.with_page(
            AsyncMock(),
            storage_path="/tmp/auth.json",
            site="Lakera",
            component="mcp_chat_poisoning",
            start_url="https://play.lakera.ai/agent-breaker/mcp_chat_poisoning",
            headless=False,
        )

        self.assertEqual(result, ("ok",))
        kwargs = human.with_page.await_args.kwargs
        self.assertEqual(kwargs["site"], "Lakera")
        self.assertEqual(kwargs["component"], "mcp_chat_poisoning")
        self.assertEqual(
            kwargs["start_url"],
            "https://play.lakera.ai/agent-breaker/mcp_chat_poisoning",
        )
        self.assertIs(kwargs["headless"], False)

    async def test_pool_tier_ignores_site_kwargs(self):
        pool = MagicMock()
        pool.with_page = AsyncMock(return_value="pooled")
        bundle = MagicMock()
        bundle.ensure_tier = AsyncMock(return_value=pool)
        proxy = LazyTierFetcher(bundle, "pool")

        result = await proxy.with_page(
            AsyncMock(),
            storage_path="/tmp/auth.json",
            site="Lakera",
            component="mcp_chat_poisoning",
            start_url="https://play.lakera.ai/x",
        )

        self.assertEqual(result, "pooled")
        kwargs = pool.with_page.await_args.kwargs
        self.assertNotIn("site", kwargs)
        self.assertNotIn("component", kwargs)
        self.assertNotIn("start_url", kwargs)


if __name__ == "__main__":
    unittest.main()
