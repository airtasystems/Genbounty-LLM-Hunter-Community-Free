"""Configure must keep +/attach as upload_menu; YAML and normalize stamp it."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from browser_bot.component_config_yaml import _format_inputs
from browser_bot.record_submission import (
    _detect_upload_menu_triggers_from_html,
    _event_looks_like_upload_menu_trigger,
    _merge_detected_inputs,
    _normalize_discovered_input,
    _resolve_upload_file_config,
    _selector_looks_like_upload_menu_trigger,
    _upload_menu_config,
    _upload_prep_config,
)

pytest.importorskip("bs4")


def test_upload_menu_config_shape():
    row = _upload_menu_config("#composer-plus-btn")
    assert row == {
        "selector": "#composer-plus-btn",
        "type": "click",
        "upload_prep": True,
        "upload_menu": True,
    }


def test_selector_looks_like_upload_menu_trigger():
    assert _selector_looks_like_upload_menu_trigger("#composer-plus-btn")
    assert _selector_looks_like_upload_menu_trigger(
        'button[aria-label="More actions"]'
    )
    assert _selector_looks_like_upload_menu_trigger(
        'button[aria-haspopup="menu"]'
    )
    assert not _selector_looks_like_upload_menu_trigger(
        '[data-testid="send-button"]'
    )


def test_event_looks_like_upload_menu_trigger():
    assert _event_looks_like_upload_menu_trigger(
        {
            "tag": "button",
            "ariaLabel": "More actions",
            "ariaHaspopup": "menu",
            "innerText": "+",
        },
        "#composer-plus-btn",
    )
    assert not _event_looks_like_upload_menu_trigger(
        {
            "tag": "button",
            "ariaLabel": "Send prompt",
            "dataTestId": "send-button",
        },
        '[data-testid="send-button"]',
    )


def test_upload_prep_config_stamps_upload_menu_for_plus():
    row = _upload_prep_config("#composer-plus-btn", kind="click")
    assert row.get("upload_menu") is True
    assert row.get("type") == "click"


def test_normalize_discovered_input_stamps_upload_menu():
    row = _normalize_discovered_input(
        {"selector": "#composer-plus-btn", "type": "click", "upload_prep": True}
    )
    assert row is not None
    assert row.get("upload_menu") is True


def test_yaml_emits_upload_menu():
    lines = _format_inputs(
        [
            _upload_menu_config("#composer-plus-btn"),
            {
                "selector": 'input[type="file"]',
                "type": "file",
                "path_from": "payload",
            },
        ]
    )
    text = "\n".join(lines)
    assert "upload_menu: true" in text
    assert "upload_prep: true" in text
    assert 'input[type="file"]' in text or "input[type=\\\"file\\\"]" in text


def test_merge_keeps_upload_menu_before_file():
    menus = [_upload_menu_config("#composer-plus-btn")]
    files = [{"selector": "input[type=file]", "type": "file", "path_from": "payload"}]
    llm = [{"selector": "#prompt-textarea", "type": "contenteditable"}]
    merged = _merge_detected_inputs([], files, llm, prep_menuitems=menus)
    assert merged[0]["selector"] == "#composer-plus-btn"
    assert merged[0].get("upload_menu") is True
    assert merged[1]["type"] == "file"


def test_detect_upload_menu_triggers_from_html_chatgpt_plus():
    html = """
    <html><body>
      <button id="composer-plus-btn" aria-haspopup="menu" aria-label="More actions">+</button>
      <input type="file" />
      <button data-testid="send-button">Send</button>
    </body></html>
    """
    rows = _detect_upload_menu_triggers_from_html(html)
    assert rows
    assert any(r.get("upload_menu") for r in rows)
    joined = " ".join(r["selector"] for r in rows)
    assert "composer-plus" in joined.lower() or "More actions" in joined


@pytest.mark.asyncio
async def test_resolve_upload_file_config_keeps_plus_as_menu():
    page = MagicMock()
    event = {
        "tag": "button",
        "inputType": "",
        "role": "button",
        "selector": "#composer-plus-btn",
        "browserSelector": "#composer-plus-btn",
        "ariaLabel": "More actions",
        "ariaHaspopup": "menu",
        "innerText": "+",
        "dataTestId": "composer-plus-btn",
    }

    async def _fake_detect(_page):
        return {
            "supports_upload": True,
            "file_inputs": [
                {
                    "selector": 'input[type="file"]',
                    "visible": False,
                    "unique": True,
                }
            ],
        }

    with (
        patch(
            "browser_bot.record_submission._detect_upload_capabilities",
            new=AsyncMock(side_effect=_fake_detect),
        ),
        patch(
            "browser_bot.record_submission._verify_selector_on_page",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "browser_bot.record_submission._best_action_selector",
            return_value="#composer-plus-btn",
        ),
    ):
        cfg = await _resolve_upload_file_config(page, event)

    assert cfg is not None
    assert cfg.get("type") == "click"
    assert cfg.get("upload_menu") is True
    assert cfg.get("selector") == "#composer-plus-btn"


@pytest.mark.asyncio
async def test_resolve_real_file_input_stays_file():
    page = MagicMock()
    event = {
        "tag": "input",
        "inputType": "file",
        "selector": 'input[type="file"]',
        "browserSelector": 'input[type="file"]',
    }
    with patch(
        "browser_bot.record_submission._best_action_selector",
        return_value='input[type="file"]',
    ):
        cfg = await _resolve_upload_file_config(page, event)
    assert cfg == {
        "selector": 'input[type="file"]',
        "type": "file",
        "path_from": "payload",
    }


def test_upload_menu_not_skipped_semantics_in_fill_gate():
    """upload_menu must not be treated as skippable upload_prep when composer usable."""
    from browser_bot.submit.common import _input_wants_upload_menu

    assert _input_wants_upload_menu(_upload_menu_config("#composer-plus-btn"))
    assert not _input_wants_upload_menu(
        {"selector": "button", "type": "click", "upload_prep": True}
    )
