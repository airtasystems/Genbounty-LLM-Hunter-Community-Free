"""Per-component Genbounty export settings (config.yaml ``export:`` block)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent

VALID_EXPORT_RISK_LEVELS = frozenset({
    "critical",
    "high",
    "medium",
    "low",
    "informational",
    "indeterminate",
})

DEFAULT_EXPORT_RISK_LEVELS = ("critical", "high", "medium")


def _ensure_browser_bot_path() -> None:
    import sys

    bb = _ROOT / "browser-bot"
    if str(bb) not in sys.path:
        sys.path.insert(0, str(bb))


def normalize_export_risk_levels(levels: object) -> list[str]:
    if levels is None:
        return list(DEFAULT_EXPORT_RISK_LEVELS)
    if isinstance(levels, str):
        parts = [p.strip() for p in levels.replace(",", " ").split() if p.strip()]
        levels = parts
    if not isinstance(levels, (list, tuple, set, frozenset)):
        return list(DEFAULT_EXPORT_RISK_LEVELS)
    out: list[str] = []
    for raw in levels:
        if isinstance(raw, str):
            level = raw.strip().lower()
            if level in VALID_EXPORT_RISK_LEVELS and level not in out:
                out.append(level)
    return out or list(DEFAULT_EXPORT_RISK_LEVELS)


def load_component_export_config(
    site: str | None,
    component: str | None,
) -> dict[str, Any]:
    """Read ``export:`` from component config.yaml."""
    site = (site or "").strip()
    component = (component or "").strip()
    if not site or not component:
        return default_export_config()
    try:
        _ensure_browser_bot_path()
        from browser_bot.sites import load_component_config_raw

        cfg = load_component_config_raw(site, component)
        block = cfg.get("export")
        if not isinstance(block, dict):
            return default_export_config()
        return normalize_export_config(block)
    except Exception:
        return default_export_config()


def default_export_config() -> dict[str, Any]:
    return {
        "auto_after_assess": False,
        "risk_levels": list(DEFAULT_EXPORT_RISK_LEVELS),
        "user_id": "",
    }


def normalize_export_config(block: dict[str, Any]) -> dict[str, Any]:
    auto = block.get("auto_after_assess", block.get("auto_export", False))
    if isinstance(auto, str):
        auto = auto.strip().lower() in ("1", "true", "yes", "on")
    levels = normalize_export_risk_levels(block.get("risk_levels"))
    user_id = str(block.get("user_id") or "").strip()
    return {
        "auto_after_assess": bool(auto),
        "risk_levels": levels,
        "user_id": user_id,
    }


def export_config_for_job(
    site: str | None,
    component: str | None,
    job_params: dict | None = None,
) -> dict[str, Any]:
    """Merge saved component export config with per-job overrides (job wins)."""
    cfg = load_component_export_config(site, component)
    params = job_params or {}
    if "auto_export" in params or "auto_after_assess" in params:
        cfg["auto_after_assess"] = bool(
            params.get("auto_export") or params.get("auto_after_assess")
        )
    if params.get("risk_levels"):
        cfg["risk_levels"] = normalize_export_risk_levels(params.get("risk_levels"))
    if params.get("user_id"):
        cfg["user_id"] = str(params["user_id"]).strip()
    return cfg


def should_auto_export(site: str | None, component: str | None, job_params: dict | None = None) -> bool:
    return export_config_for_job(site, component, job_params)["auto_after_assess"]
