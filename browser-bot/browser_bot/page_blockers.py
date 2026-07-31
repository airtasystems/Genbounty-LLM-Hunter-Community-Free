"""Detect login walls, cookie banners, and submission readiness before UI submit."""

from __future__ import annotations

import asyncio
import random
import time
from typing import TYPE_CHECKING, Any

from browser_bot.auth_state import load_auth_config
from browser_bot.sites import load_component_config, load_component_config_raw, save_component_config

if TYPE_CHECKING:
    from playwright.async_api import Page

LOGIN_URL_MARKERS = ("/login", "/signin", "/sign-in", "/auth", "/oauth", "/sso")

LOGIN_BODY_PHRASES = (
    "log in or sign up",
    "log in to continue",
    "sign in to continue",
    "sign in or sign up",
    "continue with google",
    "continue with apple",
    "continue with microsoft",
)

LOGIN_WALL_SELECTORS = (
    'text=Log in or sign up',
    'text=Log in to continue',
    'text=Sign in to continue',
    'button:has-text("Continue with Google")',
    'button:has-text("Continue with Apple")',
    'button:has-text("Continue with Microsoft")',
)

DEFAULT_COOKIE_SELECTORS = (
    'button:has-text("Accept all")',
    'button:has-text("Accept All")',
    'button:has-text("Accept")',
    'button:has-text("I agree")',
    'button:has-text("Allow all")',
    'button:has-text("Reject all")',
    'button:has-text("Got it")',
)

CAPTCHA_HINTS = (
    "captcha",
    "recaptcha",
    "hcaptcha",
    "security check",
)

CLOUDFLARE_CHALLENGE_PHRASES = (
    "verify you are human",
    "verify that you are human",
    "verify you're human",
    "confirm you are human",
    "confirm that you are human",
    "confirm you're human",
    "checking your browser",
    "checking if the site connection is secure",
    "just a moment",
    "needs to review the security",
    "review the security of your connection",
)

# Backward-compatible alias (challenge phrases only).
CLOUDFLARE_BODY_HINTS = CLOUDFLARE_CHALLENGE_PHRASES

CLOUDFLARE_IFRAME_SELECTORS = (
    'iframe[src*="challenges.cloudflare.com"]',
    'iframe[src*="challenges.cloudflare"]',
    'iframe[src*="turnstile"]',
    'iframe[title*="Widget"]',
    'iframe[title*="challenge"]',
)

CLOUDFLARE_WIDGET_SELECTORS = (
    'input[type="checkbox"]',
    '[role="checkbox"]',
    "label",
    ".ctp-checkbox-label",
    "#challenge-stage",
    ".mark",
)

DEFAULT_CLOUDFLARE_WAIT_SEC = 120.0
DEFAULT_CLOUDFLARE_CLICK_INTERVAL_SEC = 4.0
_TURNSTILE_FRAME_URL_HINTS = (
    "challenges.cloudflare.com",
    "turnstile",
    "cloudflare.com/cdn-cgi",
)

TURNSTILE_SELECTORS = (
    "#cf-turnstile",
    '[class*="cf-turnstile"]',
    '[id*="turnstile"]',
    'div:has-text("Verify you are human")',
    'label:has-text("Verify you are human")',
    'div:has-text("Confirm you are human")',
    'label:has-text("Confirm you are human")',
)

RATE_LIMIT_BODY_PHRASES = (
    "too many requests",
    # Avoid bare "rate limit" - matches settings labels (e.g. "Rate Limit (local)" on
    # virtualsteve-star.github.io/chat-playground guardrails UI).
    "rate limit exceeded",
    "rate limits exceeded",
    "rate limit reached",
    "rate limited",
    "rate-limit exceeded",
    "slow down",
    "try again later",
    "try again in",
    "usage limit",
    "request limit",
    "quota exceeded",
    "temporarily unavailable",
    "exceeded the limit",
    "too many messages",
    "too many attempts",
)

RATE_LIMIT_SELECTORS = (
    'text=Too many requests',
    'text=Rate limit exceeded',
    'text=Please try again later',
    'text=You have exceeded',
    'text=Slow down',
    'text=Try again later',
)

DEFAULT_RATE_LIMIT_BACKOFF_SEC = 60.0
DEFAULT_RATE_LIMIT_AUTO_RETRIES = 3
DEFAULT_RATE_LIMIT_BACKOFF_SCHEDULE = (10.0, 10.0, 120.0)


class PageBlockedError(Exception):
    """Submission blocked by login wall, captcha, or similar."""

    def __init__(self, kind: str, *, advice: list[str] | None = None, message: str = "") -> None:
        self.kind = kind
        self.advice = advice or []
        self.message = message or kind
        super().__init__(self.message)


def _site_has_saved_session(site: str, component: str | None = None) -> bool:
    """True only when auth.json holds a real session (not public/no-login stub)."""
    config = load_auth_config(site, component)
    if not config:
        return False
    if config.get("auth_mode") in ("none", "api_key"):
        return False
    if config.get("cookies"):
        return True
    return any(
        o.get("localStorage") or o.get("sessionStorage")
        for o in config.get("origins", [])
    )


def _resolve_login_url(site: str, component: str, start_url: str) -> str:
    from browser_bot.sites import normalize_target_access_url

    config = load_component_config(site, component)
    login_url = config.get("login_url") or ""
    if isinstance(login_url, str) and login_url.strip():
        return normalize_target_access_url(login_url) or login_url.strip()
    if start_url.strip():
        return normalize_target_access_url(start_url) or start_url.strip()
    return normalize_target_access_url(site) or (
        f"http://{site}" if site.startswith("localhost") or ":" in site else f"https://{site}"
    )


def get_rate_limit_settings(site: str, component: str) -> dict[str, float | int]:
    """Resolve rate-limit backoff settings from submission.rate_limit and browser settings."""
    from browser_bot.config import EVASION_MAX_RETRIES, EVASION_RETRY_WAIT_S

    config = load_component_config(site, component)
    sub = config.get("submission") if isinstance(config.get("submission"), dict) else {}
    rl = sub.get("rate_limit") if isinstance(sub.get("rate_limit"), dict) else {}
    settings = config.get("settings") if isinstance(config.get("settings"), dict) else {}

    backoff_raw = rl.get("backoff_sec")
    if backoff_raw is None:
        backoff_raw = settings.get("EVASION_RETRY_WAIT_S", EVASION_RETRY_WAIT_S)
    try:
        backoff_sec = max(1.0, float(backoff_raw))
    except (TypeError, ValueError):
        backoff_sec = DEFAULT_RATE_LIMIT_BACKOFF_SEC

    max_auto = rl.get("max_auto_retries")
    if max_auto is None:
        max_auto = min(DEFAULT_RATE_LIMIT_AUTO_RETRIES, max(0, int(EVASION_MAX_RETRIES or 0)))
    try:
        max_auto_retries = max(0, int(max_auto))
    except (TypeError, ValueError):
        max_auto_retries = DEFAULT_RATE_LIMIT_AUTO_RETRIES

    schedule_raw = rl.get("backoff_schedule")
    if isinstance(schedule_raw, list) and schedule_raw:
        backoff_schedule: tuple[float, ...] = tuple(
            max(1.0, float(x)) for x in schedule_raw if x is not None
        )
    else:
        backoff_schedule = (
            backoff_sec,
            backoff_sec,
            float(DEFAULT_RATE_LIMIT_BACKOFF_SCHEDULE[2]),
        )

    if max_auto_retries > len(backoff_schedule):
        tail = backoff_schedule[-1] if backoff_schedule else float(DEFAULT_RATE_LIMIT_BACKOFF_SCHEDULE[2])
        backoff_schedule = backoff_schedule + (tail,) * (max_auto_retries - len(backoff_schedule))
    elif max_auto_retries > 0:
        backoff_schedule = backoff_schedule[:max_auto_retries]

    return {
        "backoff_sec": backoff_sec,
        "max_auto_retries": max_auto_retries,
        "backoff_schedule": backoff_schedule,
    }


async def _body_suggests_rate_limit(page: "Page") -> bool:
    try:
        body = (await page.inner_text("body")).lower()
    except Exception:
        return False
    return body_text_suggests_rate_limit(body)


def body_text_suggests_rate_limit(body: str) -> bool:
    """True when page body copy looks like an active rate-limit error (not settings labels)."""
    text = (body or "").lower()
    if not text:
        return False
    return any(phrase in text for phrase in RATE_LIMIT_BODY_PHRASES)


async def _selector_suggests_rate_limit(page: "Page", blockers: list[dict] | None = None) -> bool:
    for sel in RATE_LIMIT_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                return True
        except Exception:
            continue
    for entry in _blocker_entries(blockers):
        if (entry.get("action") or "click") != "detect":
            continue
        label = (entry.get("label") or "").lower()
        if "rate" not in label and "limit" not in label:
            continue
        sel = entry.get("selector") or ""
        if not sel:
            continue
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                return True
        except Exception:
            continue
    return False


async def _rate_limit_visible(page: "Page", blockers: list[dict] | None = None) -> bool:
    if await _body_suggests_rate_limit(page):
        return True
    if await _selector_suggests_rate_limit(page, blockers):
        return True
    return False


def _emit_blocked_rate_limit(site: str, *, backoff_sec: float) -> None:
    from browser_bot.submit.common import log_genbounty_progress

    advice = [
        f"Wait at least {int(backoff_sec)} seconds before resuming tests.",
        "Reduce pool/cluster concurrency in Settings → Browser if limits persist.",
        "Switch Fetch Method to human for targets that throttle automated browsers.",
        "Click Wait and resume in the Run Tests dialog when the countdown completes.",
    ]
    log_genbounty_progress(
        {
            "type": "blocked",
            "kind": "rate_limited",
            "message": "Rate limit detected - too many requests.",
            "action": "prompt_rate_limit",
            "backoff_sec": round(backoff_sec, 1),
            "site": site,
            "advice": advice,
        }
    )


async def _resolve_rate_limit(
    page: "Page",
    *,
    site: str,
    component: str,
    blockers: list[dict] | None = None,
) -> None:
    if not await _rate_limit_visible(page, blockers):
        return

    cfg = get_rate_limit_settings(site, component)
    max_auto_retries = int(cfg["max_auto_retries"])
    backoff_schedule = tuple(float(x) for x in cfg["backoff_schedule"])
    final_backoff_sec = backoff_schedule[-1] if backoff_schedule else float(cfg["backoff_sec"])

    for attempt in range(1, max_auto_retries + 1):
        from browser_bot.submit.common import log_resilience

        backoff_sec = backoff_schedule[attempt - 1] if attempt <= len(backoff_schedule) else final_backoff_sec
        log_resilience(
            "rate_limit_backoff",
            "Rate limit detected - backing off before page reload",
            attempt=attempt,
            max_attempts=max_auto_retries,
            wait_sec=backoff_sec,
        )
        await asyncio.sleep(backoff_sec)
        try:
            await page.reload(wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_load_state("load", timeout=10000)
            except Exception:
                pass
            await asyncio.sleep(0.5)
        except Exception:
            pass
        if not await _rate_limit_visible(page, blockers):
            from browser_bot.submit.common import log_resilience

            log_resilience("rate_limit_cleared", "Rate limit cleared after backoff reload")
            return

    _emit_blocked_rate_limit(site, backoff_sec=final_backoff_sec)
    raise PageBlockedError(
        "rate_limited",
        advice=[
            f"Wait {int(final_backoff_sec)} seconds, then resume tests from the Run Tests dialog.",
            "Lower concurrency or switch to human fetch mode if this recurs.",
        ],
        message="Rate limit detected - too many requests.",
    )


async def check_rate_limit_before_submit(
    page: "Page",
    *,
    site: str,
    component: str,
    blockers: list[dict] | None = None,
) -> None:
    """Per-prompt rate-limit check for multi-turn runs."""
    await _resolve_rate_limit(page, site=site, component=component, blockers=blockers)


async def _url_suggests_login(page: "Page") -> bool:
    url = (page.url or "").lower()
    return any(marker in url for marker in LOGIN_URL_MARKERS)


async def _body_suggests_login(page: "Page") -> bool:
    try:
        body = (await page.inner_text("body")).lower()
    except Exception:
        return False
    return any(phrase in body for phrase in LOGIN_BODY_PHRASES)


async def _selector_suggests_login(page: "Page") -> bool:
    for sel in LOGIN_WALL_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                return True
        except Exception:
            continue
    return False


async def _login_wall_visible(page: "Page") -> bool:
    if await _url_suggests_login(page):
        return True
    if await _selector_suggests_login(page):
        return True
    if await _body_suggests_login(page):
        return True
    return False


def _emit_blocked_login(site: str, login_url: str) -> None:
    from browser_bot.submit.common import log_genbounty_progress

    advice = [
        "Click Log in in the Run Tests dialog to open a browser.",
        "Complete sign-in in the browser window.",
        "After sign-in, click Save auth to store your session.",
        "Tests will resume automatically once auth is saved.",
    ]
    log_genbounty_progress(
        {
            "type": "blocked",
            "kind": "login_required",
            "message": "Sign-in required to continue tests.",
            "action": "prompt_login",
            "login_url": login_url,
            "site": site,
            "advice": advice,
        }
    )


async def _resolve_login_wall(
    page: "Page",
    *,
    site: str,
    component: str,
    start_url: str,
) -> None:
    if not await _login_wall_visible(page):
        return

    if _site_has_saved_session(site, component):
        from browser_bot.submit.common import log_resilience

        log_resilience(
            "login_session_reload",
            "Login wall detected - reloading saved session",
        )
        try:
            await page.reload(wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_load_state("load", timeout=10000)
            except Exception:
                pass
            await asyncio.sleep(0.5)
        except Exception:
            pass
        if not await _login_wall_visible(page):
            from browser_bot.submit.common import log_resilience

            log_resilience("login_cleared", "Login wall cleared after session reload")
            return

    login_url = _resolve_login_url(site, component, start_url)
    _emit_blocked_login(site, login_url)
    raise PageBlockedError(
        "login_required",
        advice=[
            "Sign in via the Run Tests login dialog.",
            "Save auth after completing sign-in.",
        ],
        message="Sign-in required to continue tests.",
    )


async def check_login_wall_before_submit(
    page: "Page",
    *,
    site: str,
    component: str,
    start_url: str,
) -> None:
    """Per-prompt login check for multi-turn runs."""
    await _resolve_login_wall(page, site=site, component=component, start_url=start_url)


def submission_requires_headed_browser(site: str, component: str) -> bool:
    """True when a visible browser window is required (Cloudflare/Turnstile or Headless off)."""
    sub = load_component_config(site, component).get("submission")
    if isinstance(sub, dict) and sub.get("cloudflare_headed"):
        return True
    try:
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from pipeline.component_settings import effective_headless

        return not effective_headless(site, component)
    except Exception:
        return False


def submission_needs_headed_human(site: str, component: str) -> bool:
    """True when only the human fetcher tier should be used (FETCH_METHOD=human)."""
    try:
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from pipeline.component_settings import get_effective_settings

        method = str(get_effective_settings(site=site, component=component).get("FETCH_METHOD") or "").lower()
        return method == "human"
    except Exception:
        return False


def _is_headless_browser(site: str = "", component: str = "") -> bool:
    import os

    try:
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from pipeline.component_settings import effective_headless

        resolved_site = (site or os.getenv("GENBOUNTY_SITE") or "").strip() or None
        resolved_component = (component or os.getenv("GENBOUNTY_COMPONENT") or "").strip() or None
        if resolved_site and resolved_component:
            return effective_headless(resolved_site, resolved_component)
    except Exception:
        pass
    try:
        from browser_bot.config import HEADLESS

        return bool(HEADLESS)
    except Exception:
        return True


def _blocker_entries(blockers: list[dict] | None) -> list[dict]:
    if not blockers:
        return []
    return [b for b in blockers if isinstance(b, dict) and b.get("selector")]


def _persist_blocker(site: str, component: str, selector: str, *, label: str, action: str) -> None:
    config = load_component_config_raw(site, component)
    sub = config.setdefault("submission", {})
    if not isinstance(sub, dict):
        sub = {}
        config["submission"] = sub
    entries = sub.setdefault("blockers", [])
    if not isinstance(entries, list):
        entries = []
        sub["blockers"] = entries
    for entry in entries:
        if isinstance(entry, dict) and entry.get("selector") == selector:
            return
    entries.append({"selector": selector, "label": label, "action": action})
    save_component_config(site, component, config)


def _persist_cloudflare_headed(site: str, component: str) -> bool:
    """Ensure submission.cloudflare_headed is set on the component config. Returns True if written."""
    config = load_component_config_raw(site, component)
    sub = config.setdefault("submission", {})
    if not isinstance(sub, dict):
        sub = {}
        config["submission"] = sub
    if sub.get("cloudflare_headed"):
        return False
    sub["cloudflare_headed"] = True
    save_component_config(site, component, config)
    return True


async def _on_cloudflare_challenge_cleared(
    page: "Page",
    *,
    site: str,
    component: str,
) -> None:
    """Persist clearance cookies and remember Cloudflare-headed for subsequent runs."""
    from browser_bot.auth_state import merge_browser_cookies_into_auth
    from browser_bot.submit.common import log_resilience

    try:
        wrote = await merge_browser_cookies_into_auth(site, component, page)
    except Exception:
        wrote = False
    if wrote:
        log_resilience(
            "cloudflare_auth_persist",
            "Saved Cloudflare clearance cookies into auth.json",
        )
    if _persist_cloudflare_headed(site, component):
        log_resilience(
            "cloudflare_headed_persist",
            "Marked component cloudflare_headed for CDP / stealth on later runs",
        )


async def _click_blocker(page: "Page", selector: str) -> bool:
    try:
        loc = page.locator(selector).first
        if await loc.count() == 0:
            return False
        if not await loc.is_visible():
            return False
        await loc.click(timeout=3000)
        await asyncio.sleep(0.4)
        return True
    except Exception:
        return False


async def _attempt_cookie_self_heal(
    page: "Page",
    *,
    site: str,
    component: str,
    blockers: list[dict] | None,
) -> None:
    if await _login_wall_visible(page):
        return

    configured = _blocker_entries(blockers)
    click_blockers = [b for b in configured if (b.get("action") or "click") == "click"]
    selectors = [b["selector"] for b in click_blockers if b.get("selector")]
    labels = {b["selector"]: b.get("label") or "blocker" for b in click_blockers if b.get("selector")}

    for sel in selectors:
        if await _click_blocker(page, sel):
            from browser_bot.submit.common import log_resilience

            log_resilience(
                "cookie_dismiss",
                f"Dismissed blocker: {labels.get(sel, 'blocker')}",
            )
            return

    for sel in DEFAULT_COOKIE_SELECTORS:
        if sel in selectors:
            continue
        if await _click_blocker(page, sel):
            from browser_bot.submit.common import log_resilience

            log_resilience("cookie_dismiss", "Dismissed cookie consent banner")
            _persist_blocker(site, component, sel, label=label, action="click")
            return


async def check_submission_readiness(
    page: "Page",
    inputs: list[dict],
    *,
    submit_selector: str = "",
    wait_ms: int = 8000,
) -> list[str]:
    """Check prompt inputs only - never the submit button. Returns warnings (non-blocking)."""
    import asyncio
    import time

    deadline = time.monotonic() + max(0, wait_ms) / 1000.0
    last_warnings: list[str] = []
    while True:
        warnings: list[str] = []
        _ = submit_selector  # intentionally excluded from readiness
        for inp in inputs:
            if not isinstance(inp, dict):
                continue
            sel = inp.get("selector") or ""
            if not sel:
                continue
            inp_type = (inp.get("type") or "text").lower()
            if inp_type == "file":
                continue
            if inp.get("upload_prep") or inp_type == "click":
                continue
            try:
                from browser_bot.submit.common import _first_visible_locator

                if await page.locator(sel).count() == 0:
                    warnings.append(f"Input not found: {sel}")
                else:
                    loc = await _first_visible_locator(page, sel)
                    if not await loc.is_visible():
                        warnings.append(f"Input not visible: {sel}")
                    elif not await loc.is_enabled():
                        warnings.append(f"Input not enabled: {sel}")
            except Exception as exc:
                warnings.append(f"Input check failed ({sel}): {exc}")
        last_warnings = warnings
        # Poll while the composer is missing *or* still hidden (gated UIs after
        # surface_prep often leave textarea in the DOM with display:none).
        blocking = [
            w for w in warnings
            if w.startswith("Input not found")
            or w.startswith("Input not visible")
            or w.startswith("Input not enabled")
        ]
        if not blocking or time.monotonic() >= deadline:
            return warnings
        await asyncio.sleep(0.35)


async def _turnstile_widget_visible(page: "Page") -> bool:
    for sel in (*CLOUDFLARE_IFRAME_SELECTORS, *TURNSTILE_SELECTORS):
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                return True
        except Exception:
            continue
    for frame in page.frames:
        frame_url = (frame.url or "").lower()
        if "challenges.cloudflare.com" in frame_url or "turnstile" in frame_url:
            return True
    return False


async def _submission_ui_ready(page: "Page", site: str, component: str) -> bool:
    """True when configured prompt/submit controls are visible (app is not blocked)."""
    try:
        from browser_bot.sites import get_submission_config
        from browser_bot.submit.common import configured_prompt_selectors
    except Exception:
        return False
    sub = get_submission_config(site, component)
    if not sub:
        return False

    for sel in configured_prompt_selectors(site, component):
        try:
            loc = page.locator(sel).first
            if await loc.count() == 0:
                continue
            if await loc.is_visible():
                return True
        except Exception:
            continue

    submit_sel = (sub.get("submit_selector") or "").strip()
    if submit_sel:
        try:
            loc = page.locator(submit_sel).first
            if await loc.count() > 0 and await loc.is_visible():
                return True
        except Exception:
            pass
    return False


async def _cloudflare_challenge_visible(
    page: "Page",
    *,
    site: str = "",
    component: str = "",
) -> bool:
    """True when a blocking Cloudflare interstitial is showing (not passive page widgets)."""
    if site and component and await _submission_ui_ready(page, site, component):
        return False

    url = (page.url or "").lower()
    if "challenges.cloudflare.com" in url:
        return True

    try:
        title = (await page.title() or "").lower()
    except Exception:
        title = ""
    if any(
        phrase in title
        for phrase in ("just a moment", "attention required", "checking your browser")
    ):
        return True

    for sel in (
        "#challenge-stage",
        "#cf-wrapper",
        "#challenge-running",
        "#challenge-body-text",
    ):
        try:
            loc = page.locator(sel).first
            if await loc.count() == 0 or not await loc.is_visible():
                continue
            box = await loc.bounding_box()
            if box and float(box.get("height") or 0) >= 120:
                return True
        except Exception:
            continue

    try:
        body = (await page.inner_text("body")).lower()
    except Exception:
        body = ""
    if not body.strip():
        return False

    # Full-page interstitial: challenge copy dominates and the composer is absent.
    has_verify = any(phrase in body for phrase in CLOUDFLARE_CHALLENGE_PHRASES)
    if has_verify and len(body) < 2500:
        return True

    return False


async def _submission_prompt_ready(page: "Page", site: str, component: str) -> bool:
    """Backward-compatible alias."""
    return await _submission_ui_ready(page, site, component)


async def _wait_for_turnstile_widget(page: "Page", timeout_sec: float = 12.0) -> None:
    """Give Turnstile iframes time to mount after navigation."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        for sel in (
            *CLOUDFLARE_IFRAME_SELECTORS,
            "#cf-turnstile",
            '[class*="cf-turnstile"]',
            'div:has-text("Verify you are human")',
        ):
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    return
            except Exception:
                continue
        await asyncio.sleep(0.4)


async def _turnstile_iframe_elements(page: "Page") -> list:
    """Collect iframe locators that likely host Turnstile."""
    found: list = []
    seen_ids: set[int] = set()

    async def _add(candidate) -> None:
        try:
            key = id(candidate)
            if key in seen_ids:
                return
            seen_ids.add(key)
            found.append(candidate)
        except Exception:
            pass

    for iframe in await page.locator("iframe").all():
        try:
            src = (await iframe.get_attribute("src") or "").lower()
            title = (await iframe.get_attribute("title") or "").lower()
            if any(h in src for h in _TURNSTILE_FRAME_URL_HINTS) or "widget" in title:
                await _add(iframe)
        except Exception:
            continue

    for sel in CLOUDFLARE_IFRAME_SELECTORS:
        try:
            for iframe in await page.locator(sel).all():
                await _add(iframe)
        except Exception:
            continue
    return found


async def _turnstile_click_coordinates(page: "Page") -> list[tuple[float, float]]:
    """Return viewport (x, y) points where the Turnstile checkbox is likely located."""
    points: list[tuple[float, float]] = []
    selectors = (
        "#cf-turnstile",
        '[class*="cf-turnstile"]',
        '[class*="turnstile"]',
        "#challenge-stage",
        'div:has-text("Verify you are human")',
        'label:has-text("Verify you are human")',
        'div:has-text("Confirm you are human")',
        'label:has-text("Confirm you are human")',
        *CLOUDFLARE_IFRAME_SELECTORS,
    )
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() == 0:
                continue
            box = await loc.bounding_box()
            if not box or box.get("width", 0) < 1 or box.get("height", 0) < 1:
                continue
            w, h = float(box["width"]), float(box["height"])
            points.append((box["x"] + min(28.0, max(12.0, w * 0.14)), box["y"] + h / 2))
            points.append((box["x"] + w / 2, box["y"] + h / 2))
        except Exception:
            continue

    for iframe in await _turnstile_iframe_elements(page):
        try:
            box = await iframe.bounding_box()
            if not box or box.get("width", 0) < 1 or box.get("height", 0) < 1:
                continue
            w, h = float(box["width"]), float(box["height"])
            points.append((box["x"] + min(28.0, max(12.0, w * 0.14)), box["y"] + h / 2))
            points.append((box["x"] + w / 2, box["y"] + h / 2))
        except Exception:
            continue
    return points


async def _click_turnstile_verify_label(page: "Page") -> list[str]:
    strategies: list[str] = []
    for getter in (
        lambda: page.get_by_text("Verify you are human", exact=False),
        lambda: page.get_by_text("Verify you're human", exact=False),
        lambda: page.get_by_text("Confirm you are human", exact=False),
        lambda: page.get_by_text("Confirm you're human", exact=False),
        lambda: page.locator('label:has-text("Verify")'),
        lambda: page.locator('label:has-text("Confirm")'),
    ):
        try:
            loc = getter().first
            if await loc.count() == 0 or not await loc.is_visible():
                continue
            await loc.click(timeout=4000, force=True)
            strategies.append("verify_label")
            await asyncio.sleep(0.8)
            return strategies
        except Exception:
            continue
    return strategies


async def _click_turnstile_iframe_hosts(page: "Page") -> list[str]:
    """Click inside Turnstile iframe hosts at typical checkbox offsets."""
    strategies: list[str] = []
    positions = (
        (18, 18),
        (24, 24),
        (30, 22),
        (16, 16),
        (40, 20),
    )
    for iframe in await _turnstile_iframe_elements(page):
        box = await iframe.bounding_box()
        host_positions = list(positions)
        if box and box.get("width", 0) >= 1 and box.get("height", 0) >= 1:
            w, h = float(box["width"]), float(box["height"])
            host_positions.extend(
                (
                    (min(28.0, max(12.0, w * 0.14)), h / 2),
                    (w / 2, h / 2),
                )
            )
        for px, py in host_positions:
            try:
                await iframe.click(position={"x": px, "y": py}, force=True, timeout=4000)
                strategies.append(f"iframe_host@{int(px)},{int(py)}")
                await asyncio.sleep(0.8)
                return strategies
            except Exception:
                continue
    return strategies


async def _click_turnstile_frame_bodies(page: "Page") -> list[str]:
    """Click cross-origin Turnstile frame bodies at checkbox offsets."""
    strategies: list[str] = []
    positions = ((24, 24), (18, 18), (32, 20), (40, 28), (14, 14))
    for frame in page.frames:
        frame_url = (frame.url or "").lower()
        if not any(h in frame_url for h in _TURNSTILE_FRAME_URL_HINTS):
            continue
        for px, py in positions:
            try:
                await frame.locator("body").click(
                    position={"x": px, "y": py},
                    force=True,
                    timeout=4000,
                )
                strategies.append(f"frame_body@{px},{py}")
                await asyncio.sleep(0.8)
                return strategies
            except Exception:
                continue
    return strategies


async def _human_click_at(page: "Page", x: float, y: float) -> bool:
    try:
        from browser_bot.browser.human_behavior import human_mouse_move

        await human_mouse_move(page, x, y)
        await asyncio.sleep(random.uniform(0.08, 0.2))
        await page.mouse.click(x, y, delay=random.randint(40, 120))
        return True
    except Exception:
        try:
            await page.mouse.click(x, y)
            return True
        except Exception:
            return False


async def _click_cloudflare_via_js(page: "Page") -> bool:
    """Traverse shadow roots and click the first checkbox-like control."""
    try:
        return bool(
            await page.evaluate(
                """() => {
                    function walk(root) {
                        const nodes = root.querySelectorAll('*');
                        for (const el of nodes) {
                            if (el.shadowRoot && walk(el.shadowRoot)) return true;
                            const role = el.getAttribute && el.getAttribute('role');
                            const tag = (el.tagName || '').toLowerCase();
                            if (role === 'checkbox' || tag === 'input' && el.type === 'checkbox') {
                                el.click();
                                return true;
                            }
                        }
                        return false;
                    }
                    return walk(document);
                }"""
            )
        )
    except Exception:
        return False


async def _try_click_cloudflare_checkbox(page: "Page") -> bool:
    """Try several strategies to activate Turnstile. Returns True if any click was sent."""
    strategies: list[str] = []

    for batch in (
        _click_turnstile_verify_label,
        _click_turnstile_iframe_hosts,
        _click_turnstile_frame_bodies,
    ):
        strategies.extend(await batch(page))
        if strategies:
            break

    if not strategies:
        for x, y in await _turnstile_click_coordinates(page):
            if await _human_click_at(page, x, y):
                strategies.append(f"coordinates@{int(x)},{int(y)}")
                await asyncio.sleep(1.2)
                break

    if not strategies:
        for iframe_sel in CLOUDFLARE_IFRAME_SELECTORS:
            try:
                fl = page.frame_locator(iframe_sel)
                for inner in CLOUDFLARE_WIDGET_SELECTORS:
                    loc = fl.locator(inner).first
                    if await loc.count() == 0:
                        continue
                    try:
                        await loc.click(timeout=4000, delay=80, force=True)
                        strategies.append(f"frame:{iframe_sel}:{inner}")
                        await asyncio.sleep(1.0)
                        break
                    except Exception:
                        continue
                if strategies:
                    break
            except Exception:
                continue

    if not strategies:
        for frame in page.frames:
            frame_url = (frame.url or "").lower()
            if not any(h in frame_url for h in _TURNSTILE_FRAME_URL_HINTS):
                continue
            for inner in CLOUDFLARE_WIDGET_SELECTORS:
                try:
                    loc = frame.locator(inner).first
                    if await loc.count() == 0:
                        continue
                    await loc.click(timeout=4000, delay=80, force=True)
                    strategies.append(f"child_frame:{inner}")
                    await asyncio.sleep(1.0)
                    break
                except Exception:
                    continue
            if strategies:
                break

    if not strategies:
        for sel in (
            'input[type="checkbox"]',
            '[role="checkbox"]',
            'label:has-text("Verify")',
            'label:has-text("Confirm")',
        ):
            try:
                loc = page.locator(sel).first
                if await loc.count() == 0 or not await loc.is_visible():
                    continue
                await loc.click(timeout=4000, delay=80, force=True)
                strategies.append(sel)
                await asyncio.sleep(1.0)
                break
            except Exception:
                continue

    if not strategies and await _click_cloudflare_via_js(page):
        strategies.append("shadow_dom_js")
        await asyncio.sleep(1.0)

    if strategies:
        from browser_bot.submit.common import log_resilience

        log_resilience(
            "cloudflare_click",
            "Cloudflare auto-click attempt",
            detail=", ".join(strategies),
        )
        return True
    return False


async def _cloudflare_click_diagnostics(page: "Page") -> str:
    """Short reason string when auto-click found no target."""
    iframe_count = 0
    turnstile_frames = 0
    for frame in page.frames:
        frame_url = (frame.url or "").lower()
        if "challenges.cloudflare.com" in frame_url or "turnstile" in frame_url:
            turnstile_frames += 1
    for sel in CLOUDFLARE_IFRAME_SELECTORS:
        try:
            iframe_count += await page.locator(sel).count()
        except Exception:
            continue
    if turnstile_frames or iframe_count:
        return (
            "Turnstile iframe present but no click landed "
            "(widget may still be loading, or Cloudflare blocked automated interaction)"
        )
    return "No Turnstile iframe or checkbox in the DOM (possible false detection or spinner-only page)"


def _emit_cloudflare_waiting(site: str, *, remaining_sec: float) -> None:
    from browser_bot.submit.common import log_genbounty_progress, log_resilience

    log_resilience(
        "cloudflare_wait",
        "Cloudflare challenge - waiting for verification",
        wait_sec=remaining_sec,
        detail="Complete the verification prompt in the visible browser window",
    )
    advice = [
        "Complete the Cloudflare human verification prompt in the live browser window.",
        "Settings → Browser: set Fetch Method to human and turn off Headless.",
        "Automated Turnstile bypass is unreliable; manual completion is expected for ChatGPT and similar targets.",
    ]
    log_genbounty_progress(
        {
            "type": "cloudflare_wait",
            "kind": "cloudflare",
            "message": "Cloudflare verification required - complete in the browser window.",
            "remaining_sec": max(0, int(remaining_sec)),
            "site": site,
        }
    )


def _emit_cloudflare_headed_required(site: str) -> None:
    from browser_bot.submit.common import log_genbounty_progress

    advice = [
        "Cloudflare Turnstile cannot be completed in a headless browser.",
        "Settings → Browser: turn Headless off for this component (pool/auto with a visible window is fine).",
        "Use Fetch Method pool or auto for throughput; human is optional unless you need maximum stealth.",
        "Re-run tests after saving settings; complete the checkbox once in the visible browser window.",
    ]
    log_genbounty_progress(
        {
            "type": "blocked",
            "kind": "cloudflare",
            "message": "Cloudflare requires a visible browser (Headless off).",
            "action": "prompt_cloudflare",
            "site": site,
            "needs_headed_browser": True,
            "stop_run": True,
            "fatal": True,
            "advice": advice,
        }
    )


async def _resolve_cloudflare_challenge(
    page: "Page",
    *,
    site: str,
    component: str,
) -> None:
    """Detect Cloudflare challenge, try auto-click, then wait for manual completion in the browser.

    Do **not** poll for the composer here: gated UIs only show the textarea after
    ``surface_prep``, and a 10×0.4s wait burned ~4s (×2 call sites ≈ 8s) on every
    clean page load before the first pre-step click.
    """
    if await _submission_ui_ready(page, site, component):
        return
    if not await _cloudflare_challenge_visible(page, site=site, component=component):
        return

    if _is_headless_browser(site=site, component=component):
        from browser_bot.submit.common import log_resilience

        log_resilience(
            "cloudflare_headed_required",
            "Cloudflare detected but browser is headless - Turnstile needs a visible window",
            detail="Set Headless=off (pool/auto with visible browser is fine), then re-run",
        )
        _emit_cloudflare_headed_required(site)
        raise PageBlockedError(
            "cloudflare",
            advice=[
                "Turn Headless off in Settings → Browser (component overrides). Pool or auto fetch method is OK.",
                "Re-run tests and complete the verification checkbox in the browser window.",
            ],
            message="Cloudflare requires a visible browser window.",
        )

    wait_sec = DEFAULT_CLOUDFLARE_WAIT_SEC
    try:
        from browser_bot.config import EVASION_RETRY_WAIT_S

        wait_sec = max(float(EVASION_RETRY_WAIT_S or 0), wait_sec)
    except Exception:
        pass
    wait_sec = min(max(wait_sec, 30.0), 180.0)

    from browser_bot.submit.common import log_resilience

    log_resilience(
        "cloudflare_detected",
        "Cloudflare challenge detected - auto-click then manual verification",
        wait_sec=wait_sec,
    )
    await _wait_for_turnstile_widget(page)

    deadline = time.monotonic() + wait_sec
    last_click = 0.0
    last_ui_emit = 0.0
    _emit_cloudflare_waiting(site, remaining_sec=wait_sec)

    while time.monotonic() < deadline:
        if await _submission_ui_ready(page, site, component):
            log_resilience(
                "cloudflare_cleared",
                "Chat composer ready - Cloudflare wait ended",
            )
            await _on_cloudflare_challenge_cleared(page, site=site, component=component)
            return
        if not await _cloudflare_challenge_visible(page, site=site, component=component):
            log_resilience("cloudflare_cleared", "Cloudflare challenge cleared")
            await _on_cloudflare_challenge_cleared(page, site=site, component=component)
            return

        now = time.monotonic()
        if now - last_click >= DEFAULT_CLOUDFLARE_CLICK_INTERVAL_SEC:
            last_click = now
            clicked = await _try_click_cloudflare_checkbox(page)
            if not clicked:
                reason = await _cloudflare_click_diagnostics(page)
                log_resilience(
                    "cloudflare_click",
                    "Cloudflare auto-click attempt (no checkbox target found)",
                    detail=reason,
                )

        if now - last_ui_emit >= 15.0:
            last_ui_emit = now
            _emit_cloudflare_waiting(site, remaining_sec=deadline - now)

        await asyncio.sleep(0.8)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            pass

    if not await _cloudflare_challenge_visible(page, site=site, component=component):
        log_resilience("cloudflare_cleared", "Cloudflare challenge cleared")
        await _on_cloudflare_challenge_cleared(page, site=site, component=component)
        return

    from browser_bot.submit.common import log_genbounty_progress, log_resilience

    log_resilience(
        "cloudflare_timeout",
        "Cloudflare verification timed out",
        wait_sec=wait_sec,
        detail="Complete the checkbox in the visible browser window",
    )
    advice = [
        "Cloudflare blocked automated verification.",
        "Settings → Browser: Fetch Method = human, Headless = off, then re-run tests.",
        "Complete sign-in and the Turnstile checkbox once in the visible browser before batch runs.",
    ]
    log_genbounty_progress(
        {
            "type": "blocked",
            "kind": "cloudflare",
            "message": "Cloudflare verification not completed in time.",
            "action": "prompt_cloudflare",
            "site": site,
            "stop_run": True,
            "fatal": True,
            "advice": advice,
        }
    )
    raise PageBlockedError(
        "cloudflare",
        advice=advice,
        message="Cloudflare verification not completed.",
    )


async def _detect_captcha(page: "Page", *, site: str = "", component: str = "") -> bool:
    if await _cloudflare_challenge_visible(page, site=site, component=component):
        return True
    try:
        body = (await page.inner_text("body")).lower()
    except Exception:
        body = ""
    if any(hint in body for hint in CAPTCHA_HINTS):
        return True
    for frame_sel in ('iframe[src*="recaptcha"]', 'iframe[src*="hcaptcha"]', '[class*="captcha"]'):
        try:
            if await page.locator(frame_sel).count() > 0:
                return True
        except Exception:
            continue
    return False


async def detect_heuristic_blockers(
    page: "Page",
    *,
    site: str,
    component: str,
    start_url: str,
    blockers: list[dict] | None = None,
    skip_cloudflare: bool = False,
) -> None:
    if await _login_wall_visible(page):
        login_url = _resolve_login_url(site, component, start_url)
        _emit_blocked_login(site, login_url)
        raise PageBlockedError("login_required", message="Sign-in required to continue tests.")

    if await _rate_limit_visible(page, blockers):
        await _resolve_rate_limit(page, site=site, component=component, blockers=blockers)

    if not skip_cloudflare:
        await _resolve_cloudflare_challenge(page, site=site, component=component)

    if await _detect_captcha(page, site=site, component=component):
        from browser_bot.submit.common import log_genbounty_progress

        log_genbounty_progress(
            {
                "type": "blocked",
                "kind": "captcha",
                "message": "CAPTCHA or security check detected.",
                "action": "manual",
                "site": site,
                "advice": ["Complete the CAPTCHA in the browser, then retry Run Tests."],
            }
        )
        raise PageBlockedError(
            "captcha",
            advice=["Complete the CAPTCHA manually, then retry."],
            message="CAPTCHA detected.",
        )


# Set on the Playwright page after surface_prep gates ran in ensure_page_ready_for_submit
# so _do_one_submit_step does not re-click them (multi-turn / same-page follow-ups).
_SURFACE_PREP_DONE_ATTR = "_genbounty_surface_prep_done"


def _inputs_have_surface_prep(inputs: list[dict] | None) -> bool:
    return any(
        isinstance(inp, dict) and inp.get("surface_prep") for inp in (inputs or [])
    )


async def ensure_page_ready_for_submit(
    page: "Page",
    *,
    site: str,
    component: str,
    inputs: list[dict],
    submit_selector: str,
    start_url: str,
    blockers: list[dict] | None = None,
) -> None:
    """Full pre-submit pipeline: login wall, cookies, cloudflare, readiness, heuristics.

    When ``surface_prep`` inputs are configured, gates run *before* readiness so we do
    not burn ~8s waiting for a textarea that only appears after those clicks.
    """
    await _resolve_login_wall(page, site=site, component=component, start_url=start_url)
    await _attempt_cookie_self_heal(page, site=site, component=component, blockers=blockers)
    await _resolve_login_wall(page, site=site, component=component, start_url=start_url)
    await _resolve_cloudflare_challenge(page, site=site, component=component)
    await _resolve_rate_limit(page, site=site, component=component, blockers=blockers)

    has_surface_prep = _inputs_have_surface_prep(inputs)
    # Fresh navigation: clear prior same-page mark so gates re-run after reload.
    try:
        setattr(page, _SURFACE_PREP_DONE_ATTR, False)
    except Exception:
        pass

    if has_surface_prep:
        try:
            from browser_bot.submit.common import ensure_submission_surface_ready

            await ensure_submission_surface_ready(page, inputs)
            setattr(page, _SURFACE_PREP_DONE_ATTR, True)
        except Exception:
            pass
        # Gates already waited; still allow a short poll if the composer is painting.
        ready_wait_ms = 2500
    else:
        ready_wait_ms = 8000

    warnings = await check_submission_readiness(
        page, inputs, submit_selector=submit_selector, wait_ms=ready_wait_ms
    )
    for w in warnings:
        print(f"[!] Readiness: {w}", flush=True)

    # Heuristics re-check Cloudflare; skip when gates just opened the composer so we
    # do not pay another challenge scan on every gated submit.
    await detect_heuristic_blockers(
        page,
        site=site,
        component=component,
        start_url=start_url,
        blockers=blockers,
        skip_cloudflare=has_surface_prep,
    )
