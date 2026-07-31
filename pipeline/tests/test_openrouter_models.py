"""OpenRouter live-catalog model validation (mocked HTTP)."""

from __future__ import annotations

import json
from io import BytesIO
from urllib.error import HTTPError

import pytest

from pipeline.llm import openrouter_models as orm


@pytest.fixture(autouse=True)
def _clear_catalog_cache():
    orm.reset_openrouter_model_cache()
    yield
    orm.reset_openrouter_model_cache()


class _FakeResp:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_fetch_openrouter_model_ids_parses_catalog(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(req, timeout=15.0):
        calls["n"] += 1
        return _FakeResp({"data": [{"id": "x-ai/grok-4.3"}, {"id": "tencent/hy3"}]})

    monkeypatch.setattr(orm.urllib.request, "urlopen", fake_urlopen)
    ids = orm.fetch_openrouter_model_ids()
    assert ids == {"x-ai/grok-4.3", "tencent/hy3"}
    # Cached: second call does not hit the network.
    assert orm.fetch_openrouter_model_ids() == ids
    assert calls["n"] == 1


def test_validate_rejects_unknown_slug():
    profiles = {
        "offensive_generator": {"provider": "openrouter", "model": "x-ai/grok-4-fast"},
        "operator": {"provider": "gemini", "model": "gemini-3.1-flash-lite"},
    }
    result = orm.validate_openrouter_assignments(
        profiles,
        catalog={"x-ai/grok-4.3", "tencent/hy3"},
    )
    assert result.checked is True
    assert result.ok is False
    assert result.unknown_models == [
        {"profile": "offensive_generator", "model": "x-ai/grok-4-fast"}
    ]
    assert "x-ai/grok-4-fast" in result.errors[0]


def test_validate_accepts_known_slugs():
    profiles = {
        "offensive_generator": {"provider": "openrouter", "model": "x-ai/grok-4.3"},
        "grounder": {"provider": "openrouter", "model": "tencent/hy3"},
    }
    result = orm.validate_openrouter_assignments(
        profiles,
        catalog={"x-ai/grok-4.3", "tencent/hy3"},
    )
    assert result.checked is True
    assert result.ok is True
    assert result.errors == []


def test_validate_catalog_unavailable_warns_when_not_required(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("network down")

    monkeypatch.setattr(orm, "fetch_openrouter_model_ids", boom)
    result = orm.validate_openrouter_assignments(
        {"offensive_fast": {"provider": "openrouter", "model": "x-ai/grok-4.3"}},
        require_catalog=False,
    )
    assert result.checked is False
    assert result.ok is True
    assert result.warnings
    assert "catalog unavailable" in result.warnings[0].lower() or "network down" in result.warnings[0]


def test_validate_catalog_unavailable_errors_when_required(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("network down")

    monkeypatch.setattr(orm, "fetch_openrouter_model_ids", boom)
    result = orm.validate_openrouter_assignments(
        {"offensive_fast": {"provider": "openrouter", "model": "x-ai/grok-4.3"}},
        require_catalog=True,
    )
    assert result.checked is False
    assert result.ok is False
    assert result.errors


def test_save_llm_profiles_rejects_unknown_openrouter_model(tmp_path, monkeypatch):
    yaml_path = tmp_path / "llm.yaml"
    yaml_path.write_text(
        "llm:\n"
        "  profiles:\n"
        "    offensive_generator: { provider: openrouter, model: x-ai/grok-4.3 }\n"
        "    offensive_fast: { provider: openrouter, model: x-ai/grok-4.3 }\n"
        "    offensive_editor: { provider: openai, model: gpt-5.6-sol }\n"
        "    triager: { provider: anthropic, model: claude-sonnet-5 }\n"
        "    methodologist: { provider: anthropic, model: claude-sonnet-5 }\n"
        "    grounder: { provider: openrouter, model: tencent/hy3 }\n"
        "    operator: { provider: gemini, model: gemini-3.1-flash-lite }\n"
        "  roles:\n"
        "    generation_expert: offensive_generator\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("pipeline.llm.profiles_editor._LLM_YAML", yaml_path)
    monkeypatch.setattr("pipeline.llm.config._LLM_YAML", yaml_path)
    from pipeline.llm.config import reset_caches

    reset_caches()

    monkeypatch.setattr(
        orm,
        "fetch_openrouter_model_ids",
        lambda **_k: {"x-ai/grok-4.3", "tencent/hy3"},
    )

    from pipeline.llm.profiles_editor import save_llm_profiles

    with pytest.raises(ValueError, match="not in the live OpenRouter catalog"):
        save_llm_profiles(
            {
                "offensive_generator": {
                    "provider": "openrouter",
                    "model": "x-ai/grok-4-fast",
                }
            }
        )


def test_fetch_http_error_message(monkeypatch):
    def fake_urlopen(req, timeout=15.0):
        raise HTTPError(
            orm.OPENROUTER_MODELS_URL,
            503,
            "Unavailable",
            hdrs=None,
            fp=BytesIO(b"busy"),
        )

    monkeypatch.setattr(orm.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="HTTP 503"):
        orm.fetch_openrouter_model_ids(force=True)


def test_require_valid_raises_on_unknown_slug(monkeypatch):
    monkeypatch.setattr(
        orm,
        "collect_openrouter_assignments",
        lambda profiles=None: [("triager", "anthropic/sonnet-3.5-sonnet")],
    )
    monkeypatch.setattr(
        orm,
        "fetch_openrouter_model_ids",
        lambda **_k: {"x-ai/grok-4.3", "tencent/hy3"},
    )
    with pytest.raises(RuntimeError, match="refusing to start"):
        orm.require_valid_openrouter_models()


def test_require_valid_raises_when_catalog_unavailable(monkeypatch):
    monkeypatch.setattr(
        orm,
        "collect_openrouter_assignments",
        lambda profiles=None: [("offensive_fast", "x-ai/grok-4.3")],
    )

    def boom(**_k):
        raise RuntimeError("network down")

    monkeypatch.setattr(orm, "fetch_openrouter_model_ids", boom)
    with pytest.raises(RuntimeError, match="refusing to start"):
        orm.require_valid_openrouter_models()


def test_require_valid_ok_when_all_known(monkeypatch):
    monkeypatch.setattr(
        orm,
        "collect_openrouter_assignments",
        lambda profiles=None: [
            ("offensive_fast", "x-ai/grok-4.3"),
            ("grounder", "tencent/hy3"),
        ],
    )
    monkeypatch.setattr(
        orm,
        "fetch_openrouter_model_ids",
        lambda **_k: {"x-ai/grok-4.3", "tencent/hy3"},
    )
    result = orm.require_valid_openrouter_models()
    assert result.ok is True
    assert result.checked is True


def test_require_valid_ok_when_no_openrouter_profiles(monkeypatch):
    monkeypatch.setattr(orm, "collect_openrouter_assignments", lambda profiles=None: [])
    result = orm.require_valid_openrouter_models()
    assert result.ok is True
    assert result.checked is True


def test_format_startup_failure_lists_unknown_models():
    result = orm.OpenRouterValidationResult(
        checked=True,
        ok=False,
        errors=["OpenRouter profile 'triager' model 'bad' is not in the live OpenRouter catalog"],
        unknown_models=[{"profile": "triager", "model": "bad"}],
    )
    text = orm.format_openrouter_startup_failure(result)
    assert "refusing to start" in text
    assert "triager" in text
    assert "bad" in text
