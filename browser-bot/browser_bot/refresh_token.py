"""
Token refresh: call refresh_url from component config, update auth.json with new tokens.
Uses Playwright (browser) when direct HTTP is blocked (e.g. Cloudflare).
"""

import json
import time
from typing import Any

from browser_bot.auth_state import load_auth_config, save_auth_config
from browser_bot.sites import load_component_config, load_site_config


def _get_base_url(domain: str, component: str | None = None) -> str:
    """Get base URL (scheme + domain) from config. Defaults to https for unknown domains."""
    from urllib.parse import urlparse

    def _from_config(cfg: dict) -> str | None:
        for key in ("refresh_url", "login_url", "endpoint_url"):
            url = cfg.get(key)
            if url and "://" in url:
                parsed = urlparse(url)
                return f"{parsed.scheme}://{parsed.netloc}"
        return None

    if component:
        result = _from_config(load_component_config(domain, component))
        if result:
            return result
    from browser_bot.sites import list_components

    for comp in list_components(domain):
        result = _from_config(load_component_config(domain, comp))
        if result:
            return result
    return f"https://{domain}"


def _get_refresh_url(domain: str, component: str | None = None) -> str | None:
    """Get refresh_url from component config (merged with site config). Tries component first, then site, then all components."""
    if component:
        config = load_component_config(domain, component)
        url = config.get("refresh_url")
        if url:
            return url
    # Fallback: site config, then any component
    site_cfg = load_site_config(domain)
    if site_cfg.get("refresh_url"):
        return site_cfg["refresh_url"]
    from browser_bot.sites import list_components

    for comp in list_components(domain):
        cfg = load_component_config(domain, comp)
        if cfg.get("refresh_url"):
            return cfg["refresh_url"]
    return None


def _get_refresh_config(domain: str, component: str | None) -> dict:
    """
    Get refresh-related config with defaults. Used for cookie names and Cookie header.
    Returns dict with: refresh_token_cookie_name, access_token_cookie_name, refresh_cookies, exclude_cookies.
    """
    cfg = load_component_config(domain, component or "")
    rt_name = cfg.get("refresh_token_cookie_name") or "refresh_token"
    at_name = cfg.get("access_token_cookie_name") or "access_token"
    refresh_cookies = cfg.get("refresh_cookies")
    if refresh_cookies is None:
        refresh_cookies = ["_ga", "_ga_D3E6G93TN9", rt_name]
    exclude_cookies = cfg.get("exclude_cookies")
    if exclude_cookies is None:
        exclude_cookies = [at_name]
    return {
        "refresh_token_cookie_name": rt_name,
        "access_token_cookie_name": at_name,
        "refresh_cookies": refresh_cookies,
        "exclude_cookies": exclude_cookies,
    }


def _get_cookie_value(cookies: list[dict], name: str) -> str | None:
    """Extract cookie value by name."""
    for c in cookies:
        if c.get("name") == name:
            return c.get("value")
    return None


# Common CSRF configs: (header_name, storage_type, key). Try in order; on 401/403, try next.
CSRF_CONFIGS = [
    ("X-CSRF-Token", "localStorage", "csrfToken"),
    ("X-CSRF-Token", "localStorage", "csrf_token"),
    ("X-XSRF-Token", "cookie", "XSRF-TOKEN"),  # Angular
    ("X-CSRFToken", "localStorage", "csrfToken"),
    ("X-CSRF-Token", "cookie", "_csrf"),
    ("Csrf-Token", "localStorage", "csrfToken"),
    ("X-CSRF-Token", "localStorage", "XSRF-TOKEN"),
    ("X-CSRF-Token", "cookie", "csrfToken"),
    (None, None, None),  # No CSRF
]


def _get_token_from_config(config: dict, storage_type: str, key: str) -> str | None:
    """Extract token from config by storage type and key."""
    if storage_type == "localStorage":
        for origin in config.get("origins", []):
            for item in origin.get("localStorage", []):
                if item.get("name") == key:
                    return item.get("value")
    elif storage_type == "cookie":
        return _get_cookie_value(config.get("cookies", []), key)
    return None


def _get_csrf_headers(config: dict) -> list[dict[str, str]]:
    """Build list of header dicts to try, one per CSRF config that has a token (or empty for no-CSRF)."""
    result = []
    for header_name, storage_type, key in CSRF_CONFIGS:
        if header_name is None:
            result.append({})
            continue
        token = _get_token_from_config(config, storage_type, key)
        if token:
            result.append({header_name: token})
    if not result:
        result.append({})  # At least try without CSRF
    return result


def _update_cookie(
    cookies: list[dict],
    name: str,
    value: str,
    expires_delta: int = 900,
    domain: str | None = None,
    token_cookie_names: tuple[str, ...] = ("access_token", "refresh_token"),
) -> None:
    """Update or add a cookie by name. Sets expires to now + expires_delta seconds."""
    now = time.time()
    expires = now + expires_delta
    for c in cookies:
        if c.get("name") == name:
            c["value"] = value
            c["expires"] = expires
            return
    # Add new cookie - need domain from existing token cookie or caller-provided domain
    if not domain:
        for c in cookies:
            if c.get("name") in token_cookie_names:
                domain = c.get("domain")
                if domain:
                    break
    if not domain:
        domain = "localhost"  # fallback for local dev
    cookies.append({
        "name": name,
        "value": value,
        "domain": domain,
        "path": "/",
        "expires": expires,
        "httpOnly": True,
        "secure": True,
        "sameSite": "Strict",
    })


def _parse_refresh_response(body: str) -> tuple[str | None, str | None, int, str | None]:
    """Parse refresh API response. Returns (access_token, refresh_token, expires_in, csrf_token)."""
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None, None, 900, None

    access_token = data.get("accessToken") or data.get("access_token")
    new_refresh = data.get("refreshToken") or data.get("refresh_token")
    expires_in = data.get("expires_in") or data.get("expiresIn") or 900
    csrf_token = data.get("csrfToken")

    inner = data.get("data") or data.get("tokens")
    if isinstance(inner, dict):
        access_token = access_token or inner.get("accessToken") or inner.get("access_token")
        new_refresh = new_refresh or inner.get("refreshToken") or inner.get("refresh_token")
        expires_in = expires_in or inner.get("expires_in") or inner.get("expiresIn") or 900
        csrf_token = csrf_token or inner.get("csrfToken")

    return access_token, new_refresh, expires_in, csrf_token


def _apply_tokens_to_auth(
    config: dict,
    access_token: str,
    new_refresh: str | None,
    expires_in: int,
    *,
    access_token_cookie_name: str = "access_token",
    refresh_token_cookie_name: str = "refresh_token",
    domain: str | None = None,
) -> None:
    """Update auth config cookies with new tokens."""
    cookies = config.get("cookies", [])
    token_names = (access_token_cookie_name, refresh_token_cookie_name)
    _update_cookie(
        cookies,
        access_token_cookie_name,
        access_token,
        expires_delta=expires_in,
        domain=domain,
        token_cookie_names=token_names,
    )
    if new_refresh:
        _update_cookie(
            cookies,
            refresh_token_cookie_name,
            new_refresh,
            expires_delta=7 * 24 * 3600,
            domain=domain,
            token_cookie_names=token_names,
        )
    config["cookies"] = cookies


async def refresh_auth_async(
    domain: str, component: str | None = None, playwright=None, debug: bool = False
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Refresh tokens via Playwright (browser). Use when direct HTTP is blocked (Cloudflare).
    Returns (updated auth config, None) on success, (None, error_message) on failure.
    """
    refresh_url = _get_refresh_url(domain, component or "")
    if not refresh_url:
        return None, "No refresh_url in config. Add refresh_url to component config.yaml."

    config = load_auth_config(domain, component)
    if not config:
        label = f"{domain}/{component}" if component else domain
        return None, f"No auth.json for {label}. Run 'Add login' first."

    refresh_cfg = _get_refresh_config(domain, component)
    rt_name = refresh_cfg["refresh_token_cookie_name"]
    at_name = refresh_cfg["access_token_cookie_name"]
    refresh_cookies_list = refresh_cfg["refresh_cookies"]
    exclude_cookies_set = set(refresh_cfg["exclude_cookies"])

    cookies = config.get("cookies", [])
    refresh_token_val = _get_cookie_value(cookies, rt_name)
    if not refresh_token_val:
        return None, f"No {rt_name} in auth.json. Run 'Add login' to get fresh tokens."

    csrf_headers_list = _get_csrf_headers(config)

    from browser_bot.sites import get_storage_state_path

    storage_path = get_storage_state_path(domain, component)
    if not storage_path:
        label = f"{domain}/{component}" if component else domain
        return None, f"No auth config found for {label}."

    comp_config = load_component_config(domain, component or "")
    refresh_mode = comp_config.get("refresh_mode", "both")
    post_body = "{}" if refresh_mode == "cookie" else json.dumps({
        "refreshToken": refresh_token_val,
        "refresh_token": refresh_token_val,
    })

    # Build Cookie header from refresh_cookies config, excluding exclude_cookies
    refresh_cookie_set = set(refresh_cookies_list)
    cookie_parts = [
        f"{c['name']}={c['value']}"
        for c in cookies
        if c.get("name") in refresh_cookie_set and c.get("name") not in exclude_cookies_set
    ]
    explicit_cookie = "; ".join(cookie_parts) if cookie_parts else None

    base_url = _get_base_url(domain, component)
    # Match curl: Origin, Referer, Cookie - ensure auth headers are sent
    base_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Origin": base_url,
        "Referer": f"{base_url}/",
    }
    if explicit_cookie:
        base_headers["Cookie"] = explicit_cookie

    debug_lines: list[str] = []

    def _debug(msg: str, *args) -> None:
        if debug:
            debug_lines.append(msg % args if args else msg)

    def _print_debug() -> None:
        if debug_lines:
            print("\n  [Refresh debug]")
            for line in debug_lines:
                print(f"    {line}")
            print()

    _debug("domain=%s component=%s", domain, component)
    _debug("refresh_url=%s", refresh_url)
    _debug("refresh_mode=%s post_body=%s", refresh_mode, repr(post_body[:80]))
    _debug("base_url=%s", base_url)
    _debug("cookies in auth: %s", [c["name"] for c in cookies])
    rt_cookie = next((c for c in cookies if c.get("name") == rt_name), None)
    _debug("refresh_token source: auth.json -> cookies[%s]", rt_name)
    if rt_cookie:
        _debug("refresh_token cookie: domain=%s path=%s expires=%s", rt_cookie.get("domain"), rt_cookie.get("path"), rt_cookie.get("expires"))
    _debug("refresh_token value: %s", refresh_token_val or "(none)")
    _debug("Cookie header (excludes access_token to match working curl): %s", (explicit_cookie or "")[:150])
    _debug("csrf_headers_list count=%d", len(csrf_headers_list))

    def _storage_state_from_auth(cfg: dict, exclude_cookie_names: set[str] | None = None) -> dict:
        from browser_bot.browser.launcher import _filter_storage_items
        from browser_bot.config import LOCALSTORAGE_MAX_VALUE_LEN

        cookies = cfg.get("cookies", [])
        if exclude_cookie_names:
            cookies = [c for c in cookies if c.get("name") not in exclude_cookie_names]
        max_len = LOCALSTORAGE_MAX_VALUE_LEN
        return {
            "cookies": cookies,
            "origins": [
                {
                    "origin": o["origin"],
                    "localStorage": _filter_storage_items(o.get("localStorage", []), max_len),
                }
                for o in cfg.get("origins", [])
            ],
        }

    async def _do_refresh_via_fetchers(p, storage_state_or_path, try_csrf: bool = False) -> tuple[int, str, dict | None]:
        """Use fetcher flow: with_page callback does goto + fetch. Returns (status, body, storage_state or None)."""
        from main import run_with_page_from_fetchers

        async def _cb(page):
            await page.goto(base_url, wait_until="domcontentloaded", timeout=15000)
            _debug("Refresh via fetcher: page_url=%s", page.url)
            last_status, last_body, last_storage = 0, "", None
            headers_to_try = csrf_headers_list if try_csrf else [{}]
            for csrf_headers in headers_to_try:
                headers = {**base_headers, **csrf_headers}
                if comp_config.get("refresh_use_bearer"):
                    headers["Authorization"] = f"Bearer {refresh_token_val}"
                header_obj = dict(headers)
                result = await page.evaluate(
                    """async ([url, body, headers]) => {
                        const r = await fetch(url, {
                            method: 'POST',
                            credentials: 'include',
                            headers: headers,
                            body: body
                        });
                        return { status: r.status, body: await r.text() };
                    }""",
                    [refresh_url, post_body, header_obj],
                )
                last_status, last_body = result["status"], result["body"]
                _debug("Refresh fetch: csrf=%s status=%d", list(csrf_headers.keys()) if csrf_headers else [], last_status)
                if 200 <= last_status < 300:
                    last_storage = await page.context.storage_state()
                    return (last_status, last_body, last_storage)
                if last_status in (401, 403):
                    continue
                return (last_status, last_body, None)
            return (last_status, last_body, last_storage)

        if isinstance(storage_state_or_path, dict):
            result = await run_with_page_from_fetchers(
                p, domain, _cb, storage_state=storage_state_or_path, allow_all=True
            )
        else:
            result = await run_with_page_from_fetchers(
                p, domain, _cb, storage_path=storage_state_or_path, allow_all=True
            )
        return result or (0, "", None)

    response_status, body, storage = 0, "", None
    if playwright is None:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            _debug("Trying flow: Fetcher (browser + storage_state + fetch, exclude access_token)")
            storage_excluded = _storage_state_from_auth(config, exclude_cookie_names={at_name})
            response_status, body, storage = await _do_refresh_via_fetchers(p, storage_excluded, try_csrf=False)
            if 200 <= response_status < 300 and storage:
                new_cookies = storage.get("cookies", [])
                if new_cookies:
                    existing = {c["name"]: c for c in config.get("cookies", [])}
                    for c in new_cookies:
                        existing[c["name"]] = c
                    config["cookies"] = list(existing.values())
            if response_status in (401, 403):
                _debug("Excluded storage failed, trying: Full storage + CSRF")
                response_status, body, storage = await _do_refresh_via_fetchers(p, str(storage_path), try_csrf=True)
                if 200 <= response_status < 300 and storage:
                    new_cookies = storage.get("cookies", [])
                    if new_cookies:
                        existing = {c["name"]: c for c in config.get("cookies", [])}
                        for c in new_cookies:
                            existing[c["name"]] = c
                        config["cookies"] = list(existing.values())
    else:
        storage_excluded = _storage_state_from_auth(config, exclude_cookie_names={at_name})
        response_status, body, storage = await _do_refresh_via_fetchers(playwright, storage_excluded, try_csrf=False)
        if 200 <= response_status < 300 and storage:
            new_cookies = storage.get("cookies", [])
            if new_cookies:
                existing = {c["name"]: c for c in config.get("cookies", [])}
                for c in new_cookies:
                    existing[c["name"]] = c
                config["cookies"] = list(existing.values())
        elif response_status in (401, 403):
            response_status, body, storage = await _do_refresh_via_fetchers(playwright, str(storage_path), try_csrf=True)
            if 200 <= response_status < 300 and storage:
                new_cookies = storage.get("cookies", [])
                if new_cookies:
                    existing = {c["name"]: c for c in config.get("cookies", [])}
                    for c in new_cookies:
                        existing[c["name"]] = c
                    config["cookies"] = list(existing.values())

    if response_status >= 400:
        try:
            err = json.loads(body)
            msg = err.get("message") or err.get("error") or body[:200]
        except Exception:
            msg = body[:200] if body else f"HTTP {response_status}"
        _debug("Final: status=%d", response_status)
        _debug("Response body: %s", body[:500] if body else "(empty)")
        _print_debug()
        return None, f"API error ({response_status}): {msg}"

    access_token, new_refresh, expires_in, csrf_token_resp = _parse_refresh_response(body)
    success = False
    try:
        data = json.loads(body)
        success = data.get("success") is True
    except Exception:
        pass

    # Derive domain from base_url for new cookie fallback
    from urllib.parse import urlparse
    parsed = urlparse(base_url)
    domain_for_cookies = parsed.netloc.split(":")[0] if parsed.netloc else None

    # API may return tokens in body, or set them via Set-Cookie (browser applies automatically)
    if access_token:
        _apply_tokens_to_auth(
            config,
            access_token,
            new_refresh,
            expires_in,
            access_token_cookie_name=at_name,
            refresh_token_cookie_name=rt_name,
            domain=domain_for_cookies,
        )
    elif not success:
        return None, f"Unexpected API response (no access token): {body[:200]}"
    # else: success but no access_token in body - tokens set via Set-Cookie; update csrfToken from response

    if csrf_token_resp:
        for origin in config.get("origins", []):
            for item in origin.get("localStorage", []):
                if item.get("name") == "csrfToken":
                    item["value"] = csrf_token_resp
                    break

    save_auth_config(domain, config, component=component)
    return config, None


def refresh_auth(domain: str, component: str | None = None, debug: bool = False) -> tuple[dict[str, Any] | None, str | None]:
    """
    Call refresh_url with refresh_token from auth.json, then update auth.json with new tokens.
    Uses Playwright (browser) to avoid Cloudflare/bot blocking.
    Returns (config, None) on success, (None, error_message) on failure.
    """
    import asyncio

    return asyncio.run(refresh_auth_async(domain, component, debug=debug))
