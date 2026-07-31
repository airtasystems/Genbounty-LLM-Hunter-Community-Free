"""Cloudflare stealth, CDP auto-enable, and clearance cookie persistence."""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).resolve().parents[2]
_BB = _ROOT / "browser-bot"
if str(_BB) not in sys.path:
    sys.path.insert(0, str(_BB))
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline.component_settings import (  # noqa: E402
    _force_cloudflare_pool_stealth,
    apply_browser_settings,
)


def test_force_stealth_when_fetch_method_human():
    settings: dict = {"FETCH_METHOD": "human", "POOL_CLUSTER_USE_STEALTH": False}
    _force_cloudflare_pool_stealth(
        settings, site=None, component=None, effective={}
    )
    assert settings["POOL_CLUSTER_USE_STEALTH"] is True
    assert settings["POOL_CLUSTER_USE_HUMAN_CONTEXT"] is True


def test_force_stealth_when_cloudflare_headed():
    settings: dict = {"FETCH_METHOD": "pool", "POOL_CLUSTER_USE_STEALTH": False}
    with patch(
        "pipeline.component_settings._submission_cloudflare_headed",
        return_value=True,
    ):
        _force_cloudflare_pool_stealth(
            settings, site="example.com", component="chat", effective={}
        )
    assert settings["POOL_CLUSTER_USE_STEALTH"] is True
    assert settings["POOL_CLUSTER_USE_HUMAN_CONTEXT"] is True


def test_force_stealth_noop_for_plain_pool():
    settings: dict = {
        "FETCH_METHOD": "pool",
        "POOL_CLUSTER_USE_STEALTH": False,
        "POOL_CLUSTER_USE_HUMAN_CONTEXT": False,
    }
    with patch(
        "pipeline.component_settings._submission_cloudflare_headed",
        return_value=False,
    ):
        _force_cloudflare_pool_stealth(
            settings, site="example.com", component="chat", effective={}
        )
    assert settings["POOL_CLUSTER_USE_STEALTH"] is False
    assert settings["POOL_CLUSTER_USE_HUMAN_CONTEXT"] is False


def test_apply_browser_settings_forces_stealth_for_human():
    target = types.ModuleType("fake_browser_config")
    effective = {
        "FETCH_METHOD": "human",
        "POOL_CLUSTER_USE_STEALTH": False,
        "POOL_CLUSTER_USE_HUMAN_CONTEXT": False,
        "POOL_SIZE": 1,
    }
    with patch(
        "pipeline.component_settings.get_effective_settings",
        return_value=effective,
    ), patch(
        "pipeline.component_settings._submission_cloudflare_headed",
        return_value=False,
    ):
        out = apply_browser_settings(
            site="example.com",
            component="chat",
            target_module=target,
        )
    assert out["POOL_CLUSTER_USE_STEALTH"] is True
    assert out["POOL_CLUSTER_USE_HUMAN_CONTEXT"] is True
    assert target.POOL_CLUSTER_USE_STEALTH is True
    assert target.POOL_CLUSTER_USE_HUMAN_CONTEXT is True


def test_should_use_cdp_for_cloudflare_headed_without_global_flag():
    from browser_bot.browser.launcher import should_use_cdp_for_headed_request

    with patch("browser_bot.config.use_cdp_browser", return_value=False), patch(
        "browser_bot.sites.load_component_config",
        return_value={"submission": {"cloudflare_headed": True}},
    ):
        assert should_use_cdp_for_headed_request(
            headless=False,
            headed=True,
            site="example.com",
            component="chat",
        ) is True


def test_should_use_cdp_false_when_headless():
    from browser_bot.browser.launcher import should_use_cdp_for_headed_request

    with patch("browser_bot.config.use_cdp_browser", return_value=True), patch(
        "browser_bot.sites.load_component_config",
        return_value={"submission": {"cloudflare_headed": True}},
    ):
        assert should_use_cdp_for_headed_request(
            headless=True,
            site="example.com",
            component="chat",
        ) is False


def test_should_use_cdp_false_without_flag_or_cloudflare():
    from browser_bot.browser.launcher import should_use_cdp_for_headed_request

    with patch("browser_bot.config.use_cdp_browser", return_value=False), patch(
        "browser_bot.sites.load_component_config",
        return_value={"submission": {}},
    ):
        assert should_use_cdp_for_headed_request(
            headless=False,
            headed=True,
            site="example.com",
            component="chat",
        ) is False


def test_merge_browser_cookies_into_auth_writes_cf_clearance():
    from browser_bot.auth_state import merge_browser_cookies_into_auth

    config = {
        "cookies": [
            {"name": "session", "value": "1", "domain": ".ex.com", "path": "/"},
        ],
        "origins": [],
        "auth_mode": "session",
    }
    saved: dict = {}

    async def storage_state():
        return {
            "cookies": [
                {
                    "name": "cf_clearance",
                    "value": "tok",
                    "domain": ".ex.com",
                    "path": "/",
                },
                {
                    "name": "unrelated",
                    "value": "x",
                    "domain": ".ex.com",
                    "path": "/",
                },
            ]
        }

    page = SimpleNamespace(context=SimpleNamespace(storage_state=storage_state))

    with patch(
        "browser_bot.auth_state.load_auth_config", return_value=config
    ), patch(
        "browser_bot.auth_state.save_auth_config",
        side_effect=lambda site, cfg, component=None: saved.update(cfg) or Path("."),
    ), patch(
        "browser_bot.auth_state.resolve_auth_scope", return_value="component"
    ), patch(
        "browser_bot.auth_state.resolve_auth_shared_from", return_value=None
    ):
        ok = asyncio.run(merge_browser_cookies_into_auth("ex.com", "chat", page))

    assert ok is True
    names = {c["name"] for c in saved["cookies"]}
    assert "cf_clearance" in names
    assert "session" in names
    assert "unrelated" not in names


def test_merge_browser_cookies_skips_api_key_auth():
    from browser_bot.auth_state import merge_browser_cookies_into_auth

    config = {
        "auth_mode": "api_key",
        "headers": {"Authorization": "Bearer x"},
        "cookies": [],
        "origins": [],
    }

    async def storage_state():
        return {
            "cookies": [
                {
                    "name": "cf_clearance",
                    "value": "tok",
                    "domain": ".ex.com",
                    "path": "/",
                }
            ]
        }

    page = SimpleNamespace(context=SimpleNamespace(storage_state=storage_state))

    with patch("browser_bot.auth_state.load_auth_config", return_value=config):
        ok = asyncio.run(merge_browser_cookies_into_auth("ex.com", "chat", page))
    assert ok is False


def test_merge_browser_cookies_noop_when_no_matching_cookie():
    from browser_bot.auth_state import merge_browser_cookies_into_auth

    config = {
        "cookies": [
            {"name": "session", "value": "1", "domain": ".ex.com", "path": "/"},
        ],
        "origins": [],
        "auth_mode": "session",
    }
    save = MagicMock()

    async def storage_state():
        return {
            "cookies": [
                {"name": "session", "value": "1", "domain": ".ex.com", "path": "/"},
            ]
        }

    page = SimpleNamespace(context=SimpleNamespace(storage_state=storage_state))

    with patch(
        "browser_bot.auth_state.load_auth_config", return_value=config
    ), patch(
        "browser_bot.auth_state.save_auth_config", save
    ), patch(
        "browser_bot.auth_state.resolve_auth_scope", return_value="component"
    ):
        ok = asyncio.run(merge_browser_cookies_into_auth("ex.com", "chat", page))

    assert ok is False
    save.assert_not_called()
