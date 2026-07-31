"""OpenRouter adapter.

OpenRouter exposes an OpenAI-compatible Chat Completions API, so this reuses
the OpenAI adapter with ``base_url`` pointed at OpenRouter. Used for low-refusal
red-team prompt generation (Hermes / Dolphin, etc.) while judges stay on other
providers.
"""

from __future__ import annotations

import os
from typing import Any, Dict

from pipeline.llm.base import LLMRequest
from pipeline.llm.providers.openai import OpenAIAdapter


def _attribution_headers() -> Dict[str, str]:
    """Optional OpenRouter app-attribution headers from env (omit when empty)."""
    headers: Dict[str, str] = {}
    referer = (os.getenv("OPENROUTER_HTTP_REFERER") or "").strip()
    title = (os.getenv("OPENROUTER_APP_TITLE") or "").strip()
    if referer:
        headers["HTTP-Referer"] = referer
    if title:
        headers["X-OpenRouter-Title"] = title
    return headers


class OpenRouterAdapter(OpenAIAdapter):
    name = "openrouter"
    base_url = "https://openrouter.ai/api/v1"
    # Most routed models accept legacy ``max_tokens``; unsupported-param retry
    # still renames/drops if a specific upstream rejects it.
    max_tokens_param = "max_tokens"
    _cache_provider = "openai"

    def _client(self, api_key: str) -> Any:
        with self._lock:
            client = self._clients.get(api_key)
            if client is None:
                from openai import OpenAI

                kwargs: Dict[str, Any] = {
                    "api_key": api_key,
                    "base_url": self.base_url,
                }
                default_headers = _attribution_headers()
                if default_headers:
                    kwargs["default_headers"] = default_headers
                client = OpenAI(**kwargs)
                self._clients[api_key] = client
            return client

    def _apply_cache(self, req: LLMRequest, kwargs: Dict[str, Any]) -> None:
        """No OpenRouter-specific prompt-cache toggle; skip OpenAI cache hints."""
        return

    def _restricts_sampling_params(self, model: str) -> bool:
        """OpenRouter routes many families; send temperature/top_p and drop on 400."""
        return False
