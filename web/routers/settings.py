from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re as _re
import sys
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from web.paths import BB_DIR, ROOT, ensure_generate_tests_path

router = APIRouter()

from pipeline.component_settings import (
    EDITABLE_BROWSER_VARS as _EDITABLE_VARS,
    get_effective_settings_detail,
    parse_browser_config_py,
    save_defaults_yaml_settings,
    reset_all_settings_to_factory,
    settings_schema_payload,
)
from pipeline.llm.profiles_editor import llm_config_payload, save_llm_profiles

_CONFIG_PY = BB_DIR / "browser_bot" / "config.py"


def _parse_config() -> dict:
    return parse_browser_config_py()


def _write_config_value(source: str, name: str, value) -> str:
    if name == "BLOCKED_TYPES":
        items = ", ".join(f'"{v}"' for v in sorted(value))
        new_repr = ("{" + items + "}") if items else "set()"
    elif isinstance(value, bool):
        new_repr = "True" if value else "False"
    elif isinstance(value, str):
        new_repr = repr(value)
    elif isinstance(value, (int, float)):
        new_repr = repr(value)
    elif isinstance(value, list):
        new_repr = repr(value)
    else:
        new_repr = repr(value)

    # Match both ``NAME = …`` and annotated ``NAME: int = …`` assignments.
    pattern = _re.compile(
        r"^(" + _re.escape(name) + r"(?:\s*:\s*[^=]+)?\s*=\s*)(.*)$",
        _re.MULTILINE,
    )
    new_source, n = pattern.subn(lambda m: m.group(1) + new_repr, source, count=1)
    if n != 1:
        raise ValueError(f"Could not find assignment for {name} in config.py")
    return new_source


@router.get("/api/config")
async def api_get_config():
    return _parse_config()


@router.get("/api/settings-schema")
async def api_settings_schema():
    """Schema + global defaults for component settings overrides."""
    return settings_schema_payload()


class SaveDefaultsBody(BaseModel):
    changes: dict


@router.post("/api/defaults-config")
async def api_save_defaults_config(body: SaveDefaultsBody):
    """Update shipped defaults (config.defaults.yaml settings block)."""
    try:
        updated = save_defaults_yaml_settings(body.changes or {})
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "updated": updated}


@router.get("/api/llm-config")
async def api_get_llm_config():
    """Assistant LLM profile provider/model assignments (llm.yaml)."""
    try:
        return llm_config_payload()
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


class SaveLlmProfilesBody(BaseModel):
    profiles: dict


@router.post("/api/llm-config")
async def api_save_llm_config(body: SaveLlmProfilesBody):
    """Update llm.yaml profile provider/model entries."""
    try:
        updated = save_llm_profiles(body.profiles or {})
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "updated": updated}


class PipelineSettingsBody(BaseModel):
    security_assess_concurrency: int | None = None
    open_loop_prompts: int | None = None
    closed_loop_prompts: int | None = None
    payloads_output_dir: str | None = None
    # export_host accepted for older clients but ignored (host is hardcoded).
    export_host: str | None = None
    export_batch_size: int | None = None
    export_delay_seconds: float | None = None
    export_max_retries: int | None = None
    export_retry_base_seconds: float | None = None


@router.get("/api/pipeline-settings")
async def api_get_pipeline_settings():
    """Global pipeline + export knobs from pipeline_settings.yaml (not .env)."""
    from pipeline.pipeline_settings import pipeline_settings_payload

    return pipeline_settings_payload()


@router.post("/api/pipeline-settings")
async def api_save_pipeline_settings(body: PipelineSettingsBody):
    """Persist Settings → Pipeline values to pipeline_settings.yaml."""
    from pipeline.pipeline_settings import save_export_settings, save_pipeline_settings

    updates: dict = {}
    if body.security_assess_concurrency is not None:
        updates["security_assess_concurrency"] = body.security_assess_concurrency
    if body.open_loop_prompts is not None:
        updates["open_loop_prompts"] = body.open_loop_prompts
    if body.closed_loop_prompts is not None:
        updates["closed_loop_prompts"] = body.closed_loop_prompts
    if body.payloads_output_dir is not None:
        updates["payloads_output_dir"] = body.payloads_output_dir
    export_updates: dict = {}
    if body.export_batch_size is not None:
        export_updates["batch_size"] = body.export_batch_size
    if body.export_delay_seconds is not None:
        export_updates["delay_seconds"] = body.export_delay_seconds
    if body.export_max_retries is not None:
        export_updates["max_retries"] = body.export_max_retries
    if body.export_retry_base_seconds is not None:
        export_updates["retry_base_seconds"] = body.export_retry_base_seconds
    try:
        values = save_pipeline_settings(updates) if updates else None
        export_values = save_export_settings(export_updates) if export_updates else None
        if values is None:
            from pipeline.pipeline_settings import load_pipeline_settings

            values = load_pipeline_settings()
        if export_values is None:
            from pipeline.pipeline_settings import load_export_settings

            export_values = load_export_settings()
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "values": values, "export": export_values}


@router.post("/api/settings/reset-factory")
async def api_reset_settings_factory():
    """Restore factory settings and clear all higher-layer overrides."""
    try:
        result = reset_all_settings_to_factory()
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    # Cache globals are written to pipeline_settings.yaml inside reset_all_settings_to_factory.
    result["cache_updated"] = sorted((result.get("cache_settings") or {}).keys())
    return {"ok": True, **result}


@router.get("/api/sites/{site}/{component}/effective-settings")
async def api_effective_settings(site: str, component: str):
    """Per-key global, override, and effective values for a component."""
    return get_effective_settings_detail(site=site, component=component)


class SaveConfigBody(BaseModel):
    changes: dict

@router.post("/api/config")
async def api_save_config(body: SaveConfigBody):
    source = _CONFIG_PY.read_text(encoding="utf-8")
    try:
        for name, value in body.changes.items():
            if name not in _EDITABLE_VARS:
                raise HTTPException(400, f"Not an editable config key: {name}")
            source = _write_config_value(source, name, value)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _CONFIG_PY.write_text(source, encoding="utf-8")
    return {"ok": True, "updated": list(body.changes.keys())}

# ---------------------------------------------------------------------------
# Credentials - stored in root .env, never returned to browser
# ---------------------------------------------------------------------------

_ENV_FILE = ROOT / ".env"
# .env is secrets-only: provider keys + Genbounty API key. Cache lives in YAML; export host is hardcoded.
_GB_API_KEY_VAR = "GENBOUNTY_API_KEY"
_GB_USER_ID_VAR = "GENBOUNTY_USER_ID"
_LLM_KEY_PROVIDERS: tuple[tuple[str, str, str], ...] = (
    ("gemini", "Gemini", "GEMINI_API_KEY"),
    ("anthropic", "Anthropic", "ANTHROPIC_API_KEY"),
    ("openai", "OpenAI", "OPENAI_API_KEY"),
    ("grok", "Grok", "GROK_API_KEY"),
    ("openrouter", "OpenRouter", "OPENROUTER_API_KEY"),
)
_LLM_KEY_VARS = {pid: env_var for pid, _label, env_var in _LLM_KEY_PROVIDERS}
_ENV_WRITE_ALLOWLIST = frozenset({*_LLM_KEY_VARS.values(), _GB_API_KEY_VAR, _GB_USER_ID_VAR})
_TARGET_API_KEY_PREFIX = "TARGET_API_KEY_"


def _env_key_writable(name: str) -> bool:
    """True for allowlisted provider/Genbounty keys or per-target TARGET_API_KEY_* secrets."""
    if name in _ENV_WRITE_ALLOWLIST:
        return True
    return name.startswith(_TARGET_API_KEY_PREFIX)


def _llm_key_status() -> list[dict[str, object]]:
    """Return provider key presence from .env / process env (never the secret value)."""
    env = _read_env()
    rows: list[dict[str, object]] = []
    for pid, label, env_var in _LLM_KEY_PROVIDERS:
        present = bool((env.get(env_var) or os.environ.get(env_var) or "").strip())
        rows.append(
            {
                "id": pid,
                "label": label,
                "env_var": env_var,
                "has_key": present,
            }
        )
    return rows


def _read_env() -> dict[str, str]:
    """Parse key=value lines from .env, ignoring comments and blank lines."""
    result: dict[str, str] = {}
    if not _ENV_FILE.exists():
        return result
    for raw in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def _write_env(updates: dict[str, str | None]) -> None:
    """Update or remove API-key keys in .env without touching other lines.

    Only allowlisted keys may be written (provider keys, GENBOUNTY_API_KEY,
    GENBOUNTY_USER_ID, and ``TARGET_API_KEY_*`` target secrets).
    Also syncs ``os.environ`` so the running server picks up key changes without restart.
    """
    allowed = {k: v for k, v in (updates or {}).items() if _env_key_writable(k)}
    if not allowed:
        return

    lines: list[str] = []
    if _ENV_FILE.exists():
        lines = _ENV_FILE.read_text(encoding="utf-8").splitlines()

    replaced: set[str] = set()
    new_lines: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(raw)
            continue
        if "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k in allowed:
                replaced.add(k)
                if allowed[k] is not None:
                    new_lines.append(f'{k}="{allowed[k]}"')
                # None → delete the line
                continue
        new_lines.append(raw)

    # Append keys that weren't already in the file
    for k, v in allowed.items():
        if k not in replaced and v is not None:
            new_lines.append(f'{k}="{v}"')

    _ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    for k, v in allowed.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


class CredentialsBody(BaseModel):
    # host accepted for older clients but ignored (platform host is hardcoded).
    host: str = ""
    api_key: str = ""
    user_id: str = ""


def _genbounty_user_id_from_env(env: dict[str, str] | None = None) -> str:
    src = env if env is not None else _read_env()
    return (
        (src.get(_GB_USER_ID_VAR) or "").strip()
        or (os.environ.get(_GB_USER_ID_VAR) or "").strip()
    )


@router.get("/api/credentials")
async def api_get_credentials():
    """Return Genbounty credentials status - api_key is never sent, only has_api_key flag."""
    from pipeline.pipeline_settings import export_host

    env = _read_env()
    return {
        "host": export_host(),
        "has_api_key": bool(env.get(_GB_API_KEY_VAR, "") or os.environ.get(_GB_API_KEY_VAR, "")),
        # Prefer .env GENBOUNTY_USER_ID; component config.yaml may override in the UI.
        "user_id": _genbounty_user_id_from_env(env),
    }


def _normalize_env_target(raw: str) -> str:
    """Map TARGET .env value to site directory name (host:port, no scheme)."""
    text = (raw or "").strip().strip("/")
    if not text:
        return ""
    if "://" in text or text.startswith("//"):
        domain = get_domain_from_url(text if "://" in text else f"https://{text}")
        return domain or text
    return text


def _resolve_env_site_component(target: str, component: str) -> tuple[str, str]:
    """Match .env TARGET/COMPONENT to existing site and component ids."""
    site = _normalize_env_target(target)
    comp = (component or "").strip()
    if not site:
        return "", comp

    sites = list_sites()
    if site not in sites:
        lower = site.lower()
        for name in sites:
            if name.lower() == lower:
                site = name
                break

    if not comp:
        return site, ""

    if site in sites or any(s.lower() == site.lower() for s in sites):
        if site not in sites:
            site = next(s for s in sites if s.lower() == site.lower())
        comps = list_components(site)
        if comp not in comps:
            lower_c = comp.lower()
            for name in comps:
                if name.lower() == lower_c:
                    comp = name
                    break
    return site, comp


@router.get("/api/env-defaults")
async def api_env_defaults():
    """Legacy: return TARGET/COMPONENT from .env.

    The web UI restores site/component from browser local storage instead.
    Kept for older clients and tooling that still call this endpoint.
    """
    env = _read_env()
    target, component = _resolve_env_site_component(
        env.get("TARGET", ""),
        env.get("COMPONENT", ""),
    )
    return {
        "target": target,
        "component": component,
    }


@router.post("/api/credentials")
async def api_save_credentials(body: CredentialsBody):
    """Persist Genbounty API key / user id to .env. Empty string = leave existing. Host is hardcoded."""
    from pipeline.pipeline_settings import export_host

    updates: dict[str, str | None] = {}
    if body.api_key:
        updates[_GB_API_KEY_VAR] = body.api_key
    if body.user_id is not None and str(body.user_id).strip():
        updates[_GB_USER_ID_VAR] = str(body.user_id).strip()
    if updates:
        _write_env(updates)
    env = _read_env()
    return {
        "ok": True,
        "host": export_host(),
        "has_api_key": bool(env.get(_GB_API_KEY_VAR, "") or os.environ.get(_GB_API_KEY_VAR, "")),
        "user_id": _genbounty_user_id_from_env(env),
    }


@router.delete("/api/credentials")
async def api_clear_credentials():
    """Remove Genbounty API key and user id from .env."""
    _write_env({_GB_API_KEY_VAR: None, _GB_USER_ID_VAR: None})
    return {"ok": True}


class LlmKeysBody(BaseModel):
    gemini: str = ""
    anthropic: str = ""
    openai: str = ""
    grok: str = ""
    openrouter: str = ""


@router.get("/api/llm-keys")
async def api_get_llm_keys():
    """Return which provider API keys are set. Secret values are never sent."""
    return {"providers": _llm_key_status()}


@router.post("/api/llm-keys")
async def api_save_llm_keys(body: LlmKeysBody):
    """Persist provider API keys to .env. Empty string = leave existing value."""
    updates: dict[str, str | None] = {}
    for pid, env_var in _LLM_KEY_VARS.items():
        val = str(getattr(body, pid, "") or "").strip()
        if val:
            updates[env_var] = val
    if updates:
        _write_env(updates)
    return {"ok": True, "providers": _llm_key_status()}


@router.delete("/api/llm-keys")
async def api_clear_llm_keys(provider: str = ""):
    """Remove one provider key (``?provider=gemini``) or all LLM provider keys."""
    pid = (provider or "").strip().lower()
    if pid:
        env_var = _LLM_KEY_VARS.get(pid)
        if not env_var:
            raise HTTPException(400, f"Unknown provider: {provider}")
        _write_env({env_var: None})
    else:
        _write_env({env_var: None for env_var in _LLM_KEY_VARS.values()})
    return {"ok": True, "providers": _llm_key_status()}


class CacheSettingsBody(BaseModel):
    gemini_use_cache: bool = False
    openai_use_cache: bool = True
    openai_cache_retention: str = "standard"
    grok_use_cache: bool = True
    anthropic_use_cache: bool = True
    anthropic_cache_ttl: str = "5m"


@router.get("/api/cache-settings")
async def api_get_cache_settings(site: str = "", component: str = ""):
    """Return global cache settings and effective values for optional site/component."""
    from pipeline.component_settings import (
        component_gemini_cache_override,
        gemini_cache_enabled,
        get_global_settings,
        provider_cache_settings,
    )

    site = site.strip() or None
    component = component.strip() or None
    override = component_gemini_cache_override(site=site, component=component) if site and component else None
    globals_ = get_global_settings()
    openai_eff = provider_cache_settings("openai", site=site, component=component)
    grok_eff = provider_cache_settings("grok", site=site, component=component)
    anthropic_eff = provider_cache_settings("anthropic", site=site, component=component)
    return {
        "gemini_use_cache": bool(globals_.get("gemini_use_cache")),
        "effective_gemini_use_cache": gemini_cache_enabled(site=site, component=component),
        "component_override": override,
        "openai_use_cache": bool(globals_.get("openai_use_cache")),
        "openai_cache_retention": str(globals_.get("openai_cache_retention") or "standard"),
        "grok_use_cache": bool(globals_.get("grok_use_cache")),
        "anthropic_use_cache": bool(globals_.get("anthropic_use_cache")),
        "anthropic_cache_ttl": str(globals_.get("anthropic_cache_ttl") or "5m"),
        "effective_openai_use_cache": bool(openai_eff.get("enabled")),
        "effective_openai_cache_retention": str(openai_eff.get("retention") or "standard"),
        "effective_grok_use_cache": bool(grok_eff.get("enabled")),
        "effective_anthropic_use_cache": bool(anthropic_eff.get("enabled")),
        "effective_anthropic_cache_ttl": str(anthropic_eff.get("ttl") or "5m"),
    }


@router.post("/api/cache-settings")
async def api_save_cache_settings(body: CacheSettingsBody):
    """Persist global prompt-cache toggles to pipeline_settings.yaml."""
    from pipeline.pipeline_settings import save_cache_settings

    retention = body.openai_cache_retention if body.openai_cache_retention in {"standard", "24h"} else "standard"
    ttl = body.anthropic_cache_ttl if body.anthropic_cache_ttl in {"5m", "1h"} else "5m"
    saved = save_cache_settings({
        "gemini_use_cache": bool(body.gemini_use_cache),
        "openai_use_cache": bool(body.openai_use_cache),
        "openai_cache_retention": retention,
        "grok_use_cache": bool(body.grok_use_cache),
        "anthropic_use_cache": bool(body.anthropic_use_cache),
        "anthropic_cache_ttl": ttl,
    })
    return {
        "ok": True,
        "gemini_use_cache": bool(saved.get("gemini_use_cache")),
        "openai_use_cache": bool(saved.get("openai_use_cache")),
        "openai_cache_retention": str(saved.get("openai_cache_retention") or retention),
        "grok_use_cache": bool(saved.get("grok_use_cache")),
        "anthropic_use_cache": bool(saved.get("anthropic_use_cache")),
        "anthropic_cache_ttl": str(saved.get("anthropic_cache_ttl") or ttl),
    }

