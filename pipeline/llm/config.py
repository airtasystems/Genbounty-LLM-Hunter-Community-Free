"""Central configuration for the multi-provider assistant LLM layer.

Responsibilities:
- Load ``.config`` then ``.env`` exactly once (``.env`` overrides ``.config``).
- Parse ``llm.yaml`` (role -> profile -> {provider, model}).
- Resolve a logical ``role`` to a concrete ``{provider, model, api_key}``.
  Provider/model come from ``llm.yaml``; when a Gemini role has no model set,
  a built-in default is used. API keys come from ``.env``.

Secrets (API keys) live in ``.env`` only; ``llm.yaml`` never contains keys.
Missing keys fail at call time with a clear per-role error, never at import.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_FILE = _ROOT / ".config"
_ENV_FILE = _ROOT / ".env"
_LLM_YAML = _ROOT / "llm.yaml"

_BOOTSTRAP_LOCK = threading.Lock()
_BOOTSTRAPPED = False
_YAML_LOCK = threading.Lock()
_YAML_CACHE: Optional[Dict[str, Any]] = None
_YAML_MTIME: Optional[float] = None

# Provider -> ordered list of env vars checked for the API key.
PROVIDER_KEY_ENV: Dict[str, tuple[str, ...]] = {
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "grok": ("GROK_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
}

# Used only when llm.yaml is missing/incomplete for a Gemini role (no model set).
_DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"


class LLMConfigError(RuntimeError):
    """Raised when a role cannot be resolved to a usable provider/model/key."""


@dataclass(frozen=True)
class ResolvedRole:
    """A fully resolved assignment for one logical LLM role."""

    role: str
    provider: str
    model: str
    api_key: str
    key_env: str
    extra: Dict[str, Any] = field(default_factory=dict)


def ensure_env_loaded() -> None:
    """Load ``.config`` then ``.env`` once. ``.env`` overrides ``.config``.

    This corrects the historical behaviour where per-module ``load_dotenv``
    calls left ``.config`` values winning over ``.env`` (dotenv default is
    ``override=False``). Shell environment variables still win over both.
    """
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    with _BOOTSTRAP_LOCK:
        if _BOOTSTRAPPED:
            return
        try:
            from dotenv import load_dotenv

            if _CONFIG_FILE.is_file():
                load_dotenv(_CONFIG_FILE)
            if _ENV_FILE.is_file():
                load_dotenv(_ENV_FILE, override=True)
        except ImportError:
            pass
        _BOOTSTRAPPED = True


def _llm_yaml_mtime() -> Optional[float]:
    try:
        return _LLM_YAML.stat().st_mtime if _LLM_YAML.is_file() else None
    except OSError:
        return None


def load_llm_yaml(*, force: bool = False) -> Dict[str, Any]:
    """Return the parsed ``llm.yaml`` mapping (``{}`` when absent/invalid)."""
    global _YAML_CACHE, _YAML_MTIME
    mtime = _llm_yaml_mtime()
    if _YAML_CACHE is not None and not force and mtime == _YAML_MTIME:
        return _YAML_CACHE
    with _YAML_LOCK:
        mtime = _llm_yaml_mtime()
        if _YAML_CACHE is not None and not force and mtime == _YAML_MTIME:
            return _YAML_CACHE
        data: Dict[str, Any] = {}
        if _LLM_YAML.is_file():
            try:
                import yaml

                loaded = yaml.safe_load(_LLM_YAML.read_text(encoding="utf-8")) or {}
                if isinstance(loaded, dict):
                    block = loaded.get("llm", loaded)
                    if isinstance(block, dict):
                        data = block
            except Exception:
                data = {}
        _YAML_CACHE = data
        _YAML_MTIME = mtime
        return data


def _profile_for_role(cfg: Dict[str, Any], role: str) -> Dict[str, Any]:
    """Resolve role -> profile dict from llm.yaml, or {} when unmapped."""
    roles = cfg.get("roles") if isinstance(cfg.get("roles"), dict) else {}
    profiles = cfg.get("profiles") if isinstance(cfg.get("profiles"), dict) else {}
    profile_ref = roles.get(role)
    if isinstance(profile_ref, dict):
        # Role maps directly to an inline {provider, model} bundle.
        return profile_ref
    if isinstance(profile_ref, str) and profile_ref in profiles:
        prof = profiles[profile_ref]
        return prof if isinstance(prof, dict) else {}
    return {}


def _resolve_api_key(provider: str) -> tuple[str, str]:
    """Return (api_key, key_env) for a provider, raising if none is set."""
    candidates = PROVIDER_KEY_ENV.get(provider)
    if not candidates:
        raise LLMConfigError(f"Unknown LLM provider '{provider}'.")
    for env_name in candidates:
        val = (os.getenv(env_name) or "").strip()
        if val:
            return val, env_name
    raise LLMConfigError(
        f"No API key for provider '{provider}': set one of "
        f"{', '.join(candidates)} in .env."
    )


def resolve_role(
    role: str,
    *,
    provider_override: Optional[str] = None,
    model_override: Optional[str] = None,
) -> ResolvedRole:
    """Resolve a logical role to a concrete provider/model/key.

    Order of precedence:
      1. Explicit ``provider``/``model`` overrides passed by the caller.
      2. ``llm.yaml`` role -> profile mapping.
      3. Provider defaults to ``gemini``; if still no model, use
         ``_DEFAULT_GEMINI_MODEL`` (Gemini only). Other providers require an
         explicit model in ``llm.yaml``.
    """
    ensure_env_loaded()
    cfg = load_llm_yaml()
    profile = _profile_for_role(cfg, role)

    provider = (provider_override or profile.get("provider") or "gemini").strip().lower()
    model = (model_override or profile.get("model") or "").strip()

    if not model:
        if provider == "gemini":
            model = _DEFAULT_GEMINI_MODEL
        else:
            raise LLMConfigError(
                f"Role '{role}' -> provider '{provider}' has no model. "
                f"Set a model in llm.yaml for this role."
            )

    api_key, key_env = _resolve_api_key(provider)

    extra: Dict[str, Any] = {}
    for k, v in profile.items():
        if k not in ("provider", "model"):
            extra[k] = v

    return ResolvedRole(
        role=role,
        provider=provider,
        model=model,
        api_key=api_key,
        key_env=key_env,
        extra=extra,
    )


def defaults() -> Dict[str, Any]:
    """Return the ``defaults`` block from llm.yaml (retry, rate_limit, ...)."""
    cfg = load_llm_yaml()
    d = cfg.get("defaults")
    return d if isinstance(d, dict) else {}


def refusal_fallback() -> Optional[Dict[str, str]]:
    """Provider/model to retry on a content-policy refusal, or None if unset.

    Sourced from ``defaults.refusal_fallback`` in llm.yaml, which may be either a
    profile name (resolved via ``profiles``) or an inline ``{provider, model}``
    mapping. Env overrides: ``REFUSAL_FALLBACK_PROVIDER`` / ``REFUSAL_FALLBACK_MODEL``.
    Used when a provider (e.g. OpenAI's ``cyber_policy``) refuses adversarial
    red-team content so generation can continue on a permissive provider.
    """
    ensure_env_loaded()
    env_provider = (os.getenv("REFUSAL_FALLBACK_PROVIDER") or "").strip().lower()
    env_model = (os.getenv("REFUSAL_FALLBACK_MODEL") or "").strip()
    if env_provider and env_model:
        return {"provider": env_provider, "model": env_model}

    ref: Any = defaults().get("refusal_fallback")
    if isinstance(ref, str):
        cfg = load_llm_yaml()
        profiles = cfg.get("profiles") if isinstance(cfg.get("profiles"), dict) else {}
        prof = profiles.get(ref)
        ref = prof if isinstance(prof, dict) else None
    if isinstance(ref, dict):
        provider = (ref.get("provider") or "").strip().lower()
        model = (ref.get("model") or "").strip()
        if provider and model:
            return {"provider": provider, "model": model}
    return None


def reset_caches() -> None:
    """Test hook: clear the cached llm.yaml and force env re-bootstrap."""
    global _BOOTSTRAPPED, _YAML_CACHE, _YAML_MTIME
    _BOOTSTRAPPED = False
    _YAML_CACHE = None
    _YAML_MTIME = None
