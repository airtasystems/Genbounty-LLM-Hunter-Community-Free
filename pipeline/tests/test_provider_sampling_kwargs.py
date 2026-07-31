"""Cross-provider sampling kwargs: top_k / top_p / temperature wiring."""

from __future__ import annotations

from pipeline.llm.base import LLMRequest
from pipeline.llm.providers.anthropic import AnthropicAdapter
from pipeline.llm.providers.gemini import GeminiAdapter
from pipeline.llm.providers.grok import GrokAdapter
from pipeline.llm.providers.openai import OpenAIAdapter


def _req(**overrides):
    base = dict(
        system="sys",
        user="user",
        model="test-model",
        api_key="test-key",
        temperature=0.8,
        top_p=0.7,
        top_k=25,
    )
    base.update(overrides)
    return LLMRequest(**base)


def test_gemini_generation_config_includes_top_k_and_top_p():
    kwargs = GeminiAdapter._generation_config_kwargs(
        _req(model="gemini-3.1-flash-lite")
    )
    assert kwargs["top_k"] == 25
    assert kwargs["top_p"] == 0.7
    assert kwargs["temperature"] == 0.8


def test_gemini_generation_config_omits_unset_sampling():
    kwargs = GeminiAdapter._generation_config_kwargs(
        _req(temperature=None, top_p=None, top_k=None)
    )
    assert "temperature" not in kwargs
    assert "top_p" not in kwargs
    assert "top_k" not in kwargs


def test_gemini_lc_bind_includes_top_k_and_top_p():
    bind = GeminiAdapter._lc_bind_kwargs(_req(temperature=0.12, top_p=0.4, top_k=10))
    # Default LC client temp is 0.12, so temperature is not rebound.
    assert "temperature" not in bind
    assert bind["top_p"] == 0.4
    assert bind["top_k"] == 10


def test_gemini_lc_bind_includes_non_default_temperature():
    bind = GeminiAdapter._lc_bind_kwargs(_req(temperature=0.9, top_k=None, top_p=None))
    assert bind == {"temperature": 0.9}


def test_anthropic_build_kwargs_includes_top_k_and_top_p():
    kwargs = AnthropicAdapter()._build_kwargs(_req(model="claude-sonnet-4-5"))
    assert kwargs["top_k"] == 25
    assert kwargs["top_p"] == 0.7
    assert kwargs["temperature"] == 0.8
    assert kwargs["model"] == "claude-sonnet-4-5"


def test_anthropic_build_kwargs_omits_unset_sampling():
    kwargs = AnthropicAdapter()._build_kwargs(
        _req(model="claude-sonnet-4-5", temperature=None, top_p=None, top_k=None)
    )
    assert "temperature" not in kwargs
    assert "top_p" not in kwargs
    assert "top_k" not in kwargs


def test_openai_forwards_top_p_but_not_top_k():
    """Chat Completions has no top_k field; style relies on prompt guidance."""
    kwargs = OpenAIAdapter()._build_kwargs(_req(model="gpt-4o"))
    assert "top_k" not in kwargs
    assert kwargs["top_p"] == 0.7
    assert kwargs["temperature"] == 0.8


def test_openai_reasoning_model_omits_sampling():
    kwargs = OpenAIAdapter()._build_kwargs(_req(model="gpt-5.4-mini"))
    assert "top_k" not in kwargs
    assert "temperature" not in kwargs
    assert "top_p" not in kwargs


def test_grok_forwards_top_k_and_top_p():
    kwargs = GrokAdapter()._build_kwargs(_req(model="grok-4.3"))
    assert kwargs["top_k"] == 25
    assert kwargs["top_p"] == 0.7
    assert kwargs["temperature"] == 0.8
