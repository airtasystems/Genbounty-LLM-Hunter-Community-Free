"""
Auth state: full capture and load (cookies, localStorage, sessionStorage, headers).

Primary store: ``sites/{site}/{component}/auth.json``
Fallback (legacy): ``sites/{site}/auth.json``

Target API-key secrets are stored in the project ``.env`` as
``TARGET_API_KEY_<SITE>_<COMPONENT>``. ``auth.json`` keeps only non-secret
metadata (header/query param names, bearer flag, env var name).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

AUTH_FILE = "auth.json"
STORAGE_STATE_FILE = "storage_state.json"  # Legacy
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _PROJECT_ROOT / ".env"
_TARGET_API_KEY_PREFIX = "TARGET_API_KEY_"

PUBLIC_AUTH_TEMPLATE: dict[str, Any] = {
    "cookies": [],
    "origins": [],
    "headers": {},
    "query_params": {},
    "auth_mode": "none",
}


def _site_dir(site: str) -> Path:
    from browser_bot.sites import _domain_to_site_dir

    return _domain_to_site_dir(site)


def _component_dir(site: str, component: str) -> Path:
    return _site_dir(site) / component


def get_auth_path(site: str, component: str | None = None) -> Path:
    """Directory that holds auth for a site or component."""
    if component:
        return _component_dir(site, component)
    return _site_dir(site)


def _auth_file_candidates(site: str, component: str | None) -> list[Path]:
    candidates: list[Path] = []
    if component:
        comp_dir = _component_dir(site, component)
        candidates.extend([comp_dir / AUTH_FILE, comp_dir / STORAGE_STATE_FILE])
    site_dir = _site_dir(site)
    candidates.extend([site_dir / AUTH_FILE, site_dir / STORAGE_STATE_FILE])
    return candidates


def _sanitize_env_token(raw: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", (raw or "").strip()).strip("_")
    return text.upper() or "TARGET"


def target_api_key_env_name(site: str, component: str | None = None) -> str:
    """Deterministic ``.env`` key for a site/component target API secret."""
    parts = [_sanitize_env_token(site)]
    if component:
        parts.append(_sanitize_env_token(component))
    return _TARGET_API_KEY_PREFIX + "_".join(parts)


def _read_dotenv_var(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return ""
    if _ENV_FILE.is_file():
        try:
            for raw in _ENV_FILE.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == name:
                    return v.strip().strip('"').strip("'")
        except OSError:
            pass
    return (os.environ.get(name) or "").strip()


def _write_dotenv_var(name: str, value: str | None) -> None:
    """Update or remove a ``TARGET_API_KEY_*`` (or other) key in project ``.env``."""
    name = (name or "").strip()
    if not name:
        return
    lines: list[str] = []
    if _ENV_FILE.is_file():
        try:
            lines = _ENV_FILE.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []

    replaced = False
    new_lines: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(raw)
            continue
        k = stripped.split("=", 1)[0].strip()
        if k != name:
            new_lines.append(raw)
            continue
        replaced = True
        if value is not None:
            new_lines.append(f'{name}="{value}"')
    if not replaced and value is not None:
        new_lines.append(f'{name}="{value}"')
    try:
        _ENV_FILE.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8")
    except OSError:
        return
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


def _extract_plaintext_api_key(config: dict[str, Any]) -> str:
    """Pull a legacy plaintext key out of auth.json headers/query_params."""
    headers = config.get("headers") if isinstance(config.get("headers"), dict) else {}
    for val in headers.values():
        text = str(val or "").strip()
        if not text:
            continue
        lower = text.lower()
        if lower.startswith("bearer "):
            return text[7:].strip()
        if lower.startswith("basic "):
            continue
        return text
    query = config.get("query_params") if isinstance(config.get("query_params"), dict) else {}
    for val in query.values():
        text = str(val or "").strip()
        if text:
            return text
    return ""


def _api_key_metadata(config: dict[str, Any]) -> tuple[str, str, bool]:
    """Return (header_name, query_param_name, use_bearer) from metadata or legacy fields."""
    header = str(config.get("api_key_header") or "").strip()
    qparam = str(config.get("api_key_query_param") or "").strip()
    use_bearer = config.get("api_key_use_bearer")
    headers = config.get("headers") if isinstance(config.get("headers"), dict) else {}
    query = config.get("query_params") if isinstance(config.get("query_params"), dict) else {}
    if not header and headers:
        header = str(next(iter(headers.keys()), "") or "").strip()
    if not qparam and query:
        qparam = str(next(iter(query.keys()), "") or "").strip()
    if use_bearer is None and header.lower() == "authorization":
        val = str(headers.get(header) or headers.get("Authorization") or "")
        use_bearer = bool(val) and val.lower().startswith("bearer ")
    if use_bearer is None:
        use_bearer = header.lower() == "authorization"
    return header, qparam, bool(use_bearer)


def _api_key_header_value(
    header_name: str,
    key: str,
    *,
    use_bearer: bool | None = None,
) -> str:
    header = (header_name or "Authorization").strip() or "Authorization"
    if header.lower() != "authorization":
        return key
    lower = key.lower()
    if lower.startswith("bearer ") or lower.startswith("basic "):
        return key
    if use_bearer is False:
        return key
    if use_bearer is True or use_bearer is None:
        return f"Bearer {key}"
    return key


def _scrubbed_api_key_config(
    *,
    env_name: str,
    header_name: str,
    query_param_name: str,
    use_bearer: bool,
) -> dict[str, Any]:
    return {
        "cookies": [],
        "origins": [],
        "headers": {},
        "query_params": {},
        "auth_mode": "api_key",
        "api_key_env": env_name,
        "api_key_header": header_name or "Authorization",
        "api_key_query_param": query_param_name or "",
        "api_key_use_bearer": bool(use_bearer),
    }


def _hydrate_api_key_auth(
    config: dict[str, Any],
    site: str,
    component: str | None,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Resolve secret from ``.env`` into headers/query_params for runtime use."""
    env_name = str(config.get("api_key_env") or "").strip() or target_api_key_env_name(site, component)
    key = _read_dotenv_var(env_name)
    header_name, query_param_name, use_bearer = _api_key_metadata(config)

    # One-time migration: plaintext secret still in auth.json → move to .env
    if not key:
        legacy = _extract_plaintext_api_key(config)
        if legacy:
            key = legacy
            _write_dotenv_var(env_name, key)
            scrubbed = _scrubbed_api_key_config(
                env_name=env_name,
                header_name=header_name or "Authorization",
                query_param_name=query_param_name,
                use_bearer=use_bearer,
            )
            if path is not None:
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(scrubbed, indent=2) + "\n", encoding="utf-8")
                except OSError:
                    pass
            config = scrubbed

    out = dict(config)
    out["api_key_env"] = env_name
    out["api_key_header"] = header_name or "Authorization"
    out["api_key_query_param"] = query_param_name or ""
    out["api_key_use_bearer"] = bool(use_bearer)
    out["headers"] = {}
    out["query_params"] = {}
    if key:
        header = out["api_key_header"]
        qparam = out["api_key_query_param"]
        if header:
            out["headers"][header] = _api_key_header_value(
                header, key, use_bearer=bool(use_bearer) if header.lower() == "authorization" else False
            )
        if qparam:
            out["query_params"][qparam] = key
        if not out["headers"] and not out["query_params"]:
            out["headers"]["Authorization"] = _api_key_header_value(
                "Authorization", key, use_bearer=True
            )
    return out


def _is_configured_auth_data(data: dict[str, Any] | None) -> bool:
    if not isinstance(data, dict):
        return False
    mode = data.get("auth_mode")
    if mode == "none":
        return True
    if mode == "api_key":
        return bool(
            data.get("api_key_env")
            or data.get("headers")
            or data.get("query_params")
        )
    if data.get("cookies"):
        return True
    return any(
        o.get("localStorage") or o.get("sessionStorage")
        for o in data.get("origins", [])
        if isinstance(o, dict)
    )


def _load_auth_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return _normalize_auth_config(data)


def _is_configured_auth_file(path: Path) -> bool:
    return _is_configured_auth_data(_load_auth_file(path))


def _sibling_auth_files(site: str, exclude_component: str | None = None) -> list[Path]:
    site_dir = _site_dir(site)
    if not site_dir.is_dir():
        return []
    paths: list[Path] = []
    for item in site_dir.iterdir():
        if not item.is_dir() or item.name.startswith("."):
            continue
        if exclude_component and item.name == exclude_component:
            continue
        for name in (AUTH_FILE, STORAGE_STATE_FILE):
            candidate = item / name
            if candidate.is_file():
                paths.append(candidate)
    return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)


def _configured_auth_locations(
    site: str, component: str | None = None
) -> list[tuple[str, str | None, Path]]:
    """Return configured auth sources in read priority: own, site, siblings (newest first)."""
    locations: list[tuple[str, str | None, Path]] = []
    if component:
        comp_dir = _component_dir(site, component)
        for name in (AUTH_FILE, STORAGE_STATE_FILE):
            path = comp_dir / name
            if _is_configured_auth_file(path):
                return [("component", component, path)]
    site_dir = _site_dir(site)
    for name in (AUTH_FILE, STORAGE_STATE_FILE):
        path = site_dir / name
        if _is_configured_auth_file(path):
            locations.append(("site", None, path))
            break
    seen_components: set[str] = set()
    for path in _sibling_auth_files(site, exclude_component=component):
        sibling = path.parent.name
        if sibling in seen_components:
            continue
        if not _is_configured_auth_file(path):
            continue
        seen_components.add(sibling)
        locations.append(("component", sibling, path))
    return locations


def component_auth_configured(site: str, component: str) -> bool:
    """True when this component directory has its own configured auth.json."""
    comp_dir = _component_dir(site, component)
    for name in (AUTH_FILE, STORAGE_STATE_FILE):
        if _is_configured_auth_file(comp_dir / name):
            return True
    return False


def list_auth_reuse_options(site: str, component: str) -> list[dict[str, Any]]:
    """Auth sources on the same site that a new component can copy."""
    if component_auth_configured(site, component):
        return []
    options: list[dict[str, Any]] = []
    for scope, source_component, path in _configured_auth_locations(site, component):
        data = _load_auth_file(path)
        if not data:
            continue
        mode = data.get("auth_mode")
        if mode not in ("none", "api_key"):
            mode = "session"
        kind = "site" if scope == "site" else "component"
        label = site if scope == "site" else (source_component or "")
        options.append(
            {
                "source": kind,
                "component": source_component or "",
                "label": label,
                "mode": mode,
                "path": str(path),
            }
        )
    return options


def copy_auth_to_component(
    site: str,
    target_component: str,
    *,
    source: str,
    source_component: str | None = None,
) -> Path:
    """Copy configured auth from site or sibling component into target component."""
    source_kind = (source or "").strip().lower()
    if source_kind not in ("site", "component"):
        raise ValueError("source must be 'site' or 'component'")
    if source_kind == "component" and not (source_component or "").strip():
        raise ValueError("source_component is required when source is 'component'")

    locations = _configured_auth_locations(site, None if source_kind == "site" else source_component)
    chosen: Path | None = None
    for scope, comp, path in locations:
        if source_kind == "site" and scope == "site":
            chosen = path
            break
        if source_kind == "component" and scope == "component" and comp == source_component:
            chosen = path
            break
    if chosen is None:
        raise FileNotFoundError("Configured auth source not found")

    config = _load_auth_file(chosen)
    if not config or not _is_configured_auth_data(config):
        raise ValueError("Auth source is empty or not configured")
    return save_auth_config(site, config, component=target_component)


def resolve_auth_read_path(site: str, component: str | None = None) -> Path | None:
    """Return existing configured auth file (component, site, then sibling fallback)."""
    locations = _configured_auth_locations(site, component)
    return locations[0][2] if locations else None


def auth_data_has_browser_session(data: dict[str, Any] | None) -> bool:
    """True when auth.json carries cookies/origin storage usable by a UI browser.

    API-key-only configs (including sibling OpenAI keys) are not a browser session.
    """
    if not isinstance(data, dict):
        return False
    mode = str(data.get("auth_mode") or "").strip().lower()
    if mode in ("api_key", "none"):
        return False
    if data.get("cookies"):
        return True
    return any(
        isinstance(origin, dict)
        and (origin.get("localStorage") or origin.get("sessionStorage"))
        for origin in data.get("origins") or []
    )


def resolve_browser_auth_read_path(site: str, component: str | None = None) -> Path | None:
    """Auth file for UI browser launches — skips api_key / public stubs.

    Sibling API-key auth must not be treated as a ChatGPT (etc.) browser session.
    """
    for _scope, _source, path in _configured_auth_locations(site, component):
        data = _load_auth_file(path)
        if auth_data_has_browser_session(data):
            return path
    return None


def resolve_auth_scope(site: str, component: str | None = None) -> str:
    """Return ``component``, ``site``, ``shared``, or ``none`` for the resolved auth file."""
    locations = _configured_auth_locations(site, component)
    if not locations:
        return "none"
    scope, source_component, _path = locations[0]
    if scope == "component" and component and source_component == component:
        return "component"
    if scope == "site":
        return "site"
    if scope == "component" and source_component:
        return "shared"
    return "none"


def resolve_auth_shared_from(site: str, component: str | None = None) -> str | None:
    """When scope is ``shared``, return the sibling component name."""
    locations = _configured_auth_locations(site, component)
    if not locations:
        return None
    scope, source_component, _path = locations[0]
    if scope == "component" and component and source_component and source_component != component:
        return source_component
    return None


def get_auth_write_path(site: str, component: str | None = None) -> Path:
    """Path to write auth.json (component dir when component is set)."""
    if component:
        from browser_bot.sites import ensure_component_dir

        ensure_component_dir(site, component)
        return _component_dir(site, component) / AUTH_FILE
    from browser_bot.sites import ensure_site_dir

    ensure_site_dir(site)
    return _site_dir(site) / AUTH_FILE


def get_auth_config_path(site: str, component: str | None = None) -> Path:
    """Preferred auth path for reads; falls back to site-level legacy path."""
    resolved = resolve_auth_read_path(site, component)
    if resolved:
        return resolved
    if component:
        return _component_dir(site, component) / AUTH_FILE
    return _site_dir(site) / AUTH_FILE


def auth_config_exists(site: str, component: str | None = None) -> bool:
    """True if auth config exists for component (with site fallback) or site only."""
    return resolve_auth_read_path(site, component) is not None


def load_auth_config(site: str, component: str | None = None) -> dict[str, Any] | None:
    """Load auth config. Returns dict or None if not found.

    For ``auth_mode: api_key``, hydrates header/query values from ``.env``
    (never returns the secret in a way that rewrites it into auth.json).
    """
    path = resolve_auth_read_path(site, component)
    if not path:
        return None
    data = _load_auth_file(path)
    if not data:
        return None
    if data.get("auth_mode") == "api_key":
        # Env var is keyed by the auth.json owner (site-level or component folder).
        owning = None if path.parent == _site_dir(site) else path.parent.name
        return _hydrate_api_key_auth(data, site, owning, path=path)
    return data


def _normalize_auth_config(data: dict) -> dict:
    """Normalize legacy storage_state or full auth.json to unified format."""
    for origin in data.get("origins", []):
        if "sessionStorage" not in origin:
            origin["sessionStorage"] = []
    if "headers" not in data:
        data["headers"] = {}
    if "query_params" not in data:
        data["query_params"] = {}
    return data


def save_auth_config(site: str, config: dict[str, Any], component: str | None = None) -> Path:
    """Save auth config to component or site auth.json."""
    path = get_auth_write_path(site, component)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    return path


def _auth_write_component(site: str, component: str | None) -> str | None:
    """Component name to write auth into (owning component, sibling share, or site-level None)."""
    scope = resolve_auth_scope(site, component)
    if scope == "component":
        return component
    if scope == "shared":
        return resolve_auth_shared_from(site, component)
    return None


def _cookie_matches_prefixes(name: str, prefixes: tuple[str, ...]) -> bool:
    n = (name or "").strip()
    if not n:
        return False
    return any(n == p or n.startswith(p) for p in prefixes)


def _cookie_identity(cookie: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(cookie.get("name") or ""),
        str(cookie.get("domain") or ""),
        str(cookie.get("path") or "/"),
    )


async def merge_browser_cookies_into_auth(
    site: str,
    component: str | None,
    page: Any,
    *,
    cookie_name_prefixes: tuple[str, ...] = ("cf_clearance", "__cf_bm", "cf_chl"),
) -> bool:
    """
    Merge Cloudflare-related cookies from a live page into auth.json.

    Skips ``auth_mode`` none/api_key and empty session auth. Returns True when
    at least one matching cookie was written.
    """
    config = load_auth_config(site, component)
    if not config:
        return False
    mode = config.get("auth_mode")
    if mode in ("none", "api_key"):
        return False
    has_session = bool(config.get("cookies")) or any(
        o.get("localStorage") or o.get("sessionStorage")
        for o in config.get("origins", [])
        if isinstance(o, dict)
    )
    if not has_session:
        return False

    try:
        storage = await page.context.storage_state()
    except Exception:
        return False
    new_cookies = storage.get("cookies") if isinstance(storage, dict) else None
    if not isinstance(new_cookies, list) or not new_cookies:
        return False

    existing_list = [c for c in (config.get("cookies") or []) if isinstance(c, dict)]
    by_id = {_cookie_identity(c): c for c in existing_list}
    changed = False
    for cookie in new_cookies:
        if not isinstance(cookie, dict):
            continue
        name = str(cookie.get("name") or "")
        if not _cookie_matches_prefixes(name, cookie_name_prefixes):
            continue
        key = _cookie_identity(cookie)
        prev = by_id.get(key)
        if prev != cookie:
            by_id[key] = cookie
            changed = True

    if not changed:
        return False

    config["cookies"] = list(by_id.values())
    write_component = _auth_write_component(site, component)
    save_auth_config(site, config, component=write_component)
    return True


def clear_auth_config(site: str, component: str | None = None) -> Path:
    """Reset auth so the user can choose login vs public access again."""
    path = get_auth_write_path(site, component)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_auth_file(path)
    if existing and existing.get("auth_mode") == "api_key":
        env_name = str(existing.get("api_key_env") or "").strip() or target_api_key_env_name(
            site, component
        )
        _write_dotenv_var(env_name, None)
    path.write_text("{}", encoding="utf-8")
    return path


def is_auth_configured(site: str, component: str | None = None) -> bool:
    """True when auth is ready for browser/API runs."""
    config = load_auth_config(site, component)
    if not config:
        return False
    mode = config.get("auth_mode")
    if mode == "none":
        return True
    if mode == "api_key":
        return bool(config.get("headers") or config.get("query_params"))
    if config.get("cookies"):
        return True
    return any(
        o.get("localStorage") or o.get("sessionStorage")
        for o in config.get("origins", [])
    )


def auth_mode_for_domain(site: str, component: str | None = None) -> str | None:
    """Return ``none``, ``api_key``, ``session``, or None when auth is not configured."""
    if not is_auth_configured(site, component):
        return None
    config = load_auth_config(site, component) or {}
    mode = config.get("auth_mode")
    if mode in ("none", "api_key"):
        return mode
    return "session"


def save_public_auth(site: str, component: str | None = None) -> Path:
    """Save a no-login auth stub for public targets."""
    return save_auth_config(site, dict(PUBLIC_AUTH_TEMPLATE), component=component)


def save_api_key_auth(
    site: str,
    api_key: str,
    *,
    component: str | None = None,
    header_name: str = "Authorization",
    scheme: str = "Bearer",
    use_bearer: bool | None = None,
    query_param_name: str = "",
) -> Path:
    """Save target API key secret to ``.env``; metadata only in auth.json."""
    key = (api_key or "").strip()
    if not key:
        raise ValueError("API key is required")
    header = (header_name or "").strip() or "Authorization"
    qparam = (query_param_name or "").strip()
    bearer = use_bearer
    if bearer is None and header.lower() == "authorization":
        bearer = True
    if bearer is None:
        bearer = False
    env_name = target_api_key_env_name(site, component)
    _write_dotenv_var(env_name, key)
    config = _scrubbed_api_key_config(
        env_name=env_name,
        header_name=header,
        query_param_name=qparam,
        use_bearer=bool(bearer),
    )
    # scheme retained for API compatibility; Authorization bearer flag is what matters
    _ = scheme
    return save_auth_config(site, config, component=component)


def has_target_api_key(site: str, component: str | None = None) -> bool:
    """True when a target API key secret is available (``.env`` or legacy auth.json)."""
    path = resolve_auth_read_path(site, component)
    if not path:
        return False
    raw = _load_auth_file(path)
    if not raw or raw.get("auth_mode") != "api_key":
        return False
    owning = component
    if path.parent == _site_dir(site):
        owning = None
    elif component and path.parent.name != component:
        owning = path.parent.name
    env_name = str(raw.get("api_key_env") or "").strip() or target_api_key_env_name(site, owning)
    if _read_dotenv_var(env_name):
        return True
    return bool(_extract_plaintext_api_key(raw))


def auth_status_payload(site: str, component: str | None = None) -> dict[str, Any]:
    """Non-secret auth status for API responses."""
    if not auth_config_exists(site, component):
        payload = {
            "configured": False,
            "own_configured": False,
            "mode": None,
            "scope": "none",
            "shared_from": None,
            "has_api_key": False,
            "auth_header": "",
            "auth_query_param": "",
            "use_bearer": False,
            "api_key_env": "",
            "reuse_options": list_auth_reuse_options(site, component) if component else [],
        }
        return payload
    cfg = load_auth_config(site, component) or {}
    auth_header = str(cfg.get("api_key_header") or "").strip()
    auth_query_param = str(cfg.get("api_key_query_param") or "").strip()
    if not auth_header and cfg.get("headers"):
        auth_header = str(next(iter((cfg.get("headers") or {}).keys()), "") or "")
    if not auth_query_param and cfg.get("query_params"):
        auth_query_param = str(next(iter((cfg.get("query_params") or {}).keys()), "") or "")
    use_bearer = bool(cfg.get("api_key_use_bearer"))
    if not use_bearer and auth_header.lower() == "authorization":
        val = str((cfg.get("headers") or {}).get(auth_header) or "")
        use_bearer = bool(val) and val.lower().startswith("bearer ")
    scope = resolve_auth_scope(site, component)
    own = bool(component and component_auth_configured(site, component))
    return {
        "configured": is_auth_configured(site, component),
        "own_configured": own,
        "mode": auth_mode_for_domain(site, component),
        "scope": scope,
        "shared_from": resolve_auth_shared_from(site, component) if scope == "shared" else None,
        "has_api_key": has_target_api_key(site, component),
        "auth_header": auth_header,
        "auth_query_param": auth_query_param,
        "use_bearer": use_bearer,
        "api_key_env": str(cfg.get("api_key_env") or ""),
        "reuse_options": list_auth_reuse_options(site, component) if component and not own else [],
    }


def clean_auth_storage(
    site: str,
    component: str | None = None,
    max_value_len: int | None = None,
) -> tuple[bool, str]:
    """
    Strip localStorage/sessionStorage items with value length > max_value_len.
    Re-saves auth.json. Returns (success, message).
    """
    from browser_bot.config import LOCALSTORAGE_MAX_VALUE_LEN

    max_len = max_value_len if max_value_len is not None else LOCALSTORAGE_MAX_VALUE_LEN
    scope = resolve_auth_scope(site, component)
    config = load_auth_config(site, component)
    if not config:
        label = f"{site}/{component}" if component else site
        return False, f"No auth.json for {label}"

    def _filter(items: list) -> list:
        return [i for i in items if len(str(i.get("value", ""))) <= max_len]

    removed = 0
    for origin in config.get("origins", []):
        ls = origin.get("localStorage", [])
        ss = origin.get("sessionStorage", [])
        new_ls = _filter(ls)
        new_ss = _filter(ss)
        removed += (len(ls) - len(new_ls)) + (len(ss) - len(new_ss))
        origin["localStorage"] = new_ls
        origin["sessionStorage"] = new_ss

    if removed == 0:
        return True, f"No items over {max_len} chars to remove."
    write_component = component if scope == "component" else None
    save_auth_config(site, config, component=write_component)
    return True, f"Removed {removed} items (value > {max_len} chars)."
