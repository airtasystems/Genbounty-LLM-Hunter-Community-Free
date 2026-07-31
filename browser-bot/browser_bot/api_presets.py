"""LLM HTTP API presets for Connect Target API endpoint discovery."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

LLM_API_PRESETS: list[dict[str, Any]] = [
    {
        "id": "custom",
        "label": "Custom / app wrapper",
        "description": "Generic JSON chat API. Set URL, body, and response path yourself.",
        "url": "http://localhost:3000/api/chat",
        "method": "POST",
        "response_path": "response",
        "body": {"prompt": "{{prompt}}"},
        "headers": {},
        "auth_header": "",
        "auth_query_param": "",
        "default_model": "",
        "requires_auth": False,
    },
    {
        "id": "openai",
        "label": "OpenAI Chat Completions",
        "description": "POST /v1/chat/completions - use Bearer token in Step 1 (Authorization).",
        "url": "https://api.openai.com/v1/chat/completions",
        "method": "POST",
        "response_path": "choices.0.message.content",
        "body": {
            "model": "{{model}}",
            "messages": [{"role": "user", "content": "{{prompt}}"}],
        },
        "headers": {"Content-Type": "application/json"},
        "auth_header": "Authorization",
        "auth_query_param": "",
        "default_model": "gpt-5.6",
        "requires_auth": True,
    },
    {
        "id": "openrouter",
        "label": "OpenRouter Chat Completions",
        "description": (
            "OpenAI-compatible POST https://openrouter.ai/api/v1/chat/completions - "
            "use OpenRouter API key as Bearer in Step 1 (Authorization). "
            "Model ids are OpenRouter slugs (e.g. openai/gpt-4o-mini, x-ai/grok-4.3)."
        ),
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "method": "POST",
        "response_path": "choices.0.message.content",
        "body": {
            "model": "{{model}}",
            "messages": [{"role": "user", "content": "{{prompt}}"}],
        },
        "headers": {
            "Content-Type": "application/json",
            # Optional OpenRouter attribution (recommended by OpenRouter; safe to leave).
            "HTTP-Referer": "https://genbounty.com",
            "X-OpenRouter-Title": "Genbounty LLM Hunter",
        },
        "auth_header": "Authorization",
        "auth_query_param": "",
        "default_model": "openai/gpt-4o-mini",
        "requires_auth": True,
    },
    {
        "id": "gemini",
        "label": "Google Gemini (generateContent)",
        "description": "Gemini API - use x-goog-api-key header or ?key= query in Step 1.",
        "url": "https://generativelanguage.googleapis.com/v1beta/models/{{model}}:generateContent",
        "method": "POST",
        "response_path": "candidates.0.content.parts.0.text",
        "body": {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": "{{prompt}}"}],
                }
            ],
        },
        "headers": {"Content-Type": "application/json"},
        "auth_header": "x-goog-api-key",
        "auth_query_param": "key",
        "default_model": "gemini-3.1-flash-lite",
        "requires_auth": True,
    },
    {
        "id": "anthropic",
        "label": "Anthropic Messages",
        "description": "POST /v1/messages - use x-api-key in Step 1.",
        "url": "https://api.anthropic.com/v1/messages",
        "method": "POST",
        "response_path": "content.0.text",
        "body": {
            "model": "{{model}}",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": "{{prompt}}"}],
        },
        "headers": {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        },
        "auth_header": "x-api-key",
        "auth_query_param": "",
        "default_model": "claude-3-5-haiku-20241022",
        "requires_auth": True,
    },
    {
        "id": "azure_openai",
        "label": "Azure OpenAI (deployments API)",
        "description": "Replace {resource} in the URL with your Azure resource name. api-key header in Step 1.",
        "url": "https://{resource}.openai.azure.com/openai/deployments/{{model}}/chat/completions?api-version=2024-10-21",
        "method": "POST",
        "response_path": "choices.0.message.content",
        "body": {
            "messages": [{"role": "user", "content": "{{prompt}}"}],
        },
        "headers": {"Content-Type": "application/json"},
        "auth_header": "api-key",
        "auth_query_param": "",
        "default_model": "gpt-5.6",
        "requires_auth": True,
    },
    {
        "id": "test_target",
        "label": "Genbounty Hunter test target (local)",
        "description": "Local test-target app - no API key (public) in Step 1.",
        "url": "http://127.0.0.1:3000/api/chat",
        "method": "POST",
        "response_path": "response",
        "body": {"prompt": "{{prompt}}"},
        "headers": {"Content-Type": "application/json"},
        "auth_header": "",
        "auth_query_param": "",
        "default_model": "",
        "requires_auth": False,
    },
]


def get_llm_api_presets() -> list[dict[str, Any]]:
    """Return preset list for UI (safe to serialize)."""
    return deepcopy(LLM_API_PRESETS)


def get_preset(preset_id: str) -> dict[str, Any] | None:
    pid = (preset_id or "").strip().lower()
    for p in LLM_API_PRESETS:
        if p["id"] == pid:
            return deepcopy(p)
    return None
