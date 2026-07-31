"""Anthropic (Claude) adapter.

Anthropic takes the system prompt as a top-level ``system`` parameter and always
requires ``max_tokens``. JSON mode is prompt-driven (no native JSON response
format), so JSON output is lightly validated/repaired before return.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from typing import Any, Dict

from pipeline.llm.base import LLMRequest, LLMResponse, ProviderAdapter
from pipeline.llm.retry import call_with_retry

logger = logging.getLogger(__name__)

_DEFAULT_MAX_TOKENS = 4096

# Anthropic reports unsupported params in backticks, e.g.
# "`temperature` is deprecated for this model."
_PARAM_RE = re.compile(r"[`']([A-Za-z_][A-Za-z0-9_]*)[`']")
# Sampling params that are safe to drop and retry without (model-dependent).
_DROPPABLE_PARAMS = frozenset({"temperature", "top_p", "top_k"})


def _repair_json(text: str) -> str:
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


class AnthropicAdapter(ProviderAdapter):
    name = "anthropic"

    def __init__(self) -> None:
        self._clients: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def _client(self, api_key: str) -> Any:
        with self._lock:
            client = self._clients.get(api_key)
            if client is None:
                import anthropic

                client = anthropic.Anthropic(api_key=api_key)
                self._clients[api_key] = client
            return client

    def _create_message(self, client: Any, base_kwargs: Dict[str, Any]) -> Any:
        """Call messages.create, dropping unsupported sampling params on a 400.

        Newer Claude models deprecate params like ``temperature`` for certain
        modes; on that error we remove the offending sampling param and retry
        (each param is dropped at most once, guaranteeing termination).
        """
        try:
            from anthropic import BadRequestError
        except ImportError:  # pragma: no cover - anthropic is a listed dependency
            BadRequestError = Exception  # type: ignore[assignment]

        kwargs = dict(base_kwargs)
        dropped: set = set()
        while True:
            try:
                return client.messages.create(**kwargs)
            except BadRequestError as exc:
                if not self._drop_unsupported_param(kwargs, exc, dropped):
                    raise

    def _drop_unsupported_param(
        self, kwargs: Dict[str, Any], exc: Exception, dropped: set
    ) -> bool:
        msg = str(getattr(exc, "message", "") or exc)
        param = getattr(exc, "param", None)
        candidates = [param] if param else _PARAM_RE.findall(msg)
        for cand in candidates:
            if cand in kwargs and cand in _DROPPABLE_PARAMS and cand not in dropped:
                kwargs.pop(cand, None)
                dropped.add(cand)
                logger.info("Anthropic: dropped unsupported param %r", cand)
                return True
        return False

    def _cache_settings(self) -> Dict[str, Any]:
        """Effective prompt-cache settings (site/component-aware) for Anthropic."""
        try:
            from pipeline.component_settings import provider_cache_settings

            return provider_cache_settings("anthropic")
        except Exception:  # pragma: no cover - settings are best-effort
            return {"enabled": True, "ttl": "5m"}

    def _apply_system_cache(
        self, system: str, kwargs: Dict[str, Any]
    ) -> None:
        """Mark the (large, static) system prompt as a cache breakpoint.

        Anthropic caches by content prefix rather than by key, so marking the
        system prompt lets every call that shares it (e.g. repeated assessment
        runs) reuse the cached prefix. A 1h TTL requires the extended-cache beta
        header. Small prefixes are simply not cached by the API (no error).
        """
        if not system:
            return
        opts = self._cache_settings()
        if not opts.get("enabled", True):
            kwargs["system"] = system
            return
        cache_control: Dict[str, Any] = {"type": "ephemeral"}
        ttl = str(opts.get("ttl") or "5m").strip()
        if ttl == "1h":
            cache_control["ttl"] = "1h"
            headers = dict(kwargs.get("extra_headers") or {})
            headers.setdefault("anthropic-beta", "extended-cache-ttl-2025-04-11")
            kwargs["extra_headers"] = headers
        kwargs["system"] = [
            {"type": "text", "text": system, "cache_control": cache_control}
        ]

    def _build_kwargs(self, req: LLMRequest) -> Dict[str, Any]:
        """Build Messages API kwargs, including sampling when the model allows it.

        Newer Claude models may reject ``temperature`` / ``top_p`` / ``top_k``;
        ``_create_message`` drops those via ``_DROPPABLE_PARAMS`` and retries.
        """
        system = req.system or ""
        if req.json_mode:
            # Anthropic has no native JSON mode, so always steer via the system
            # prompt (even when the caller supplied none) and repair afterwards.
            json_hint = "Respond with a single valid JSON value only, no prose or code fences."
            system = f"{system}\n\n{json_hint}".strip() if system else json_hint
        kwargs: Dict[str, Any] = {
            "model": req.model,
            "max_tokens": req.max_output_tokens or _DEFAULT_MAX_TOKENS,
            "messages": [{"role": "user", "content": req.user}],
        }
        if system:
            self._apply_system_cache(system, kwargs)
        if req.temperature is not None:
            kwargs["temperature"] = req.temperature
        if req.top_p is not None:
            kwargs["top_p"] = req.top_p
        if req.top_k is not None:
            kwargs["top_k"] = int(req.top_k)
        return kwargs

    def complete(self, req: LLMRequest) -> LLMResponse:
        client = self._client(req.api_key)
        kwargs = self._build_kwargs(req)

        response = call_with_retry(self._create_message, client, kwargs)
        text = ""
        try:
            parts = [
                block.text
                for block in response.content
                if getattr(block, "type", None) == "text"
            ]
            text = "\n".join(p for p in parts if p).strip()
        except (AttributeError, TypeError):
            text = ""

        if req.json_mode and text:
            text = _repair_json(text)

        usage: Dict[str, Any] = {}
        cache_hit = False
        try:
            if response.usage is not None:
                usage = {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                }
                cache_read = getattr(response.usage, "cache_read_input_tokens", None)
                cache_created = getattr(response.usage, "cache_creation_input_tokens", None)
                if cache_read:
                    usage["cache_read_input_tokens"] = int(cache_read)
                    cache_hit = True
                if cache_created:
                    usage["cache_creation_input_tokens"] = int(cache_created)
        except (AttributeError, TypeError, ValueError):
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
