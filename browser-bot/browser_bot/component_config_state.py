"""Component config reuse: copy submission settings between sibling components."""

from __future__ import annotations

import copy
from typing import Any

from browser_bot.sites import (
    get_component_config_path,
    list_components,
    load_component_config_raw,
    save_component_config,
)


def submission_config_complete(sub: dict[str, Any] | None) -> bool:
    """True when submission block is enough to run tests (mirrors web UI logic)."""
    if not sub or not isinstance(sub, dict):
        return False
    transport = (sub.get("transport") or "ui").strip().lower()
    if transport in ("api", "api_multipart"):
        return bool(sub.get("api_url") or sub.get("start_url"))
    if transport == "api_document":
        return bool(sub.get("upload_url") and sub.get("api_url"))
    inputs = sub.get("inputs") or []
    has_file = any(
        isinstance(i, dict) and (i.get("type") == "file" or i.get("path_from") == "payload")
        for i in inputs
    )
    if has_file:
        return bool(sub.get("start_url") and sub.get("submit_selector") and inputs)
    return bool(
        sub.get("start_url")
        and sub.get("submit_selector")
        and (inputs or sub.get("input_selector"))
    )


def component_submission_configured(site: str, component: str) -> bool:
    """True when this component has its own complete submission config."""
    raw = load_component_config_raw(site, component)
    return submission_config_complete(raw.get("submission"))


def list_config_reuse_options(site: str, component: str) -> list[dict[str, Any]]:
    """Sibling components with complete submission config this component can copy."""
    if component_submission_configured(site, component):
        return []
    options: list[dict[str, Any]] = []
    for sibling in list_components(site):
        if sibling == component:
            continue
        raw = load_component_config_raw(site, sibling)
        sub = raw.get("submission")
        if not submission_config_complete(sub):
            continue
        transport = (sub.get("transport") or "ui").strip().lower()
        options.append(
            {
                "component": sibling,
                "label": sibling,
                "transport": transport,
                "path": str(get_component_config_path(site, sibling)),
            }
        )
    return sorted(options, key=lambda o: o["label"])


def copy_config_to_component(site: str, target_component: str, *, source_component: str) -> str:
    """Copy submission (+ login_url) from a sibling into target component config."""
    source = (source_component or "").strip()
    if not source:
        raise ValueError("source_component is required")
    if source == target_component:
        raise ValueError("Cannot copy config from the same component")

    source_raw = load_component_config_raw(site, source)
    source_sub = source_raw.get("submission")
    if not submission_config_complete(source_sub):
        raise ValueError("Source component has no complete submission config")

    target_raw = load_component_config_raw(site, target_component)
    target_raw["submission"] = copy.deepcopy(source_sub)
    if source_raw.get("login_url"):
        target_raw["login_url"] = source_raw["login_url"]
    path = save_component_config(site, target_component, target_raw)
    return str(path)


def config_status_payload(site: str, component: str) -> dict[str, Any]:
    """Non-secret component config status for API responses."""
    own = component_submission_configured(site, component)
    return {
        "own_complete": own,
        "reuse_options": list_config_reuse_options(site, component) if not own else [],
    }
