"""Resolve multimodal test artifacts for browser-bot submission."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from payloads.resolve import (  # noqa: E402
    infer_strategy_from_suite_path,
    load_suite_multi_test_cases,
    load_suite_test_cases,
    resolve_test_artifact,
)

__all__ = [
    "infer_strategy_from_suite_path",
    "load_suite_multi_test_cases",
    "load_suite_test_cases",
    "resolve_test_artifact",
]
