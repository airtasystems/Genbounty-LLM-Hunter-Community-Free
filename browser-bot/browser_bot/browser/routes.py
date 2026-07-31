"""Resource blocking for Playwright routes."""

from __future__ import annotations

import re

# URL hints when Chromium reports fetch/xhr/other instead of font|media|stylesheet.
_FONT_URL = re.compile(r"\.(woff2?|ttf|otf|eot)(\?|$)", re.I)
_MEDIA_URL = re.compile(r"\.(mp4|webm|mp3|ogg|wav|m4a|avi|mov)(\?|$)", re.I)
_STYLESHEET_URL = re.compile(r"\.css(\?|$)", re.I)


def _live_blocked_types() -> set:
    """Read BLOCKED_TYPES from config at call time (settings may apply after import)."""
    from browser_bot.config import BLOCKED_TYPES

    if isinstance(BLOCKED_TYPES, set):
        return set(BLOCKED_TYPES)
    if isinstance(BLOCKED_TYPES, (list, tuple)):
        return set(BLOCKED_TYPES)
    return set()


def get_blocked_types(*, allow_styles: bool = False) -> set:
    """Types to block for a browser context.

    BLOCKED_TYPES from settings is always honored for image/font/media/stylesheet.
    When allow_styles is False, stylesheets are blocked even if omitted from BLOCKED_TYPES.
    When allow_styles is True, stylesheets load unless explicitly listed in BLOCKED_TYPES.
    """
    blocked = _live_blocked_types()
    if not allow_styles:
        blocked.add("stylesheet")
    return blocked


def _should_block_request(request, blocked_types: set) -> bool:
    rtype = request.resource_type
    if rtype in blocked_types:
        return True
    url = request.url or ""
    if "stylesheet" in blocked_types and _STYLESHEET_URL.search(url):
        return True
    if "font" in blocked_types and _FONT_URL.search(url):
        return True
    if "media" in blocked_types and _MEDIA_URL.search(url):
        return True
    return False


async def block_resources(route, blocked_types: set | None = None):
    """Block images, fonts, media, stylesheets to speed up loading."""
    types = blocked_types if blocked_types is not None else get_blocked_types()
    if _should_block_request(route.request, types):
        await route.abort()
    else:
        await route.continue_()
