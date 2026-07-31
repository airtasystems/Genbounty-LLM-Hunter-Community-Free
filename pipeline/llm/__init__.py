"""Shared multi-provider assistant LLM layer.

Public entry point for every assistant LLM call in Genbounty Hunter. Call sites
use :func:`complete` with a logical ``role``; the role is resolved to a
provider + model via ``llm.yaml``, and the
matching provider adapter runs the completion with shared retry, rate limiting,
and telemetry.

Scope: assistant LLMs only (generation, assessment, discovery, etc.). This layer
is NOT used for the target LLM under test.
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

from pipeline.llm import rate_limit, telemetry
from pipeline.llm.base import LLMRequest, LLMResponse, ProviderAdapter
from pipeline.llm.config import (
    LLMConfigError,
    ResolvedRole,
    ensure_env_loaded,
    refusal_fallback,
    resolve_role,
)
from pipeline.llm.providers import all_instantiated, get_adapter
from pipeline.llm.temperatures import ROLE_TEMPERATURES, temperature_for_role

__all__ = [
    "complete",
    "complete_text",
    "resolve_role",
    "temperature_for_role",
    "ROLE_TEMPERATURES",
    "clear_gemini_context_cache",
    "LLMRequest",
    "LLMResponse",
    "ResolvedRole",
    "ProviderAdapter",
    "LLMConfigError",
]


def _echo_model_in_use(role: str, resolved: ResolvedRole) -> None:
    """Print an uppercase, real-time line naming the model handling this call.

    Emitted to stdout (not just the logger) so it appears live in the UI's
    experiment output, which captures subprocess/thread stdout. This is the
    single point every assistant LLM call passes through, so it confirms in real
    time which provider/model actually served each role (no silent fallbacks).
    Set ``GENBOUNTY_LLM_ECHO=0`` to silence.
    """
    if (os.getenv("GENBOUNTY_LLM_ECHO") or "").strip() in ("0", "false", "no", "off"):
        return
    print(
        f"[LLM] ROLE={role.upper()} PROVIDER={resolved.provider.upper()} "
        f"MODEL={resolved.model.upper()}",
        flush=True,
    )


# Substrings / codes that indicate a provider refused on content-policy grounds
# (as opposed to a transient error). These are retried on the configured
# permissive fallback provider rather than surfaced as a hard failure.
_REFUSAL_TOKENS = (
    "cyber_policy",
    "content was flagged",
    "flagged for possible",
    "content_policy",
    "content policy",
    "usage_policy",
    "usage policy",
    "safety policy",
)


def _is_policy_refusal(exc: BaseException) -> bool:
    """True when an error looks like a content-policy refusal, not a transient fault."""
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code.strip().lower() in (
        "cyber_policy",
        "content_policy_violation",
    ):
        return True
    msg = str(exc).lower()
    return any(token in msg for token in _REFUSAL_TOKENS)


def _try_policy_fallback(role: str, primary: ResolvedRole, req: LLMRequest) -> Optional[LLMResponse]:
    """Retry a refused call on the configured permissive fallback provider.

    Returns the fallback response, or None when no usable fallback is configured
    (missing config, missing key, or the fallback resolves to the same target).
    """
    fb = refusal_fallback()
    if not fb:
        return None
    if fb["provider"] == primary.provider and fb["model"] == primary.model:
        return None
    try:
        resolved = resolve_role(
            role, provider_override=fb["provider"], model_override=fb["model"]
        )
    except LLMConfigError as exc:
        print(f"[LLM] policy-refusal fallback unavailable: {exc}", flush=True)
        return None

    print(
        f"[LLM] ROLE={role.upper()} REFUSED by "
        f"{primary.provider.upper()}/{primary.model.upper()} - FALLBACK to "
        f"{resolved.provider.upper()}/{resolved.model.upper()}",
        flush=True,
    )
    adapter = get_adapter(resolved.provider)
    fb_req = LLMRequest(
        system=req.system,
        user=req.user,
        model=resolved.model,
        api_key=resolved.api_key,
        json_mode=req.json_mode,
        temperature=req.temperature,
        max_output_tokens=req.max_output_tokens,
        top_p=req.top_p,
        top_k=req.top_k,
        cache_key=req.cache_key,
        extra=dict(resolved.extra),
    )
    rate_limit.acquire(provider=resolved.provider)
    t0 = time.perf_counter()
    try:
        resp = adapter.complete(fb_req)
    except BaseException as exc:  # noqa: BLE001 - record then re-raise
        telemetry.record(
            role=role,
            provider=resolved.provider,
            model=resolved.model,
            latency_s=time.perf_counter() - t0,
            error=exc,
        )
        raise
    telemetry.record(
        role=role,
        provider=resolved.provider,
        model=resolved.model,
        latency_s=time.perf_counter() - t0,
        response=resp,
    )
    return resp


def complete(
    role: str,
    *,
    system: str = "",
    user: str,
    json_mode: bool = False,
    temperature: Optional[float] = None,
    max_output_tokens: Optional[int] = None,
    top_p: Optional[float] = None,
    top_k: Optional[int] = None,
    cache_key: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> LLMResponse:
    """Run one completion for a logical ``role`` and return a normalized response.

    ``provider`` / ``model`` override llm.yaml for the rare call site that needs
    an explicit assignment. ``cache_key`` opts the request into provider-side
    prompt/context caching (honoured by the Gemini adapter only).

    When ``temperature`` is omitted, :func:`temperature_for_role` supplies a
    role-appropriate default so providers do not silently fall back to ~1.0.
    """
    if temperature is None:
        temperature = temperature_for_role(role)
    resolved = resolve_role(role, provider_override=provider, model_override=model)
    adapter = get_adapter(resolved.provider)
    _echo_model_in_use(role, resolved)
    req = LLMRequest(
        system=system,
        user=user,
        model=resolved.model,
        api_key=resolved.api_key,
        json_mode=json_mode,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        top_p=top_p,
        top_k=top_k,
        cache_key=cache_key,
        extra=dict(resolved.extra),
    )

    rate_limit.acquire(provider=resolved.provider)
    t0 = time.perf_counter()
    try:
        resp = adapter.complete(req)
    except BaseException as exc:  # noqa: BLE001 - record then re-raise
        telemetry.record(
            role=role,
            provider=resolved.provider,
            model=resolved.model,
            latency_s=time.perf_counter() - t0,
            error=exc,
        )
        if _is_policy_refusal(exc):
            fb_resp = _try_policy_fallback(role, resolved, req)
            if fb_resp is not None:
                return fb_resp
        raise
    telemetry.record(
        role=role,
        provider=resolved.provider,
        model=resolved.model,
        latency_s=time.perf_counter() - t0,
        response=resp,
    )
    return resp


def complete_text(role: str, **kwargs: Any) -> str:
    """Convenience wrapper returning just the response text."""
    return complete(role, **kwargs).text


def clear_gemini_context_cache(*, delete_remote: bool = False) -> None:
    """Clear the Gemini adapter's server-side context-cache handles.

    Safe no-op when the Gemini adapter has not been used. Kept as the single
    shared implementation behind the per-module ``clear_gemini_cache`` wrappers.
    """
    ensure_env_loaded()
    for name, adapter in all_instantiated().items():
        if name == "gemini":
            adapter.clear_caches(delete_remote=delete_remote)
