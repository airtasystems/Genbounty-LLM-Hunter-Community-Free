"""DELETE /api/sites/{site}/{component}/tests/{strategy}/{playbook}."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from web.routers import tests as tests_router  # noqa: E402
from web.services import suite_io  # noqa: E402


@pytest.fixture
def bb_dir(tmp_path, monkeypatch):
    """Point suite path helpers and the delete route at a temp browser-bot root."""
    monkeypatch.setattr(suite_io, "BB_DIR", tmp_path)
    monkeypatch.setattr(tests_router, "BB_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def client(bb_dir):
    app = FastAPI()
    app.include_router(tests_router.router)
    return TestClient(app)


def test_delete_test_file_succeeds_and_removes_file(client, bb_dir):
    site, component, strategy, playbook = "example.test", "chat", "zero-shot", "demo-play"
    path = bb_dir / "sites" / site / component / "tests" / strategy / f"{playbook}.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"schema_version": 3, "prompts": []}) + "\n",
        encoding="utf-8",
    )
    assert path.is_file()

    resp = client.delete(f"/api/sites/{site}/{component}/tests/{strategy}/{playbook}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["strategy"] == strategy
    assert body["playbook"] == playbook
    assert not path.exists()


def test_delete_test_file_missing_returns_404(client, bb_dir):
    site, component, strategy, playbook = "example.test", "chat", "zero-shot", "missing-play"
    (bb_dir / "sites").mkdir(parents=True, exist_ok=True)

    resp = client.delete(f"/api/sites/{site}/{component}/tests/{strategy}/{playbook}")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()
