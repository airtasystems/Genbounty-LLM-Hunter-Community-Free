"""Baseline-before-enhance: never enhance cold suites."""

from __future__ import annotations

from pathlib import Path

from web.jobs import _attack_log_needs_assessment, _play_has_fresh_assessment


def test_attack_log_needs_assessment_missing_report(tmp_path: Path):
    log = tmp_path / "attack_log.json"
    log.write_text("{}", encoding="utf-8")
    assert _attack_log_needs_assessment(log) is True


def test_attack_log_fresh_when_report_newer(tmp_path: Path):
    log = tmp_path / "attack_log.json"
    report = tmp_path / "pipeline_report.json"
    log.write_text("{}", encoding="utf-8")
    report.write_text("{}", encoding="utf-8")
    # Ensure report mtime >= log mtime.
    log.touch()
    report.touch()
    assert _attack_log_needs_assessment(log) is False


def test_play_has_fresh_assessment_none(monkeypatch):
    monkeypatch.setattr(
        "web.jobs._find_latest_attack_log_for_play",
        lambda *_a, **_k: None,
    )
    assert (
        _play_has_fresh_assessment("Site", "comp", "cot_hunt_fixture", "zero_shot")
        is False
    )


def test_play_has_fresh_assessment_true(tmp_path: Path, monkeypatch):
    log = tmp_path / "attack_log.json"
    report = tmp_path / "pipeline_report.json"
    log.write_text("{}", encoding="utf-8")
    report.write_text("{}", encoding="utf-8")
    log.touch()
    report.touch()
    monkeypatch.setattr(
        "web.jobs._find_latest_attack_log_for_play",
        lambda *_a, **_k: log,
    )
    assert (
        _play_has_fresh_assessment("Site", "comp", "cot_hunt_fixture", "zero_shot")
        is True
    )


def test_baseline_skips_when_fresh(monkeypatch, tmp_path: Path):
    import asyncio
    from types import SimpleNamespace

    from web.jobs import _baseline_run_suite_before_enhance

    log = tmp_path / "attack_log.json"
    report = tmp_path / "pipeline_report.json"
    log.write_text("{}", encoding="utf-8")
    report.write_text("{}", encoding="utf-8")
    log.touch()
    report.touch()
    monkeypatch.setattr(
        "web.jobs._find_latest_attack_log_for_play",
        lambda *_a, **_k: log,
    )
    job = SimpleNamespace(
        site="Site",
        component="comp",
        output=[],
        _event=SimpleNamespace(set=lambda: None),
    )
    suite = tmp_path / "suite.json"
    suite.write_text("{}", encoding="utf-8")
    ok = asyncio.run(
        _baseline_run_suite_before_enhance(
            job, suite, "cot_hunt_fixture", "zero_shot"
        )
    )
    assert ok is True
    assert any("Fresh Analysis present" in line for line in job.output)
