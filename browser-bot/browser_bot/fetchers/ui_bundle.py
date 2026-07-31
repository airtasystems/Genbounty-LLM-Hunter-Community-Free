"""UI submission fetcher bundle: fast pool/cluster tiers plus stealth fallbacks and human."""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar

from browser_bot.browser.launcher import (
    auth_config_mtime,
    close_login_chrome_cdp,
    launch_browser,
    new_pool_cluster_browser_context,
    open_cdp_browser_session,
    should_use_cdp_for_headed_request,
)
from browser_bot.config import (
    CONTEXT_COUNT,
    FETCH_METHOD,
    PAGES_PER_CONTEXT,
    POOL_CLUSTER_HUMAN_LIKE,
    POOL_SIZE,
    get_pool_cluster_browser_enhancements,
)
from browser_bot.fetchers.cluster import ClusterFetcher
from browser_bot.fetchers.human import HumanFetcher
from browser_bot.fetchers.pool import PoolFetcher
from browser_bot.sites import get_browser_storage_state_path
from browser_bot.submit.common import log_resilience

T = TypeVar("T")


def resolve_headful_resource_limits(
    *,
    method: str,
    headed: bool,
    pool_size: int,
    cluster_workers: int,
    need_cluster: bool,
) -> tuple[int, int, bool]:
    """Cap pool/cluster for visible browser runs (low-RAM friendly).

    Returns (pool_size, cluster_workers, need_cluster).
    """
    if not headed:
        return pool_size, cluster_workers, need_cluster
    pool_size = min(pool_size, 1)
    if method == "auto":
        return pool_size, 0, False
    if method == "cluster":
        return 0, min(cluster_workers, 1), True
    if method == "pool":
        return pool_size, 0, False
    return pool_size, cluster_workers, need_cluster


def build_lazy_tier_plan(
    method: str,
    *,
    need_enhanced: bool,
    need_pool: bool,
    need_cluster: bool,
) -> list[tuple[str, bool]]:
    """Ordered (tier_key, human_behavior) ladder without launching browsers."""
    tiers: list[tuple[str, bool]] = []
    if need_pool and method in ("auto", "pool"):
        tiers.append(("pool", False))
    if need_cluster and method in ("auto", "cluster"):
        tiers.append(("cluster", False))
    if need_enhanced and need_pool and method in ("auto", "pool"):
        tiers.append(("pool_stealth", False))
    if need_enhanced and need_cluster and method in ("auto", "cluster"):
        tiers.append(("cluster_stealth", False))
    if method in ("auto", "human", "pool", "cluster"):
        tiers.append(("human", True))
    return tiers


class LazyTierFetcher:
    """Proxy that launches a fetcher tier on first use (shared-browser + lazy fallback)."""

    tier_name: str

    def __init__(self, bundle: "UIFetcherBundle", tier_key: str):
        self._bundle = bundle
        self._tier_key = tier_key
        self.tier_name = tier_key.split("_")[0]

    async def _resolve(self) -> Any | None:
        return await self._bundle.ensure_tier(self._tier_key)

    async def fetch(self, url: str):
        fetcher = await self._resolve()
        if fetcher is None:
            return None
        return await fetcher.fetch(url)

    async def post(
        self,
        url: str,
        *,
        data: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ):
        fetcher = await self._resolve()
        if fetcher is None:
            return None
        return await fetcher.post(url, data=data, json_data=json_data, headers=headers)

    async def with_page(
        self,
        callback: Callable[..., Awaitable[T]],
        storage_path: str | None = None,
        storage_state: dict | None = None,
        *,
        headless: bool | None = None,
        allow_all: bool = False,
        discovery_layout: bool = False,
        guided_discovery: bool = False,
        record_har_path: str | None = None,
        record_har_url_filter: str | None = None,
        record_har_content: str = "embed",
        site: str | None = None,
        component: str | None = None,
        start_url: str | None = None,
    ) -> T | None:
        fetcher = await self._resolve()
        if fetcher is None:
            return None
        # Pool/cluster only accept the shared page kwargs; HumanFetcher also takes
        # CDP targeting (site/component/start_url) and discovery/HAR options.
        common = dict(
            storage_path=storage_path,
            storage_state=storage_state,
            headless=headless,
            allow_all=allow_all,
            discovery_layout=discovery_layout,
        )
        if self._tier_key == "human" or isinstance(fetcher, HumanFetcher):
            return await fetcher.with_page(
                callback,
                **common,
                guided_discovery=guided_discovery,
                record_har_path=record_har_path,
                record_har_url_filter=record_har_url_filter,
                record_har_content=record_har_content,
                site=site,
                component=component,
                start_url=start_url,
            )
        return await fetcher.with_page(callback, **common)


@dataclass
class _CdpSession:
    browser: Any
    context: Any
    page: Any
    chrome_proc: Any
    site: str
    component: str | None
    auth_mtime: float = 0.0


@dataclass
class UIFetcherBundle:
    """Ordered fetcher strategies (fastest first) plus cleanup handles."""

    strategies: list[tuple[Any, bool, str]] = field(default_factory=list)
    pool_fast: PoolFetcher | None = None
    pool_enhanced: PoolFetcher | None = None
    cluster_fast: ClusterFetcher | None = None
    cluster_enhanced: ClusterFetcher | None = None
    human: HumanFetcher | None = None
    _playwright: Any = field(default=None, repr=False)
    _shared_browser: Any = field(default=None, repr=False)
    _storage_state_str: str | None = field(default=None, repr=False)
    _launch_headless: bool | None = field(default=None, repr=False)
    _pool_size: int = field(default=0, repr=False)
    _cluster_workers: int = field(default=0, repr=False)
    _need_enhanced: bool = field(default=False, repr=False)
    _tier_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _browsers: list[Any] = field(default_factory=list, repr=False)
    _extra_contexts: list[Any] = field(default_factory=list, repr=False)
    _cdp_session: _CdpSession | None = field(default=None, repr=False)
    _use_cdp: bool = field(default=False, repr=False)

    async def _close_cdp_session(self) -> None:
        session = self._cdp_session
        self._cdp_session = None
        if session is None:
            return
        await close_login_chrome_cdp(session.browser, session.chrome_proc)

    async def ensure_cdp_session(
        self,
        site: str,
        component: str | None,
        start_url: str | None,
    ) -> tuple[Any, Any, Any, bool]:
        """Reuse one CDP Chrome tab for all prompts in a Run Tests session.

        The fourth return value is always True (bundle-owned): HumanFetcher must not
        close Chrome after each prompt — only UIFetcherBundle.close() does that.
        """
        auth_mtime = auth_config_mtime(site, component)
        if (
            self._cdp_session is not None
            and self._cdp_session.site == site
            and self._cdp_session.component == component
            and self._cdp_session.auth_mtime >= auth_mtime
        ):
            session = self._cdp_session
            try:
                page = session.page
                if page is not None and not page.is_closed():
                    return session.browser, session.context, page, True
            except Exception:
                pass
            # Stale / closed tab — drop and reopen below.
            await self._close_cdp_session()

        await self._close_cdp_session()
        from browser_bot.sites import normalize_target_access_url

        launch_url = normalize_target_access_url(str(start_url or site).strip()) or str(
            start_url or site
        ).strip()
        if launch_url and not launch_url.startswith(("http://", "https://")):
            launch_url = f"https://{launch_url.lstrip('/')}"
        browser, context, page, chrome_proc = await open_cdp_browser_session(
            self._playwright,
            site=site,
            start_url=launch_url or "about:blank",
            component=component,
            auto_launch=True,
            log_tag="run",
        )
        self._cdp_session = _CdpSession(
            browser=browser,
            context=context,
            page=page,
            chrome_proc=chrome_proc,
            site=site,
            component=component,
            auth_mtime=auth_mtime,
        )
        # Always True: session lifecycle belongs to the bundle, not per-prompt release.
        return browser, context, page, True

    async def close(self) -> None:
        await self._close_cdp_session()
        for ctx in self._extra_contexts:
            try:
                await ctx.close()
            except Exception:
                pass
        for browser in self._browsers:
            try:
                await browser.close()
            except Exception:
                pass
        self._browsers.clear()
        self._extra_contexts.clear()
        self._shared_browser = None

    async def _get_shared_browser(self) -> Any:
        if self._shared_browser is None:
            human_mode = (
                POOL_CLUSTER_HUMAN_LIKE
                or self._launch_headless is False
                or self._need_enhanced
            )
            self._shared_browser = await launch_browser(
                self._playwright,
                human_mode=human_mode,
                headless=self._launch_headless,
            )
            self._browsers.append(self._shared_browser)
        return self._shared_browser

    async def ensure_tier(self, tier_key: str) -> Any | None:
        """Launch a fetcher tier on first use (lazy fallback + shared browser)."""
        async with self._tier_lock:
            if tier_key == "human":
                return self.human
            if tier_key == "pool":
                if self.pool_fast is None:
                    enhanced = POOL_CLUSTER_HUMAN_LIKE
                    self.pool_fast, contexts = await _launch_pool_tier(
                        self._playwright,
                        browser=await self._get_shared_browser(),
                        storage_state_str=self._storage_state_str,
                        pool_size=self._pool_size,
                        launch_headless=self._launch_headless,
                        enhanced=enhanced,
                    )
                    self._extra_contexts.extend(contexts)
                return self.pool_fast
            if tier_key == "pool_stealth":
                if self.pool_enhanced is None:
                    self.pool_enhanced, contexts = await _launch_pool_tier(
                        self._playwright,
                        browser=await self._get_shared_browser(),
                        storage_state_str=self._storage_state_str,
                        pool_size=self._pool_size,
                        launch_headless=self._launch_headless,
                        enhanced=True,
                    )
                    self._extra_contexts.extend(contexts)
                return self.pool_enhanced
            if tier_key == "cluster":
                if self.cluster_fast is None:
                    self.cluster_fast, contexts = await _launch_cluster_tier(
                        self._playwright,
                        browser=await self._get_shared_browser(),
                        storage_state_str=self._storage_state_str,
                        cluster_workers=self._cluster_workers,
                        launch_headless=self._launch_headless,
                        enhanced=False,
                    )
                    self._extra_contexts.extend(contexts)
                return self.cluster_fast
            if tier_key == "cluster_stealth":
                if self.cluster_enhanced is None:
                    self.cluster_enhanced, contexts = await _launch_cluster_tier(
                        self._playwright,
                        browser=await self._get_shared_browser(),
                        storage_state_str=self._storage_state_str,
                        cluster_workers=self._cluster_workers,
                        launch_headless=self._launch_headless,
                        enhanced=True,
                    )
                    self._extra_contexts.extend(contexts)
                return self.cluster_enhanced
        return None


async def _launch_pool_tier(
    playwright,
    *,
    browser,
    storage_state_str: str | None,
    pool_size: int,
    launch_headless: bool | None,
    enhanced: bool,
) -> tuple[PoolFetcher | None, list[Any]]:
    if pool_size <= 0:
        return None, []
    # Human-like/stealth flags must not collapse the worker pool — POOL_SIZE wins.
    size = max(1, int(pool_size))
    _human_chrome, pool_allow_styles, pool_stealth, pool_human_ctx = get_pool_cluster_browser_enhancements()
    if POOL_CLUSTER_HUMAN_LIKE:
        full_bundle = True
        allow_styles = pool_allow_styles
        use_stealth = pool_stealth
        use_human_context = pool_human_ctx
    elif enhanced:
        full_bundle = True
        allow_styles = True
        use_stealth = True
        use_human_context = True
    else:
        full_bundle = False
        allow_styles = False
        use_stealth = False
        use_human_context = False

    page_queue: asyncio.Queue = asyncio.Queue()
    contexts: list[Any] = []
    for _ in range(size):
        ctx = await new_pool_cluster_browser_context(
            browser,
            storage_state_path=storage_state_str,
            full_human_tier_bundle=full_bundle,
            allow_styles=allow_styles,
            use_stealth=use_stealth,
            use_human_context=use_human_context,
        )
        contexts.append(ctx)
        page = await ctx.new_page()
        await page_queue.put(page)
    headed = launch_headless is False
    print(f"  [pool] launched {size} page(s) (enhanced={bool(enhanced)})", flush=True)
    return PoolFetcher(page_queue, headed=headed), contexts


async def _launch_cluster_tier(
    playwright,
    *,
    browser,
    storage_state_str: str | None,
    cluster_workers: int,
    launch_headless: bool | None,
    enhanced: bool,
) -> tuple[ClusterFetcher | None, list[Any]]:
    if cluster_workers <= 0:
        return None, []
    # Same as pool: enhancements must not force a single worker.
    workers = max(1, int(cluster_workers))
    _human_chrome, pool_allow_styles, pool_stealth, pool_human_ctx = get_pool_cluster_browser_enhancements()
    if POOL_CLUSTER_HUMAN_LIKE:
        full_bundle = True
        allow_styles = pool_allow_styles
        use_stealth = pool_stealth
        use_human_context = pool_human_ctx
    elif enhanced:
        full_bundle = True
        allow_styles = True
        use_stealth = True
        use_human_context = True
    else:
        full_bundle = False
        allow_styles = False
        use_stealth = False
        use_human_context = False

    page_queue: asyncio.Queue = asyncio.Queue()
    contexts: list[Any] = []
    pages_created = 0
    for _ in range(CONTEXT_COUNT):
        if pages_created >= workers:
            break
        ctx = await new_pool_cluster_browser_context(
            browser,
            storage_state_path=storage_state_str,
            full_human_tier_bundle=full_bundle,
            allow_styles=allow_styles,
            use_stealth=use_stealth,
            use_human_context=use_human_context,
        )
        contexts.append(ctx)
        for _ in range(PAGES_PER_CONTEXT):
            if pages_created >= workers:
                break
            page = await ctx.new_page()
            await page_queue.put(page)
            pages_created += 1
    headed = launch_headless is False
    print(f"  [cluster] launched {pages_created} page(s) (enhanced={bool(enhanced)})", flush=True)
    return ClusterFetcher(page_queue, headed=headed), contexts


def _resolve_launch_headless(primary_domain: str, component: str | None) -> bool | None:
    if not (component or primary_domain):
        return None
    try:
        root = Path(__file__).resolve().parent.parent.parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from pipeline.component_settings import playwright_headless_kwarg

        return playwright_headless_kwarg(
            site=primary_domain,
            component=component or os.getenv("GENBOUNTY_COMPONENT") or None,
        )
    except Exception:
        return None


async def setup_ui_fetcher_bundle(
    playwright,
    primary_domain: str,
    post_count: int,
    *,
    component: str | None = None,
    human_only: bool = False,
) -> UIFetcherBundle:
    """Create lazy pool/cluster tiers (shared browser) and human fetcher for UI resilience."""
    bundle = UIFetcherBundle()
    bundle._playwright = playwright
    storage_state = get_browser_storage_state_path(primary_domain, component)
    bundle._storage_state_str = str(storage_state) if storage_state else None

    method = "human" if human_only else str(FETCH_METHOD or "auto").lower()
    need_pool = method in ("auto", "pool")
    need_cluster = method in ("auto", "cluster")
    need_enhanced = not POOL_CLUSTER_HUMAN_LIKE and method != "human"
    bundle._need_enhanced = need_enhanced
    count = max(post_count, 1)
    pool_size = min(POOL_SIZE, count) if (count and need_pool) else 0
    cluster_workers = min(CONTEXT_COUNT * PAGES_PER_CONTEXT, count) if (count and need_cluster) else 0

    bundle._launch_headless = _resolve_launch_headless(primary_domain, component)
    headed = bundle._launch_headless is False
    bundle._use_cdp = should_use_cdp_for_headed_request(
        headless=bundle._launch_headless,
        headed=headed,
        site=primary_domain,
        component=component,
    )

    orig_pool, orig_cluster, orig_need_cluster = pool_size, cluster_workers, need_cluster
    pool_size, cluster_workers, need_cluster = resolve_headful_resource_limits(
        method=method,
        headed=headed,
        pool_size=pool_size,
        cluster_workers=cluster_workers,
        need_cluster=need_cluster,
    )
    if bundle._use_cdp:
        log_resilience(
            "cdp_browser",
            "Chrome CDP enabled: Run Tests use real Chrome (pool/cluster skipped)",
            detail="Headed human tier attaches via CDP port 9222 with the login profile",
        )
        pool_size = 0
        cluster_workers = 0
        need_cluster = False
    elif headed and (pool_size != orig_pool or cluster_workers != orig_cluster or need_cluster != orig_need_cluster):
        log_resilience(
            "headful_resource_limits",
            "Headed browser: capped pool/cluster for low-RAM runs",
            detail=(
                f"pool {orig_pool}→{pool_size}, cluster workers {orig_cluster}→{cluster_workers}, "
                f"cluster={'on' if need_cluster else 'off (lazy only if fallback)'}; "
                "fallback tiers launch on demand"
            ),
        )

    bundle._pool_size = pool_size
    bundle._cluster_workers = cluster_workers

    if method in ("auto", "pool", "cluster", "human"):
        bundle.human = HumanFetcher(playwright, cdp_bundle=bundle if bundle._use_cdp else None)

    tier_plan = build_lazy_tier_plan(
        method,
        need_enhanced=need_enhanced,
        need_pool=need_pool and pool_size > 0,
        need_cluster=need_cluster and cluster_workers > 0,
    )

    # Eagerly warm only the first pool/cluster tier (one shared browser, one context set).
    if tier_plan:
        first_tier = tier_plan[0][0]
        if first_tier in ("pool", "cluster"):
            try:
                await bundle.ensure_tier(first_tier)
            except Exception:
                pass

    site = primary_domain
    comp = (component or os.getenv("GENBOUNTY_COMPONENT") or "").strip() or None
    if site and comp:
        bundle.strategies = [
            (LazyTierFetcher(bundle, tier_key), human_behavior, tier_key)
            for tier_key, human_behavior in tier_plan
        ]
    elif bundle.human and method == "human":
        bundle.strategies = [(bundle.human, True, "human")]

    return bundle
