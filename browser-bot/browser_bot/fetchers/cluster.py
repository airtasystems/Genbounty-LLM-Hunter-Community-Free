"""Tier 4: Max power - multi-context cluster (from 106)."""

import asyncio
import time
from typing import Any, Optional

from browser_bot.fetchers.base import BaseFetcher, FetchResult, PostResult, extract_first_p_from_dom
from browser_bot.submit.common import NonSuccessResponseError


class ClusterFetcher(BaseFetcher):
    """Max power: multi-context, multi-page pool for maximum parallelism."""

    tier_name = "cluster"

    def __init__(self, page_queue: asyncio.Queue, *, headed: bool = False):
        self.page_queue = page_queue
        self.headed = headed

    async def fetch(self, url: str) -> Optional[FetchResult]:
        try:
            page = await self.page_queue.get()
            try:
                start = time.perf_counter()
                response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                first_p = await extract_first_p_from_dom(page)
                content = await page.content()
                title = await page.title()
                elapsed = time.perf_counter() - start
                status = response.status if response else None
                return FetchResult(
                    content=content,
                    tier=self.tier_name,
                    elapsed=elapsed,
                    status_code=status,
                    title=title,
                    first_p=first_p,
                )
            finally:
                await self.page_queue.put(page)
        except Exception:
            return None

    async def post(
        self,
        url: str,
        *,
        data: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Optional[PostResult]:
        try:
            page = await self.page_queue.get()
            try:
                start = time.perf_counter()
                opts: dict[str, Any] = {}
                if json_data:
                    opts["data"] = json_data
                elif data:
                    opts["form"] = data
                if headers:
                    opts["headers"] = headers
                response = await page.request.post(url, **opts)
                body = await response.text()
                elapsed = time.perf_counter() - start
                return PostResult(url=url, tier=self.tier_name, status=response.status, body=body, elapsed=elapsed)
            finally:
                await self.page_queue.put(page)
        except Exception:
            return None

    async def with_page(
        self,
        callback,
        storage_path: str | None = None,
        storage_state: dict | None = None,
        *,
        headless=None,
        allow_all: bool = False,
        discovery_layout: bool = False,
        site: str | None = None,  # noqa: ARG002 - API parity with HumanFetcher
        component: str | None = None,  # noqa: ARG002
        start_url: str | None = None,  # noqa: ARG002
    ):
        # site/component/start_url accepted for API parity with HumanFetcher /
        # LazyTierFetcher (fetcher_with_page_kwargs); unused for cluster pages.
        if allow_all or storage_state is not None:
            return None
        if headless is False and not self.headed:
            return None  # caller wants visible browser but cluster pages are headless
        try:
            page = await self.page_queue.get()
            try:
                return await callback(page)
            finally:
                await self.page_queue.put(page)
        except NonSuccessResponseError:
            raise
        except Exception:
            return None
