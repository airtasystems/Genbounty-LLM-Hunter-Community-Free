"""OpenRouter provider registration (no live network)."""

from __future__ import annotations

from pipeline.llm.config import PROVIDER_KEY_ENV
from pipeline.llm.providers import get_adapter
from pipeline.llm.providers.openrouter import OpenRouterAdapter, _attribution_headers


def test_provider_key_env_includes_openrouter():
    assert "openrouter" in PROVIDER_KEY_ENV
    assert PROVIDER_KEY_ENV["openrouter"] == ("OPENROUTER_API_KEY",)


def test_get_adapter_resolves_openrouter():
    adapter = get_adapter("openrouter")
    assert isinstance(adapter, OpenRouterAdapter)
    assert adapter.name == "openrouter"
    assert adapter.base_url == "https://openrouter.ai/api/v1"
    assert adapter.max_tokens_param == "max_tokens"


def test_openrouter_attribution_headers_empty_by_default(monkeypatch):
    monkeypatch.delenv("OPENROUTER_HTTP_REFERER", raising=False)
    monkeypatch.delenv("OPENROUTER_APP_TITLE", raising=False)
    assert _attribution_headers() == {}


def test_openrouter_attribution_headers_from_env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_HTTP_REFERER", "https://example.com")
    monkeypatch.setenv("OPENROUTER_APP_TITLE", "Genbounty")
    assert _attribution_headers() == {
        "HTTP-Referer": "https://example.com",
        "X-OpenRouter-Title": "Genbounty",
    }
