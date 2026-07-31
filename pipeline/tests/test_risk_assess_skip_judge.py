"""Unit tests for single-call triage + skip-judge helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_RLA = _ROOT / "risk-level-agent" / "risk_level_agent.py"


def _load_rla():
    if "risk_level_agent" in sys.modules:
        return sys.modules["risk_level_agent"]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    spec = importlib.util.spec_from_file_location("risk_level_agent", _RLA)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["risk_level_agent"] = mod
    spec.loader.exec_module(mod)
    return mod


def _resp(**kwargs):
    base = {
        "parse_ok": True,
        "risk_level": "low",
        "confidence": "high",
        "exploit_status": "not_exploited",
        "reasoning": "Model refused cleanly.",
    }
    base.update(kwargs)
    return base


def test_expert_verdict_solid_high_confidence_elevated():
    rla = _load_rla()
    assert rla.expert_verdict_is_solid(_resp(risk_level="critical", confidence="high"))
    assert rla.expert_verdict_is_solid(_resp(risk_level="medium", confidence="high"))


def test_expert_verdict_requires_high_confidence_even_for_low():
    rla = _load_rla()
    assert not rla.expert_verdict_is_solid(_resp(risk_level="low", confidence="medium"))
    assert not rla.expert_verdict_is_solid(_resp(risk_level="informational", confidence=""))
    assert not rla.expert_verdict_is_solid(_resp(risk_level="low", confidence="low"))
    assert rla.expert_verdict_is_solid(_resp(risk_level="low", confidence="high"))


def test_expert_verdict_not_solid_when_ambiguous_or_broken():
    rla = _load_rla()
    assert not rla.expert_verdict_is_solid(
        _resp(risk_level="high", confidence="medium")
    )
    assert not rla.expert_verdict_is_solid(_resp(risk_level="high", confidence="low"))
    assert not rla.expert_verdict_is_solid(
        _resp(risk_level="indeterminate", confidence="high")
    )
    assert not rla.expert_verdict_is_solid(
        _resp(parse_ok=False, risk_level="low", confidence="high")
    )


def test_should_skip_judge_requires_agreement():
    rla = _load_rla()
    a = _resp(risk_level="low", confidence="high")
    b = _resp(risk_level="informational", confidence="high")
    assert rla.should_skip_judge([a])
    assert not rla.should_skip_judge([a, b])
    assert not rla.should_skip_judge(
        [a, _resp(risk_level="low", confidence="medium")]
    )
    assert rla.should_skip_judge(
        [a, _resp(risk_level="low", confidence="high")]
    )
    assert not rla.should_skip_judge(
        [a, _resp(risk_level="low", exploit_status="exploited")]
    )


def test_accept_expert_as_final_marks_reasoning():
    rla = _load_rla()
    out = rla.accept_expert_as_final(
        [_resp(risk_level="critical", confidence="high", reasoning="Leak confirmed.")]
    )
    assert out["final_answer"] == "critical"
    assert out["confidence"] == "high"
    assert out["exploit_status"] == "not_exploited"
    assert out["judge_reasoning"].startswith("[expert-accepted]")
    assert "Leak confirmed." in out["judge_reasoning"]


def test_judge_node_skips_llm_when_solid(monkeypatch):
    rla = _load_rla()
    calls = []

    def _boom(*_a, **_k):
        calls.append(1)
        raise AssertionError("judge must not call complete when expert is solid")

    monkeypatch.setattr(rla, "complete", _boom)
    state = {
        "user_query": "eval",
        "expert_responses": [
            _resp(risk_level="low", confidence="high", reasoning="Blocked.")
        ],
        "judge_reasoning": "",
        "final_answer": "",
        "confidence": "",
    }
    result = rla.judge_node(state)
    assert calls == []
    assert result["final_answer"] == "low"
    assert result["exploit_status"] == "not_exploited"
    assert result["judge_reasoning"].startswith("[expert-accepted]")


def test_judge_payload_extracts_nested_semantic_oracle_status():
    rla = _load_rla()
    reasoning, risk, confidence, status = rla._extract_judge_output_from_payload(
        {
            "response": {
                "reasoning": "The semantic rubric is satisfied by the concrete response.",
                "risk_level": "medium",
                "confidence": "high",
                "exploit_status": "exploited",
            }
        }
    )
    assert reasoning.startswith("The semantic rubric")
    assert risk == "medium"
    assert confidence == "high"
    assert status == "exploited"


def test_cache_record_retains_exploit_status(monkeypatch):
    rla = _load_rla()
    monkeypatch.setattr(rla, "LOCAL_CACHE_ENABLED", False)
    record = rla._save_cached_result(
        "evaluation",
        {
            "expert_responses": [],
            "judge_reasoning": "Semantic oracle matched.",
            "final_answer": "medium",
            "confidence": "high",
            "exploit_status": "exploited",
        },
        expert_ids=["expert_play"],
    )
    assert record["judge"]["exploit_status"] == "exploited"


def test_build_graph_expert_play_fallback_when_other_experts_exist(monkeypatch):
    """Regression: expert_play must remain a valid START entrypoint."""
    rla = _load_rla()
    rubric = {
        "playbook": "Synthetic play",
        "playbook_id": "synthetic_play",
        "play": "Exercise a synthetic assessment path.",
    }
    monkeypatch.setattr(
        "playbooks.registry.list_playbook_stems",
        lambda: ["synthetic_play"],
    )
    monkeypatch.setattr(
        "playbooks.registry.load_playbook",
        lambda stem: rubric if stem == "synthetic_play" else None,
    )
    rla.refresh_expert_registry()
    assert any(t[0] != "expert_play" for t in rla.EXPERT_DEFINITIONS)
    app = rla.build_graph(selected_expert_ids=["expert_play"])
    assert app is not None


def test_build_graph_unknown_playbook_does_not_crash():
    rla = _load_rla()
    ids = rla.get_experts_for_playbook("no_such_playbook_zzz")
    assert ids == ["expert_play"]
    app = rla.build_graph(selected_expert_ids=ids)
    assert app is not None


def test_get_experts_refreshes_for_on_disk_playbook(monkeypatch):
    rla = _load_rla()
    rubric = {
        "playbook": "Custom hunt",
        "playbook_id": "custom_hunt",
        "play": "Exercise a custom assessment path.",
    }
    monkeypatch.setattr(
        "playbooks.registry.list_playbook_stems",
        lambda: ["custom_hunt"],
    )
    monkeypatch.setattr(
        "playbooks.registry.load_playbook",
        lambda stem: rubric if stem == "custom_hunt" else None,
    )
    # Simulate a long-lived process whose cache predates an existing playbook.
    rla.EXPERT_DEFINITIONS = [
        (
            "expert_direct_instruction_override",
            "Direct Instruction Override",
            "Assess.",
        )
    ]
    rla.PLAYBOOK_TO_EXPERT = {
        "direct_instruction_override": "expert_direct_instruction_override"
    }
    rla._EXPERT_PLAYBOOK_ID = {
        "expert_direct_instruction_override": "direct_instruction_override"
    }
    ids = rla.get_experts_for_playbook("custom_hunt")
    assert ids == ["expert_custom_hunt"]
    app = rla.build_graph(selected_expert_ids=ids)
    assert app is not None


def test_promote_nested_verdict_from_reasoning_json():
    rla = _load_rla()
    nested = (
        '{\n  "playbook": "Hidden reasoning leak",\n'
        '  "risk_level": "low",\n'
        '  "exploit_status": "not_exploited",\n'
        '  "reasoning": "The model cleanly refused to expose its internal deliberation.",\n'
        '  "confidence": "high"\n}'
    )
    promoted = rla._promote_nested_verdict_fields(
        {
            "playbook": "Hidden reasoning leak",
            "risk_level": "indeterminate",
            "exploit_status": "unknown",
            "reasoning": nested,
        }
    )
    assert promoted["risk_level"] == "low"
    assert promoted["exploit_status"] == "not_exploited"
    assert promoted["confidence"] == "high"
    assert "cleanly refused" in promoted["reasoning"]
    assert promoted["reasoning"].startswith("{") is False


def test_extract_judge_output_promotes_nested_reasoning_json():
    rla = _load_rla()
    nested = (
        '{"risk_level":"low","exploit_status":"not_exploited",'
        '"confidence":"high","reasoning":"Clean refusal of deliberation leak."}'
    )
    reasoning, risk, confidence, status = rla._extract_judge_output_from_payload(
        {"reasoning": nested}
    )
    assert risk == "low"
    assert status == "not_exploited"
    assert confidence == "high"
    assert "Clean refusal" in reasoning
