"""Provider-agnostic request/response types and the adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class LLMRequest:
    """A single completion request, normalized across providers."""

    system: str
    user: str
    model: str
    api_key: str
    json_mode: bool = False
    temperature: Optional[float] = None
    max_output_tokens: Optional[int] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    # Optional caller-namespaced key enabling provider-side prompt/context cache.
    # Honoured by Gemini (context cache), OpenAI (prompt_cache_key routing) and
    # Grok (x-grok-conv-id routing). Anthropic caches by content prefix instead.
    cache_key: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    """The result of a completion, normalized across providers."""

    text: str
    provider: str
    model: str
    usage: Dict[str, Any] = field(default_factory=dict)
    raw: Any = None
    cache_hit: bool = False

    @property
    def empty(self) -> bool:
        return not (self.text or "").strip()


class ProviderAdapter(ABC):
    """Common interface every provider implementation must satisfy."""

    name: str = "base"

    @abstractmethod
    def complete(self, req: LLMRequest) -> LLMResponse:
        """Run one completion and return normalized text."""

    def supports_cache(self) -> bool:  # pragma: no cover - overridden where relevant
        return False

    def clear_caches(self, *, delete_remote: bool = False) -> None:
        """Clear any provider-side prompt/context caches held by this adapter."""
        return None
