"""Connect Target LLM API presets (including OpenRouter as a target)."""

from __future__ import annotations

from browser_bot.api_presets import get_llm_api_presets, get_preset


def test_openrouter_preset_is_openai_compatible():
    preset = get_preset("openrouter")
    assert preset is not None
    assert preset["id"] == "openrouter"
    assert preset["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert preset["method"] == "POST"
    assert preset["response_path"] == "choices.0.message.content"
    assert preset["auth_header"] == "Authorization"
    assert preset["requires_auth"] is True
    assert preset["default_model"] == "openai/gpt-4o-mini"
    body = preset["body"]
    assert body["model"] == "{{model}}"
    assert body["messages"] == [{"role": "user", "content": "{{prompt}}"}]
    headers = preset["headers"]
    assert headers.get("Content-Type") == "application/json"


def test_llm_api_presets_include_openrouter():
    ids = [p["id"] for p in get_llm_api_presets()]
    assert "openrouter" in ids
    assert ids.index("openrouter") == ids.index("openai") + 1
