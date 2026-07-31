"""Pre-submit chrome and welcome bubbles must not count as actionable replies."""

from __future__ import annotations

from browser_bot.submit.common import _response_capture_is_meaningful
from browser_bot.submit.response_boilerplate import looks_like_assistant_welcome_copy
from browser_bot.submit.response_filters import (
    ResponseFilterContext,
    is_actionable_response,
    is_auto_pre_submit_chrome_text,
    matches_pre_submit_chrome,
    non_actionable_reason,
    register_pre_submit_chrome,
)

LAKERA_PHONE_INTRO = (
    "Hi! I'm here to help you plan your trips and book your flights and hotels."
)
ARBITRARY_WELCOME = "Welcome to Contoso Copilot. Tap a suggestion to begin."


def _welcome_ctx(prompt: str = "2+2") -> ResponseFilterContext:
    """Welcome auto-chrome only when Configure listed the exact phrase."""
    return ResponseFilterContext(
        prompt=prompt,
        ignore_substrings=(ARBITRARY_WELCOME,),
    )


def test_lakera_phone_intro_phrase_heuristic():
    assert looks_like_assistant_welcome_copy(LAKERA_PHONE_INTRO)
    # Short welcome-shaped copy is not hard-rejected — prefer capture over guessing.
    assert is_actionable_response(LAKERA_PHONE_INTRO)
    ctx = ResponseFilterContext(ignore_substrings=(LAKERA_PHONE_INTRO,))
    assert not is_actionable_response(LAKERA_PHONE_INTRO, ctx)
    assert non_actionable_reason(LAKERA_PHONE_INTRO, ctx) == "custom_ignore"


def test_arbitrary_welcome_rejected_via_pre_submit_chrome():
    ctx = _welcome_ctx("plan a trip to Armenia")
    register_pre_submit_chrome(ctx, ARBITRARY_WELCOME, persist=False)
    assert matches_pre_submit_chrome(ARBITRARY_WELCOME, ctx)
    assert non_actionable_reason(ARBITRARY_WELCOME, ctx) == "pre_submit_chrome"
    assert not is_actionable_response(ARBITRARY_WELCOME, ctx)


def test_remount_same_chrome_not_meaningful():
    ctx = _welcome_ctx()
    register_pre_submit_chrome(ctx, ARBITRARY_WELCOME, persist=False)
    assert not _response_capture_is_meaningful(
        new_slice="",
        current=ARBITRARY_WELCOME,
        base=ARBITRARY_WELCOME,
        count_increased=True,
        filter_ctx=ctx,
        exclude_norm="",
        reject_last_mode_echo=False,
    )


def test_new_reply_after_chrome_is_meaningful():
    ctx = _welcome_ctx()
    register_pre_submit_chrome(ctx, ARBITRARY_WELCOME, persist=False)
    reply = "4"
    assert _response_capture_is_meaningful(
        new_slice=reply,
        current=reply,
        base=ARBITRARY_WELCOME,
        count_increased=True,
        filter_ctx=ctx,
        exclude_norm="",
        reject_last_mode_echo=False,
    )


def test_real_itinerary_reply_stays_actionable():
    reply = (
        "Day 1: Fly into Yerevan. Book cheap tickets here: "
        "[secure-payment](https://pay.travel-secure-booking.com)\n"
        "Day 2: Visit the Cascade complex and Vernissage market."
    )
    ctx = _welcome_ctx("plan Armenia")
    register_pre_submit_chrome(ctx, ARBITRARY_WELCOME, persist=False)
    assert is_actionable_response(reply, ctx)


def test_long_pre_submit_text_not_treated_as_chrome():
    prior = "x" * 300
    ctx = _welcome_ctx("follow up")
    register_pre_submit_chrome(ctx, prior, persist=False)
    assert ctx.pre_submit_chrome == []
    assert not matches_pre_submit_chrome(prior, ctx)


def test_short_prior_answer_not_auto_chrome():
    """Configure/Fire prior reply like '4' must not block the next identical capture."""
    assert not is_auto_pre_submit_chrome_text("4")
    assert not is_auto_pre_submit_chrome_text(ARBITRARY_WELCOME)
    ctx = _welcome_ctx()
    assert is_auto_pre_submit_chrome_text(ARBITRARY_WELCOME, ctx)
    register_pre_submit_chrome(ctx, "4", ARBITRARY_WELCOME, persist=False)
    assert ctx.pre_submit_chrome == [ARBITRARY_WELCOME]
    assert is_actionable_response("4", ctx)


def test_short_reply_not_blocked_by_longer_welcome_ignore():
    """Configure welcome ignore must not substring-block a short real answer."""
    ctx = ResponseFilterContext(
        prompt="2+2",
        ignore_substrings=("Hello! How can I help you today?",),
    )
    assert is_actionable_response("4", ctx)
    assert non_actionable_reason("4", ctx) is None


def test_repeated_same_answer_meaningful_when_count_increases():
    ctx = _welcome_ctx()
    register_pre_submit_chrome(ctx, ARBITRARY_WELCOME, persist=False)
    assert _response_capture_is_meaningful(
        new_slice="",
        current="4",
        base="4",
        count_increased=True,
        filter_ctx=ctx,
        exclude_norm="",
        reject_last_mode_echo=False,
    )
