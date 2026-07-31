"""Login flow: open browser, user logs in, save full auth state."""

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

from browser_bot.auth_state import resolve_auth_read_path, save_auth_config
from browser_bot.browser.launcher import (
    close_login_chrome_cdp,
    connect_login_over_cdp,
    format_google_cdp_launch_command,
    launch_login_chrome_cdp,
    launch_persistent_context_for_login,
    wait_for_cdp_endpoint,
)
from browser_bot.config import (
    LOCALSTORAGE_MAX_VALUE_LEN,
    LOGIN_CDP_PORT,
    LOGIN_CDP_URL,
    LOGIN_USE_PERSISTENT_CONTEXT,
    use_cdp_browser,
)
from browser_bot.sites import get_domain_from_url, ensure_site_dir, get_login_profile_path

LOGIN_CDP_CMD_MARKER = "[genbounty_login_cdp_cmd]"


def is_google_login_target(domain: str, login_url: str) -> bool:
    text = f"{domain} {login_url}".lower()
    return "google.com" in text or "googleapis.com" in text


def google_login_cdp_command(
    domain: str,
    login_url: str,
    component: str | None = None,
) -> str:
    """Shell command to start Chrome for Google OAuth (not Playwright-launched)."""
    profile_path = get_login_profile_path(domain, component)
    port = int(LOGIN_CDP_PORT) if isinstance(LOGIN_CDP_PORT, int) and LOGIN_CDP_PORT > 0 else 9222
    return format_google_cdp_launch_command(profile_path, login_url, port=port)


def login_cdp_output_lines(
    domain: str,
    login_url: str,
    component: str | None = None,
    *,
    auto_launch: bool = False,
    google_blocked: bool = False,
) -> list[str]:
    """Lines for Experiment Output / job log when CDP login is used."""
    cmd = google_login_cdp_command(domain, login_url, component)
    cdp_url = _resolve_cdp_url()
    lines: list[str] = []
    if google_blocked:
        lines.append("[login] Google blocks sign-in in Playwright-launched browsers.")
    elif auto_launch:
        lines.append("[login] Using Chrome CDP login (auto-launch).")
    else:
        lines.append("[login] Using Chrome CDP login.")
    lines.append(f"{LOGIN_CDP_CMD_MARKER} {cmd}")
    if auto_launch:
        lines.extend([
            "[login] Launching Chrome automatically…",
            f"[login] Waiting for Chrome CDP at {cdp_url} (up to 3 min)...",
            "[login] Complete sign-in in the Chrome window, then click Press Enter (done).",
        ])
    else:
        lines.extend([
            "[login] Run the command above in a separate terminal, complete sign-in in that Chrome window.",
            f"[login] Waiting for Chrome CDP at {cdp_url} (up to 3 min)...",
            "[login] When finished, click Press Enter (done) in the UI or press Enter in this terminal.",
        ])
    return lines


def google_login_cdp_output_lines(
    domain: str,
    login_url: str,
    component: str | None = None,
    *,
    auto_launch: bool = False,
) -> list[str]:
    """Backward-compatible wrapper for Google CDP login job output."""
    return login_cdp_output_lines(
        domain,
        login_url,
        component,
        auto_launch=auto_launch,
        google_blocked=True,
    )


def _filter_storage_items(items: list, max_len: int) -> list:
    """Exclude storage items with value length > max_len."""
    return [i for i in items if len(str(i.get("value", ""))) <= max_len]


async def _wait_for_enter():
    """Non-blocking wait for Enter key."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, input)


def _build_config_from_page(storage: dict, session_items: list, page_origin: str, max_len: int) -> dict:
    """Build auth config from storage_state and sessionStorage."""
    config = {
        "cookies": storage["cookies"],
        "origins": [
            {
                "origin": o["origin"],
                "localStorage": _filter_storage_items(o.get("localStorage", []), max_len),
            }
            for o in storage["origins"]
        ],
        "headers": {},
    }
    session_items = _filter_storage_items(session_items, max_len)
    origin_found = False
    for origin in config["origins"]:
        if origin.get("origin") == page_origin:
            origin["sessionStorage"] = session_items
            origin_found = True
            break
    if not origin_found:
        config["origins"].append({
            "origin": page_origin,
            "localStorage": [],
            "sessionStorage": session_items,
        })
    return config


def _is_google_login_target(domain: str, login_url: str) -> bool:
    return is_google_login_target(domain, login_url)


def _resolve_cdp_url() -> str:
    explicit = str(LOGIN_CDP_URL or os.getenv("LOGIN_CDP_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    port = int(LOGIN_CDP_PORT) if isinstance(LOGIN_CDP_PORT, int) and LOGIN_CDP_PORT > 0 else 9222
    return f"http://127.0.0.1:{port}"


async def _capture_via_cdp(
    playwright,
    *,
    login_url: str,
    domain: str,
    component: str | None,
    auto_launch: bool = False,
    google_blocked: bool = False,
) -> dict | None:
    """CDP login: attach to user-started or auto-launched Chrome."""
    cdp_url = _resolve_cdp_url()
    profile_path = get_login_profile_path(domain, component)
    profile_path.mkdir(parents=True, exist_ok=True)
    port = int(LOGIN_CDP_PORT) if isinstance(LOGIN_CDP_PORT, int) and LOGIN_CDP_PORT > 0 else 9222
    chrome_proc = None

    for line in login_cdp_output_lines(
        domain,
        login_url,
        component,
        auto_launch=auto_launch,
        google_blocked=google_blocked,
    ):
        print(line.replace(LOGIN_CDP_CMD_MARKER, " ").strip())

    if auto_launch:
        try:
            chrome_proc = launch_login_chrome_cdp(profile_path, login_url, port=port)
            print(f"[login] Started Chrome (CDP {cdp_url}).")
        except OSError as exc:
            print(f"[!] Failed to launch Chrome: {exc}")
            return None

    if not await wait_for_cdp_endpoint(cdp_url, timeout_s=180):
        if auto_launch:
            print("[!] Chrome CDP not reachable after auto-launch. Check that Chrome is installed.")
        else:
            print("[!] Chrome CDP not reachable. Run the command above, log in, then retry Add Login.")
        return None

    browser, context, page = await connect_login_over_cdp(playwright, cdp_url, login_url)
    from browser_bot.discovery_ui_bridge import apply_full_cdp_window_layout

    await apply_full_cdp_window_layout(page)
    print(f"\n  Attached to Chrome. Finish login at {login_url}")
    print("  Press Enter when you're done logging in...")
    await _wait_for_enter()

    storage = await context.storage_state()
    session_items = await page.evaluate(
        """() => Object.entries(sessionStorage).map(([name, value]) => ({name, value}))"""
    )
    parsed = urlparse(page.url)
    page_origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else ""
    config = _build_config_from_page(storage, session_items, page_origin, LOCALSTORAGE_MAX_VALUE_LEN)
    if auto_launch:
        await close_login_chrome_cdp(browser, chrome_proc)
        print("[login] Closed auto-launched Chrome.")
    # Manual CDP: do not browser.close() - that would quit the user's Chrome window.
    return config


async def capture_login(
    login_url: str,
    *,
    site: str | None = None,
    component: str | None = None,
    force_persistent: bool = False,
    use_cdp: bool = False,
) -> str | None:
    """
    Open headful browser, navigate to login_url, wait for user to log in,
    then save full auth state: cookies, localStorage, sessionStorage, headers.
    Auth is stored per component when *component* is set, else site-level (legacy).
    Returns site id on success.
    """
    if not isinstance(login_url, str):
        login_url = str(login_url or "").strip()
    else:
        login_url = login_url.strip()
    if not login_url:
        return None
    domain = (site or "").strip() or get_domain_from_url(login_url)
    if not domain:
        return None
    component = (component or "").strip() or None

    if component:
        from browser_bot.sites import ensure_component_dir

        ensure_component_dir(domain, component)
    else:
        ensure_site_dir(domain)

    auth_path = resolve_auth_read_path(domain, component)
    storage_path = str(auth_path) if auth_path else None

    google_target = _is_google_login_target(domain, login_url)
    use_cdp_login = use_cdp_browser(use_cdp) or google_target

    async with async_playwright() as p:
        if use_cdp_login:
            config = await _capture_via_cdp(
                p,
                login_url=login_url,
                domain=domain,
                component=component,
                auto_launch=use_cdp_browser(use_cdp),
                google_blocked=google_target and not use_cdp_browser(use_cdp),
            )
            if config is None:
                return None
        else:
            use_persistent = LOGIN_USE_PERSISTENT_CONTEXT or force_persistent
            if use_persistent:
                profile_path = get_login_profile_path(domain, component)
                profile_path.mkdir(parents=True, exist_ok=True)
                browser, context = await launch_persistent_context_for_login(
                    p, str(profile_path), site=domain, component=component
                )
                page = await context.new_page()
                await page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
                print(f"\n  Log in at {login_url}")
                print("  Press Enter when you're done logging in...")
                await _wait_for_enter()
                storage = await context.storage_state()
                session_items = await page.evaluate(
                    """() => Object.entries(sessionStorage).map(([name, value]) => ({name, value}))"""
                )
                parsed = urlparse(page.url)
                page_origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else ""
                config = _build_config_from_page(storage, session_items, page_origin, LOCALSTORAGE_MAX_VALUE_LEN)
                await context.close()
                if browser:
                    await browser.close()
            else:
                from main import run_with_page_from_fetchers

                async def _do_login(page):
                    await page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
                    print(f"\n  Log in at {login_url}")
                    if storage_path:
                        print("  (Loaded existing auth. Re-login if needed, then press Enter to save.)")
                    print("  Press Enter when you're done logging in...")
                    await _wait_for_enter()
                    storage = await page.context.storage_state()
                    session_items = await page.evaluate(
                        """() => Object.entries(sessionStorage).map(([name, value]) => ({name, value}))"""
                    )
                    parsed = urlparse(page.url)
                    page_origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else ""
                    return _build_config_from_page(storage, session_items, page_origin, LOCALSTORAGE_MAX_VALUE_LEN)

                config = await run_with_page_from_fetchers(
                    p, domain, _do_login, storage_path=storage_path, interactive=True, component=component
                )
                if config is None:
                    return None

    save_auth_config(domain, config, component=component)

    from browser_bot.auth_state import get_auth_path
    from browser_bot.sites import STORAGE_STATE_FILE

    legacy = get_auth_path(domain, component) / STORAGE_STATE_FILE
    if legacy.exists():
        legacy.unlink()

    return domain
