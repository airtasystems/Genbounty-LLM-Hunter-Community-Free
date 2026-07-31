"""Global settings (pipeline, cache, export) persisted in ``pipeline_settings.yaml``.

Editable from Settings → Pipeline / Cache Control and the Export tab.
``.env`` is used only for API keys - not for these knobs.
Genbounty platform host is hardcoded (``GENBOUNTY_EXPORT_HOST``), not stored in YAML.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_SETTINGS_FILE = _ROOT / "pipeline_settings.yaml"
_ENV_FILE = _ROOT / ".env"

_LOCK = threading.RLock()
_CACHE: dict[str, Any] | None = None
_MTIME: float | None = None
_SEEDED = False

PIPELINE_DEFAULTS: dict[str, Any] = {
    "security_assess_concurrency": 4,
    "open_loop_prompts": 4,
    "closed_loop_prompts": 4,
    "payloads_output_dir": "payloads/generate",
}

# Back-compat alias used by older callers / tests.
DEFAULTS = PIPELINE_DEFAULTS

_PIPELINE_INT_BOUNDS: dict[str, tuple[int, int]] = {
    "security_assess_concurrency": (1, 32),
    "open_loop_prompts": (1, 64),
    "closed_loop_prompts": (1, 64),
}

CACHE_DEFAULTS: dict[str, Any] = {
    "gemini_use_cache": False,
    "openai_use_cache": True,
    "openai_cache_retention": "standard",
    "grok_use_cache": True,
    "anthropic_use_cache": True,
    "anthropic_cache_ttl": "5m",
}

_CACHE_BOOL_KEYS = frozenset({
    "gemini_use_cache",
    "openai_use_cache",
    "grok_use_cache",
    "anthropic_use_cache",
})
_CACHE_CHOICE_OPTIONS: dict[str, frozenset[str]] = {
    "openai_cache_retention": frozenset({"standard", "24h"}),
    "anthropic_cache_ttl": frozenset({"5m", "1h"}),
}

# Legacy .env keys used only for one-time seed into YAML.
_CACHE_ENV_BOOL: dict[str, str] = {
    "gemini_use_cache": "GEMINI_USE_CACHE",
    "openai_use_cache": "OPENAI_USE_CACHE",
    "grok_use_cache": "GROK_USE_CACHE",
    "anthropic_use_cache": "ANTHROPIC_USE_CACHE",
}
_CACHE_ENV_CHOICE: dict[str, str] = {
    "openai_cache_retention": "OPENAI_CACHE_RETENTION",
    "anthropic_cache_ttl": "ANTHROPIC_CACHE_TTL",
}

# Platform submit target - not configurable via Settings / YAML / .env.
GENBOUNTY_EXPORT_HOST = "https://genbounty.com"

EXPORT_DEFAULTS: dict[str, Any] = {
    "batch_size": 25,
    "delay_seconds": 2.0,
    "max_retries": 6,
    "retry_base_seconds": 5.0,
}

_EXPORT_INT_BOUNDS: dict[str, tuple[int, int]] = {
    "batch_size": (1, 2500),
    "max_retries": (1, 20),
}

_EXPORT_ENV_SEED: dict[str, str] = {
    "batch_size": "GENBOUNTY_EXPORT_BATCH_SIZE",
    "delay_seconds": "GENBOUNTY_EXPORT_DELAY_SECONDS",
    "max_retries": "GENBOUNTY_EXPORT_MAX_RETRIES",
    "retry_base_seconds": "GENBOUNTY_EXPORT_RETRY_BASE_SECONDS",
}

_FALSE = frozenset({"0", "false", "no", "off", ""})


def _is_docker() -> bool:
    return Path("/.dockerenv").exists()


def reset_cache() -> None:
    """Test hook: drop the in-memory settings cache."""
    global _CACHE, _MTIME
    with _LOCK:
        _CACHE = None
        _MTIME = None


def _coerce_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _coerce_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _coerce_path(value: Any, default: str) -> str:
    text = str(value or "").strip()
    return text or default


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if not text:
        return default
    return text not in _FALSE


def _read_env_file() -> dict[str, str]:
    result: dict[str, str] = {}
    if not _ENV_FILE.is_file():
        return result
    try:
        for raw in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return result


def _env_lookup(env: dict[str, str], name: str) -> str:
    return (env.get(name) or os.environ.get(name) or "").strip()


def _normalize_pipeline(raw: dict[str, Any] | None) -> dict[str, Any]:
    src = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}
    for key, default in PIPELINE_DEFAULTS.items():
        if key in _PIPELINE_INT_BOUNDS:
            lo, hi = _PIPELINE_INT_BOUNDS[key]
            out[key] = _coerce_int(src.get(key, default), int(default), minimum=lo, maximum=hi)
        elif key == "payloads_output_dir":
            out[key] = _coerce_path(src.get(key, default), str(default))
        else:
            out[key] = src.get(key, default)
    return out


def _normalize_cache(raw: dict[str, Any] | None) -> dict[str, Any]:
    src = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}
    for key, default in CACHE_DEFAULTS.items():
        if key in _CACHE_BOOL_KEYS:
            out[key] = _coerce_bool(src.get(key, default), bool(default))
        elif key in _CACHE_CHOICE_OPTIONS:
            text = str(src.get(key, default) or default).strip()
            allowed = _CACHE_CHOICE_OPTIONS[key]
            out[key] = text if text in allowed else str(default)
        else:
            out[key] = src.get(key, default)
    return out


def _normalize_export(raw: dict[str, Any] | None) -> dict[str, Any]:
    src = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {
        # Always surface the hardcoded platform host (YAML host is ignored).
        "host": GENBOUNTY_EXPORT_HOST,
    }
    for key, (lo, hi) in _EXPORT_INT_BOUNDS.items():
        default = int(EXPORT_DEFAULTS[key])
        out[key] = _coerce_int(src.get(key, default), default, minimum=lo, maximum=hi)
    out["delay_seconds"] = _coerce_float(
        src.get("delay_seconds", EXPORT_DEFAULTS["delay_seconds"]),
        float(EXPORT_DEFAULTS["delay_seconds"]),
    )
    out["retry_base_seconds"] = _coerce_float(
        src.get("retry_base_seconds", EXPORT_DEFAULTS["retry_base_seconds"]),
        float(EXPORT_DEFAULTS["retry_base_seconds"]),
    ) or float(EXPORT_DEFAULTS["retry_base_seconds"])
    return out


def _file_mtime() -> float | None:
    try:
        return _SETTINGS_FILE.stat().st_mtime if _SETTINGS_FILE.is_file() else None
    except OSError:
        return None


def _load_raw_file() -> dict[str, Any]:
    if not _SETTINGS_FILE.is_file():
        return {}
    try:
        import yaml

        loaded = yaml.safe_load(_SETTINGS_FILE.read_text(encoding="utf-8")) or {}
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _seed_cache_from_env(present: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    """Fill missing cache keys from legacy .env values."""
    seeded = dict(present)
    for key, env_name in _CACHE_ENV_BOOL.items():
        if key in seeded:
            continue
        raw = _env_lookup(env, env_name)
        if raw:
            seeded[key] = raw not in _FALSE
    for key, env_name in _CACHE_ENV_CHOICE.items():
        if key in seeded:
            continue
        raw = _env_lookup(env, env_name)
        if raw:
            seeded[key] = raw
    return seeded


def _seed_export_from_env(present: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    seeded = dict(present)
    for key, env_name in _EXPORT_ENV_SEED.items():
        if key in seeded:
            continue
        raw = _env_lookup(env, env_name)
        if raw:
            seeded[key] = raw
    return seeded


def _yaml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _format_bool(value: bool) -> str:
    return "true" if value else "false"


def _write_all(
    pipeline: dict[str, Any],
    cache: dict[str, Any],
    export: dict[str, Any],
) -> None:
    path_val = _yaml_escape(str(pipeline["payloads_output_dir"]))
    text = (
        "# Global settings (Settings → Pipeline / Cache Control / Export).\n"
        "# Not for API keys - those stay in .env.\n"
        "# Genbounty export host is hardcoded (https://genbounty.com), not stored here.\n"
        "pipeline:\n"
        f"  security_assess_concurrency: {pipeline['security_assess_concurrency']}\n"
        f"  open_loop_prompts: {pipeline['open_loop_prompts']}\n"
        f"  closed_loop_prompts: {pipeline['closed_loop_prompts']}\n"
        f'  payloads_output_dir: "{path_val}"\n'
        "cache:\n"
        f"  gemini_use_cache: {_format_bool(bool(cache['gemini_use_cache']))}\n"
        f"  openai_use_cache: {_format_bool(bool(cache['openai_use_cache']))}\n"
        f"  openai_cache_retention: {cache['openai_cache_retention']}\n"
        f"  grok_use_cache: {_format_bool(bool(cache['grok_use_cache']))}\n"
        f"  anthropic_use_cache: {_format_bool(bool(cache['anthropic_use_cache']))}\n"
        f"  anthropic_cache_ttl: {cache['anthropic_cache_ttl']}\n"
        "export:\n"
        f"  batch_size: {export['batch_size']}\n"
        f"  delay_seconds: {export['delay_seconds']}\n"
        f"  max_retries: {export['max_retries']}\n"
        f"  retry_base_seconds: {export['retry_base_seconds']}\n"
    )
    _SETTINGS_FILE.write_text(text, encoding="utf-8")
    reset_cache()


def _load_all(*, force: bool = False) -> dict[str, Any]:
    """Return ``{pipeline, cache, export}`` normalized (cached until file changes)."""
    global _CACHE, _MTIME, _SEEDED
    mtime = _file_mtime()
    if _CACHE is not None and not force and mtime == _MTIME:
        return {
            "pipeline": dict(_CACHE["pipeline"]),
            "cache": dict(_CACHE["cache"]),
            "export": dict(_CACHE["export"]),
        }
    with _LOCK:
        mtime = _file_mtime()
        if _CACHE is not None and not force and mtime == _MTIME:
            return {
                "pipeline": dict(_CACHE["pipeline"]),
                "cache": dict(_CACHE["cache"]),
                "export": dict(_CACHE["export"]),
            }
        raw = _load_raw_file()
        # Legacy: entire file was a flat pipeline block (no top-level keys).
        if raw and "pipeline" not in raw and "cache" not in raw and "export" not in raw:
            pipeline_raw = raw
            cache_raw: dict[str, Any] = {}
            export_raw: dict[str, Any] = {}
        else:
            pipeline_raw = raw.get("pipeline") if isinstance(raw.get("pipeline"), dict) else {}
            cache_raw = raw.get("cache") if isinstance(raw.get("cache"), dict) else {}
            export_raw = raw.get("export") if isinstance(raw.get("export"), dict) else {}

        env = _read_env_file()
        cache_present = dict(cache_raw)
        export_present = dict(export_raw)
        cache_seeded = _seed_cache_from_env(cache_present, env) if not _SEEDED else cache_present
        export_seeded = _seed_export_from_env(export_present, env) if not _SEEDED else export_present
        pipeline_norm = _normalize_pipeline(pipeline_raw)
        cache_norm = _normalize_cache(cache_seeded)
        export_norm = _normalize_export(export_seeded)

        if not _SEEDED and (
            cache_seeded != cache_present
            or export_seeded != export_present
            or "cache" not in raw
            or "export" not in raw
        ):
            # Persist seeded / newly structured values so .env is no longer needed.
            _write_all(pipeline_norm, cache_norm, export_norm)
            mtime = _file_mtime()
            _SEEDED = True
        elif not _SEEDED:
            _SEEDED = True

        _CACHE = {
            "pipeline": pipeline_norm,
            "cache": cache_norm,
            "export": export_norm,
        }
        _MTIME = mtime
        return {
            "pipeline": dict(pipeline_norm),
            "cache": dict(cache_norm),
            "export": dict(export_norm),
        }


def load_pipeline_settings(*, force: bool = False) -> dict[str, Any]:
    """Return normalized pipeline settings (cached until the file changes)."""
    return _load_all(force=force)["pipeline"]


def load_cache_settings(*, force: bool = False) -> dict[str, Any]:
    """Return normalized global cache settings."""
    return _load_all(force=force)["cache"]


def load_export_settings(*, force: bool = False) -> dict[str, Any]:
    """Return normalized global export settings (hardcoded host + batching)."""
    return _load_all(force=force)["export"]


def save_pipeline_settings(updates: dict[str, Any]) -> dict[str, Any]:
    """Merge pipeline updates into pipeline_settings.yaml and return pipeline values."""
    all_data = _load_all(force=True)
    merged = _normalize_pipeline({**all_data["pipeline"], **(updates or {})})
    _write_all(merged, all_data["cache"], all_data["export"])
    return load_pipeline_settings(force=True)


def save_cache_settings(updates: dict[str, Any]) -> dict[str, Any]:
    """Merge cache updates into pipeline_settings.yaml and return cache values."""
    all_data = _load_all(force=True)
    merged = _normalize_cache({**all_data["cache"], **(updates or {})})
    _write_all(all_data["pipeline"], merged, all_data["export"])
    return load_cache_settings(force=True)


def save_export_settings(updates: dict[str, Any]) -> dict[str, Any]:
    """Merge export updates into pipeline_settings.yaml and return export values.

    ``host`` in updates is ignored (platform host is hardcoded).
    """
    all_data = _load_all(force=True)
    incoming = dict(updates or {})
    incoming.pop("host", None)
    merged = _normalize_export({**all_data["export"], **incoming})
    _write_all(all_data["pipeline"], all_data["cache"], merged)
    return load_export_settings(force=True)


def pipeline_settings_payload() -> dict[str, Any]:
    """Schema + current values for the Settings → Pipeline tab."""
    all_data = _load_all()
    try:
        rel = str(_SETTINGS_FILE.relative_to(_ROOT))
    except ValueError:
        rel = str(_SETTINGS_FILE)
    return {
        "path": rel,
        "values": all_data["pipeline"],
        "defaults": dict(PIPELINE_DEFAULTS),
        "bounds": {
            key: {"min": lo, "max": hi} for key, (lo, hi) in _PIPELINE_INT_BOUNDS.items()
        },
        "export": all_data["export"],
        "export_defaults": {**dict(EXPORT_DEFAULTS), "host": GENBOUNTY_EXPORT_HOST},
        "export_bounds": {
            key: {"min": lo, "max": hi} for key, (lo, hi) in _EXPORT_INT_BOUNDS.items()
        },
    }


def cache_settings() -> dict[str, Any]:
    return load_cache_settings()


def export_host() -> str:
    """Return the hardcoded Genbounty platform host."""
    return GENBOUNTY_EXPORT_HOST


def export_batch_size_setting() -> int:
    return int(load_export_settings().get("batch_size", EXPORT_DEFAULTS["batch_size"]))


def export_delay_seconds_setting() -> float:
    return float(load_export_settings().get("delay_seconds", EXPORT_DEFAULTS["delay_seconds"]))


def export_max_retries_setting() -> int:
    return int(load_export_settings().get("max_retries", EXPORT_DEFAULTS["max_retries"]))


def export_retry_base_seconds_setting() -> float:
    return float(
        load_export_settings().get("retry_base_seconds", EXPORT_DEFAULTS["retry_base_seconds"])
    )


def security_assess_concurrency(default: int = 4) -> int:
    values = load_pipeline_settings()
    return int(values.get("security_assess_concurrency", default))


def open_loop_prompts(default: int = 4) -> int:
    values = load_pipeline_settings()
    return int(values.get("open_loop_prompts", default))


def closed_loop_prompts(default: int = 4) -> int:
    values = load_pipeline_settings()
    return int(values.get("closed_loop_prompts", default))


def payloads_output_dir() -> Path:
    """Resolved payloads output directory (created if missing)."""
    values = load_pipeline_settings()
    raw = str(values.get("payloads_output_dir") or PIPELINE_DEFAULTS["payloads_output_dir"]).strip()
    if raw:
        p = Path(raw)
        if not p.is_absolute():
            p = _ROOT / p
    else:
        if _is_docker():
            p = Path("/tmp/payloads/generate")
        else:
            p = _ROOT / "payloads" / "generate"
    p.mkdir(parents=True, exist_ok=True)
    return p.resolve()
