#!/usr/bin/env python3
"""
Browser Bot: Tiered fetching via Playwright browser automation.

Tiers (in order):
  1. Pool     - Full speed, page pool + queue
  2. Cluster  - Max power, multi-context
  3. Human    - Stealth, new context per request
"""

import asyncio
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich import box
from rich.markup import escape

# Add project root for imports
sys.path.insert(0, str(Path(__file__).parent))

console = Console()


from playwright.async_api import async_playwright

from browser_bot.config import (
    CONTEXT_COUNT,
    FETCH_METHOD,
    POOL_CLUSTER_HUMAN_LIKE,
    PAGES_PER_CONTEXT,
    POOL_SIZE,
    POSTS,
    get_pool_cluster_browser_enhancements,
)
from browser_bot.sites import (
    get_browser_storage_state_path,
    get_component_urls_and_posts,
    get_domain_from_url,
    load_component_config,
    get_submission_config,
    describe_submission_config_issue,
)
from browser_bot.browser.launcher import launch_browser, new_pool_cluster_browser_context
from browser_bot.fetchers.pool import PoolFetcher
from browser_bot.fetchers.cluster import ClusterFetcher
from browser_bot.fetchers.human import HumanFetcher
from browser_bot.fetchers.base import PostResult
from browser_bot.metrics import Metrics


def _describe_submission_config_issue(site: str, component: str) -> str:
    return describe_submission_config_issue(load_component_config(site, component))


async def post_url(
    url: str,
    *,
    data: dict | None = None,
    json_data: dict | None = None,
    headers: dict | None = None,
    pool_fetcher: PoolFetcher | None = None,
    cluster_fetcher: ClusterFetcher | None = None,
    human_fetcher: HumanFetcher = None,
    metrics: Metrics = None,
) -> PostResult | None:
    """Try POST tiers in order until one succeeds (same pipeline as GET)."""
    def _log(r: PostResult):
        status_style = "green" if 200 <= r.status < 300 else "yellow" if r.status < 400 else "red"
        console.print(f"  [bold cyan]{r.tier.upper()}[/] [dim]{r.url}[/] [{status_style}]{r.status}[/] {len(r.body):,} chars · {r.elapsed:.2f}s")
        if r.body:
            preview = (r.body[:120] + "…") if len(r.body) > 120 else r.body
            console.print(f"      [dim]{escape(preview)}[/]")

    method = FETCH_METHOD.lower()
    if method not in ("auto", "pool", "cluster", "human"):
        method = "auto"

    # Tier 1: Pool
    if method in ("auto", "pool") and pool_fetcher:
        result = await pool_fetcher.post(url, data=data, json_data=json_data, headers=headers)
        if result:
            if metrics:
                metrics.record(result.tier, result.elapsed)
            _log(result)
            return result
        if method == "pool":
            console.print(f"[bold red]FAIL[/] [dim]{url}[/] [red]→ Pool POST failed[/]")
            return None

    # Tier 2: Cluster
    if method in ("auto", "cluster") and cluster_fetcher:
        result = await cluster_fetcher.post(url, data=data, json_data=json_data, headers=headers)
        if result:
            if metrics:
                metrics.record(result.tier, result.elapsed)
            _log(result)
            return result
        if method == "cluster":
            console.print(f"[bold red]FAIL[/] [dim]{url}[/] [red]→ Cluster POST failed[/]")
            return None

    # Tier 3: Human
    if method in ("auto", "human") and human_fetcher:
        result = await human_fetcher.post(url, data=data, json_data=json_data, headers=headers)
        if result:
            if metrics:
                metrics.record(result.tier, result.elapsed)
            _log(result)
            return result

    console.print(f"[bold red]FAIL[/] [dim]{url}[/] [red]→ all tiers failed[/]")
    return None


async def _setup_fetchers(
    playwright,
    primary_domain: str,
    url_count: int | None = None,
    post_count: int | None = None,
    *,
    component: str | None = None,
    human_only: bool = False,
):
    """Shared setup for GET and POST. Returns (pool_fetcher, cluster_fetcher, human_fetcher, pool_context, cluster_browser, cluster_contexts).

    human_only: when True, behave like FETCH_METHOD=human (no pool/cluster browsers or fetchers).
    """
    p = playwright
    storage_state = get_browser_storage_state_path(primary_domain, component)
    storage_state_str = str(storage_state) if storage_state else None

    pool_fetcher = None
    cluster_fetcher = None
    pool_context = None
    cluster_browser = None
    cluster_contexts = []
    url_count = url_count if url_count is not None else 0
    post_count = post_count if post_count is not None else len(POSTS)
    count = max(post_count, url_count)
    method = "human" if human_only else FETCH_METHOD.lower()
    need_pool = method in ("auto", "pool")
    need_cluster = method in ("auto", "cluster")
    pool_size = min(POOL_SIZE, count) if (count and need_pool) else 0
    cluster_workers = min(CONTEXT_COUNT * PAGES_PER_CONTEXT, count) if (count and need_cluster) else 0

    use_human_chrome, allow_styles, use_stealth, use_human_context = get_pool_cluster_browser_enhancements()

    launch_headless = None
    if component or primary_domain:
        try:
            import os
            from pathlib import Path

            root = Path(__file__).resolve().parent.parent
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            from pipeline.component_settings import playwright_headless_kwarg

            launch_headless = playwright_headless_kwarg(
                site=primary_domain,
                component=component or os.getenv("GENBOUNTY_COMPONENT") or None,
            )
        except Exception:
            launch_headless = None

    from browser_bot.fetchers.ui_bundle import resolve_headful_resource_limits
    from browser_bot.browser.launcher import should_use_cdp_for_headed_request

    headed = launch_headless is False
    use_cdp_headed = should_use_cdp_for_headed_request(
        headless=launch_headless,
        headed=headed,
        site=primary_domain,
        component=component or os.getenv("GENBOUNTY_COMPONENT") or None,
    )
    pool_size, cluster_workers, need_cluster = resolve_headful_resource_limits(
        method=method,
        headed=headed,
        pool_size=pool_size,
        cluster_workers=cluster_workers,
        need_cluster=need_cluster,
    )
    if use_cdp_headed:
        pool_size = 0
        cluster_workers = 0
        need_cluster = False

    shared_browser = None
    try:
        if pool_size > 0 or (need_cluster and cluster_workers > 0):
            shared_browser = await launch_browser(
                p, human_mode=use_human_chrome or headed, headless=launch_headless
            )
    except Exception as e:
        console.print(f"[yellow]Shared browser setup skipped:[/] {e}")
        shared_browser = None

    try:
        if pool_size > 0 and shared_browser:
            page_queue = asyncio.Queue()
            for _ in range(pool_size):
                ctx = await new_pool_cluster_browser_context(
                    shared_browser,
                    storage_state_path=storage_state_str,
                    full_human_tier_bundle=POOL_CLUSTER_HUMAN_LIKE,
                    allow_styles=allow_styles,
                    use_stealth=use_stealth,
                    use_human_context=use_human_context,
                )
                page = await ctx.new_page()
                await page_queue.put(page)
            pool_fetcher = PoolFetcher(page_queue, headed=launch_headless is False)
            pool_context = shared_browser
    except Exception as e:
        console.print(f"[yellow]Pool setup skipped:[/] {e}")
        pool_fetcher = None

    try:
        if need_cluster and cluster_workers > 0 and shared_browser:
            cluster_page_queue = asyncio.Queue()
            pages_created = 0
            for ci in range(CONTEXT_COUNT):
                if pages_created >= cluster_workers:
                    break
                ctx = await new_pool_cluster_browser_context(
                    shared_browser,
                    storage_state_path=storage_state_str,
                    full_human_tier_bundle=POOL_CLUSTER_HUMAN_LIKE,
                    allow_styles=allow_styles,
                    use_stealth=use_stealth,
                    use_human_context=use_human_context,
                )
                cluster_contexts.append(ctx)
                for _ in range(PAGES_PER_CONTEXT):
                    if pages_created >= cluster_workers:
                        break
                    page = await ctx.new_page()
                    await cluster_page_queue.put(page)
                    pages_created += 1
            cluster_fetcher = ClusterFetcher(cluster_page_queue, headed=launch_headless is False)
    except Exception as e:
        console.print(f"[yellow]Cluster setup skipped:[/] {e}")
        cluster_fetcher = None

    if shared_browser:
        pool_context = shared_browser

    human_fetcher = HumanFetcher(p)

    return pool_fetcher, cluster_fetcher, human_fetcher, pool_context, cluster_browser, cluster_contexts


async def _close_fetcher_resources(pool_context, cluster_browser, cluster_contexts) -> None:
    """Close pool/cluster contexts and browser once (shared browser safe)."""
    for ctx in cluster_contexts:
        try:
            await ctx.close()
        except Exception:
            pass
    browser = pool_context or cluster_browser
    if browser:
        try:
            await browser.close()
        except Exception:
            pass


async def run_with_page_from_fetchers(
    playwright,
    primary_domain: str,
    callback,
    storage_path: str | None = None,
    storage_state: dict | None = None,
    *,
    interactive: bool = False,
    allow_all: bool = False,
    headless: bool | None = None,
    human_only: bool = False,
    component: str | None = None,
    guided_discovery: bool = False,
    start_url: str | None = None,
):
    """
    Run callback(page) using first successful fetcher.
    interactive=True: headless=False, allow_all=True (for login, create config). Only Human supports this.
    allow_all: when True, skip resource blocking (e.g. for refresh). Can be used without interactive.
    headless: explicit override - True forces headless regardless of config, False forces visible.
              When None (default), interactive=True → False, else uses effective component HEADLESS.
    storage_state: optional dict (overrides storage_path). Only Human supports this.
    human_only: when True, skip pool/cluster setup and fetchers (same as FETCH_METHOD=human). Use for discovery / selector recording.
    start_url: preferred launch URL for headed CDP / login-profile sessions (e.g. Firing Range).
    Returns callback result or None if all fail.
    """
    import os

    resolved_component = component or os.getenv("GENBOUNTY_COMPONENT") or None
    (
        pool_fetcher,
        cluster_fetcher,
        human_fetcher,
        pool_context,
        cluster_browser,
        cluster_contexts,
    ) = await _setup_fetchers(
        playwright,
        primary_domain,
        post_count=1,
        component=resolved_component,
        human_only=human_only,
    )
    storage_str = str(storage_path) if storage_path else None
    try:
        root = Path(__file__).resolve().parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from pipeline.component_settings import playwright_headless_kwarg

        resolved_headless = playwright_headless_kwarg(
            site=primary_domain,
            component=resolved_component,
            explicit=headless,
            interactive=interactive,
        )
    except Exception:
        if headless is not None:
            resolved_headless = headless
        else:
            resolved_headless = False if interactive else None
    allow_all_flag = interactive or allow_all

    fetchers_to_try = []
    if not interactive and pool_fetcher:
        fetchers_to_try.append(pool_fetcher)
    if not interactive and cluster_fetcher:
        fetchers_to_try.append(cluster_fetcher)
    if human_fetcher:
        fetchers_to_try.append(human_fetcher)

    from browser_bot.discovery_ui_bridge import UiDiscoveryRestartRequested

    common_page_kw = dict(
        storage_path=storage_str,
        storage_state=storage_state,
        headless=resolved_headless,
        allow_all=allow_all_flag,
        discovery_layout=interactive,
    )
    human_page_kw = {
        **common_page_kw,
        "guided_discovery": guided_discovery,
        "site": primary_domain,
        "component": resolved_component,
    }
    if start_url:
        human_page_kw["start_url"] = start_url

    result = None
    try:
        for fetcher in fetchers_to_try:
            page_kw = human_page_kw if fetcher is human_fetcher else common_page_kw
            result = await fetcher.with_page(callback, **page_kw)
            if result is not None:
                break
    except UiDiscoveryRestartRequested:
        await _close_fetcher_resources(pool_context, cluster_browser, cluster_contexts)
        raise

    await _close_fetcher_resources(pool_context, cluster_browser, cluster_contexts)

    return result


async def run_post_from_fetchers(
    playwright,
    url: str,
    primary_domain: str,
    *,
    data: dict | None = None,
    json_data: dict | None = None,
    headers: dict | None = None,
) -> PostResult | None:
    """Run single POST through fetcher pipeline. Returns PostResult or None."""
    (
        pool_fetcher,
        cluster_fetcher,
        human_fetcher,
        pool_context,
        cluster_browser,
        cluster_contexts,
    ) = await _setup_fetchers(playwright, primary_domain, post_count=1)

    result = await post_url(
        url,
        data=data,
        json_data=json_data,
        headers=headers,
        pool_fetcher=pool_fetcher,
        cluster_fetcher=cluster_fetcher,
        human_fetcher=human_fetcher,
    )

    await _close_fetcher_resources(pool_context, cluster_browser, cluster_contexts)

    return result


async def run_posts(site: str | None = None, component: str | None = None, *, mode: str | None = None, suite_path=None) -> bool:
    """Run POST submissions. Returns True when at least one prompt was executed."""
    if site and component:
        from browser_bot.config import apply_component_settings

        applied = apply_component_settings(site, component)
        if applied:
            from browser_bot.submit.common import log_resilience

            method = applied.get("FETCH_METHOD", "")
            headless = applied.get("HEADLESS", "")
            log_resilience(
                "settings_applied",
                f"Component browser settings applied (FETCH_METHOD={method}, HEADLESS={headless})",
            )

    # UI mode: component has submission config
    if site and component:
        sub = get_submission_config(site, component)
        if suite_path and not sub:
            reason = _describe_submission_config_issue(site, component)
            console.print(
                f"[yellow]Cannot run UI test suite for {site}/{component}: {reason}. "
                "Run Discovery or complete the component submission config before running generated tests.[/]"
            )
            return False
        if sub:
            from browser_bot.config import get_posts_batches, get_posts_strings, get_suite_test_cases
            from browser_bot.submit import is_adaptive_suite, resolve_ui_submission_use_multi, run_submission

            use_multi = resolve_ui_submission_use_multi(sub, suite_path, mode)
            transport = sub.get("transport", "ui")
            transport_label = "API" if transport == "api" else "UI"
            post_count = 0
            if is_adaptive_suite(suite_path):
                try:
                    import sys as _sys
                    from pathlib import Path as _Path

                    _proj = _Path(__file__).resolve().parent.parent
                    if str(_proj) not in _sys.path:
                        _sys.path.insert(0, str(_proj))
                    from pipeline.edition import is_premium_strategy, premium_error_message

                    if is_premium_strategy("adaptive"):
                        console.print(f"[yellow]{premium_error_message('adaptive')}[/]")
                        return False
                except ImportError:
                    pass
                post_count = len(get_suite_test_cases(suite_path) if suite_path else [])
                src_label = str(suite_path) if suite_path else "adaptive suite"
                if not post_count:
                    console.print(
                        "[yellow]No adaptive seed cases found in the suite JSON "
                        "(categories[].prompts must be non-empty).[/]"
                    )
                    return False
                console.print(
                    f"\n[bold]{transport_label} ADAPTIVE[/] {site}/{component} "
                    f"({post_count} seed case(s), up to 5 turns / 4 LLM follow-ups each from {src_label})\n"
                )
            elif use_multi:
                batches = get_posts_batches(suite_path=suite_path)
                if not batches:
                    console.print(
                        "[yellow]No multi batches found. "
                        "Add posts/posts_multi.json (or posts_multi.json at project root) with "
                        "mandates[].prompts[].prompts (string arrays), a top-level batches[] array-of-arrays, "
                        "or a legacy JSON [[\"a\",\"b\"], ...].[/]"
                    )
                    return False
                post_count = len(batches)
                total = sum(len(b) for b in batches)
                src_label = str(suite_path) if suite_path else "posts/posts_multi.json"
                console.print(
                    f"\n[bold]{transport_label} POST[/] {site}/{component} "
                    f"({total} prompts in {post_count} batch(es) from {src_label})\n"
                )
            else:
                posts_strings = get_posts_strings(suite_path=suite_path)
                if not posts_strings:
                    console.print(
                        "[yellow]No UI prompts found. "
                        "The suite JSON has no runnable prompts (categories[].prompts is empty). "
                        "Regenerate the suite or pick a different strategy/play.[/]"
                    )
                    return False
                post_count = len(posts_strings)
                src_label = str(suite_path) if suite_path else "posts/posts_single.json"
                console.print(
                    f"\n[bold]{transport_label} POST[/] {site}/{component} "
                    f"({post_count} prompt(s) from {src_label})\n"
                )

            from browser_bot.submit.common import prepare_run_log_dir

            prepare_run_log_dir(site, component, reuse_env=True)

            if transport == "api":
                results, log_path = await run_submission(
                    site,
                    component,
                    mode_override=mode,
                    suite_path=suite_path,
                )
            else:
                primary_domain = site
                from browser_bot.fetchers.ui_bundle import setup_ui_fetcher_bundle
                from browser_bot.submit.common import effective_fetch_method

                human_only = effective_fetch_method(site, component) == "human"
                from browser_bot.page_blockers import submission_requires_headed_browser

                if submission_requires_headed_browser(site, component) and not human_only:
                    from browser_bot.submit.common import log_resilience

                    log_resilience(
                        "cloudflare_headed",
                        "Headed browser target - fast pool/cluster tiers launch visible when Headless is off",
                    )
                async with async_playwright() as p:
                    bundle = await setup_ui_fetcher_bundle(
                        p,
                        primary_domain,
                        post_count,
                        component=component,
                        human_only=human_only,
                    )
                    try:
                        results, log_path = await run_submission(
                            site,
                            component,
                            fetcher_bundle=bundle,
                            mode_override=mode,
                            suite_path=suite_path,
                        )
                    finally:
                        await bundle.close()

            for inp, resp in results:
                inp_short = (inp[:60] + "…") if len(inp) > 60 else inp
                console.print(f"  [bold]Input:[/] {escape(inp_short)}")
                if resp:
                    resp_short = (resp[:200] + "…") if len(resp) > 200 else resp
                    console.print(f"  [dim]Response:[/] {escape(resp_short)}")
                else:
                    console.print("  [dim]Response:[/] (none)")
            console.print(f"\n[bold green]Finished:[/] {len(results)} {transport_label} submission(s)")
            if log_path:
                console.print(f"  [dim]Log:[/] {log_path}")
            return True

    # HTTP mode
    posts = POSTS
    if site and component:
        _, comp_posts = get_component_urls_and_posts(site, component)
        if comp_posts:
            posts = comp_posts
    if not posts:
        console.print("[yellow]No posts in posts/posts.json. Add entries with url, data/json, headers.[/]")
        return False

    from browser_bot.refresh_token import refresh_auth

    primary_domain = get_domain_from_url(posts[0]["url"]) if posts else ""
    # Refresh token if refresh_url is configured for this domain
    if primary_domain:
        result, _ = refresh_auth(primary_domain, None)
        if result:
            console.print("[dim]Refreshed auth tokens.[/]")

    metrics = Metrics()

    async with async_playwright() as p:
        pool_fetcher, cluster_fetcher, human_fetcher, pool_context, cluster_browser, cluster_contexts = await _setup_fetchers(p, primary_domain, post_count=len(posts))

        console.print(f"\n[bold]POST[/] {len(posts)} request(s) from posts/posts.json...\n")
        results: list[PostResult | None] = []
        for entry in posts:
            r = await post_url(
                entry["url"],
                data=entry.get("data"),
                json_data=entry.get("json"),
                headers=entry.get("headers"),
                pool_fetcher=pool_fetcher,
                cluster_fetcher=cluster_fetcher,
                human_fetcher=human_fetcher,
                metrics=metrics,
            )
            results.append(r)

        # Cleanup
        await _close_fetcher_resources(pool_context, cluster_browser, cluster_contexts)

    # Metrics table
    summary = metrics.summary()
    if summary != "No metrics":
        table = Table(title="POST Metrics", box=box.ROUNDED, show_header=True)
        table.add_column("Tier", style="cyan")
        table.add_column("Total", justify="right", style="green")
        table.add_column("Avg", justify="right", style="green")
        table.add_column("Count", justify="right", style="dim")
        for line in summary.splitlines():
            parts = line.split(":")
            if len(parts) >= 2:
                tier = parts[0].strip()
                rest = parts[1].strip()
                vals = rest.replace("s", "").split()
                total = vals[1] if len(vals) > 1 else "-"
                avg = vals[3] if len(vals) > 3 else "-"
                count = vals[5] if len(vals) > 5 else "-"
                table.add_row(tier, f"{total}s", f"{avg}s", count)
        console.print()
        console.print(table)
    ok = sum(1 for r in results if r and 200 <= r.status < 300)
    console.print(f"\n[bold green]Finished:[/] {ok}/{len(results)} successful")
    return bool(results)


if __name__ == "__main__":
    print("Browser Bot is used by Genbounty LLM Hunter and the test runner.")
    print("Launch the UI with: python start.py")
    sys.exit(0)
