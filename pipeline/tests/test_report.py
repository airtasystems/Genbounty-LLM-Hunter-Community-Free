"""Tests for pipeline report helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_RLA = _ROOT / "risk-level-agent" / "risk_level_agent.py"


def _ensure_risk_level_agent() -> None:
    if "risk_level_agent" in sys.modules:
        return
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    spec = importlib.util.spec_from_file_location("risk_level_agent", _RLA)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["risk_level_agent"] = mod
    spec.loader.exec_module(mod)


_ensure_risk_level_agent()

from pipeline.report import (  # noqa: E402
    build_pipeline_report,
    category_rollup_from_results,
    delete_adversarial_result,
)


def _row(rid: str, category: str, risk_level: str) -> dict:
    return {
        "id": rid,
        "category": category,
        "risk_level": risk_level,
        "prompt": f"p-{rid}",
        "response": f"r-{rid}",
    }


def test_delete_adversarial_result_by_id_recomputes_rollup():
    report = {
        "adversarial_results": [
            _row("a", "cat-a", "critical"),
            _row("b", "cat-a", "low"),
            _row("c", "cat-b", "high"),
        ],
        "category_rollup": {"cat-a": "critical", "cat-b": "high"},
    }

    removed, updated = delete_adversarial_result(report, prompt_id="a")

    assert removed["id"] == "a"
    assert [r["id"] for r in updated["adversarial_results"]] == ["b", "c"]
    assert updated["category_rollup"] == {"cat-a": "low", "cat-b": "high"}
    assert updated["category_rollup"] == category_rollup_from_results(
        updated["adversarial_results"]
    )


def test_delete_adversarial_result_by_position():
    report = {
        "adversarial_results": [
            _row("a", "x", "medium"),
            _row("b", "y", "high"),
        ],
    }

    removed, updated = delete_adversarial_result(report, position=1)

    assert removed["id"] == "b"
    assert [r["id"] for r in updated["adversarial_results"]] == ["a"]
    assert updated["category_rollup"] == {"x": "medium"}


def test_delete_adversarial_result_prefers_id_over_position():
    report = {
        "adversarial_results": [
            _row("a", "x", "low"),
            _row("b", "y", "high"),
        ],
    }

    removed, _ = delete_adversarial_result(report, prompt_id="b", position=0)
    assert removed["id"] == "b"


def test_delete_adversarial_result_missing_id():
    report = {"adversarial_results": [_row("a", "x", "low")]}
    with pytest.raises(KeyError, match="not found"):
        delete_adversarial_result(report, prompt_id="missing")


def test_delete_adversarial_result_empty_report():
    with pytest.raises(ValueError, match="no adversarial_results"):
        delete_adversarial_result({"adversarial_results": []}, prompt_id="a")


def test_delete_adversarial_result_requires_selector():
    report = {"adversarial_results": [_row("a", "x", "low")]}
    with pytest.raises(ValueError, match="prompt_id or position"):
        delete_adversarial_result(report)


def test_build_pipeline_report_stamps_oracle_model():
    rows = [
        {
            **_row("a", "x", "high"),
            "oracle_version": "1",
            "oracle_hash": "abc123",
        }
    ]
    report = build_pipeline_report({}, rows, "/tmp/run", "/tmp/attack.json")
    assert report["oracle_version"] == "1"
    assert report["oracle_hash"] == "abc123"
