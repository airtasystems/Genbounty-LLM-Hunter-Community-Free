"""Enhance hunt mode: compliance vs bug-bounty vs open-hunt.

Compliance keeps today's freeze/escalate rails. Bug Bounty and Open Hunt use
the elite+novelty self-improving loop aimed at reportable findings.
"""
from __future__ import annotations

import os
from typing import Any

HUNT_MODE_COMPLIANCE = "compliance"
HUNT_MODE_BUG_BOUNTY = "bug_bounty"
HUNT_MODE_OPEN_HUNT = "open_hunt"

HUNT_MODES = frozenset(
    {
        HUNT_MODE_COMPLIANCE,
        HUNT_MODE_BUG_BOUNTY,
        HUNT_MODE_OPEN_HUNT,
    }
)

BOUNTY_STYLE_MODES = frozenset({HUNT_MODE_BUG_BOUNTY, HUNT_MODE_OPEN_HUNT})

ENV_HUNT_MODE = "GENBOUNTY_HUNT_MODE"
ENV_OPEN_BROADEN = "GENBOUNTY_OPEN_BROADEN"


def normalize_hunt_mode(raw: Any) -> str:
    m = str(raw or "").strip().lower().replace("-", "_")
    if m in ("bounty", "bugbounty"):
        return HUNT_MODE_BUG_BOUNTY
    if m in ("open", "openhunt"):
        return HUNT_MODE_OPEN_HUNT
    if m in HUNT_MODES:
        return m
    return HUNT_MODE_COMPLIANCE


def is_bounty_style(mode: Any = None) -> bool:
    """True for bug_bounty or open_hunt (elite+novelty loop)."""
    if mode is None:
        mode = os.getenv(ENV_HUNT_MODE, HUNT_MODE_COMPLIANCE)
    return normalize_hunt_mode(mode) in BOUNTY_STYLE_MODES


def is_open_hunt(mode: Any = None) -> bool:
    try:
        from pipeline.edition import is_community

        if is_community():
            return False
    except ImportError:
        # Fail closed without edition helpers (Community ships edition.py).
        return False
    if mode is None:
        mode = os.getenv(ENV_HUNT_MODE, HUNT_MODE_COMPLIANCE)
    return normalize_hunt_mode(mode) == HUNT_MODE_OPEN_HUNT


def current_hunt_mode() -> str:
    return normalize_hunt_mode(os.getenv(ENV_HUNT_MODE, HUNT_MODE_COMPLIANCE))


def open_broaden_enabled() -> bool:
    """True when Open Hunt stagnation armed hypothesis-broadening this round."""
    try:
        from pipeline.edition import is_community

        if is_community():
            return False
    except ImportError:
        return False
    return os.getenv(ENV_OPEN_BROADEN, "").strip() == "1"
