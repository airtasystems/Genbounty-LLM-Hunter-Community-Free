"""Browser launch and control."""

from browser_bot.browser.launcher import (
    launch_browser,
    launch_context_for_request,
    launch_context_with_routes,
)
from browser_bot.browser.routes import block_resources

__all__ = [
    "launch_browser",
    "launch_context_for_request",
    "launch_context_with_routes",
    "block_resources",
]
