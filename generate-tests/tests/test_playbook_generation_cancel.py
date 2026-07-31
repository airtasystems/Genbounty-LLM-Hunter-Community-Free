"""Cancel checks during playbook authoring must stop between LLM attempts."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_GEN = _ROOT / "generate-tests"
for _path in (str(_ROOT), str(_GEN)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from playbook_generator import (  # noqa: E402
    PlaybookGenerationCancelled,
    generate_playbook_json,
)


def test_generate_playbook_json_honors_cancel_before_llm():
    cancelled = {"hit": False}

    def _cancel() -> bool:
        return True

    def _should_not_run(**_kwargs):
        cancelled["hit"] = True
        raise AssertionError("LLM author must not run after cancel")

    with patch("playbook_generator._generate_playbook_from_llm", side_effect=_should_not_run):
        with pytest.raises(PlaybookGenerationCancelled):
            generate_playbook_json(
                play="Demonstrate a concrete observable security outcome for cancel.",
                display_name="Cancel Probe",
                play_category="mission.hunt",
                play_category_path=["mission", "hunt"],
                play_category_label="Cancel probe",
                success_rules="Model reveals the secret.",
                failure_rules="Model refuses.",
                cancel_check=_cancel,
            )
    assert cancelled["hit"] is False
