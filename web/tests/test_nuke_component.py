"""Nuke wipes component experiment artifacts; keeps config, auth, and recon.json."""

from __future__ import annotations

from pathlib import Path

import browser_bot.sites as sites


def test_nuke_component_removes_artifacts_keeps_config_auth_and_recon(tmp_path, monkeypatch):
    monkeypatch.setattr(sites, "SITES_DIR", tmp_path)
    root = tmp_path / "ExampleSite" / "comp-a"
    root.mkdir(parents=True)
    (root / "config.yaml").write_text("urls: []\n", encoding="utf-8")
    (root / "auth.json").write_text("{}\n", encoding="utf-8")
    (root / "enhance_theory_history.json").write_text("[]\n", encoding="utf-8")
    (root / "recon.json").write_text('{"capabilities":[]}\n', encoding="utf-8")
    (root / "recon.har").write_text("{}\n", encoding="utf-8")
    (root / "recon-network.json").write_text("{}\n", encoding="utf-8")
    (root / "tests" / "zero_shot").mkdir(parents=True)
    (root / "tests" / "zero_shot" / "play.json").write_text("{}\n", encoding="utf-8")
    (root / "logs" / "probes" / "run1").mkdir(parents=True)
    (root / "logs" / "probes" / "run1" / "pipeline_report.json").write_text(
        "{}\n", encoding="utf-8"
    )
    (root / "intel").mkdir()
    (root / "intel" / "play.json").write_text("{}\n", encoding="utf-8")
    (root / "html").mkdir()
    (root / ".login_profile").mkdir()

    result = sites.nuke_component("ExampleSite", "comp-a")

    assert result["ok"] is True
    assert Path(result["path"]) == root
    backup = Path(result["backup"])
    assert backup.is_dir()
    assert backup.parent.name == "nuke_backups"
    assert backup.parent.parent == root
    assert (backup / "tests" / "zero_shot" / "play.json").is_file()
    assert (backup / "logs" / "probes" / "run1" / "pipeline_report.json").is_file()
    assert (backup / "intel" / "play.json").is_file()
    assert (backup / "recon.json").read_text(encoding="utf-8") == '{"capabilities":[]}\n'
    assert (backup / "recon.har").is_file()
    assert (backup / "recon-network.json").is_file()
    assert (backup / "config.yaml").read_text(encoding="utf-8") == "urls: []\n"

    names = {p.name for p in root.iterdir()}
    assert names == {
        "config.yaml",
        "auth.json",
        "recon.json",
        "nuke_backups",
    }
    assert "tests" in result["removed"]
    assert "logs" in result["removed"]
    assert "intel" in result["removed"]
    assert "enhance_theory_history.json" in result["removed"]
    assert "recon.har" in result["removed"]
    assert "recon-network.json" in result["removed"]
    assert "recon.json" not in result["removed"]
    assert set(result["kept"]) == {
        "auth.json",
        "config.yaml",
        "nuke_backups",
        "recon.json",
    }
    assert (root / "config.yaml").read_text(encoding="utf-8") == "urls: []\n"
    assert (root / "auth.json").read_text(encoding="utf-8") == "{}\n"
    assert (root / "recon.json").read_text(encoding="utf-8") == '{"capabilities":[]}\n'
    assert not (root / "recon.har").exists()
    assert not (root / "recon-network.json").exists()


def test_nuke_component_does_not_nest_prior_backups(tmp_path, monkeypatch):
    monkeypatch.setattr(sites, "SITES_DIR", tmp_path)
    root = tmp_path / "ExampleSite" / "comp-b"
    root.mkdir(parents=True)
    (root / "config.yaml").write_text("urls: []\n", encoding="utf-8")
    prior = root / "nuke_backups" / "20200101T000000Z"
    prior.mkdir(parents=True)
    (prior / "old.txt").write_text("prior\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "play.json").write_text("{}\n", encoding="utf-8")

    result = sites.nuke_component("ExampleSite", "comp-b")
    backup = Path(result["backup"])
    assert backup != prior
    assert not (backup / "nuke_backups").exists()
    assert (prior / "old.txt").read_text(encoding="utf-8") == "prior\n"
    assert {p.name for p in (root / "nuke_backups").iterdir()} == {
        "20200101T000000Z",
        backup.name,
    }


def test_nuke_component_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(sites, "SITES_DIR", tmp_path)
    try:
        sites.nuke_component("Missing", "nope")
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass


def test_nuke_keep_set_includes_recon_and_backups():
    assert "recon.json" in sites.NUKE_COMPONENT_KEEP
    assert "recon.har" not in sites.NUKE_COMPONENT_KEEP
    assert "recon-network.json" not in sites.NUKE_COMPONENT_KEEP
    assert "nuke_backups" in sites.NUKE_COMPONENT_KEEP
    assert "config.yaml" in sites.NUKE_COMPONENT_KEEP
    assert "auth.json" in sites.NUKE_COMPONENT_KEEP


def test_nuke_wiring_contract():
    root = Path(__file__).resolve().parents[2]
    header = (root / "web" / "static" / "partials" / "header.html").read_text(
        encoding="utf-8"
    )
    starters = (root / "web" / "static" / "js" / "tabs" / "run-starters.js").read_text(
        encoding="utf-8"
    )
    jobs = (root / "web" / "jobs.py").read_text(encoding="utf-8")
    assert "startNuke" in header
    assert ">Nuke<" in header or "Nuke')" in header or "'Nuke'" in header
    assert "header-nuke" in header
    assert "aria-label=\"Nuke help\"" in header
    assert "openNukeHelpModal" in header
    assert "nuke_backups" in header
    assert "recon.har" not in header
    assert "recon-network.json" not in header
    assert "async function startNuke" in starters
    assert "startJob('nuke'" in starters
    assert 'job_type == "nuke"' in jobs
    assert "_start_nuke" in jobs
    assert "[nuke] Backup:" in jobs
    assert "nuke_component" in (root / "browser-bot" / "browser_bot" / "sites.py").read_text(
        encoding="utf-8"
    )
