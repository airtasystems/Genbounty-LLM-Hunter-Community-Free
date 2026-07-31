"""Pipeline clean-lane contracts and unit checks."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def test_pipeline_clean_lane_js_contracts():
    pipeline = (_ROOT / "web/static/js/tabs/pipeline.js").read_text(encoding="utf-8")
    starters = (_ROOT / "web/static/js/tabs/run-starters.js").read_text(encoding="utf-8")
    modal = (_ROOT / "web/static/partials/modals/pipeline-run.html").read_text(
        encoding="utf-8"
    )

    assert "allowCustomEnhance" in starters
    assert "opts.allowCustomEnhance === true" in starters
    assert "allowCustomEnhance: true" in starters  # Run tab
    assert "allowCustomEnhance: !!pipelineAllowCustomEnhance" in pipeline
    assert "useCustomEnhance" in pipeline
    assert "Use Run custom enhance" in modal
    assert "Hunt mode" in modal
    assert 'v-model="run.huntMode"' in modal
    assert "pipelineHuntMode" in modal
    assert "huntMode: run.huntMode" in pipeline

    assert "theory-history?" in pipeline
    assert "Cleared theory history" in pipeline
    assert "clear_elite" in pipeline
    assert "reseed elite" in pipeline
    assert "forceSuiteRegen" in pipeline
    assert "pipelineForceSuiteRegen" in pipeline
    assert "Invalidated" in pipeline and "clean lane regen" in pipeline

    assert "playbook: enhancePlay" in pipeline
    assert "strategy: enhanceStrat" in pipeline
    assert "Baseline Attack" in pipeline
    assert "baselineSuite" in pipeline
    assert "startJob('run_tests'" in pipeline

    jobs = (_ROOT / "web/jobs.py").read_text(encoding="utf-8")
    assert "mutate_followup_deferred" in jobs
    assert "_baseline_run_suite_before_enhance" in jobs
    assert "_play_has_fresh_assessment" in jobs
    assert "never enhanced cold" in jobs or "Baseline: running existing suite" in jobs
    assert "escalate_followup_deferred" in jobs
    assert "_bounty_stop_followup_decision" in jobs
    assert "Bounty stop deferred one round for" in jobs
    assert 'reason="hit"' in jobs or "reason='hit'" in jobs
    assert "maybe_write_handoff_after_enhance" in jobs


def test_report_matches_rejects_empty_strategy_when_filter_set():
    import sys

    gen = str(_ROOT / "generate-tests")
    if gen not in sys.path:
        sys.path.insert(0, gen)
    from strategies.prior_results import _report_matches

    report = {"playbook_id": "cot_hunt_id", "strategy": ""}
    assert _report_matches(report, "cot_hunt_id", "zero_shot") is False
    report2 = {"playbook_id": "cot_hunt_id", "strategy": "zero_shot"}
    assert _report_matches(report2, "cot_hunt_id", "zero_shot") is True
    assert _report_matches(report2, "cot_hunt_id", "jailbreak") is False
    # No strategy filter → still matches (any strategy).
    assert _report_matches(report, "cot_hunt_id", None) is True


def test_attack_log_matches_rejects_empty_strategy():
    import sys

    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from web.jobs import _attack_log_matches_play

    log = {"playbook_id": "cot_hunt_id", "strategy": ""}
    assert _attack_log_matches_play(log, "cot_hunt_id", "zero_shot") is False
    log2 = {"playbook_id": "cot_hunt_id", "strategy": "zero-shot"}
    assert _attack_log_matches_play(log2, "cot_hunt_id", "zero_shot") is True


def test_intel_strategy_slice_write_and_read():
    import sys

    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from pipeline.intel import empty_intel, resolve_intel_for_strategy
    from pipeline.recon_from_report import apply_report_intel_merge

    base = empty_intel("cot_hunt_id")
    assert "by_strategy" in base

    delta = {
        "security_observations": ["jailbreak-specific note"],
        "recon_findings": ["finding from jailbreak"],
    }
    ctx = {
        "pipeline_report": "/tmp/r.json",
        "last_strategy": "jailbreak",
        "playbook_id": "cot_hunt_id",
    }
    merged = apply_report_intel_merge(base, delta, ctx)
    assert "jailbreak" in (merged.get("by_strategy") or {})
    slice_jb = merged["by_strategy"]["jailbreak"]
    assert any(
        (isinstance(x, dict) and "jailbreak-specific" in str(x.get("text") or ""))
        or "jailbreak-specific" in str(x)
        for x in (slice_jb.get("security_observations") or [])
    )

    # Second strategy gets its own slice; top-level still unions.
    delta2 = {"security_observations": ["zero-shot note only"]}
    ctx2 = {
        "pipeline_report": "/tmp/r2.json",
        "last_strategy": "zero_shot",
        "playbook_id": "cot_hunt_id",
    }
    merged2 = apply_report_intel_merge(merged, delta2, ctx2)
    by = merged2.get("by_strategy") or {}
    assert "zero_shot" in by
    resolved_zs = resolve_intel_for_strategy(merged2, "zero_shot")
    zs_obs = resolved_zs.get("security_observations") or []
    assert any("zero-shot note" in str(x) for x in zs_obs)
    # Jailbreak slice still has its note when resolved for jailbreak.
    resolved_jb = resolve_intel_for_strategy(merged2, "jailbreak")
    jb_obs = resolved_jb.get("security_observations") or []
    assert any("jailbreak-specific" in str(x) for x in jb_obs)
    # Missing strategy falls back to top-level (union).
    resolved_missing = resolve_intel_for_strategy(merged2, "cot")
    assert resolved_missing is merged2 or len(
        resolved_missing.get("security_observations") or []
    ) >= 1
