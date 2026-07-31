"""Browser and context launchers.

Unified flow: login, refresh, fetch, and POST all use launch_context_for_request()
when FETCH_METHOD=human, ensuring consistent stealth, fingerprint, and behavior.
"""

import json
import os
import shutil
import signal
import subprocess
from pathlib import Path
from typing import Any

from browser_bot.browser.routes import block_resources, get_blocked_types
from browser_bot.config import (
    CHROME_ARGS,
    CHROMIUM_EXECUTABLE_PATH,
    CHROME_CHANNEL,
    FETCH_METHOD,
    HEADLESS,
    HUMAN_ALLOW_STYLES,
    HUMAN_CHROME_ARGS,
    HUMAN_USER_AGENT,
    LOCALSTORAGE_MAX_VALUE_LEN,
    LOGIN_CHROME_ARGS,
    get_discovery_context_opts,
    get_human_context_opts,
    get_login_context_opts,
)


def _chromium_executable_path() -> str | None:
    """Return configured Chromium path if it exists, else Playwright bundled browser."""
    path = CHROMIUM_EXECUTABLE_PATH
    if not path or not str(path).strip():
        return None
    resolved = Path(str(path))
    if resolved.is_file():
        return str(resolved)
    return None


def _launch_options(
    human_mode: bool = False,
    headless: bool | None = None,
    *,
    always_on_top: bool = False,
):
    """Return launch options dict for chromium.launch()."""
    args = list(HUMAN_CHROME_ARGS if (human_mode and HUMAN_CHROME_ARGS) else CHROME_ARGS)
    if always_on_top:
        from browser_bot.config import GUIDED_DISCOVERY_ALWAYS_ON_TOP

        if GUIDED_DISCOVERY_ALWAYS_ON_TOP and "--always-on-top" not in args:
            args = [*args, "--always-on-top"]
    opts = {"headless": headless if headless is not None else HEADLESS, "args": args}
    if human_mode and CHROME_CHANNEL:
        opts["channel"] = CHROME_CHANNEL
    else:
        exe = _chromium_executable_path()
        if exe:
            opts["executable_path"] = exe
    return opts


def _load_auth_config(path: Path) -> dict | list | None:
    """Load auth config from auth.json or storage_state.json."""
    if not path or not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def _normalize_auth_config(raw: dict | list) -> dict:
    """Convert auth config to standard format. Handles raw cookie list from browser extensions."""
    if isinstance(raw, dict) and "cookies" in raw:
        return raw
    if isinstance(raw, list):
        # Raw cookie export from extension (Cookie-Editor, EditThisCookie, etc.)
        cookies = []
        for c in raw:
            if not isinstance(c, dict) or "name" not in c or "value" not in c:
                continue
            pw = {
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain", ""),
                "path": c.get("path", "/"),
                "httpOnly": c.get("httpOnly", False),
                "secure": c.get("secure", False),
            }
            exp = c.get("expirationDate") or c.get("expires")
            if exp is not None and not c.get("session"):
                pw["expires"] = int(exp) if isinstance(exp, (int, float)) else exp
            same = c.get("sameSite", "Lax")
            if same in ("Strict", "Lax", "None"):
                pw["sameSite"] = same
            else:
                pw["sameSite"] = "Lax"
            cookies.append(pw)
        return {"cookies": cookies, "origins": [], "headers": {}}
    return {"cookies": [], "origins": [], "headers": {}}


def _filter_storage_items(items: list, max_len: int) -> list:
    """Exclude storage items (localStorage/sessionStorage) with value length > max_len."""
    return [i for i in items if len(str(i.get("value", ""))) <= max_len]


def _storage_state_from_auth(config: dict) -> dict:
    """Extract Playwright storage_state (cookies + localStorage) from auth config.
    Excludes localStorage items with value length > LOCALSTORAGE_MAX_VALUE_LEN.
    """
    max_len = LOCALSTORAGE_MAX_VALUE_LEN
    return {
        "cookies": config.get("cookies", []),
        "origins": [
            {
                "origin": o["origin"],
                "localStorage": _filter_storage_items(o.get("localStorage", []), max_len),
            }
            for o in config.get("origins", [])
        ],
    }


def _load_normalized_auth_config(path: Path) -> dict | None:
    """Load and normalize auth.json or legacy storage_state.json."""
    raw = _load_auth_config(path)
    if not raw:
        return None
    if path.name == "auth.json":
        return _normalize_auth_config(raw)
    if isinstance(raw, dict) and ("cookies" in raw or "origins" in raw):
        return raw
    return _normalize_auth_config(raw)


def load_auth_config_for_site(site: str, component: str | None = None) -> dict | None:
    """Load normalized browser-session auth for a site/component, or None if missing/empty.

    Skips sibling/own API-key-only auth — those are not browser sessions.
    """
    from browser_bot.sites import get_browser_storage_state_path

    path = get_browser_storage_state_path(site, component)
    if not path or not path.exists():
        return None
    config = _load_normalized_auth_config(path)
    if not config:
        return None
    if config.get("auth_mode") == "none" and not _auth_config_has_session_data(config):
        return None
    return config


def _auth_config_has_session_data(config: dict) -> bool:
    if config.get("cookies"):
        return True
    if config.get("headers"):
        return True
    for origin in config.get("origins", []):
        if origin.get("localStorage") or origin.get("sessionStorage"):
            return True
    return False


async def apply_auth_config_to_context(
    context,
    config: dict,
    *,
    include_cookies: bool = True,
    include_session_script: bool = True,
    include_headers: bool = True,
) -> None:
    """Apply auth.json session data to a browser context (ephemeral or persistent)."""
    if include_cookies:
        cookies = config.get("cookies") or []
        if cookies:
            await context.add_cookies(cookies)

    if include_session_script:
        session_by_origin: dict[str, list] = {}
        for origin in config.get("origins", []):
            origin_url = origin.get("origin") or ""
            if origin.get("sessionStorage") and origin_url:
                session_by_origin[origin_url] = _filter_storage_items(
                    origin["sessionStorage"], LOCALSTORAGE_MAX_VALUE_LEN
                )
        if session_by_origin:
            script = f"""
                (function() {{
                    const data = {json.dumps(session_by_origin)};
                    const origin = location.origin;
                    if (data[origin]) {{
                        data[origin].forEach(item => sessionStorage.setItem(item.name, item.value));
                    }}
                }})();
            """
            await context.add_init_script(script)

    if include_headers:
        headers = {
            k: v for k, v in (config.get("headers") or {}).items() if k.lower() != "authorization"
        }
        if headers:
            await context.set_extra_http_headers(headers)


async def seed_auth_local_storage(context, config: dict, page=None) -> None:
    """Visit each auth origin and restore localStorage (required for some SPAs e.g. Visme)."""
    items_by_origin = {
        o["origin"]: _filter_storage_items(o.get("localStorage", []), LOCALSTORAGE_MAX_VALUE_LEN)
        for o in config.get("origins", [])
        if o.get("origin") and o.get("localStorage")
    }
    items_by_origin = {k: v for k, v in items_by_origin.items() if v}
    if not items_by_origin:
        return

    owns_page = page is None
    if owns_page:
        page = await context.new_page()

    try:
        for origin, items in items_by_origin.items():
            loaded = False
            for url in (origin, origin.rstrip("/") + "/"):
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    loaded = True
                    break
                except Exception:
                    continue
            if not loaded:
                continue
            try:
                await page.evaluate(
                    """(entries) => {
                        entries.forEach(({ name, value }) => localStorage.setItem(name, value));
                    }""",
                    items,
                )
            except Exception:
                pass
    finally:
        if owns_page and page is not None:
            await page.close()


def _auth_config_has_browser_session_data(config: dict) -> bool:
    """True when auth carries cookies / origin storage (not API-key headers alone)."""
    if config.get("cookies"):
        return True
    for origin in config.get("origins") or []:
        if not isinstance(origin, dict):
            continue
        if origin.get("localStorage") or origin.get("sessionStorage"):
            return True
    return False


async def apply_site_auth_to_context(
    context,
    site: str,
    *,
    component: str | None = None,
    page=None,
    replace_cookies: bool = False,
) -> bool:
    """Merge auth.json into any context. Returns True when auth was applied."""
    config = load_auth_config_for_site(site, component)
    if not config:
        return False
    mode = str(config.get("auth_mode") or "").strip().lower()
    has_browser_session = _auth_config_has_browser_session_data(config)
    # Sibling API-key auth (headers only) must never wipe a persistent login profile.
    if mode == "api_key" and not has_browser_session:
        return False
    if replace_cookies and has_browser_session and config.get("cookies"):
        try:
            await context.clear_cookies()
        except Exception:
            pass
    await apply_auth_config_to_context(context, config)
    await seed_auth_local_storage(context, config, page=page)
    return True


def auth_config_mtime(site: str, component: str | None = None) -> float:
    """mtime of browser-session auth.json for CDP session freshness checks."""
    from browser_bot.sites import get_browser_storage_state_path

    auth_path = get_browser_storage_state_path(site, component)
    if not auth_path or not auth_path.exists():
        return 0.0
    try:
        return auth_path.stat().st_mtime
    except OSError:
        return 0.0


async def launch_browser(
    playwright,
    human_mode: bool = False,
    headless: bool | None = None,
    *,
    always_on_top: bool = False,
):
    """Launch ephemeral browser (no persistent profile).
    human_mode: use HUMAN_CHROME_ARGS (fewer automation flags) for stealth.
    headless: override config (e.g. False for login).
    always_on_top: keep window above others (guided discovery).
    """
    browser = await playwright.chromium.launch(
        **_launch_options(
            human_mode=human_mode,
            headless=headless,
            always_on_top=always_on_top,
        )
    )
    return browser


def _is_human_mode() -> bool:
    """True when FETCH_METHOD selects human tier."""
    return FETCH_METHOD.lower() == "human"


async def apply_human_stealth_async(context) -> None:
    """Apply playwright-stealth to a browser context (same options as human tier)."""
    import platform as _platform

    from playwright_stealth import Stealth

    opts = get_human_context_opts()
    locale = opts["locale"]
    base = locale.split("-")[0] if "-" in locale else locale
    _plat = _platform.system()
    platform_override = "Win32" if _plat == "Windows" else "MacIntel" if _plat == "Darwin" else "Linux x86_64"
    stealth_opts = {
        "navigator_languages_override": (locale, base),
        "navigator_platform_override": platform_override,
    }
    if HUMAN_USER_AGENT:
        stealth_opts["navigator_user_agent_override"] = HUMAN_USER_AGENT
    stealth = Stealth(**stealth_opts)
    await stealth.apply_stealth_async(context)


async def new_pool_cluster_browser_context(
    browser,
    storage_state_path: str | None = None,
    *,
    full_human_tier_bundle: bool = False,
    allow_styles: bool = False,
    use_stealth: bool = False,
    use_human_context: bool = False,
):
    """
    Create a context for pool/cluster tiers.
    When full_human_tier_bundle=True: same as full human tier (styles, context opts, stealth).
    Otherwise combine granular flags (for A/B testing).
    """
    if full_human_tier_bundle:
        from browser_bot.config import get_pool_cluster_browser_enhancements

        _, bundle_allow_styles, _, _ = get_pool_cluster_browser_enhancements()
        context = await launch_context_with_routes(
            browser,
            storage_state_path=storage_state_path,
            allow_styles=bundle_allow_styles,
            **get_human_context_opts(),
        )
        await apply_human_stealth_async(context)
        return context

    context_opts = get_human_context_opts() if use_human_context else {}
    styles_for_route = bool(allow_styles)
    context = await launch_context_with_routes(
        browser,
        storage_state_path=storage_state_path,
        allow_styles=styles_for_route,
        **context_opts,
    )
    if use_stealth:
        await apply_human_stealth_async(context)
    return context


def _clear_stale_profile_locks(user_data_dir: str) -> None:
    """Remove Chromium Singleton* locks that block re-launch when a prior session
    didn't shut down cleanly. Safe no-op when files don't exist."""
    p = Path(user_data_dir)
    if not p.exists():
        return
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        target = p / name
        try:
            if target.is_symlink() or target.exists():
                target.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass


async def launch_persistent_context(
    playwright,
    user_data_dir: str,
    *,
    headless: bool = False,
    site: str | None = None,
    component: str | None = None,
    record_har_path: str | None = None,
    always_on_top: bool = False,
) -> tuple[None, "BrowserContext"]:
    """
    Launch Chrome with persistent profile for login. Google trusts real profiles more.
    Returns (None, context). Caller closes context only (no separate browser).

    When site is provided, auth.json is merged into the profile (cookies, sessionStorage,
    headers, and localStorage seeded via origin visits).
    """
    from playwright.async_api import BrowserContext

    args = list(HUMAN_CHROME_ARGS or CHROME_ARGS)
    if "--disable-blink-features=AutomationControlled" not in args:
        args.insert(0, "--disable-blink-features=AutomationControlled")
    if always_on_top:
        from browser_bot.config import GUIDED_DISCOVERY_ALWAYS_ON_TOP

        if GUIDED_DISCOVERY_ALWAYS_ON_TOP and "--always-on-top" not in args:
            args = [*args, "--always-on-top"]

    opts = {
        **get_discovery_context_opts(),
        "headless": headless,
        "args": args,
        "accept_downloads": True,
    }
    if record_har_path:
        opts["record_har_path"] = record_har_path
    if CHROME_CHANNEL:
        opts["channel"] = CHROME_CHANNEL
    else:
        exe = _chromium_executable_path()
        if exe:
            opts["executable_path"] = exe

    _clear_stale_profile_locks(user_data_dir)

    try:
        context = await playwright.chromium.launch_persistent_context(user_data_dir, **opts)
    except Exception as exc:
        msg = str(exc).lower()
        if "closed" in msg or "target" in msg or "browser" in msg:
            _clear_stale_profile_locks(user_data_dir)
            context = await playwright.chromium.launch_persistent_context(user_data_dir, **opts)
        else:
            raise

    import platform as _platform
    from playwright_stealth import Stealth
    from browser_bot.config import get_human_context_opts

    opts_human = get_human_context_opts()
    locale = opts_human["locale"]
    base = locale.split("-")[0] if "-" in locale else locale
    _plat = _platform.system()
    platform_override = "Win32" if _plat == "Windows" else "MacIntel" if _plat == "Darwin" else "Linux x86_64"
    stealth_opts = {
        "navigator_languages_override": (locale, base),
        "navigator_platform_override": platform_override,
    }
    if HUMAN_USER_AGENT:
        stealth_opts["navigator_user_agent_override"] = HUMAN_USER_AGENT
    stealth = Stealth(**stealth_opts)
    await stealth.apply_stealth_async(context)

    if site:
        await apply_site_auth_to_context(context, site, component=component)

    async def route_handler(route):
        await block_resources(route, get_blocked_types(allow_styles=HUMAN_ALLOW_STYLES))

    await context.route("**/*", route_handler)

    return None, context


async def launch_persistent_context_for_login(
    playwright,
    user_data_dir: str,
    *,
    site: str | None = None,
    component: str | None = None,
) -> tuple[None, "BrowserContext"]:
    """Minimal persistent Chrome for non-Google login (no stealth, blocking, or fake UA)."""
    from playwright.async_api import BrowserContext

    args = list(LOGIN_CHROME_ARGS or ["--disable-blink-features=AutomationControlled"])
    opts = {
        **get_login_context_opts(),
        "headless": False,
        "args": args,
        "accept_downloads": True,
        "ignore_default_args": ["--enable-automation"],
    }
    if CHROME_CHANNEL:
        opts["channel"] = CHROME_CHANNEL
    else:
        exe = _chromium_executable_path()
        if exe:
            opts["executable_path"] = exe

    _clear_stale_profile_locks(user_data_dir)

    try:
        context = await playwright.chromium.launch_persistent_context(user_data_dir, **opts)
    except Exception as exc:
        msg = str(exc).lower()
        if "closed" in msg or "target" in msg or "browser" in msg:
            _clear_stale_profile_locks(user_data_dir)
            context = await playwright.chromium.launch_persistent_context(user_data_dir, **opts)
        else:
            raise

    return None, context


def _resolve_login_cdp_chrome_binary() -> str:
    explicit = str(os.getenv("LOGIN_CDP_CHROME") or "").strip()
    if explicit:
        return explicit
    for name in ("google-chrome-stable", "google-chrome", "chromium-browser", "chromium"):
        found = shutil.which(name)
        if found:
            return found
    return "google-chrome-stable"


def resolve_cdp_url() -> str:
    from browser_bot.config import LOGIN_CDP_PORT, LOGIN_CDP_URL

    explicit = str(LOGIN_CDP_URL or os.getenv("LOGIN_CDP_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    port = int(LOGIN_CDP_PORT) if isinstance(LOGIN_CDP_PORT, int) and LOGIN_CDP_PORT > 0 else 9222
    return f"http://127.0.0.1:{port}"


DISCOVERY_CDP_CMD_MARKER = "[genbounty_discovery_cdp_cmd]"

# Match Playwright headed human tier (HUMAN_CHROME_ARGS) for CDP Chrome launches.
CDP_DEFAULT_CHROME_ARGS = [
    "--start-maximized",
]


def google_cdp_launch_argv(
    profile_path: str | Path,
    login_url: str,
    *,
    port: int = 9222,
    chrome_binary: str | None = None,
    extra_args: list[str] | None = None,
) -> list[str]:
    """Argv to start real Chrome for CDP login (not Playwright-launched)."""
    profile = str(profile_path)
    binary = chrome_binary or _resolve_login_cdp_chrome_binary()
    argv = [
        binary,
        f"--user-data-dir={profile}",
        f"--remote-debugging-port={port}",
    ]
    merged_extra = [*CDP_DEFAULT_CHROME_ARGS, *(extra_args or [])]
    for arg in merged_extra:
        if arg and arg not in argv:
            argv.append(arg)
    argv.append(login_url)
    return argv


def format_google_cdp_launch_command(
    profile_path: str | Path,
    login_url: str,
    *,
    port: int = 9222,
    extra_args: list[str] | None = None,
) -> str:
    """Shell command to start real Chrome for Google sign-in (not Playwright-launched)."""
    argv = google_cdp_launch_argv(
        profile_path, login_url, port=port, extra_args=extra_args
    )
    profile = argv[1].split("=", 1)[1]
    middle = " ".join(f'"{arg}"' if " " in arg else arg for arg in argv[3:-1])
    url = argv[-1]
    base = f'{argv[0]} --user-data-dir="{profile}" --remote-debugging-port={port}'
    if middle:
        return f'{base} {middle} "{url}"'
    return f'{base} "{url}"'


def discovery_cdp_output_lines(
    profile_path: str | Path,
    start_url: str,
    *,
    auto_launch: bool = False,
    port: int = 9222,
) -> list[str]:
    """Experiment Output lines when guided discovery uses CDP Chrome."""
    cdp_url = resolve_cdp_url()
    cmd = format_google_cdp_launch_command(profile_path, start_url, port=port)
    lines: list[str] = []
    if auto_launch:
        lines.append("[discovery] Using Chrome CDP browser (auto-launch) for guided discovery.")
    else:
        lines.append("[discovery] Using Chrome CDP browser for guided discovery.")
    lines.append(f"{DISCOVERY_CDP_CMD_MARKER} {cmd}")
    if auto_launch:
        lines.extend([
            "[discovery] Launching Chrome automatically…",
            f"[discovery] Waiting for Chrome CDP at {cdp_url} (up to 3 min)…",
        ])
    else:
        lines.extend([
            "[discovery] Run the command above in a separate terminal, then continue in Experiment Output.",
            f"[discovery] Waiting for Chrome CDP at {cdp_url} (up to 3 min)…",
        ])
    return lines


def launch_login_chrome_cdp(
    profile_path: str | Path,
    login_url: str,
    *,
    port: int = 9222,
    chrome_binary: str | None = None,
    extra_args: list[str] | None = None,
) -> subprocess.Popen:
    """Start Chrome for CDP login in a detached process."""
    argv = google_cdp_launch_argv(
        profile_path,
        login_url,
        port=port,
        chrome_binary=chrome_binary,
        extra_args=extra_args,
    )
    return subprocess.Popen(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


async def wait_for_cdp_endpoint(cdp_url: str, *, timeout_s: float = 180) -> bool:
    """Poll CDP /json/version until Chrome is listening."""
    import asyncio
    import time
    import urllib.error
    import urllib.request

    base = str(cdp_url or "").strip().rstrip("/")
    if not base:
        return False
    version_url = f"{base}/json/version"
    deadline = time.monotonic() + max(5.0, timeout_s)

    async def _probe() -> bool:
        try:
            def _fetch():
                with urllib.request.urlopen(version_url, timeout=2) as resp:
                    return resp.status == 200

            return await asyncio.get_event_loop().run_in_executor(None, _fetch)
        except (urllib.error.URLError, OSError, TimeoutError, ValueError):
            return False

    while time.monotonic() < deadline:
        if await _probe():
            return True
        await asyncio.sleep(1.0)
    return False


async def close_existing_cdp_chrome(playwright, cdp_url: str) -> bool:
    """Close Chrome already listening on the CDP port (stale session from a prior run)."""
    import asyncio

    if not await wait_for_cdp_endpoint(cdp_url, timeout_s=1.5):
        return False
    try:
        browser = await playwright.chromium.connect_over_cdp(cdp_url)
        await browser.close()
    except Exception:
        return False
    for _ in range(24):
        if not await wait_for_cdp_endpoint(cdp_url, timeout_s=0.5):
            return True
        await asyncio.sleep(0.25)
    return False


async def connect_login_over_cdp(
    playwright,
    cdp_url: str,
    login_url: str,
) -> tuple[Any, Any, Any]:
    """Attach Playwright to a user-started Chrome. Does not launch automation flags."""
    browser = await playwright.chromium.connect_over_cdp(cdp_url)
    context = browser.contexts[0] if browser.contexts else await browser.new_context()
    page = context.pages[0] if context.pages else await context.new_page()
    if login_url and (not page.url or page.url in ("about:blank", "chrome://newtab/")):
        await page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
    return browser, context, page


def mark_cdp_browser(browser: Any, chrome_proc: subprocess.Popen | None) -> None:
    """Tag a CDP-attached browser for cleanup via close_login_chrome_cdp."""
    browser._genbounty_cdp_proc = chrome_proc  # noqa: SLF001
    browser._genbounty_cdp_auto = chrome_proc is not None  # noqa: SLF001


def attach_cdp_session_page(browser: Any, page: Any) -> None:
    """Remember the primary CDP tab so callers reuse it instead of opening another."""
    browser._genbounty_cdp_page = page  # noqa: SLF001


def get_cdp_session_page(browser: Any) -> Any | None:
    return getattr(browser, "_genbounty_cdp_page", None)


def get_cdp_chrome_proc(browser: Any) -> subprocess.Popen | None:
    return getattr(browser, "_genbounty_cdp_proc", None)


def should_use_cdp_for_headed_request(
    *,
    headless: bool | None,
    headed: bool | None = None,
    site: str | None = None,
    component: str | None = None,
) -> bool:
    """True for headed runs when CDP is on, a login profile exists, or Cloudflare-headed."""
    from browser_bot.config import use_cdp_browser

    if headless is True:
        return False
    is_headed = headless is False or headed is True
    if not is_headed:
        return False
    if use_cdp_browser():
        return True
    if site:
        try:
            from browser_bot.sites import has_usable_login_profile

            if has_usable_login_profile(site, component):
                return True
        except Exception:
            pass
    if site and component:
        try:
            from browser_bot.sites import load_component_config

            sub = (load_component_config(site, component) or {}).get("submission") or {}
            if isinstance(sub, dict) and sub.get("cloudflare_headed"):
                return True
        except Exception:
            pass
    return False


async def open_cdp_browser_session(
    playwright,
    *,
    site: str,
    start_url: str,
    component: str | None = None,
    auto_launch: bool = True,
    extra_args: list[str] | None = None,
    apply_auth: bool = True,
    log_tag: str = "cdp",
    window_width_ratio: float | None = 1.0,
    window_always_on_top: bool = False,
) -> tuple[Any, Any, Any, subprocess.Popen | None]:
    """
    Launch or attach to real Chrome via CDP (bot-detection friendly).
    Returns (browser, context, page, chrome_proc). Caller should close via close_login_chrome_cdp.

    window_width_ratio: after attach, size the window (1.0 = full work area; 0.6 = guided discovery).
    Pass None to skip layout (caller applies it later).
    """
    from browser_bot.config import LOGIN_CDP_PORT
    from browser_bot.sites import resolve_login_profile_path

    profile_path = resolve_login_profile_path(site, component)
    profile_path.mkdir(parents=True, exist_ok=True)
    port = int(LOGIN_CDP_PORT) if isinstance(LOGIN_CDP_PORT, int) and LOGIN_CDP_PORT > 0 else 9222
    cdp_url = resolve_cdp_url()
    chrome_proc: subprocess.Popen | None = None
    tag = str(log_tag or "cdp").strip() or "cdp"
    from browser_bot.sites import normalize_target_access_url

    launch_url = normalize_target_access_url(str(start_url or site).strip()) or str(
        start_url or site
    ).strip()
    if launch_url and not launch_url.startswith(("http://", "https://")):
        launch_url = f"https://{launch_url.lstrip('/')}"
    chrome_start_url = "about:blank" if apply_auth else (launch_url or "about:blank")

    if auto_launch:
        if await close_existing_cdp_chrome(playwright, cdp_url):
            print(f"[{tag}] Closed stale Chrome on CDP port {port}.", flush=True)
        _clear_stale_profile_locks(str(profile_path))
        try:
            chrome_proc = launch_login_chrome_cdp(
                profile_path,
                chrome_start_url,
                port=port,
                extra_args=extra_args or None,
            )
            print(f"[{tag}] Started Chrome (CDP {cdp_url}, profile={profile_path}).", flush=True)
        except OSError as exc:
            raise RuntimeError(f"Failed to launch Chrome: {exc}") from exc

    if not await wait_for_cdp_endpoint(cdp_url, timeout_s=180):
        if chrome_proc is not None:
            await close_login_chrome_cdp(None, chrome_proc)
        raise RuntimeError(
            "Chrome CDP not reachable. "
            "Ensure Chrome is installed and port 9222 is free (close other CDP Chrome windows)."
        )

    browser, context, page = await connect_login_over_cdp(
        playwright,
        cdp_url,
        "" if apply_auth else chrome_start_url,
    )
    if apply_auth:
        await apply_site_auth_to_context(
            context,
            site,
            component=component,
            page=page,
            replace_cookies=True,
        )
        if launch_url and launch_url not in ("about:blank",):
            try:
                current = (page.url or "").split("#", 1)[0].rstrip("/")
                target = launch_url.split("#", 1)[0].rstrip("/")
                if current != target:
                    await page.goto(launch_url, wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass
    if window_width_ratio is not None:
        from browser_bot.discovery_ui_bridge import apply_cdp_window_layout

        await apply_cdp_window_layout(
            page,
            width_ratio=window_width_ratio,
            always_on_top=window_always_on_top,
        )
    mark_cdp_browser(browser, chrome_proc)
    attach_cdp_session_page(browser, page)
    print(f"  [{tag}] Attached to Chrome.", flush=True)
    return browser, context, page, chrome_proc


async def open_guided_discovery_cdp(
    playwright,
    *,
    site: str,
    start_url: str,
    component: str | None = None,
    auto_launch: bool = True,
) -> tuple[Any, Any, Any, subprocess.Popen | None]:
    """
    Launch or attach to real Chrome for guided discovery (bot-detection friendly).
    Returns (browser, context, page, chrome_proc). Caller should close via close_login_chrome_cdp.
    """
    from browser_bot.config import (
        GUIDED_DISCOVERY_ALWAYS_ON_TOP,
        GUIDED_DISCOVERY_WINDOW_WIDTH_RATIO,
        LOGIN_CDP_PORT,
    )
    from browser_bot.sites import resolve_login_profile_path

    port = int(LOGIN_CDP_PORT) if isinstance(LOGIN_CDP_PORT, int) and LOGIN_CDP_PORT > 0 else 9222
    profile_path = resolve_login_profile_path(site, component)

    extra_args: list[str] = []
    if GUIDED_DISCOVERY_ALWAYS_ON_TOP:
        extra_args.append("--always-on-top")

    for line in discovery_cdp_output_lines(
        profile_path, start_url, auto_launch=auto_launch, port=port
    ):
        print(line.replace(DISCOVERY_CDP_CMD_MARKER, " ").strip(), flush=True)

    return await open_cdp_browser_session(
        playwright,
        site=site,
        start_url=start_url,
        component=component,
        auto_launch=auto_launch,
        extra_args=extra_args or None,
        log_tag="discovery",
        window_width_ratio=GUIDED_DISCOVERY_WINDOW_WIDTH_RATIO,
        window_always_on_top=GUIDED_DISCOVERY_ALWAYS_ON_TOP,
    )


async def close_login_chrome_cdp(
    browser: Any,
    chrome_proc: subprocess.Popen | None = None,
) -> None:
    """Close an auto-launched CDP login Chrome and its process tree."""
    if browser is not None:
        try:
            await browser.close()
        except Exception:
            pass
    if chrome_proc is None:
        return
    try:
        if chrome_proc.poll() is not None:
            return
        pid = chrome_proc.pid
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            chrome_proc.terminate()
        try:
            chrome_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                chrome_proc.kill()
            chrome_proc.wait(timeout=3)
    except Exception:
        pass


async def launch_context_for_request(
    playwright,
    storage_state_path: str | None = None,
    storage_state: dict | None = None,
    *,
    headless: bool | None = None,
    allow_styles: bool | None = None,
    allow_all: bool = False,
    force_human: bool = False,
    discovery_layout: bool = False,
    guided_discovery: bool = False,
    record_har_path: str | None = None,
    record_har_url_filter: str | None = None,
    record_har_content: str = "embed",
    site: str | None = None,
    component: str | None = None,
    start_url: str | None = None,
):
    """
    Unified browser+context for all requests (login, refresh, fetch, POST).
    Uses FETCH_METHOD (or force_human): when human, applies stealth, human context opts, human Chrome args.
    Returns (browser, context). Caller must close both.

    storage_state_path: path to auth.json or storage_state.json (loads from file).
    storage_state: dict storage state (overrides path when provided, e.g. for refresh with excluded cookies).
    headless: override (e.g. False for login).
    allow_styles: when True, don't block stylesheets. Default: HUMAN_ALLOW_STYLES when human.
    allow_all: when True, no resource blocking (full page load, e.g. login).
    force_human: when True, use human flow even if FETCH_METHOD != human (e.g. HumanFetcher fallback).
    discovery_layout: when True with human, use discovery context opts (locale/light scheme) instead of human run opts.
    guided_discovery: when True, launch headed browser with always-on-top (Experiment Output workflow).
    site/component/start_url: when USE_CDP_BROWSER and headed, attach to real Chrome with login profile.
    """
    if (
        site
        and should_use_cdp_for_headed_request(
            headless=headless,
            site=site,
            component=component,
        )
        and not record_har_path
    ):
        from browser_bot.sites import normalize_target_access_url

        launch_url = normalize_target_access_url(str(start_url or site).strip()) or str(
            start_url or site
        ).strip()
        if launch_url and not launch_url.startswith(("http://", "https://")):
            launch_url = f"https://{launch_url.lstrip('/')}"
        browser, context, _page, chrome_proc = await open_cdp_browser_session(
            playwright,
            site=site,
            start_url=launch_url or "about:blank",
            component=component,
            auto_launch=True,
            log_tag="run",
        )
        return browser, context

    human = force_human or _is_human_mode()
    from browser_bot.config import GUIDED_DISCOVERY_ALWAYS_ON_TOP

    always_on_top = bool(guided_discovery and GUIDED_DISCOVERY_ALWAYS_ON_TOP)
    browser = await launch_browser(
        playwright,
        human_mode=human,
        headless=headless,
        always_on_top=always_on_top,
    )

    if human:
        context_opts = get_discovery_context_opts() if discovery_layout else get_human_context_opts()
    else:
        context_opts = {}
    styles = allow_styles if allow_styles is not None else (human and HUMAN_ALLOW_STYLES)

    context = await launch_context_with_routes(
        browser,
        storage_state_path=storage_state_path,
        storage_state=storage_state,
        allow_styles=styles,
        allow_all=allow_all,
        record_har_path=record_har_path,
        record_har_url_filter=record_har_url_filter,
        record_har_content=record_har_content,
        **context_opts,
    )

    if human:
        await apply_human_stealth_async(context)

    return browser, context


async def launch_context_with_routes(
    browser,
    storage_state_path: str | None = None,
    storage_state: dict | None = None,
    allow_styles: bool = False,
    allow_all: bool = False,
    record_har_path: str | None = None,
    record_har_url_filter: str | None = None,
    record_har_content: str = "embed",
    **context_opts,
):
    """
    Create a new context. Optionally load full auth from path or pass storage_state dict.
    Supports auth.json (cookies, localStorage, sessionStorage, headers) and legacy storage_state.json.
    context_opts: merged into new_context() (e.g. locale, timezone_id, geolocation, viewport).
    storage_state: when provided, used directly (overrides path); e.g. for refresh with excluded cookies.
    allow_all: when True, skip resource blocking (full page load).
    """
    opts = dict(context_opts)
    if record_har_path:
        opts["record_har_path"] = record_har_path
        if record_har_url_filter:
            opts["record_har_url_filter"] = record_har_url_filter
        if record_har_content:
            opts["record_har_content"] = record_har_content
    auth_config_for_apply: dict | None = None

    if storage_state is not None:
        opts["storage_state"] = storage_state
    elif storage_state_path:
        path = Path(storage_state_path)
        config = _load_auth_config(path)
        if config:
            if path.name == "auth.json":
                auth_config_for_apply = _normalize_auth_config(config)
                opts["storage_state"] = _storage_state_from_auth(auth_config_for_apply)
            else:
                opts["storage_state"] = str(path)

    context = await browser.new_context(**opts)
    if not allow_all:
        blocked = get_blocked_types(allow_styles=allow_styles)

        async def route_handler(route):
            await block_resources(route, blocked)

        await context.route("**/*", route_handler)

    if auth_config_for_apply:
        await apply_auth_config_to_context(
            context,
            auth_config_for_apply,
            include_cookies=False,
        )

    return context
