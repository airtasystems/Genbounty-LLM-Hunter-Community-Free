"""Site config and auth storage."""

import re
from pathlib import Path
from urllib.parse import urlparse, urlunparse

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
SITES_DIR = _PROJECT_ROOT / "sites"
STORAGE_STATE_FILE = "storage_state.json"
AUTH_FILE = "auth.json"
_IPV4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def host_looks_local(host: str) -> bool:
    """True for localhost / loopback / bare IPv4 (use http, never append .com)."""
    h = (host or "").strip().lower()
    return (
        h == "localhost"
        or h == "0.0.0.0"
        or h.startswith("127.")
        or bool(_IPV4_RE.match(h))
    )


def normalize_target_access_url(raw: str) -> str:
    """Prepend https:// (http for local) and append .com when hostname has no TLD.

    Mirrors the Connect Target UI helper so discovery/login/recon do not navigate to
    bare hosts like https://chatgpt/ when the site folder is named without a TLD.
    """
    original = (raw or "").strip()
    if not original:
        return ""
    s = original
    try:
        if s.startswith("//"):
            s = f"https:{s}"
        # Require "://" so host:port (e.g. localhost:3000) is not treated as a scheme.
        if "://" not in s:
            host_part = s.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
            host_only = host_part.split("@")[-1] if "@" in host_part else host_part
            hostname = re.sub(r":\d+$", "", host_only or "")
            scheme = "http" if host_looks_local(hostname) else "https"
            s = f"{scheme}://{s}"
        parsed = urlparse(s)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return original
        host = parsed.hostname
        if not host_looks_local(host) and "." not in host:
            netloc = f"{host}.com"
            if parsed.port:
                netloc = f"{netloc}:{parsed.port}"
            if parsed.username:
                userinfo = parsed.username
                if parsed.password is not None:
                    userinfo = f"{userinfo}:{parsed.password}"
                netloc = f"{userinfo}@{netloc}"
            parsed = parsed._replace(netloc=netloc)
        out = urlunparse(parsed)
        if (
            parsed.path in ("", "/")
            and not parsed.params
            and not parsed.query
            and not parsed.fragment
        ):
            out = out.rstrip("/")
        return out or original
    except Exception:
        return original


def resolve_discovery_launch_url(config: dict, site: str) -> str:
    """URL Configure Component / discovery should open first.

    Prefer submission.start_url (chat page) over login_url / site folder name so a
    deep path like https://play.lakera.ai/agent-breaker/... is not replaced by a
    brand-folder default such as https://Lakera → https://Lakera.com.
    """
    sub = config.get("submission") if isinstance(config.get("submission"), dict) else {}
    candidates = (
        sub.get("start_url") if isinstance(sub.get("start_url"), str) else "",
        config.get("login_url") if isinstance(config.get("login_url"), str) else "",
        site or "",
    )
    for raw in candidates:
        text = (raw or "").strip()
        if not text:
            continue
        return normalize_target_access_url(text) or text
    fallback = (site or "").strip() or "localhost"
    return (
        f"http://{fallback}"
        if host_looks_local(fallback.split(":", 1)[0])
        else f"https://{fallback}"
    )


def _domain_to_site_dir(domain: str) -> Path:
    """Convert domain (e.g. airtasystems.com) to site config directory."""
    return SITES_DIR / domain


def get_login_profile_path(domain: str, component: str | None = None) -> Path:
    """Path to persistent profile for login (Google trusts real profiles more)."""
    if component:
        return get_component_path(domain, component) / ".login_profile"
    return _domain_to_site_dir(domain) / ".login_profile"


def get_recon_path(domain: str, component: str) -> Path:
    """Path to sites/{domain}/{component}/recon.json."""
    return get_component_path(domain, component) / "recon.json"


def get_recon_har_path(domain: str, component: str) -> Path:
    """Path to sites/{domain}/{component}/recon.har (headed probe capture)."""
    return get_component_path(domain, component) / "recon.har"


def get_recon_network_log_path(domain: str, component: str) -> Path:
    """Path to sites/{domain}/{component}/recon-network.json."""
    return get_component_path(domain, component) / "recon-network.json"


INTEL_DIR_NAME = "intel"


def get_intel_dir(domain: str, component: str) -> Path:
    """Path to sites/{domain}/{component}/intel/."""
    return get_component_path(domain, component) / INTEL_DIR_NAME


def get_intel_path(domain: str, component: str, playbook_id: str) -> Path:
    """Path to sites/{domain}/{component}/intel/{playbook_id}.json."""
    from playbooks.registry import normalize_playbook_id

    pid = normalize_playbook_id(playbook_id)
    if not pid:
        raise ValueError("playbook_id is required for intel path")
    return get_intel_dir(domain, component) / f"{pid}.json"


def list_intel_playbooks(domain: str, component: str) -> list[str]:
    """List playbook_id stems with intel files for a component."""
    directory = get_intel_dir(domain, component)
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.json") if p.is_file())


def get_domain_from_url(url: str) -> str:
    """Extract domain from URL."""
    parsed = urlparse(url)
    return parsed.netloc or parsed.path.split("/")[0] or ""


def get_storage_state_path(domain: str, component: str | None = None) -> Path | None:
    """Get path to auth config for domain/component. Prefers auth.json, falls back to storage_state.json."""
    from browser_bot.auth_state import resolve_auth_read_path

    return resolve_auth_read_path(domain, component)


def get_storage_state_path_for_url(url: str, component: str | None = None) -> Path | None:
    """Get storage state path for a URL's domain."""
    return get_storage_state_path(get_domain_from_url(url), component)


def ensure_site_dir(domain: str) -> Path:
    """Ensure site directory exists. Creates auth.json with {} if new. Returns path."""
    path = _domain_to_site_dir(domain)
    path.mkdir(parents=True, exist_ok=True)
    auth_path = path / AUTH_FILE
    if not auth_path.exists():
        auth_path.write_text("{}", encoding="utf-8")
    return path


def get_storage_state_file(domain: str) -> Path:
    """Get the storage state file path for a domain (creates dir if needed)."""
    return ensure_site_dir(domain) / STORAGE_STATE_FILE


def list_sites() -> list[str]:
    """List all sites (any domain dir under sites/)."""
    if not SITES_DIR.exists():
        return []
    sites = []
    for item in SITES_DIR.iterdir():
        if item.is_dir() and not item.name.startswith("."):
            sites.append(item.name)
    return sorted(sites)


def remove_site(domain: str) -> bool:
    """Remove site config. Returns True if removed."""
    import shutil

    path = _domain_to_site_dir(domain)
    if path.exists():
        shutil.rmtree(path)
        return True
    return False


# --- Site config (sites/{domain}/config.yaml) ---
# Shared settings: login_url, refresh_url, refresh_mode, refresh_cookies.
# Components inherit these; component config overrides site config.
# Target auth (API keys / UI sessions) lives at sites/{domain}/{component}/auth.json
# with legacy fallback to sites/{domain}/auth.json.

SITE_CONFIG_FILE = "config.yaml"


def get_site_config_path(domain: str) -> Path:
    """Path to site-level config.yaml."""
    return _domain_to_site_dir(domain) / SITE_CONFIG_FILE


def load_site_config(domain: str) -> dict:
    """Load site-level config. Returns empty dict if not found."""
    path = get_site_config_path(domain)
    if path.exists():
        import yaml

        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


def save_site_config(domain: str, config: dict) -> Path:
    """Save site-level config with documented inline comments. Returns path."""
    from browser_bot.site_config_yaml import write_site_config_documented

    ensure_site_dir(domain)
    path = get_site_config_path(domain)
    write_site_config_documented(path, config)
    return path


def ensure_site_config_on_discovery(domain: str, *, login_url: str | None = None) -> Path | None:
    """Create default sites/<domain>/config.yaml on first discovery if missing."""
    from browser_bot.site_config_yaml import default_site_config, write_site_config_documented

    path = get_site_config_path(domain)
    if path.is_file():
        return None
    ensure_site_dir(domain)
    config = default_site_config(domain, login_url=login_url)
    write_site_config_documented(path, config)
    return path


# --- Component config (sites/{domain}/{component}/) ---

from browser_bot.component_config_yaml import write_component_config_documented

COMPONENT_CONFIG_FILE = "config.yaml"


def write_component_config_with_header(path: Path, config: dict) -> None:
    """Write component config.yaml with standard documentation and inline comments."""
    write_component_config_documented(path, config)


def get_component_path(domain: str, component: str) -> Path:
    """Path to component dir: sites/{domain}/{component}/."""
    return _domain_to_site_dir(domain) / component


# Runtime artifacts wiped by Nuke; config, auth, recon.json, and prior backups survive.
NUKE_COMPONENT_KEEP = frozenset({
    "config.yaml",
    "auth.json",
    "recon.json",
    "nuke_backups",
})
NUKE_BACKUP_DIR = "nuke_backups"


def nuke_component(domain: str, component: str) -> dict:
    """Delete experiment artifacts under a component; keep config, auth, and recon.json.

    Writes a full pre-wipe snapshot under ``nuke_backups/<UTC timestamp>/`` (every
    top-level child except ``nuke_backups`` itself), then removes tests, logs, intel,
    theory history, manual attacks, html, login profile, legacy recon.har /
    recon-network.json, and any other top-level children not in ``NUKE_COMPONENT_KEEP``.

    Returns ``{"ok": True, "path": str, "backup": str, "removed": [...], "kept": [...]}``.
    Raises ``FileNotFoundError`` if the component directory is missing.
    Raises ``RuntimeError`` if backup or removal fails.
    """
    import shutil
    from datetime import datetime, timezone

    root = get_component_path(domain, component)
    if not root.is_dir():
        raise FileNotFoundError(f"Component not found: {domain}/{component}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = root / NUKE_BACKUP_DIR / stamp
    errors: list[str] = []

    try:
        backup_root.mkdir(parents=True, exist_ok=False)
        for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if child.name == NUKE_BACKUP_DIR:
                continue
            dest = backup_root / child.name
            try:
                if child.is_dir() and not child.is_symlink():
                    shutil.copytree(child, dest)
                else:
                    shutil.copy2(child, dest)
            except OSError as exc:
                errors.append(f"backup {child.name}: {exc}")
    except OSError as exc:
        errors.append(f"backup dir: {exc}")

    if errors:
        raise RuntimeError(
            f"Nuke backup failed for {domain}/{component}: " + "; ".join(errors)
        )

    removed: list[str] = []
    kept: list[str] = []

    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        name = child.name
        if name in NUKE_COMPONENT_KEEP:
            kept.append(name)
            continue
        try:
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink(missing_ok=True)
            removed.append(name)
        except OSError as exc:
            errors.append(f"{name}: {exc}")

    if errors:
        raise RuntimeError(
            f"Nuke incomplete for {domain}/{component}: " + "; ".join(errors)
        )

    return {
        "ok": True,
        "path": str(root),
        "backup": str(backup_root),
        "removed": removed,
        "kept": kept,
    }


def list_components(domain: str) -> list[str]:
    """List component names for a site (subdirs of sites/{domain}/)."""
    site_dir = _domain_to_site_dir(domain)
    if not site_dir.exists():
        return []
    components = []
    for item in site_dir.iterdir():
        if item.is_dir() and not item.name.startswith("."):
            components.append(item.name)
    return sorted(components)


def _default_login_url(domain: str) -> str:
    """Build default login_url from domain (http for localhost, https otherwise)."""
    if "localhost" in domain or domain.startswith("127."):
        return f"http://{domain}"
    return f"https://{domain}"


def ensure_component_dir(domain: str, component: str) -> Path:
    """Ensure component directory exists. Creates default config.yaml if new. Returns path."""
    path = get_component_path(domain, component)
    path.mkdir(parents=True, exist_ok=True)
    config_path = get_component_config_path(domain, component)
    if not config_path.exists():
        from pipeline.component_settings import initial_config_settings

        default_config = {
            "urls": [],
            "posts": [],
            "login_url": _default_login_url(domain),
            "settings": initial_config_settings(),
        }
        write_component_config_with_header(config_path, default_config)
    return path


def get_component_config_path(domain: str, component: str) -> Path:
    """Path to component config.yaml."""
    return get_component_path(domain, component) / COMPONENT_CONFIG_FILE


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base. Override values take precedence. Does not mutate inputs."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_component_config_raw(domain: str, component: str) -> dict:
    """Load raw component config (no site merge). For internal use when saving."""
    path = get_component_config_path(domain, component)
    legacy_path = get_component_path(domain, component) / "config.json"
    if path.exists():
        import yaml

        with open(path) as f:
            return yaml.safe_load(f) or {}
    if legacy_path.exists():
        import json

        with open(legacy_path) as f:
            config = json.load(f)
        save_component_config(domain, component, config)
        legacy_path.unlink()
        return config
    return {}


def load_component_config(domain: str, component: str) -> dict:
    """Load component config merged with site config. Site provides defaults; component overrides.
    Returns empty dict if not found. Migrates config.json -> config.yaml if needed."""
    comp_raw = load_component_config_raw(domain, component)
    site_cfg = load_site_config(domain)
    return _deep_merge(site_cfg, comp_raw)


def save_component_config(domain: str, component: str, config: dict) -> Path:
    """Save component config. Returns path."""
    ensure_component_dir(domain, component)
    path = get_component_config_path(domain, component)
    write_component_config_with_header(path, config)
    return path


def get_component_urls_and_posts(domain: str, component: str) -> tuple[list, list]:
    """Load urls and posts from component config. Returns (urls, posts). Fallback to empty."""
    config = load_component_config(domain, component)
    urls = config.get("urls") or []
    posts_raw = config.get("posts") or []
    posts = [
        {"url": p["url"], "data": p.get("data"), "json": p.get("json"), "headers": p.get("headers")}
        for p in posts_raw
        if isinstance(p, dict) and "url" in p
    ]
    return urls, posts


def get_component_endpoint(domain: str, component: str) -> str | None:
    """Get endpoint_url from component config."""
    config = load_component_config(domain, component)
    return config.get("endpoint_url")


def set_component_endpoint(domain: str, component: str, url: str) -> Path:
    """Save endpoint_url to component config."""
    config = load_component_config_raw(domain, component)
    config.setdefault("urls", [])
    config.setdefault("posts", [])
    config["endpoint_url"] = url
    return save_component_config(domain, component, config)


def get_submission_config(domain: str, component: str) -> dict | None:
    """Get runnable submission config (UI or API transport).

    UI requires start_url, inputs, submit_selector.
    API requires api_url and api_body (defaults to ``{prompt: '{{prompt}}'}``).
    """
    config = load_component_config(domain, component)
    sub = config.get("submission")
    if not sub or not isinstance(sub, dict):
        return None
    transport = (sub.get("transport") or "ui").strip().lower()
    if transport == "api":
        return _normalize_api_submission(sub, config)
    return _normalize_ui_submission(sub)


def _normalize_ui_submission(sub: dict) -> dict | None:
    if not sub.get("start_url") or not sub.get("submit_selector"):
        return None
    sub = dict(sub)
    if "inputs" not in sub and sub.get("input_selector"):
        sub["inputs"] = [{"selector": sub["input_selector"], "type": "text"}]
    if not sub.get("inputs"):
        return None
    sub.setdefault("transport", "ui")
    return sub


def _normalize_api_submission(sub: dict, config: dict) -> dict | None:
    api_url = sub.get("api_url") or config.get("endpoint_url") or sub.get("start_url")
    if not api_url:
        return None
    api_body = sub.get("api_body")
    if api_body is None:
        api_body = sub.get("api_body_template")
    if api_body is None:
        api_body = {"prompt": "{{prompt}}"}
    out = {
        "transport": "api",
        "api_url": str(api_url).strip(),
        "api_method": (sub.get("api_method") or "POST").upper(),
        "api_headers": dict(sub.get("api_headers") or {}),
        "api_body": api_body,
        "api_response_path": (sub.get("api_response_path") or "response").strip(),
        "mode": sub.get("mode"),
        "batch_size": sub.get("batch_size"),
    }
    api_model = sub.get("api_model")
    if api_model:
        out["api_model"] = str(api_model).strip()
    if sub.get("api_context_mode"):
        out["api_context_mode"] = str(sub.get("api_context_mode")).strip()
    prefix = sub.get("api_messages_prefix")
    if isinstance(prefix, list) and prefix:
        out["api_messages_prefix"] = prefix
    if sub.get("api_user_role"):
        out["api_user_role"] = str(sub.get("api_user_role")).strip()
    if sub.get("api_assistant_role"):
        out["api_assistant_role"] = str(sub.get("api_assistant_role")).strip()
    return out


def describe_submission_config_issue(config: dict) -> str:
    """Human-readable reason submission config is not runnable."""
    sub = config.get("submission")
    if not sub or not isinstance(sub, dict):
        return "missing submission block"
    transport = (sub.get("transport") or "ui").strip().lower()
    if transport == "api":
        if not (sub.get("api_url") or config.get("endpoint_url") or sub.get("start_url")):
            return "missing submission.api_url"
        return "invalid API submission block"
    missing = []
    if not sub.get("start_url"):
        missing.append("submission.start_url")
    if not (sub.get("inputs") or sub.get("input_selector")):
        missing.append("submission.inputs")
    if not sub.get("submit_selector"):
        missing.append("submission.submit_selector")
    return "missing " + ", ".join(missing) if missing else "invalid submission block"
