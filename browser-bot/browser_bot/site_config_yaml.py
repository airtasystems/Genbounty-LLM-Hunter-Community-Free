"""Format site-level config.yaml with documented inline comments."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from browser_bot.component_config_yaml import SETTINGS_OVERRIDES_EXAMPLE, _yaml_scalar

SITE_CONFIG_INTRO = """# =============================================================================
# Site config - browser-bot/sites/<site>/config.yaml
# =============================================================================
#
# Shared settings for every component on this site. Component config.yaml
# overrides values here for submission selectors and per-component settings.
#
# Precedence for settings: component → this file → config.py / .env →
# config.defaults.yaml. See repo-root config.defaults.yaml for all settings keys.
#
# Created automatically on first Discovery run if missing.
"""

_KNOWN_SITE_KEYS = frozenset({
    "login_url", "refresh_url", "refresh_mode", "refresh_cookies", "settings",
})


def default_site_config(domain: str, *, login_url: str | None = None) -> dict[str, Any]:
    """Build a minimal default site config dict."""
    from pipeline.component_settings import initial_config_settings

    if not login_url:
        if "localhost" in domain or domain.startswith("127."):
            login_url = f"http://{domain}"
        else:
            login_url = f"https://{domain}"
    return {"login_url": login_url, "settings": initial_config_settings()}


def _format_settings(settings: dict[str, Any]) -> list[str]:
    import yaml

    lines = [
        "# --- Settings overrides (optional) ---------------------------------------------",
        "# Apply to all components on this site unless overridden in component config.yaml.",
        "# Full list and allowed values: see config.defaults.yaml at repo root.",
        "settings:",
    ]
    block = yaml.dump(settings, default_flow_style=False, sort_keys=False, allow_unicode=True)
    for line in block.splitlines():
        lines.append(f"  {line}" if line.strip() else "")
    return lines


def format_site_config_yaml(config: dict[str, Any]) -> str:
    """Render site config dict as documented YAML text."""
    import yaml

    lines: list[str] = [SITE_CONFIG_INTRO.rstrip(), ""]

    lines.extend([
        "# --- Auth --------------------------------------------------------------------",
        "# Page opened for \"Add Login\" / manual sign-in. Usually the site root or /login.",
        "# http:// for localhost; https:// for production hosts.",
        "# Shared by all components on this site unless a component sets its own login_url.",
    ])
    login_url = config.get("login_url")
    lines.append(f"login_url: {_yaml_scalar(login_url if login_url not in (None, '') else '')}")
    lines.append("")

    lines.extend([
        "# --- Token refresh (optional) ------------------------------------------------",
        "# Used by browser-bot to renew auth tokens. Often set once at site level.",
    ])

    refresh_fields: list[tuple[str, str, str]] = [
        ("refresh_url", "# URL called to refresh session tokens.", "# refresh_url: https://example.com/api/refresh"),
        ("refresh_mode", "# How refresh is sent. Options: cookie | both", "# refresh_mode: both"),
        ("refresh_cookies", "# Cookie names to include on refresh (list).", "# refresh_cookies:"),
    ]
    has_refresh = False
    for key, comment, placeholder in refresh_fields:
        if key in config and config[key] not in (None, ""):
            has_refresh = True
            lines.append(comment)
            val = config[key]
            if isinstance(val, list):
                lines.append(f"{key}:")
                for item in val:
                    lines.append(f"  - {_yaml_scalar(item)}")
            else:
                lines.append(f"{key}: {_yaml_scalar(val)}")
            lines.append("")

    if not has_refresh:
        lines.extend([
            "# refresh_url: https://example.com/api/auth/refresh",
            "# refresh_mode: both",
            "# refresh_cookies:",
            "#   - session_id",
            "",
        ])

    settings = config.get("settings")
    if isinstance(settings, dict) and settings:
        lines.extend(_format_settings(settings))
    else:
        lines.append(SETTINGS_OVERRIDES_EXAMPLE.rstrip().replace(
            "Settings → Browser Config and Cache Control. Omit keys to inherit.",
            "Settings → Browser Config and Cache Control. Apply site-wide; components may override.",
        ))

    extras = {k: v for k, v in config.items() if k not in _KNOWN_SITE_KEYS}
    if extras:
        lines.extend(["", "# --- Additional config ---------------------------------------------------------"])
        lines.append(yaml.dump(extras, default_flow_style=False, sort_keys=False, allow_unicode=True).rstrip())

    return "\n".join(lines).rstrip() + "\n"


def write_site_config_documented(path: Path, config: dict) -> None:
    """Write site config.yaml with full inline documentation."""
    path.write_text(format_site_config_yaml(config), encoding="utf-8")
