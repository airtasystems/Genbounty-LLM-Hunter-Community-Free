"""API-key-only sibling auth must not wipe persistent profile cookies."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from browser_bot.browser.launcher import apply_site_auth_to_context


def test_api_key_only_auth_skips_clear_and_apply():
    context = MagicMock()
    context.clear_cookies = AsyncMock()

    api_key_auth = {
        "auth_mode": "api_key",
        "api_key_env": "TARGET_API_KEY_OPENAI_GPT4O",
        "headers": {"Authorization": "Bearer x"},
        "cookies": [],
        "origins": [],
    }

    with patch(
        "browser_bot.browser.launcher.load_auth_config_for_site",
        return_value=api_key_auth,
    ):
        applied = asyncio.run(
            apply_site_auth_to_context(
                context, "OpenAI", component="chatgpt", replace_cookies=True
            )
        )

    assert applied is False
    context.clear_cookies.assert_not_called()


def test_session_cookies_still_replace_when_requested():
    context = MagicMock()
    context.clear_cookies = AsyncMock()
    context.add_cookies = AsyncMock()
    context.add_init_script = AsyncMock()
    context.set_extra_http_headers = AsyncMock()

    session_auth = {
        "auth_mode": "session",
        "cookies": [{"name": "sid", "value": "1", "domain": ".example.com", "path": "/"}],
        "origins": [],
        "headers": {},
    }

    with (
        patch(
            "browser_bot.browser.launcher.load_auth_config_for_site",
            return_value=session_auth,
        ),
        patch(
            "browser_bot.browser.launcher.seed_auth_local_storage",
            new_callable=AsyncMock,
        ),
    ):
        applied = asyncio.run(
            apply_site_auth_to_context(
                context, "example.com", component="chat", replace_cookies=True
            )
        )

    assert applied is True
    context.clear_cookies.assert_awaited_once()
