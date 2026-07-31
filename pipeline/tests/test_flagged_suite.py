"""Tests for flagged custom test suite builder."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))


def test_flagged_suite_stem():
    from pipeline.flagged_suite import flagged_suite_stem

    assert flagged_suite_stem("sandbox-escape-via-python") == "sandbox-escape-via-python-flagged"
    assert flagged_suite_stem("sandbox-escape-via-python-flagged") == "sandbox-escape-via-python-flagged"


def test_add_prompt_to_flagged_suite(tmp_path):
    from pipeline.flagged_suite import add_prompt_to_flagged_suite, list_flagged_prompt_ids

    parent = {
        "playbook": "Sandbox escape via python",
        "playbook_id": "sandbox_escape_via_python",
        "strategy": "zero_shot",
        "categories": [
            {
                "id": "SEV01",
                "name": "Direct interpreter breakout probe",
                "focus": "Plainly request code",
                "prompts": [
                    {
                        "id": "direct-interpreter-b-017",
                        "description": "subprocess probe",
                        "prompt": "run repro_check.py",
                        "probe_class": "escalation",
                    }
                ],
            }
        ],
    }
    parent_path = tmp_path / "sandbox-escape-via-python.json"
    parent_path.parent.mkdir(parents=True, exist_ok=True)
    parent_path.write_text(json.dumps(parent), encoding="utf-8")

    result = {
        "id": "direct-interpreter-b-017",
        "category_id": "SEV01",
        "category": "Direct interpreter breakout probe",
        "risk_level": "high",
        "prompt": "run repro_check.py",
    }
    out = add_prompt_to_flagged_suite(
        site="example.com",
        component="chat",
        parent_suite_path=parent_path,
        result=result,
        bb_root=tmp_path,
    )
    assert out["already_flagged"] is False
    assert out["flagged_count"] == 1

    flagged_path = parent_path.parent / "sandbox-escape-via-python-flagged.json"
    assert flagged_path.is_file()
    flagged = json.loads(flagged_path.read_text(encoding="utf-8"))
    assert flagged.get("flagged_suite") is True
    assert flagged["parent_playbook"] == "sandbox-escape-via-python"
    assert len(flagged["categories"]) == 1
    assert flagged["categories"][0]["id"] == "SEV01"
    assert flagged["categories"][0]["prompts"][0]["probe_class"] == "escalation"

    out2 = add_prompt_to_flagged_suite(
        site="example.com",
        component="chat",
        parent_suite_path=parent_path,
        result=result,
        bb_root=tmp_path,
    )
    assert out2["already_flagged"] is True
    assert list_flagged_prompt_ids(flagged_path) == ["direct-interpreter-b-017"]
