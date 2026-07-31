"""OpenAI adapter (Chat Completions).

Also serves as the base for the xAI Grok and OpenRouter adapters, which expose
an OpenAI-compatible API via a different ``base_url``.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any, Dict, Optional

from pipeline.llm.base import LLMRequest, LLMResponse, ProviderAdapter
from pipeline.llm.retry import call_with_retry

logger = logging.getLogger(__name__)

# Reasoning models (GPT-5.x, o-series) spend part of max_completion_tokens on
# hidden reasoning; too small a budget yields empty visible output. Floor the
# cap so the answer has room.
_DEFAULT_REASONING_MIN_TOKENS = 16000
_REASONING_MODEL_RE = re.compile(r"^(o[1-9]|gpt-5)", re.IGNORECASE)

# "Unsupported parameter: 'max_tokens' ... Use 'max_completion_tokens' instead."
_RENAME_RE = re.compile(r"[Uu]se '([^']+)' instead")
_PARAM_RE = re.compile(r"'([A-Za-z_][A-Za-z0-9_]*)'")

# Params safe to drop on an unsupported-parameter 400. NEVER includes
# ``model`` / ``messages`` (dropping those would break the request), so an error
# that names one of those falls through and is raised instead of silently
# corrupting the call.
_DROPPABLE_PARAMS = frozenset({
    "temperature",
    "top_p",
    "top_k",
    "max_tokens",
    "max_completion_tokens",
    "response_format",
    "frequency_penalty",
    "presence_penalty",
    "logprobs",
    "logit_bias",
    "seed",
    "n",
    "stop",
    # Prompt-cache routing hints - safe to drop if a model/endpoint rejects them
    # (caching is an optimization, never required for correctness).
    "prompt_cache_key",
    "prompt_cache_retention",
})


class OpenAIAdapter(ProviderAdapter):
    name = "openai"
    # None -> use the SDK default (OpenAI). Subclasses set a base_url.
    base_url: Optional[str] = None
    # GPT-5.x / o-series require ``max_completion_tokens``; the legacy
    # ``max_tokens`` is rejected. Grok's OpenAI-compatible API still uses
    # ``max_tokens`` (see GrokAdapter override). Any mismatch is auto-corrected
    # at call time via the unsupported-parameter fallback below.
    max_tokens_param: str = "max_completion_tokens"

    def __init__(self) -> None:
        self._clients: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def _client(self, api_key: str) -> Any:
        with self._lock:
            client = self._clients.get(api_key)
            if client is None:
                from openai import OpenAI

                kwargs: Dict[str, Any] = {"api_key": api_key}
                if self.base_url:
                    kwargs["base_url"] = self.base_url
                client = OpenAI(**kwargs)
                self._clients[api_key] = client
            return client

    def _build_kwargs(self, req: LLMRequest) -> Dict[str, Any]:
        messages = []
        if req.system:
            messages.append({"role": "system", "content": req.system})
        messages.append({"role": "user", "content": req.user})
        kwargs: Dict[str, Any] = {"model": req.model, "messages": messages}
        # OpenAI reasoning models reject non-default temperature/top_p; omit them
        # up front to avoid a guaranteed 400-then-retry on every call. ``top_k`` is
        # never sent (Chat Completions has no such field - Grok overrides this).
        # Callers that need top-k style (e.g. attribute rewrite) must encode it in
        # the prompt. The adaptive fallback in ``_create_completion`` remains the
        # safety net for any other model drift.
        restrict_sampling = self._restricts_sampling_params(req.model)
        if req.temperature is not None and not restrict_sampling:
            kwargs["temperature"] = req.temperature
        if req.max_output_tokens is not None:
            kwargs[self.max_tokens_param] = self._effective_max_tokens(
                req.model, req.max_output_tokens
            )
        if req.top_p is not None and not restrict_sampling:
            kwargs["top_p"] = req.top_p
        if req.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
            self._ensure_json_hint(messages)
        self._apply_cache(req, kwargs)
        return kwargs

    # Provider identifier used to look up cache settings; Grok overrides this.
    _cache_provider = "openai"

    def _cache_settings(self) -> Dict[str, Any]:
        """Effective prompt-cache settings (site/component-aware) for this provider."""
        try:
            from pipeline.component_settings import provider_cache_settings

            return provider_cache_settings(self._cache_provider)
        except Exception:  # pragma: no cover - settings are best-effort
            return {"enabled": True, "retention": "standard"}

    def _apply_cache(self, req: LLMRequest, kwargs: Dict[str, Any]) -> None:
        """Attach OpenAI prompt-cache routing hints when enabled.

        OpenAI caches long identical prefixes automatically; ``prompt_cache_key``
        only improves cache-hit routing for repeated prompts, so it is a no-op
        unless the caller supplies a stable ``cache_key``.
        """
        if not req.cache_key:
            return
        opts = self._cache_settings()
        if not opts.get("enabled", True):
            return
        kwargs["prompt_cache_key"] = req.cache_key
        if str(opts.get("retention") or "").strip() == "24h":
            kwargs["prompt_cache_retention"] = "24h"

    @staticmethod
    def _cached_prompt_tokens(usage: Any) -> int:
        """Best-effort cached-prompt-token count from an OpenAI-style usage object."""
        try:
            details = getattr(usage, "prompt_tokens_details", None)
            if details is not None:
                cached = getattr(details, "cached_tokens", None)
                if cached is not None:
                    return int(cached)
        except (TypeError, ValueError):
            pass
        return 0

    def _restricts_sampling_params(self, model: str) -> bool:
        """True when the model only accepts default sampling (no temperature/top_p).

        OpenAI GPT-5.x / o-series reasoning models return a 400 for any explicit
        ``temperature`` or ``top_p``. Grok (OpenAI-compatible) accepts both, so
        ``GrokAdapter`` overrides this to ``False``.
        """
        return bool(_REASONING_MODEL_RE.match((model or "").strip()))

    def _is_reasoning_model(self, model: str) -> bool:
        """True for OpenAI reasoning models that reserve reasoning tokens.

        Scoped to the OpenAI ``max_completion_tokens`` accounting; Grok uses
        ``max_tokens`` and is excluded even though its model names may contain
        'reasoning'.
        """
        if self.max_tokens_param != "max_completion_tokens":
            return False
        return bool(_REASONING_MODEL_RE.match((model or "").strip()))

    @staticmethod
    def _reasoning_min_tokens() -> int:
        return _DEFAULT_REASONING_MIN_TOKENS

    def _effective_max_tokens(self, model: str, requested: int) -> int:
        """Raise the completion cap for reasoning models so output isn't starved.

        Only widens the ceiling (never lowers the caller's request); billing is
        by actual tokens used, so a higher cap costs nothing unless the model
        genuinely needs the room.
        """
        if self._is_reasoning_model(model):
            floored = max(requested, self._reasoning_min_tokens())
            if floored != requested:
                logger.info(
                    "OpenAI: raised max_completion_tokens %d -> %d for reasoning model %r",
                    requested, floored, model,
                )
            return floored
        return requested

    @staticmethod
    def _ensure_json_hint(messages: list) -> None:
        """Guarantee the literal word 'json' appears in the messages.

        OpenAI's ``response_format={"type": "json_object"}`` (and xAI's
        compatible API) returns a 400 unless at least one message contains the
        word 'json'. Callers requesting JSON don't always phrase their prompt
        that way, so inject a short instruction when it is missing.
        """
        if any("json" in str(m.get("content", "")).lower() for m in messages):
            return
        hint = "Respond with a single valid JSON object and nothing else."
        for m in messages:
            if m.get("role") == "system":
                m["content"] = f"{str(m.get('content', '')).rstrip()}\n\n{hint}".strip()
                return
        messages.insert(0, {"role": "system", "content": hint})

    def _adapt_kwargs_for_error(
        self, kwargs: Dict[str, Any], exc: Exception, handled: set
    ) -> bool:
        """Rename or drop a single unsupported parameter based on a 400 body.

        Returns True when ``kwargs`` was modified (so the call should be retried),
        False when the error is not a fixable parameter issue. ``handled`` tracks
        prior fixes to guarantee termination.
        """
        msg = str(getattr(exc, "message", "") or exc)
        param = getattr(exc, "param", None)
        if not param:
            m = _PARAM_RE.search(msg)
            param = m.group(1) if m else None
        if not param or param not in kwargs:
            return False

        rename = _RENAME_RE.search(msg)
        target = rename.group(1) if rename else None
        if target and target not in kwargs and (param, "rename") not in handled:
            kwargs[target] = kwargs.pop(param)
            handled.add((param, "rename"))
            logger.info("OpenAI: renamed unsupported param %r -> %r", param, target)
            return True
        if param in _DROPPABLE_PARAMS and (param, "drop") not in handled:
            kwargs.pop(param, None)
            handled.add((param, "drop"))
            logger.info("OpenAI: dropped unsupported param %r", param)
            return True
        return False

    def _create_completion(self, client: Any, base_kwargs: Dict[str, Any]) -> Any:
        """Call chat.completions.create, adapting to unsupported-parameter 400s."""
        try:
            from openai import BadRequestError
        except ImportError:  # pragma: no cover - openai is a listed dependency
            BadRequestError = Exception  # type: ignore[assignment]

        kwargs = dict(base_kwargs)
        handled: set = set()
        while True:
            try:
                return client.chat.completions.create(**kwargs)
            except BadRequestError as exc:
                if not self._adapt_kwargs_for_error(kwargs, exc, handled):
                    raise

    def complete(self, req: LLMRequest) -> LLMResponse:
        client = self._client(req.api_key)
        kwargs = self._build_kwargs(req)
        response = call_with_retry(self._create_completion, client, kwargs)
        text = ""
        try:
            text = (response.choices[0].message.content or "").strip()
        except (AttributeError, IndexError, TypeError):
            text = ""
        usage: Dict[str, Any] = {}
        cache_hit = False
        try:
            if response.usage is not None:
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                }
                cached = self._cached_prompt_tokens(response.usage)
                if cached:
                    usage["cached_tokens"] = cached
                    cache_hit = True
        except AttributeError:
            pass
        return LLMResponse(
            text=text,
            provider=self.name,
            model=req.model,
            usage=usage,
            raw=response,
            cache_hit=cache_hit,
        )

    def supports_cache(self) -> bool:
        return True
