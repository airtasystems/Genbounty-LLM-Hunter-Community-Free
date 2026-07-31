"""Tests for logs/probes|manual path helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline import log_paths


def test_new_timestamped_run_dir_probes_and_manual(tmp_path: Path, monkeypatch):
    site, component = "example.com", "chat"
    root = tmp_path / "browser-bot" / "sites" / site / component / "logs"
    root.mkdir(parents=True)

    monkeypatch.setattr(log_paths, "_ROOT", tmp_path)
    monkeypatch.setattr(
        log_paths,
        "component_logs_dir",
        lambda s, c: tmp_path / "browser-bot" / "sites" / s / c / "logs",
    )

    probes = log_paths.new_timestamped_run_dir(site, component, "probes")
    assert probes.parent.name == "probes"
    assert probes.is_dir()
    manual = log_paths.new_timestamped_run_dir(site, component, "manual")
    assert manual.parent.name == "manual"
    assert manual.is_dir()
    with pytest.raises(ValueError):
        log_paths.new_timestamped_run_dir(site, component, "attack")


def test_list_lanes_and_hide_batch(tmp_path: Path, monkeypatch):
    site, component = "example.com", "chat"
    logs = tmp_path / "browser-bot" / "sites" / site / component / "logs"
    probes_ts = logs / "probes" / "2026-01-01_12-00-00"
    manual = logs / "manual"
    manual_ts = manual / "2026-01-02_09-00-00"
    batch = manual / "_batch"
    for d in (probes_ts, manual, manual_ts, batch):
        d.mkdir(parents=True)
    (probes_ts / "run_log.json").write_text("{}", encoding="utf-8")
    (probes_ts / "attack_log.json").write_text("{}", encoding="utf-8")
    (probes_ts / "pipeline_report.json").write_text("{}", encoding="utf-8")
    (manual / "attack_log.json").write_text("{}", encoding="utf-8")
    (manual / "pipeline_report.json").write_text("{}", encoding="utf-8")
    (manual_ts / "attack_log.json").write_text("{}", encoding="utf-8")
    (manual_ts / "pipeline_report.json").write_text("{}", encoding="utf-8")
    (batch / "attack_log.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        log_paths,
        "component_logs_dir",
        lambda s, c: logs,
    )

    assert log_paths.is_hidden_log_path(batch / "attack_log.json", logs)
    runs = log_paths.list_run_logs(site, component)
    assert len(runs) == 1 and runs[0].parent.name == "2026-01-01_12-00-00"
    all_logs = log_paths.list_attack_logs(site, component)
    assert len(all_logs) == 3
    batch_log = batch / "attack_log.json"
    assert batch_log not in {p.resolve() for p in all_logs}
    probe_only = log_paths.list_pipeline_reports(
        site, component, kinds=(log_paths.LOG_KIND_PROBES,)
    )
    assert len(probe_only) == 1
    assert log_paths.label_log_path(logs, probe_only[0]).startswith("probes/")
    manual_reports = log_paths.list_pipeline_reports(
        site, component, kinds=(log_paths.LOG_KIND_MANUAL,)
    )
    assert len(manual_reports) == 2
    assert "attack" not in log_paths.LOG_KINDS
