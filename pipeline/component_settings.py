"""Component-level settings overrides (config.yaml ``settings:`` + global defaults)."""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _ROOT / ".env"
_CONFIG_PY = _ROOT / "browser-bot" / "browser_bot" / "config.py"
_DEFAULTS_YAML = _ROOT / "config.defaults.yaml"
_FACTORY_YAML = _ROOT / "config.factory.yaml"
_SITES_DIR = _ROOT / "browser-bot" / "sites"

EDITABLE_BROWSER_VARS = frozenset({
    "FETCH_METHOD", "POOL_SIZE", "CONTEXT_COUNT", "PAGES_PER_CONTEXT",
    "POOL_CLUSTER_HUMAN_LIKE", "POOL_CLUSTER_ALLOW_STYLES", "POOL_CLUSTER_USE_STEALTH",
    "POOL_CLUSTER_USE_HUMAN_CHROME", "POOL_CLUSTER_USE_HUMAN_CONTEXT",
    "API_CONCURRENCY",
    "EVASION_REQUEST_DELAY_S", "EVASION_RETRY_WAIT_S", "EVASION_MAX_RETRIES",
    "RUN_SCREENSHOT_INTERVAL_S",
    "HUMAN_COUNTRY", "HUMAN_ALLOW_STYLES", "HUMAN_READ_DELAY_MS",
    "HUMAN_SCROLL_AFTER_LOAD", "HUMAN_ROTATE_REQUEST_ATTRIBUTES", "HUMAN_USER_AGENT",
    "HEADLESS", "BLOCKED_TYPES", "CHROMIUM_EXECUTABLE_PATH", "CHROME_CHANNEL",
    "USE_CDP_BROWSER",
})

CACHE_SETTING_KEYS = frozenset({
    "gemini_use_cache",
    "openai_use_cache",
    "openai_cache_retention",
    "grok_use_cache",
    "anthropic_use_cache",
    "anthropic_cache_ttl",
})

ALL_SETTING_KEYS = EDITABLE_BROWSER_VARS | CACHE_SETTING_KEYS

# Per-provider prompt-cache toggles (globals live in pipeline_settings.yaml).
_CACHE_BOOL_KEYS: frozenset[str] = frozenset({
    "gemini_use_cache",
    "openai_use_cache",
    "grok_use_cache",
    "anthropic_use_cache",
})
_CACHE_BOOL_DEFAULTS: dict[str, bool] = {
    # Gemini uses explicit server-side caches (opt-in, off by default). The
    # others are automatic / low-cost prompt caching, so default them on.
    "gemini_use_cache": False,
    "openai_use_cache": True,
    "grok_use_cache": True,
    "anthropic_use_cache": True,
}
# Provider-specific choice settings.
_CACHE_CHOICE_KEYS: frozenset[str] = frozenset({
    "openai_cache_retention",
    "anthropic_cache_ttl",
})
_CACHE_CHOICE_DEFAULTS: dict[str, str] = {
    "openai_cache_retention": "standard",
    "anthropic_cache_ttl": "5m",
}
# Legacy aliases kept for any external imports.
_CACHE_BOOL_ENV: dict[str, str] = {
    "gemini_use_cache": "GEMINI_USE_CACHE",
    "openai_use_cache": "OPENAI_USE_CACHE",
    "grok_use_cache": "GROK_USE_CACHE",
    "anthropic_use_cache": "ANTHROPIC_USE_CACHE",
}
_CACHE_CHOICE_ENV: dict[str, str] = {
    "openai_cache_retention": "OPENAI_CACHE_RETENTION",
    "anthropic_cache_ttl": "ANTHROPIC_CACHE_TTL",
}

# Written into new sites/<site>/config.yaml and sites/<site>/<component>/config.yaml.
INITIAL_CONFIG_SETTINGS: dict[str, Any] = {
    "FETCH_METHOD": "human",
    "POOL_SIZE": 1,
    "CONTEXT_COUNT": 1,
    "PAGES_PER_CONTEXT": 1,
    "POOL_CLUSTER_HUMAN_LIKE": True,
    "POOL_CLUSTER_ALLOW_STYLES": True,
    "POOL_CLUSTER_USE_STEALTH": True,
    "POOL_CLUSTER_USE_HUMAN_CHROME": True,
    "POOL_CLUSTER_USE_HUMAN_CONTEXT": True,
    "HEADLESS": False,
    "HUMAN_ALLOW_STYLES": True,
    "HUMAN_SCROLL_AFTER_LOAD": True,
    "HUMAN_ROTATE_REQUEST_ATTRIBUTES": True,
    "API_CONCURRENCY": 2,
    "BLOCKED_TYPES": ["font", "media"],
    "EVASION_REQUEST_DELAY_S": 0.5,
    "intel_credentials_and_paths": True,
}


def initial_config_settings() -> dict[str, Any]:
    """Default ``settings:`` block for newly created site/component config.yaml files."""
    return dict(INITIAL_CONFIG_SETTINGS)


SETTING_GROUPS: list[dict[str, Any]] = [
    {
        "id": "cache",
        "title": "Cache Control",
        "keys": [
            "gemini_use_cache",
            "openai_use_cache",
            "openai_cache_retention",
            "grok_use_cache",
            "anthropic_use_cache",
            "anthropic_cache_ttl",
        ],
    },
    {
        "id": "fetcher",
        "title": "Fetcher",
        "keys": ["FETCH_METHOD", "POOL_SIZE", "CONTEXT_COUNT", "PAGES_PER_CONTEXT"],
    },
    {
        "id": "pool_cluster",
        "title": "Pool / Cluster Browser Enhancements",
        "keys": [
            "POOL_CLUSTER_HUMAN_LIKE", "POOL_CLUSTER_ALLOW_STYLES", "POOL_CLUSTER_USE_STEALTH",
            "POOL_CLUSTER_USE_HUMAN_CHROME", "POOL_CLUSTER_USE_HUMAN_CONTEXT",
        ],
    },
    {
        "id": "evasion",
        "title": "API / Evasion",
        "keys": ["API_CONCURRENCY", "EVASION_REQUEST_DELAY_S", "EVASION_RETRY_WAIT_S", "EVASION_MAX_RETRIES"],
    },
    {
        "id": "human",
        "title": "Human Tier",
        "keys": [
            "HUMAN_COUNTRY", "HUMAN_READ_DELAY_MS", "HUMAN_ALLOW_STYLES",
            "HUMAN_SCROLL_AFTER_LOAD", "HUMAN_ROTATE_REQUEST_ATTRIBUTES", "HUMAN_USER_AGENT",
        ],
    },
    {
        "id": "browser",
        "title": "Browser",
        "keys": ["HEADLESS", "USE_CDP_BROWSER", "CHROME_CHANNEL", "CHROMIUM_EXECUTABLE_PATH", "BLOCKED_TYPES"],
    },
    {
        "id": "run_preview",
        "title": "Run Preview",
        "keys": ["RUN_SCREENSHOT_INTERVAL_S"],
    },
]

SETTING_META: dict[str, dict[str, Any]] = {
    "gemini_use_cache": {"type": "bool", "label": "Gemini context cache"},
    "openai_use_cache": {"type": "bool", "label": "OpenAI prompt caching"},
    "openai_cache_retention": {
        "type": "select", "label": "OpenAI cache retention",
        "options": ["standard", "24h"],
    },
    "grok_use_cache": {"type": "bool", "label": "Grok (xAI) prompt caching"},
    "anthropic_use_cache": {"type": "bool", "label": "Anthropic prompt caching"},
    "anthropic_cache_ttl": {
        "type": "select", "label": "Anthropic cache TTL",
        "options": ["5m", "1h"],
    },
    "FETCH_METHOD": {"type": "select", "label": "Fetch method", "options": ["auto", "pool", "cluster", "human"]},
    "POOL_SIZE": {"type": "int", "label": "Pool size", "min": 1, "max": 32},
    "CONTEXT_COUNT": {"type": "int", "label": "Cluster contexts", "min": 1, "max": 32},
    "PAGES_PER_CONTEXT": {"type": "int", "label": "Pages / context", "min": 1, "max": 16},
    "POOL_CLUSTER_HUMAN_LIKE": {"type": "bool", "label": "Human-like (enable all below)"},
    "POOL_CLUSTER_ALLOW_STYLES": {"type": "bool", "label": "Allow stylesheets"},
    "POOL_CLUSTER_USE_STEALTH": {"type": "bool", "label": "Playwright-stealth"},
    "POOL_CLUSTER_USE_HUMAN_CHROME": {"type": "bool", "label": "Human Chrome args"},
    "POOL_CLUSTER_USE_HUMAN_CONTEXT": {"type": "bool", "label": "Human context (locale / viewport / geo)"},
    "API_CONCURRENCY": {"type": "int", "label": "API concurrency", "min": 1, "max": 32},
    "EVASION_REQUEST_DELAY_S": {"type": "float", "label": "Request delay (s)", "min": 0, "step": 0.1},
    "EVASION_RETRY_WAIT_S": {"type": "float", "label": "Retry wait (s)", "min": 0, "step": 1},
    "EVASION_MAX_RETRIES": {"type": "int", "label": "Max retries", "min": 0, "max": 10},
    "RUN_SCREENSHOT_INTERVAL_S": {
        "type": "float",
        "label": "Screenshot interval (s)",
        "min": 0,
        "max": 120,
        "step": 1,
    },
    "HUMAN_COUNTRY": {
        "type": "select", "label": "Country",
        "options": ["US", "UK", "DE", "FR", "JP", "CA", "AU", "NL", "ES", "IT"],
    },
    "HUMAN_READ_DELAY_MS": {"type": "int", "label": "Read delay (ms)", "min": 0, "step": 100},
    "HUMAN_ALLOW_STYLES": {"type": "bool", "label": "Allow stylesheets"},
    "HUMAN_SCROLL_AFTER_LOAD": {"type": "bool", "label": "Scroll after load"},
    "HUMAN_ROTATE_REQUEST_ATTRIBUTES": {"type": "bool", "label": "Rotate request attributes"},
    "HUMAN_USER_AGENT": {"type": "string", "label": "User agent"},
    "HEADLESS": {"type": "bool", "label": "Headless"},
    "USE_CDP_BROWSER": {
        "type": "bool",
        "label": "Use Chrome CDP for all browser launches",
    },
    "CHROME_CHANNEL": {
        "type": "select", "label": "Chrome channel",
        "options": ["chromium", "chrome", "chrome-beta", "msedge"],
    },
    "CHROMIUM_EXECUTABLE_PATH": {"type": "string", "label": "Chromium path"},
    "BLOCKED_TYPES": {
        "type": "set", "label": "Block types",
        "options": ["image", "font", "media", "stylesheet"],
    },
}

_FALSE = frozenset({"0", "false", "no", "off"})
_TRUE = frozenset({"1", "true", "yes", "on"})

SETTINGS_PRECEDENCE: list[dict[str, str]] = [
    {
        "id": "component",
        "label": "Component",
        "path": "browser-bot/sites/<site>/<component>/config.yaml → settings",
        "description": "Highest priority. Per-component overrides for the selected target.",
    },
    {
        "id": "site",
        "label": "Site",
        "path": "browser-bot/sites/<site>/config.yaml → settings",
        "description": "Shared by all components on a site unless a component overrides.",
    },
    {
        "id": "browser",
        "label": "Browser Config",
        "path": "browser-bot/browser_bot/config.py (+ .env for cache)",
        "description": "Global runtime defaults edited in Settings → Browser Config.",
    },
    {
        "id": "defaults",
        "label": "Shipped Defaults",
        "path": "config.defaults.yaml → settings",
        "description": "Lowest priority baseline shipped with the app (fresh-install defaults).",
    },
]


def _env_value(key: str, default: str = "") -> str:
    if _ENV_FILE.is_file():
        try:
            for raw in _ENV_FILE.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == key:
                    return v.strip().strip('"').strip("'")
        except OSError:
            pass
    return os.getenv(key, default)


def _parse_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in _FALSE:
        return False
    if s in _TRUE:
        return True
    return default


def _normalize_settings_dict(raw: dict[str, Any] | None) -> dict[str, Any]:
    if not raw:
        return {}
    return {k: v for k, v in raw.items() if k in ALL_SETTING_KEYS}


def _merge_settings_layers(*layers: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for layer in layers:
        out.update(_normalize_settings_dict(layer))
    return out


def load_defaults_yaml() -> dict[str, Any]:
    """Shipped app-wide defaults from config.defaults.yaml (settings block)."""
    if not _DEFAULTS_YAML.is_file():
        return {}
    try:
        import yaml

        data = yaml.safe_load(_DEFAULTS_YAML.read_text(encoding="utf-8")) or {}
        settings = data.get("settings")
        return _normalize_settings_dict(settings if isinstance(settings, dict) else {})
    except Exception:
        return {}


def _ensure_browser_bot_path() -> None:
    bb_dir = _ROOT / "browser-bot"
    if str(bb_dir) not in sys.path:
        sys.path.insert(0, str(bb_dir))


def _load_site_settings(site: str | None) -> dict[str, Any]:
    if not site:
        return {}
    try:
        _ensure_browser_bot_path()
        from browser_bot.sites import load_site_config

        cfg = load_site_config(site)
        return _normalize_settings_dict(cfg.get("settings") if isinstance(cfg.get("settings"), dict) else {})
    except Exception:
        return {}


def _load_component_settings_raw(site: str | None, component: str | None) -> dict[str, Any]:
    if not site or not component:
        return {}
    try:
        _ensure_browser_bot_path()
        from browser_bot.sites import load_component_config_raw

        cfg = load_component_config_raw(site, component)
        return _normalize_settings_dict(cfg.get("settings") if isinstance(cfg.get("settings"), dict) else {})
    except Exception:
        return {}


def parse_browser_config_py() -> dict[str, Any]:
    """Read editable browser settings from config.py (file, not live module)."""
    if not _CONFIG_PY.is_file():
        return {}
    source = _CONFIG_PY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    result: dict[str, Any] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in EDITABLE_BROWSER_VARS:
                    try:
                        val = ast.literal_eval(node.value)
                        if isinstance(val, (set, frozenset)):
                            val = sorted(val)
                        result[target.id] = val
                    except Exception:
                        pass
        elif isinstance(node, ast.AnnAssign):
            if (
                isinstance(node.target, ast.Name)
                and node.target.id in EDITABLE_BROWSER_VARS
                and node.value is not None
            ):
                try:
                    val = ast.literal_eval(node.value)
                    if isinstance(val, (set, frozenset)):
                        val = sorted(val)
                    result[node.target.id] = val
                except Exception:
                    pass
    return result


def get_site_settings_overrides(
    site: str | None = None,
    component: str | None = None,
) -> dict[str, Any]:
    site = (site or os.getenv("GENBOUNTY_SITE") or "").strip() or None
    return _load_site_settings(site)


def get_component_settings_overrides(
    site: str | None = None,
    component: str | None = None,
) -> dict[str, Any]:
    site = (site or os.getenv("GENBOUNTY_SITE") or "").strip() or None
    component = (component or os.getenv("GENBOUNTY_COMPONENT") or "").strip() or None
    return _load_component_settings_raw(site, component)


def get_target_settings_overrides(
    site: str | None = None,
    component: str | None = None,
) -> dict[str, Any]:
    """Merged site + component overrides from config.yaml."""
    site = (site or os.getenv("GENBOUNTY_SITE") or "").strip() or None
    component = (component or os.getenv("GENBOUNTY_COMPONENT") or "").strip() or None
    return _merge_settings_layers(
        _load_site_settings(site),
        _load_component_settings_raw(site, component),
    )


def get_component_overrides(
    site: str | None = None,
    component: str | None = None,
) -> dict[str, Any]:
    """Target overrides (site + component config.yaml settings)."""
    return get_target_settings_overrides(site=site, component=component)


def _global_cache_bool(key: str, *, default: bool | None = None) -> bool:
    """Global (pipeline_settings.yaml → defaults.yaml → built-in) cache toggle."""
    try:
        from pipeline.pipeline_settings import load_cache_settings

        cache = load_cache_settings()
        if key in cache:
            return _parse_bool(cache[key], _CACHE_BOOL_DEFAULTS[key])
    except Exception:
        pass
    if default is not None:
        return default
    defs = load_defaults_yaml()
    if key in defs:
        return _parse_bool(defs[key], _CACHE_BOOL_DEFAULTS[key])
    return _CACHE_BOOL_DEFAULTS[key]


def _global_cache_choice(key: str) -> str:
    """Global (pipeline_settings.yaml → defaults.yaml → built-in) cache choice."""
    try:
        from pipeline.pipeline_settings import load_cache_settings

        cache = load_cache_settings()
        raw = str(cache.get(key) or "").strip()
        if raw:
            return raw
    except Exception:
        pass
    defs = load_defaults_yaml()
    if key in defs and str(defs[key]).strip():
        return str(defs[key]).strip()
    return _CACHE_CHOICE_DEFAULTS[key]


def _global_cache_layer() -> dict[str, Any]:
    """All cache settings resolved at the global layer."""
    layer: dict[str, Any] = {k: _global_cache_bool(k) for k in _CACHE_BOOL_KEYS}
    layer.update({k: _global_cache_choice(k) for k in _CACHE_CHOICE_KEYS})
    return layer


def global_gemini_cache_enabled(*, default: bool | None = None) -> bool:
    return _global_cache_bool("gemini_use_cache", default=default)


def get_global_settings() -> dict[str, Any]:
    """Global layer: shipped defaults + config.py + cache YAML (later wins)."""
    out = _merge_settings_layers(load_defaults_yaml(), parse_browser_config_py())
    out.update(_global_cache_layer())
    return out


def get_global_setting(key: str) -> Any:
    globals_ = get_global_settings()
    if key in globals_:
        return globals_[key]
    return None


def _coerce_setting(key: str, value: Any) -> Any:
    if key in _CACHE_BOOL_KEYS:
        return _parse_bool(value, _CACHE_BOOL_DEFAULTS[key])
    if key in _CACHE_CHOICE_KEYS:
        text = str(value).strip() if value is not None else ""
        return text or _CACHE_CHOICE_DEFAULTS[key]
    if key == "BLOCKED_TYPES":
        if value is None:
            return set()
        if isinstance(value, str):
            items = [v.strip() for v in value.split(",") if v.strip()]
            return set(items)
        if isinstance(value, (list, tuple, set, frozenset)):
            return set(value)
        return set()
    if key in {"POOL_SIZE", "CONTEXT_COUNT", "PAGES_PER_CONTEXT", "API_CONCURRENCY", "EVASION_MAX_RETRIES", "HUMAN_READ_DELAY_MS"}:
        return int(value)
    if key in {"EVASION_REQUEST_DELAY_S", "EVASION_RETRY_WAIT_S", "RUN_SCREENSHOT_INTERVAL_S"}:
        return float(value)
    if key in {
        "POOL_CLUSTER_HUMAN_LIKE", "POOL_CLUSTER_ALLOW_STYLES", "POOL_CLUSTER_USE_STEALTH",
        "POOL_CLUSTER_USE_HUMAN_CHROME", "POOL_CLUSTER_USE_HUMAN_CONTEXT",
        "HUMAN_ALLOW_STYLES", "HUMAN_SCROLL_AFTER_LOAD",
        "HUMAN_ROTATE_REQUEST_ATTRIBUTES", "HEADLESS",
    }:
        return _parse_bool(value, False)
    if isinstance(value, str):
        return value
    return value


def get_effective_setting(
    key: str,
    *,
    site: str | None = None,
    component: str | None = None,
) -> Any:
    return get_effective_settings(site=site, component=component).get(key)


def get_effective_settings(
    *,
    site: str | None = None,
    component: str | None = None,
) -> dict[str, Any]:
    site_id = (site or os.getenv("GENBOUNTY_SITE") or "").strip() or None
    component_id = (component or os.getenv("GENBOUNTY_COMPONENT") or "").strip() or None
    merged = _merge_settings_layers(
        load_defaults_yaml(),
        parse_browser_config_py(),
        _global_cache_layer(),
        _load_site_settings(site_id),
        _load_component_settings_raw(site_id, component_id),
    )
    return {k: _coerce_setting(k, v) for k, v in merged.items()}


def effective_headless(
    site: str | None = None,
    component: str | None = None,
    *,
    default: bool = True,
) -> bool:
    """Resolved HEADLESS for a site/component (True = no visible browser window)."""
    val = get_effective_settings(site=site, component=component).get("HEADLESS", default)
    return _parse_bool(val, default)


def ui_browser_headless_override(
    site: str | None = None,
    component: str | None = None,
) -> bool | None:
    """Playwright headless= kwarg: False when settings disable headless, else None."""
    if not effective_headless(site, component):
        return False
    return None


def playwright_headless_kwarg(
    site: str | None = None,
    component: str | None = None,
    *,
    explicit: bool | None = None,
    interactive: bool = False,
) -> bool | None:
    """Resolved Playwright launch headless= (False opens a visible browser window)."""
    if explicit is not None:
        return explicit
    if interactive:
        return False
    return ui_browser_headless_override(site=site, component=component)


def _serialize_blocked_types(val: Any) -> Any:
    if isinstance(val, set):
        return sorted(val)
    return val


def get_effective_settings_detail(
    *,
    site: str | None = None,
    component: str | None = None,
) -> dict[str, dict[str, Any]]:
    site_id = (site or os.getenv("GENBOUNTY_SITE") or "").strip() or None
    component_id = (component or os.getenv("GENBOUNTY_COMPONENT") or "").strip() or None
    defaults = load_defaults_yaml()
    globals_ = get_global_settings()
    site_ov = _load_site_settings(site_id)
    comp_ov = _load_component_settings_raw(site_id, component_id)
    detail: dict[str, dict[str, Any]] = {}
    global_cache = _global_cache_layer()
    for key in ALL_SETTING_KEYS:
        inherited_at_component = key not in comp_ov
        layers = [defaults, parse_browser_config_py()]
        if key in global_cache:
            layers.append({key: global_cache[key]})
        else:
            layers.append({})
        layers.extend([site_ov, comp_ov])
        merged = _merge_settings_layers(*layers)
        effective_raw = merged.get(key, globals_.get(key))
        effective = _coerce_setting(key, effective_raw) if effective_raw is not None else None
        detail[key] = {
            "defaults": _serialize_blocked_types(defaults.get(key)),
            "global": _serialize_blocked_types(globals_.get(key)),
            "site_override": site_ov.get(key),
            "override": comp_ov.get(key),
            "effective": _serialize_blocked_types(effective),
            "inherited": inherited_at_component,
        }
    return detail


def component_gemini_cache_override(
    site: str | None = None,
    component: str | None = None,
) -> bool | None:
    site_id = (site or os.getenv("GENBOUNTY_SITE") or "").strip() or None
    component_id = (component or os.getenv("GENBOUNTY_COMPONENT") or "").strip() or None
    merged = _merge_settings_layers(
        _load_site_settings(site_id),
        _load_component_settings_raw(site_id, component_id),
    )
    if "gemini_use_cache" not in merged:
        return None
    return _parse_bool(merged["gemini_use_cache"], global_gemini_cache_enabled())


def gemini_cache_enabled(
    *,
    site: str | None = None,
    component: str | None = None,
    default: bool = False,
) -> bool:
    override = component_gemini_cache_override(site=site, component=component)
    if override is not None:
        return override
    return global_gemini_cache_enabled(default=default)


def provider_cache_settings(
    provider: str,
    *,
    site: str | None = None,
    component: str | None = None,
) -> dict[str, Any]:
    """Effective prompt-cache settings for a provider (adapter-facing).

    Resolves through the full override pipeline (defaults → .env → site →
    component), reading GENBOUNTY_SITE / GENBOUNTY_COMPONENT when not given.
    Returns ``{"enabled": bool, ...}`` with provider-specific extras
    (``retention`` for OpenAI, ``ttl`` for Anthropic).
    """
    eff = get_effective_settings(site=site, component=component)
    p = (provider or "").strip().lower()
    if p == "openai":
        return {
            "enabled": _parse_bool(eff.get("openai_use_cache"), _CACHE_BOOL_DEFAULTS["openai_use_cache"]),
            "retention": str(eff.get("openai_cache_retention") or _CACHE_CHOICE_DEFAULTS["openai_cache_retention"]),
        }
    if p == "grok":
        return {
            "enabled": _parse_bool(eff.get("grok_use_cache"), _CACHE_BOOL_DEFAULTS["grok_use_cache"]),
        }
    if p == "anthropic":
        return {
            "enabled": _parse_bool(eff.get("anthropic_use_cache"), _CACHE_BOOL_DEFAULTS["anthropic_use_cache"]),
            "ttl": str(eff.get("anthropic_cache_ttl") or _CACHE_CHOICE_DEFAULTS["anthropic_cache_ttl"]),
        }
    if p == "gemini":
        return {"enabled": gemini_cache_enabled(site=site, component=component)}
    return {"enabled": False}


def _submission_cloudflare_headed(site: str | None, component: str | None) -> bool:
    """True when component config has submission.cloudflare_headed."""
    if not site or not component:
        return False
    try:
        bb_dir = _ROOT / "browser-bot"
        if str(bb_dir) not in sys.path:
            sys.path.insert(0, str(bb_dir))
        from browser_bot.sites import load_component_config

        sub = (load_component_config(site, component) or {}).get("submission") or {}
        return bool(isinstance(sub, dict) and sub.get("cloudflare_headed"))
    except Exception:
        return False


def _force_cloudflare_pool_stealth(
    browser_settings: dict[str, Any],
    *,
    site: str | None,
    component: str | None,
    effective: dict[str, Any],
) -> None:
    """Force pool/cluster stealth for Cloudflare-headed or human-fetch targets."""
    fetch_method = str(
        browser_settings.get("FETCH_METHOD")
        or effective.get("FETCH_METHOD")
        or ""
    ).strip().lower()
    if _submission_cloudflare_headed(site, component) or fetch_method == "human":
        browser_settings["POOL_CLUSTER_USE_STEALTH"] = True
        browser_settings["POOL_CLUSTER_USE_HUMAN_CONTEXT"] = True


def apply_browser_settings(
    site: str | None = None,
    component: str | None = None,
    *,
    target_module: Any | None = None,
) -> dict[str, Any]:
    """Apply merged effective browser settings (defaults → config.py → site → component)."""
    effective = get_effective_settings(site=site, component=component)
    browser_settings = {
        k: _coerce_setting(k, effective[k])
        for k in EDITABLE_BROWSER_VARS
        if k in effective
    }
    _force_cloudflare_pool_stealth(
        browser_settings, site=site, component=component, effective=effective
    )
    if not browser_settings:
        return {}

    if target_module is None:
        bb_dir = _ROOT / "browser-bot"
        if str(bb_dir) not in sys.path:
            sys.path.insert(0, str(bb_dir))
        import browser_bot.config as target_module  # type: ignore[import]

    for key, value in browser_settings.items():
        setattr(target_module, key, value)
    return browser_settings


def save_defaults_yaml_settings(changes: dict[str, Any]) -> list[str]:
    """Update the ``settings:`` block in config.defaults.yaml. Preserves the file header comments."""
    if not _DEFAULTS_YAML.is_file():
        raise FileNotFoundError(f"Shipped defaults not found: {_DEFAULTS_YAML}")
    import yaml

    text = _DEFAULTS_YAML.read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    settings = dict(data.get("settings") or {})
    updated: list[str] = []
    for key, raw in changes.items():
        if key not in ALL_SETTING_KEYS:
            continue
        settings[key] = _serialize_blocked_types(_coerce_setting(key, raw))
        updated.append(key)
    if not updated:
        return []

    marker = "\nsettings:"
    idx = text.find(marker)
    if idx < 0 and text.startswith("settings:"):
        idx = 0
        marker = "settings:"
    header = text[: idx + 1] if idx >= 0 else ""
    body = yaml.dump(
        {"settings": settings},
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    _DEFAULTS_YAML.write_text(header + body, encoding="utf-8")
    return updated


def load_factory_settings() -> dict[str, Any]:
    """Factory baseline from config.factory.yaml (used by reset-to-factory)."""
    if not _FACTORY_YAML.is_file():
        raise FileNotFoundError(f"Factory settings not found: {_FACTORY_YAML}")
    import yaml

    data = yaml.safe_load(_FACTORY_YAML.read_text(encoding="utf-8")) or {}
    settings = data.get("settings")
    if not isinstance(settings, dict):
        raise ValueError("config.factory.yaml must contain a settings: mapping")
    return {
        k: _coerce_setting(k, v)
        for k, v in settings.items()
        if k in ALL_SETTING_KEYS
    }


def restore_defaults_yaml_from_factory() -> list[str]:
    """Replace config.defaults.yaml settings block with the full factory snapshot."""
    factory = load_factory_settings()
    serialized = {
        k: _serialize_blocked_types(v)
        for k, v in factory.items()
    }
    if not _DEFAULTS_YAML.is_file():
        raise FileNotFoundError(f"Shipped defaults not found: {_DEFAULTS_YAML}")
    import yaml

    text = _DEFAULTS_YAML.read_text(encoding="utf-8")
    marker = "\nsettings:"
    idx = text.find(marker)
    if idx < 0 and text.startswith("settings:"):
        idx = 0
    header = text[: idx + 1] if idx >= 0 else ""
    body = yaml.dump(
        {"settings": serialized},
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    _DEFAULTS_YAML.write_text(header + body, encoding="utf-8")
    return sorted(serialized.keys())


def _write_config_py_value(source: str, name: str, value: Any) -> str:
    import re

    if name == "BLOCKED_TYPES":
        if isinstance(value, set):
            items = sorted(value)
        elif isinstance(value, list):
            items = sorted(value)
        else:
            items = []
        new_repr = ("{" + ", ".join(repr(v) for v in items) + "}") if items else "set()"
    elif isinstance(value, bool):
        new_repr = "True" if value else "False"
    elif value is None:
        new_repr = "None"
    elif isinstance(value, str):
        new_repr = repr(value)
    elif isinstance(value, (int, float)):
        new_repr = repr(value)
    elif isinstance(value, list):
        new_repr = repr(value)
    else:
        new_repr = repr(value)

    # Match both ``NAME = …`` and annotated ``NAME: int = …`` assignments.
    pattern = re.compile(
        r"^(" + re.escape(name) + r"(?:\s*:\s*[^=]+)?\s*=\s*)(.*)$",
        re.MULTILINE,
    )
    new_source, n = pattern.subn(lambda m: m.group(1) + new_repr, source, count=1)
    if n != 1:
        raise ValueError(f"Could not find assignment for {name} in config.py")
    return new_source


def restore_browser_config_from_factory() -> list[str]:
    """Reset browser-bot/browser_bot/config.py editable vars to factory values."""
    factory = load_factory_settings()
    source = _CONFIG_PY.read_text(encoding="utf-8")
    updated: list[str] = []
    for key in EDITABLE_BROWSER_VARS:
        if key not in factory:
            continue
        coerced = factory[key]
        if key == "BLOCKED_TYPES" and isinstance(coerced, list):
            coerced = set(coerced)
        source = _write_config_py_value(source, key, coerced)
        updated.append(key)
    _CONFIG_PY.write_text(source, encoding="utf-8")
    return updated


def clear_all_site_component_settings_overrides() -> dict[str, list[str]]:
    """Remove settings: blocks from every site and component config.yaml."""
    if not _SITES_DIR.is_dir():
        return {"sites": [], "components": []}

    import yaml

    _ensure_browser_bot_path()
    from browser_bot.component_config_yaml import write_component_config_documented
    from browser_bot.site_config_yaml import write_site_config_documented

    sites_cleared: list[str] = []
    components_cleared: list[str] = []

    for path in sorted(_SITES_DIR.glob("*/config.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict) or "settings" not in data:
            continue
        del data["settings"]
        write_site_config_documented(path, data)
        sites_cleared.append(path.parent.name)

    for path in sorted(_SITES_DIR.glob("*/*/config.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict) or "settings" not in data:
            continue
        del data["settings"]
        write_component_config_documented(path, data)
        components_cleared.append(f"{path.parent.parent.name}/{path.parent.name}")

    return {"sites": sites_cleared, "components": components_cleared}


def reset_all_settings_to_factory() -> dict[str, Any]:
    """Restore factory profile: defaults.yaml, config.py, clear YAML overrides."""
    defaults_keys = restore_defaults_yaml_from_factory()
    browser_keys = restore_browser_config_from_factory()
    cleared = clear_all_site_component_settings_overrides()
    factory = load_factory_settings()
    # Cache globals for callers to persist into pipeline_settings.yaml.
    cache_settings: dict[str, Any] = {}
    for key in _CACHE_BOOL_KEYS:
        cache_settings[key] = bool(factory.get(key, _CACHE_BOOL_DEFAULTS[key]))
    for key in _CACHE_CHOICE_KEYS:
        cache_settings[key] = str(factory.get(key, _CACHE_CHOICE_DEFAULTS[key]))
    try:
        from pipeline.pipeline_settings import save_cache_settings

        save_cache_settings(cache_settings)
    except Exception:
        pass
    return {
        "defaults_keys": defaults_keys,
        "browser_keys": browser_keys,
        "sites_cleared": cleared["sites"],
        "components_cleared": cleared["components"],
        "gemini_use_cache": bool(factory.get("gemini_use_cache")),
        "cache_settings": cache_settings,
        "factory_path": str(_FACTORY_YAML.relative_to(_ROOT)),
    }


def settings_schema_payload() -> dict[str, Any]:
    defaults = load_defaults_yaml()
    globals_ = get_global_settings()
    for key, val in list(globals_.items()):
        if key == "BLOCKED_TYPES" and isinstance(val, set):
            globals_[key] = sorted(val)
    for key, val in list(defaults.items()):
        if key == "BLOCKED_TYPES" and isinstance(val, set):
            defaults[key] = sorted(val)
    return {
        "groups": SETTING_GROUPS,
        "meta": SETTING_META,
        "keys": sorted(ALL_SETTING_KEYS),
        "defaults": defaults,
        "defaults_path": str(_DEFAULTS_YAML.relative_to(_ROOT)),
        "factory_path": str(_FACTORY_YAML.relative_to(_ROOT)),
        "globals": globals_,
        "precedence": SETTINGS_PRECEDENCE,
    }
