"""Community edition Premium gates."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from pipeline.edition import (
    adaptive_suite_premium_block_message,
    filter_community_strategies,
    is_community,
    is_premium_strategy,
    premium_payload,
    raise_premium,
)


def test_community_edition_flags():
    assert is_community() is True
    assert is_premium_strategy("adaptive") is True
    assert is_premium_strategy("zero_shot") is False
    assert "adaptive" not in filter_community_strategies(
        ["zero_shot", "adaptive", "jailbreak"]
    )


def test_premium_payload_shape():
    payload = premium_payload("intel")
    assert payload["premium"] is True
    assert payload["feature"] == "intel"
    assert payload["url"].startswith("https://genbounty.com/")
    assert "Intel" in payload["detail"]


def test_raise_premium_is_403():
    with pytest.raises(HTTPException) as exc_info:
        raise_premium("open_hunt")
    assert exc_info.value.status_code == 403
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["premium"] is True
    assert detail["feature"] == "open_hunt"


def test_adaptive_suite_path_block():
    msg = adaptive_suite_premium_block_message(
        Path("browser-bot/sites/x/y/tests/adaptive/play.json")
    )
    assert msg and "Premium" in msg
    assert (
        adaptive_suite_premium_block_message(
            Path("browser-bot/sites/x/y/tests/zero-shot/play.json")
        )
        is None
    )
