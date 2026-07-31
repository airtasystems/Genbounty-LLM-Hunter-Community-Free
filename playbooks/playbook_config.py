"""Playbook-specific pipeline configuration (schema v3 extension).

Public import path remains ``from playbooks.playbook_config import …``.
Implementation lives in ``playbooks.config`` (constants, accessors, lexicon,
phase1_escalate, techniques, formatters, validate).
"""

from __future__ import annotations

from playbooks.config import *  # noqa: F403

from playbooks.config import __all__ as __all__  # noqa: E402,F401
