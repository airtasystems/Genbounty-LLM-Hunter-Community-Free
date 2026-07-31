"""Surface pre-steps: start-surface detection, merge order, and runtime replay."""

from __future__ import annotations

import pytest

from browser_bot.record_submission import (
    _detect_start_surface_from_html,
    _is_rejected_initial_popup_selector,
    _is_rejected_surface_prep_selector,
    _merge_detected_inputs,
    _merge_surface_pre_steps,
    _upload_prep_config,
)
from browser_bot.submit.common import (
    _selector_matches_by_contained_text,
    _selector_part_priority,
    _split_selector_alternates,
    inputs_for_submission,
)

pytest.importorskip("bs4")


def test_detect_start_surface_matches_lakera_cta():
    html = """
    <html><body>
      <button type="button">Start your Attack</button>
      <button type="submit">Send</button>
    </body></html>
    """
    rows = _detect_start_surface_from_html(html)
    assert rows, "expected Start your Attack prep click"
    assert all(r.get("upload_prep") is True for r in rows)
    assert all(r.get("surface_prep") is True for r in rows)
    assert all(r.get("type") == "click" for r in rows)
    joined = " ".join(r["selector"] for r in rows)
    assert "Start your Attack" in joined
    assert "Send" not in joined


def test_detect_start_surface_ignores_submit_only():
    html = '<html><body><button>Send</button><button>Submit</button></body></html>'
    assert _detect_start_surface_from_html(html) == []


def test_merge_puts_surface_pre_steps_first():
    surface = [_upload_prep_config("text=Level 3", kind="click", surface=True)]
    dropdowns = [{"selector": "#model", "type": "select", "upload_prep": True}]
    files = [{"selector": "input[type=file]", "type": "file", "path_from": "payload"}]
    llm = [{"selector": "textarea", "type": "textarea"}]
    menus = [_upload_prep_config('button[aria-haspopup="menu"]', kind="click")]

    merged = _merge_detected_inputs(
        dropdowns,
        files,
        llm,
        prep_menuitems=menus,
        surface_pre_steps=surface,
    )
    assert [r["selector"] for r in merged] == [
        "text=Level 3",
        "#model",
        'button[aria-haspopup="menu"]',
        "input[type=file]",
        "textarea",
    ]
    assert merged[0].get("upload_prep") is True
    assert merged[0].get("surface_prep") is True


def test_upload_prep_config_shape():
    row = _upload_prep_config('button:has-text("Get started")')
    assert row == {
        "selector": 'button:has-text("Get started")',
        "type": "click",
        "upload_prep": True,
    }
    surface = _upload_prep_config('button:has-text("Start your Attack")', surface=True)
    assert surface.get("surface_prep") is True
    assert surface.get("upload_prep") is True


def test_merge_surface_dedupes_start_label_variants():
    recorded = [
        _upload_prep_config("text=Start your Attack", kind="click", surface=True)
    ]
    heuristic = _detect_start_surface_from_html(
        '<button type="button">Start your Attack</button>'
    )
    assert heuristic, "heuristic should find CTA"
    merged = _merge_surface_pre_steps(recorded, heuristic)
    assert len(merged) == 1
    assert merged[0]["selector"] == "text=Start your Attack"


def test_split_selector_alternates_keeps_quoted_commas():
    parts = _split_selector_alternates(
        'button:has-text("A, B"), [role="button"]:has-text("A, B"), text=Level 2'
    )
    assert parts == [
        'button:has-text("A, B")',
        '[role="button"]:has-text("A, B")',
        "text=Level 2",
    ]
    assert _selector_matches_by_contained_text("text=Level 2")
    assert _selector_matches_by_contained_text('div:has-text("Level 2")')
    assert not _selector_matches_by_contained_text("button[type=submit]")


def test_selector_part_priority_prefers_text_is():
    parts = [
        'div:has-text("Tier 2")',
        "text=Tier 2",
        ':text-is("Tier 2")',
        'button:has-text("Tier 2")',
    ]
    ordered = sorted(parts, key=_selector_part_priority)
    assert ordered[0].startswith(":text-is(")
    assert ordered[1].startswith("button:has-text")


def test_reject_fragile_and_chrome_surface_prep():
    # Pre-steps allow brittle paths (rewritten to has-text when possible).
    assert (
        _is_rejected_surface_prep_selector(
            "div > div > div:nth-of-type(3) > button",
            inner_text="Challenge card",
        )
        is None
    )
    assert _is_rejected_surface_prep_selector(
        'button:has-text("Collapse")', inner_text="Collapse"
    )
    assert not _is_rejected_surface_prep_selector(
        'button:has-text("Start your Attack")', inner_text="Start your Attack"
    )


def test_initial_popup_allows_close_label():
    """Cookie Close/Accept must not be rejected like Collapse chrome."""
    assert _is_rejected_initial_popup_selector('button:has-text("Close")') is None
    assert _is_rejected_initial_popup_selector('button:has-text("Accept")') is None
    assert _is_rejected_initial_popup_selector("div > div:nth-of-type(2) > button")


def test_inputs_for_submission_keeps_surface_prep_on_text_runs():
    """Regression: text-only runs used to strip all upload_prep/click rows."""
    inputs = [
        _upload_prep_config(
            'button:has-text("Start your Attack")', kind="click", surface=True
        ),
        _upload_prep_config('button:has-text("Level 3")', kind="click", surface=True),
        {"selector": "textarea", "type": "textarea"},
        _upload_prep_config('button[aria-haspopup="menu"]', kind="click"),
    ]
    active = inputs_for_submission(inputs)
    sels = [r["selector"] for r in active]
    assert 'button:has-text("Start your Attack")' in sels
    assert 'button:has-text("Level 3")' in sels
    assert "textarea" in sels
    assert 'button[aria-haspopup="menu"]' not in sels


def test_dismiss_overlay_label_matches_common_buttons():
    from browser_bot.submit.common import _DISMISS_OVERLAY_LABEL_RE

    assert _DISMISS_OVERLAY_LABEL_RE.match("Accept")
    assert _DISMISS_OVERLAY_LABEL_RE.match("Got it")
    assert _DISMISS_OVERLAY_LABEL_RE.match("Close")
    assert not _DISMISS_OVERLAY_LABEL_RE.match("Start your Attack")
