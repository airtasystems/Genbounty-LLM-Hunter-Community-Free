"""Sibling API-key auth is not a UI browser session; login profile is."""

from __future__ import annotations

import json

from browser_bot.auth_state import (
    auth_data_has_browser_session,
    resolve_browser_auth_read_path,
)
from browser_bot.browser.launcher import should_use_cdp_for_headed_request
from browser_bot.sites import (
    browser_ui_session_ready,
    get_browser_storage_state_path,
    get_login_profile_path,
    get_storage_state_path,
)


def _write_auth(path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_api_key_not_browser_session():
    assert not auth_data_has_browser_session(
        {
            "auth_mode": "api_key",
            "headers": {"Authorization": "Bearer x"},
            "cookies": [],
            "origins": [],
        }
    )


def test_session_cookies_are_browser_session():
    assert auth_data_has_browser_session(
        {
            "auth_mode": "session",
            "cookies": [{"name": "sid", "value": "1", "domain": ".example.com", "path": "/"}],
            "origins": [],
        }
    )


def test_sibling_api_key_ignored_for_browser_path(tmp_path, monkeypatch):
    import browser_bot.config as bb_config
    import browser_bot.sites as sites

    monkeypatch.setattr(sites, "SITES_DIR", tmp_path)
    monkeypatch.setattr(bb_config, "USE_CDP_BROWSER", False)

    site = "OpenAI"
    ui = "chatgpt"
    api = "gpt4o"
    _write_auth(
        tmp_path / site / api / "auth.json",
        {
            "auth_mode": "api_key",
            "api_key_env": "TARGET_API_KEY_OPENAI_GPT4O",
            "headers": {"Authorization": "Bearer x"},
            "cookies": [],
            "origins": [],
        },
    )

    # Still discoverable as generic auth (API reuse), but not for UI browsers.
    assert get_storage_state_path(site, ui) is not None
    assert get_browser_storage_state_path(site, ui) is None
    assert resolve_browser_auth_read_path(site, ui) is None
    assert not browser_ui_session_ready(site, ui)

    profile = get_login_profile_path(site, ui)
    profile.mkdir(parents=True)
    assert browser_ui_session_ready(site, ui)
    assert should_use_cdp_for_headed_request(
        headless=False, headed=True, site=site, component=ui
    )


def test_cdp_not_forced_when_headless(tmp_path, monkeypatch):
    import browser_bot.config as bb_config
    import browser_bot.sites as sites

    monkeypatch.setattr(sites, "SITES_DIR", tmp_path)
    monkeypatch.setattr(bb_config, "USE_CDP_BROWSER", False)
    site = "OpenAI"
    ui = "chatgpt"
    get_login_profile_path(site, ui).mkdir(parents=True)
    assert not should_use_cdp_for_headed_request(
        headless=True, site=site, component=ui
    )
