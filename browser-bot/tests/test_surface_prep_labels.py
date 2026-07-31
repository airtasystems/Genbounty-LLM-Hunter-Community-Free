"""Surface pre-step label → replay-safe selector helpers."""

from browser_bot.record_submission import (
    _gate_label_from_event,
    _is_rejected_surface_prep_selector,
    _labeled_gate_selector,
    _surface_prep_row_from_pick,
    is_generic_click_selector,
)


def test_gate_label_prefers_first_short_line():
    label = _gate_label_from_event(
        {"innerText": "Card title\nLonger description of the challenge"}
    )
    assert label.lower() == "card title"


def test_gate_label_multiline_card_uses_title_line():
    """Title line leads; later badge/score lines are ignored."""
    label = _gate_label_from_event({"innerText": "Tier 2\nready\n17/100"})
    assert label.lower() == "tier 2"


def test_gate_label_strips_score_noise():
    label = _gate_label_from_event({"innerText": "Tier 2 ready 17/100"})
    assert "17" not in label
    assert "tier 2" in label.lower()


def test_labeled_gate_selector_for_button():
    sel = _labeled_gate_selector(
        {"tag": "button", "role": "button", "innerText": "Show all options"}
    )
    assert sel is not None
    assert "Show all options" in sel
    assert "button:has-text" in sel


def test_surface_prep_row_rewrites_brittle_path():
    row = _surface_prep_row_from_pick(
        {
            "type": "pick_context",
            "selector": "div > div:nth-of-type(3) > button:nth-of-type(2)",
            "browserSelector": "div > div:nth-of-type(3) > button:nth-of-type(2)",
            "tag": "button",
            "role": "button",
            "innerText": "Tier 2",
        }
    )
    assert row is not None
    assert row.get("surface_prep") is True
    assert row.get("type") == "click"
    assert "Tier 2" in (row.get("selector") or "")
    assert ":nth-of-type" not in (row.get("selector") or "")
    assert row.get("name") == "Tier 2"


def test_surface_prep_row_rewrites_non_hint_card_label():
    """Pre-steps accept any short card label."""
    row = _surface_prep_row_from_pick(
        {
            "type": "pick_context",
            "selector": "div > div:nth-of-type(4) > div:nth-of-type(2)",
            "browserSelector": "div > div:nth-of-type(4) > div:nth-of-type(2)",
            "tag": "div",
            "role": "",
            "innerText": "Phishing basics\nEarn 100 points",
        }
    )
    assert row is not None
    assert "Phishing basics" in (row.get("selector") or "")
    assert ":nth-of-type" not in (row.get("selector") or "")


def test_surface_prep_div_card_not_button():
    """Clickable cards are often plain divs with nested title + progress UI."""
    row = _surface_prep_row_from_pick(
        {
            "type": "selector",
            "selector": "div.card-host",
            "tag": "div",
            "role": "",
            "innerText": "Tier 2\nready\n17/100",
        }
    )
    assert row is not None
    assert row.get("surface_prep") is True
    assert "Tier 2" in (row.get("selector") or "")
    assert ":text-is(" in (row.get("selector") or "")
    assert row.get("name", "").lower() == "tier 2"
    # Do not invent role=button for plain div cards (breaks get_by_role replay).
    assert row.get("role") in (None, "")


def test_labeled_gate_selector_div_prefers_text_is():
    sel = _labeled_gate_selector(
        {"tag": "div", "role": "", "innerText": "Tier 2\nready\n17/100"},
        loose=True,
    )
    assert sel is not None
    assert ':text-is("Tier 2")' in sel
    assert "div:has-text(" in sel


def test_has_text_selector_not_rejected_as_brittle():
    assert (
        _is_rejected_surface_prep_selector(
            'button:has-text("Tier 2")', inner_text="Tier 2"
        )
        is None
    )


def test_login_chrome_rejected_as_surface_prep():
    """Logged-out discovery must not persist Log in / Sign in as surface_prep."""
    for label in ("Log in", "Sign in", "Log in or sign up", "Sign up"):
        reason = _is_rejected_surface_prep_selector(
            f'button:has-text("{label}")', inner_text=label
        )
        assert reason, f"expected reject for {label!r}"
        assert "chrome" in reason.lower()


def test_generic_button_type_selector_detected():
    assert is_generic_click_selector('button[type="button"]')
    assert is_generic_click_selector("button[type=button]")
    assert is_generic_click_selector("button")
    assert not is_generic_click_selector('button:has-text("View all Levels")')


def test_surface_prep_rewrites_generic_button_selector():
    """browserSelector button[type=button] must not be persisted — it hits header icons."""
    row = _surface_prep_row_from_pick(
        {
            "type": "selector",
            "selector": 'button[type="button"]',
            "browserSelector": 'button[type="button"]',
            "tag": "button",
            "role": "button",
            "innerText": "View all Levels",
        }
    )
    assert row is not None
    assert "View all Levels" in (row.get("selector") or "")
    assert not is_generic_click_selector(str(row.get("selector") or "").split(",")[0])
    assert row.get("name") == "View all Levels"
