"""Tier 5: Human mimicking - new context per request, maximum stealth.

Mimics human interaction with:
- playwright-stealth: navigator.webdriver evasion, fingerprint masking
- Country/locale/timezone/geolocation: consistent identity per region
- Human-like mouse movement: Bezier curves, variable delays
- Full-window viewport (no fixed width/height; uses browser window size)
- Fewer automation Chrome flags (HUMAN_CHROME_ARGS)
- Full stylesheet loading for realistic rendering

Uses launch_context_for_request() for unified flow with login and refresh.
TLS: Chromium uses BoringSSL, producing Chrome-like JA3 fingerprints.
"""

import asyncio
import time
from typing import Any, Optional, TYPE_CHECKING

from browser_bot.browser.human_behavior import human_mouse_wander, human_scroll
from browser_bot.browser.launcher import (
    close_login_chrome_cdp,
    get_cdp_chrome_proc,
    get_cdp_session_page,
    launch_context_for_request,
    should_use_cdp_for_headed_request,
)
from browser_bot.config import HUMAN_SCROLL_AFTER_LOAD, HUMAN_READ_DELAY_MS
from browser_bot.submit.common import NonSuccessResponseError
from browser_bot.fetchers.base import (
    BaseFetcher,
    FetchResult,
    PostResult,
    extract_first_p_from_dom,
)
from browser_bot.sites import get_storage_state_path_for_url

if TYPE_CHECKING:
    from browser_bot.fetchers.ui_bundle import UIFetcherBundle


class HumanFetcher(BaseFetcher):
    """Human mimicking: fresh context per request, stealth, fingerprint evasion, mouse movement."""

    tier_name = "human"

    def __init__(self, playwright, cdp_bundle: "UIFetcherBundle | None" = None):
        self.playwright = playwright
        self.cdp_bundle = cdp_bundle

    def _resolve_headed(
        self,
        headless: bool | None,
    ) -> bool:
        if headless is False:
            return True
        if headless is True:
            return False
        if self.cdp_bundle is not None and self.cdp_bundle._launch_headless is False:
            return True
        return False

    async def _setup_context(
        self,
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
    ) -> tuple[Any, Any, bool, Any | None]:
        """Returns (browser, context, cdp_reuse, session_page)."""
        headed = self._resolve_headed(headless)
        use_cdp = bool(site) and should_use_cdp_for_headed_request(
            headless=headless,
            headed=headed,
            site=site,
            component=component,
        )

        if use_cdp and self.cdp_bundle is not None and not record_har_path:
            browser, context, page, reuse = await self.cdp_bundle.ensure_cdp_session(
                site,
                component,
                start_url,
            )
            return browser, context, reuse, page

        browser, context = await launch_context_for_request(
            self.playwright,
            storage_state_path=storage_path,
            storage_state=storage_state,
            headless=headless,
            allow_all=allow_all,
            force_human=True,
            discovery_layout=discovery_layout,
            guided_discovery=guided_discovery,
            record_har_path=record_har_path,
            record_har_url_filter=record_har_url_filter,
            record_har_content=record_har_content,
            site=site,
            component=component,
            start_url=start_url,
        )
        return browser, context, False, get_cdp_session_page(browser)

    async def _acquire_work_page(
        self,
        browser,
        context,
        *,
        session_page: Any | None,
    ) -> tuple[Any, bool]:
        """Return (page, close_when_done). Reuse the warmed CDP tab when available."""
        for candidate in (session_page, get_cdp_session_page(browser)):
            if candidate is None:
                continue
            try:
                if not candidate.is_closed():
                    return candidate, False
            except Exception:
                continue
        return await context.new_page(), True

    async def _release_context(
        self,
        browser,
        context,
        *,
        page=None,
        cdp_reuse: bool = False,
    ) -> None:
        if page is not None:
            try:
                await page.close()
            except Exception:
                pass
        if cdp_reuse:
            return
        chrome_proc = get_cdp_chrome_proc(browser)
        if chrome_proc is not None or getattr(browser, "_genbounty_cdp_auto", False):
            await close_login_chrome_cdp(browser, chrome_proc)
            return
        try:
            await context.close()
        except Exception:
            pass
        try:
            await browser.close()
        except Exception:
            pass

    async def fetch(self, url: str) -> Optional[FetchResult]:
        try:
            storage_path = get_storage_state_path_for_url(url)
            storage_str = str(storage_path) if storage_path else None
            from browser_bot.sites import get_domain_from_url

            site = get_domain_from_url(url)
            browser, context, cdp_reuse, session_page = await self._setup_context(
                storage_str,
                site=site,
                start_url=url,
            )
            page, close_page = await self._acquire_work_page(
                browser, context, session_page=session_page
            )

            # Brief pre-navigation delay (human hesitation)
            await asyncio.sleep(0.15 + time.perf_counter() % 0.15 + (time.perf_counter() % 100) * 0.01)

            start = time.perf_counter()
            response = await page.goto(url, wait_until="load", timeout=30000)

            # Read delay: humans pause before interacting
            await asyncio.sleep(HUMAN_READ_DELAY_MS / 1000.0)

            # Human-like mouse movement after load
            await human_mouse_wander(page, count=2)

            if HUMAN_SCROLL_AFTER_LOAD:
                await human_scroll(page)

            first_p = await extract_first_p_from_dom(page)
            content = await page.content()
            title = await page.title()
            elapsed = time.perf_counter() - start

            await self._release_context(
                browser,
                context,
                page=page if close_page else None,
                cdp_reuse=cdp_reuse,
            )

            status = response.status if response else None
            return FetchResult(
                content=content,
                tier=self.tier_name,
                elapsed=elapsed,
                status_code=status,
                title=title,
                first_p=first_p,
            )
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
            storage_path = get_storage_state_path_for_url(url)
            storage_str = str(storage_path) if storage_path else None
            from browser_bot.sites import get_domain_from_url

            site = get_domain_from_url(url)
            browser, context, cdp_reuse, session_page = await self._setup_context(
                storage_str,
                site=site,
                start_url=url,
            )
            page, close_page = await self._acquire_work_page(
                browser, context, session_page=session_page
            )

            # Human-like behavior before POST
            await asyncio.sleep(0.05 + time.perf_counter() % 0.1)
            await human_mouse_wander(page, count=1)

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

            await self._release_context(
                browser,
                context,
                page=page if close_page else None,
                cdp_reuse=cdp_reuse,
            )

            return PostResult(url=url, tier=self.tier_name, status=response.status, body=body, elapsed=elapsed)
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
        guided_discovery: bool = False,
        record_har_path: str | None = None,
        record_har_url_filter: str | None = None,
        record_har_content: str = "embed",
        site: str | None = None,
        component: str | None = None,
        start_url: str | None = None,
    ):
        try:
            storage_str = str(storage_path) if storage_path else None
            browser, context, cdp_reuse, session_page = await self._setup_context(
                storage_path=storage_str,
                storage_state=storage_state,
                headless=headless,
                allow_all=allow_all,
                discovery_layout=discovery_layout,
                guided_discovery=guided_discovery,
                record_har_path=record_har_path,
                record_har_url_filter=record_har_url_filter,
                record_har_content=record_har_content,
                site=site,
                component=component,
                start_url=start_url,
            )
            page, close_page = await self._acquire_work_page(
                browser, context, session_page=session_page
            )
            try:
                return await callback(page)
            finally:
                await self._release_context(
                    browser,
                    context,
                    page=page if close_page else None,
                    cdp_reuse=cdp_reuse,
                )
        except NonSuccessResponseError:
            raise
        except Exception as exc:
            from browser_bot.discovery_ui_bridge import UiDiscoveryRestartRequested

            if isinstance(exc, UiDiscoveryRestartRequested):
                raise
            if headless is False:
                import sys

                print(f"[!] Headed browser launch failed: {exc!r}", file=sys.stderr)
            return None
