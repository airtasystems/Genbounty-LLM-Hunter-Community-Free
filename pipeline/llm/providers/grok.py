"""xAI Grok adapter.

Grok exposes an OpenAI-compatible API, so this reuses the OpenAI adapter with a
different ``base_url``. Grok's JSON adherence is less reliable, so JSON-mode
responses are lightly validated and repaired (strip code fences, slice to the
outermost braces) before being returned.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict

from pipeline.llm.base import LLMRequest, LLMResponse
from pipeline.llm.providers.openai import OpenAIAdapter

logger = logging.getLogger(__name__)

# Grok-4+ (and any "*-reasoning" variant) reserve hidden reasoning tokens out of
# the same budget as the visible answer, so a small ``max_tokens`` can starve the
# output entirely. Floor the cap for those models.
_DEFAULT_GROK_REASONING_MIN_TOKENS = 8000
_GROK_REASONING_RE = re.compile(r"^grok-(?:[4-9]|\d{2,})", re.IGNORECASE)


def _repair_json(text: str) -> str:
    """Best-effort extraction of a JSON object/array from a noisy response."""
    stripped = text.strip()
    if "```" in stripped:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", stripped)
        if match:
            stripped = match.group(1).strip()
    try:
        json.loads(stripped)
        return stripped
    except json.JSONDecodeError:
        pass
    # Slice to the outermost object or array.
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = stripped.find(open_ch)
        end = stripped.rfind(close_ch)
        if start != -1 and end != -1 and end > start:
            candidate = stripped[start : end + 1]
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                continue
    return text


class GrokAdapter(OpenAIAdapter):
    name = "grok"
    base_url = "https://api.x.ai/v1"
    # xAI's OpenAI-compatible API uses the legacy ``max_tokens`` parameter.
    max_tokens_param = "max_tokens"
    _cache_provider = "grok"

    def _apply_cache(self, req: LLMRequest, kwargs: Dict[str, Any]) -> None:
        """Attach xAI's conversation-id header so repeated prefixes hit the cache.

        Grok caches automatically; ``x-grok-conv-id`` improves cache-hit routing
        for a repeated prompt and only applies when a stable ``cache_key`` exists.
        Unlike OpenAI, xAI does not accept ``prompt_cache_key``.
        """
        if not req.cache_key:
            return
        opts = self._cache_settings()
        if not opts.get("enabled", True):
            return
        headers = dict(kwargs.get("extra_headers") or {})
        headers["x-grok-conv-id"] = req.cache_key
        kwargs["extra_headers"] = headers

    def _restricts_sampling_params(self, model: str) -> bool:
        """xAI accepts explicit temperature/top_p on all models (incl. reasoning)."""
        return False

    def _build_kwargs(self, req: LLMRequest) -> Dict[str, Any]:
        """OpenAI path omits ``top_k``; xAI chat completions accept it.

        If a model rejects ``top_k``, the inherited unsupported-parameter retry
        drops it via ``_DROPPABLE_PARAMS``.
        """
        kwargs = super()._build_kwargs(req)
        if req.top_k is not None:
            kwargs["top_k"] = int(req.top_k)
        return kwargs

    def _is_reasoning_model(self, model: str) -> bool:
        """True for Grok reasoning models (grok-4+ or any ``*-reasoning`` id).

        The base class scopes reasoning detection to OpenAI's
        ``max_completion_tokens`` accounting and excludes Grok; override so the
        token-floor logic in ``_effective_max_tokens`` applies to Grok too.
        """
        m = (model or "").strip()
        if not m:
            return False
        low = m.lower()
        if "non-reasoning" in low:
            return False
        if "reasoning" in low:
            return True
        return bool(_GROK_REASONING_RE.match(m))

    @staticmethod
    def _reasoning_min_tokens() -> int:
        return _DEFAULT_GROK_REASONING_MIN_TOKENS

    def _effective_max_tokens(self, model: str, requested: int) -> int:
        """Widen the ``max_tokens`` cap for Grok reasoning models (never lowers)."""
        if self._is_reasoning_model(model):
            floored = max(requested, self._reasoning_min_tokens())
            if floored != requested:
                logger.info(
                    "Grok: raised max_tokens %d -> %d for reasoning model %r",
                    requested, floored, model,
                )
            return floored
        return requested

    def complete(self, req: LLMRequest) -> LLMResponse:
        resp = super().complete(req)
        if req.json_mode and resp.text:
            repaired = _repair_json(resp.text)
            if repaired != resp.text:
                logger.info("Grok JSON response repaired for role output")
                resp.text = repaired
        return resp
