"""Google Gemini adapter.

Preserves today's behaviour: direct ``google.genai`` as the primary path (with
optional server-side context cache and JSON mode), and a ``ChatGoogleGenerativeAI``
LangChain fallback when GenAI is unavailable, errors, or returns empty text.
Transient errors are retried via the shared retry helper.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

from pipeline.llm.base import LLMRequest, LLMResponse, ProviderAdapter
from pipeline.llm.retry import call_with_retry

logger = logging.getLogger(__name__)

try:
    from google import genai
    from google.genai import types
    _GENAI_AVAILABLE = True
except ImportError:  # pragma: no cover - google-genai is a listed dependency
    genai = None
    types = None
    _GENAI_AVAILABLE = False


def _model_id(model: str) -> str:
    m = (model or "").strip()
    return m if m.startswith("models/") else f"models/{m}"


def _text_from_response(response: Any) -> str:
    text = getattr(response, "text", None)
    if text is not None and str(text).strip():
        return str(text).strip()
    try:
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            content = getattr(candidates[0], "content", None)
            if content is not None:
                parts = getattr(content, "parts", None) or []
                bits = []
                for part in parts:
                    t = getattr(part, "text", None)
                    if t is not None and str(t).strip():
                        bits.append(str(t).strip())
                if bits:
                    return "\n".join(bits).strip()
    except (IndexError, AttributeError, TypeError):
        pass
    return ""


def _text_from_lc_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        bits = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text")
                if t is not None and str(t).strip():
                    bits.append(str(t).strip())
            elif isinstance(block, str) and block.strip():
                bits.append(block.strip())
        if bits:
            return "\n".join(bits).strip()
    if content is not None:
        return str(content).strip()
    return ""


class GeminiAdapter(ProviderAdapter):
    name = "gemini"

    def __init__(self) -> None:
        self._clients: Dict[str, Any] = {}
        self._lc_clients: Dict[tuple[str, str], Any] = {}
        self._cache_handles: Dict[str, str] = {}
        self._lock = threading.Lock()

    # -- client pools ---------------------------------------------------
    def _client(self, api_key: str) -> Optional[Any]:
        if not (_GENAI_AVAILABLE and genai):
            return None
        with self._lock:
            client = self._clients.get(api_key)
            if client is None:
                client = genai.Client(api_key=api_key)
                self._clients[api_key] = client
            return client

    def _lc_client(self, model: str, api_key: str):
        key = (model, api_key)
        with self._lock:
            client = self._lc_clients.get(key)
            if client is None:
                from langchain_google_genai import ChatGoogleGenerativeAI

                client = ChatGoogleGenerativeAI(model=model, api_key=api_key, temperature=0.12)
                self._lc_clients[key] = client
            return client

    def supports_cache(self) -> bool:
        return True

    # -- context cache --------------------------------------------------
    def _cache_enabled(self) -> bool:
        try:
            from pipeline.gemini_cache import gemini_cache_enabled

            return gemini_cache_enabled()
        except Exception:
            return False

    def _cache_ttl(self) -> str:
        return "3600s"

    def _get_or_create_cache(
        self, client: Any, cache_key: str, model_id: str, system: str
    ) -> str:
        store_key = f"{model_id}::{cache_key}"
        with self._lock:
            if store_key in self._cache_handles:
                return self._cache_handles[store_key]
        if client is None or types is None:
            return ""
        try:
            cache = client.caches.create(
                model=model_id,
                config=types.CreateCachedContentConfig(
                    display_name=f"genbounty-{cache_key[:50]}",
                    system_instruction=system,
                    ttl=self._cache_ttl(),
                ),
            )
            with self._lock:
                self._cache_handles[store_key] = cache.name
            logger.info("Created Gemini context cache [%s]: %s", store_key, cache.name)
            return cache.name
        except Exception as exc:
            logger.warning(
                "Gemini cache creation failed for [%s]; using direct calls. Error: %s",
                store_key, exc,
            )
            with self._lock:
                self._cache_handles[store_key] = ""
            return ""

    def clear_caches(self, *, delete_remote: bool = False) -> None:
        with self._lock:
            handles = dict(self._cache_handles)
        if delete_remote:
            for store_key, name in handles.items():
                if not name:
                    continue
                for client in list(self._clients.values()):
                    try:
                        client.caches.delete(name=name)
                        logger.info("Deleted Gemini cache %s: %s", store_key, name)
                        break
                    except Exception as exc:
                        logger.warning("Failed to delete cache %s: %s", store_key, exc)
        with self._lock:
            self._cache_handles.clear()

    # -- completion -----------------------------------------------------
    @staticmethod
    def _generation_config_kwargs(req: LLMRequest) -> Dict[str, Any]:
        """Sampling / length fields for ``GenerateContentConfig``."""
        config_kwargs: Dict[str, Any] = {}
        if req.temperature is not None:
            config_kwargs["temperature"] = req.temperature
        if req.max_output_tokens is not None:
            config_kwargs["max_output_tokens"] = req.max_output_tokens
        if req.top_p is not None:
            config_kwargs["top_p"] = req.top_p
        if req.top_k is not None:
            config_kwargs["top_k"] = int(req.top_k)
        return config_kwargs

    @staticmethod
    def _lc_bind_kwargs(req: LLMRequest) -> Dict[str, Any]:
        """Sampling overrides for the LangChain fallback path.

        The cached LC client is constructed with ``temperature=0.12``; re-bind
        whenever the request asks for a different temperature or any top-p/top-k.
        """
        bind: Dict[str, Any] = {}
        if req.temperature is not None and req.temperature != 0.12:
            bind["temperature"] = req.temperature
        if req.top_p is not None:
            bind["top_p"] = req.top_p
        if req.top_k is not None:
            bind["top_k"] = int(req.top_k)
        return bind

    def complete(self, req: LLMRequest) -> LLMResponse:
        client = self._client(req.api_key)
        model_id = _model_id(req.model)
        cache_hit = False
        text = ""

        if client is not None and types is not None:
            config_kwargs = self._generation_config_kwargs(req)

            cache_name = ""
            if req.cache_key and self._cache_enabled():
                cache_name = self._get_or_create_cache(
                    client, req.cache_key, model_id, req.system
                )

            try:
                if cache_name:
                    cache_hit = True
                    # system_instruction lives in the cache, but JSON mode must
                    # still be requested per-call or a cached request returns prose.
                    if req.json_mode:
                        config_kwargs["response_mime_type"] = "application/json"
                    config = types.GenerateContentConfig(
                        cached_content=cache_name, **config_kwargs
                    )
                else:
                    if req.system:
                        config_kwargs["system_instruction"] = req.system
                    if req.json_mode:
                        config_kwargs["response_mime_type"] = "application/json"
                    config = types.GenerateContentConfig(**config_kwargs)

                response = call_with_retry(
                    client.models.generate_content,
                    model=model_id,
                    contents=req.user,
                    config=config,
                )
                text = _text_from_response(response)
                if text:
                    return LLMResponse(
                        text=text,
                        provider=self.name,
                        model=req.model,
                        raw=response,
                        cache_hit=cache_hit,
                    )
            except Exception as exc:
                logger.warning("Gemini GenAI call failed, falling back to LangChain: %s", exc)

        # LangChain fallback (GenAI unavailable, errored, or returned empty).
        from langchain_core.messages import SystemMessage, HumanMessage

        lc = self._lc_client(req.model, req.api_key)
        bind_kwargs = self._lc_bind_kwargs(req)
        if bind_kwargs:
            lc = lc.bind(**bind_kwargs)
        messages = [SystemMessage(content=req.system), HumanMessage(content=req.user)]
        ai_msg = call_with_retry(lc.invoke, messages)
        text = _text_from_lc_content(getattr(ai_msg, "content", ai_msg))
        return LLMResponse(
            text=text, provider=self.name, model=req.model, raw=ai_msg, cache_hit=False
        )
