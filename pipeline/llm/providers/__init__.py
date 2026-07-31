"""Provider adapter registry for the assistant LLM layer."""

from __future__ import annotations

import threading
from typing import Dict

from pipeline.llm.base import ProviderAdapter

_ADAPTERS: Dict[str, ProviderAdapter] = {}
_LOCK = threading.Lock()


def get_adapter(provider: str) -> ProviderAdapter:
    """Return a lazily-instantiated singleton adapter for ``provider``."""
    key = (provider or "").strip().lower()
    adapter = _ADAPTERS.get(key)
    if adapter is not None:
        return adapter
    with _LOCK:
        adapter = _ADAPTERS.get(key)
        if adapter is not None:
            return adapter
        adapter = _build_adapter(key)
        _ADAPTERS[key] = adapter
        return adapter


def _build_adapter(provider: str) -> ProviderAdapter:
    if provider == "gemini":
        from pipeline.llm.providers.gemini import GeminiAdapter

        return GeminiAdapter()
    if provider == "openai":
        from pipeline.llm.providers.openai import OpenAIAdapter

        return OpenAIAdapter()
    if provider == "grok":
        from pipeline.llm.providers.grok import GrokAdapter

        return GrokAdapter()
    if provider == "anthropic":
        from pipeline.llm.providers.anthropic import AnthropicAdapter

        return AnthropicAdapter()
    if provider == "openrouter":
        from pipeline.llm.providers.openrouter import OpenRouterAdapter

        return OpenRouterAdapter()
    raise ValueError(f"Unknown LLM provider '{provider}'.")


def all_instantiated() -> Dict[str, ProviderAdapter]:
    """Return currently-built adapters (used for cache clearing)."""
    return dict(_ADAPTERS)
