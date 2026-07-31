"""Welcome/intro ignore recording and filter priority."""

from __future__ import annotations

from browser_bot.record_submission import (
    _merge_response_ignore_into_submission,
    _phrase_for_response_ignore,
)
from browser_bot.submit.response_filters import (
    filter_context_from_submission,
    non_actionable_reason,
)


def test_phrase_for_response_ignore_normalizes():
    phrase = _phrase_for_response_ignore(
        "  Hi! I'm here to help you plan your trips.  "
    )
    assert phrase
    assert "here to help" in phrase.lower()


def test_phrase_for_response_ignore_rejects_tiny():
    assert _phrase_for_response_ignore("Hi!") == ""


def test_merge_response_ignore_into_submission_dedupes():
    sub: dict = {}
    first = _merge_response_ignore_into_submission(
        sub, "Hi! I'm here to help you plan your trips."
    )
    second = _merge_response_ignore_into_submission(
        sub, "Hi! I'm here to help you plan your trips."
    )
    assert first
    assert second is None
    assert sub["response_ignore_substrings"] == [first]


def test_recorded_intro_is_non_actionable_via_custom_ignore():
    intro = "Hi! I'm here to help you plan your trips."
    sub = {"response_ignore_substrings": [intro]}
    ctx = filter_context_from_submission(sub, prompt="Hello")
    assert non_actionable_reason(intro, ctx) == "custom_ignore"


def test_welcome_phrase_fallback_still_rejects():
    """Phrase heuristic remains a fallback when Configure intro was not recorded."""
    intro = "Hi! I'm here to help you plan your trips."
    ctx = filter_context_from_submission({}, prompt="Hello")
    assert non_actionable_reason(intro, ctx) == "assistant_welcome"


def test_intro_text_from_pick_context_uses_inner_text():
    """v2 pick_context payloads must yield text without a resolved selector."""
    import asyncio

    from browser_bot.record_submission import _intro_text_from_pick

    event = {
        "type": "pick_context",
        "innerText": "Hi! I'm here to help you plan your trips.",
        "browserSelector": "",
    }

    class _NoPage:
        pass

    text = asyncio.run(_intro_text_from_pick(_NoPage(), event))
    assert "here to help" in text
