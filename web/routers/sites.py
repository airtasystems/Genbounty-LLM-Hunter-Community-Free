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

from browser_bot.auth_state import (
    auth_status_payload,
    clear_auth_config,
    copy_auth_to_component,
    save_api_key_auth,
    save_public_auth,
)
from browser_bot.component_config_state import (
    config_status_payload,
    copy_config_to_component,
)
from browser_bot.sites import (
    ensure_component_dir,
    ensure_site_dir,
    get_component_path,
    get_domain_from_url,
    list_components,
    list_sites,
    load_component_config,
    load_component_config_raw,
    remove_site,
    save_component_config,
)

@router.get("/api/sites")
def api_list_sites():
    return list_sites()


class CreateSiteBody(BaseModel):
    domain: str


class RenameSiteBody(BaseModel):
    domain: str


@router.post("/api/sites")
async def api_create_site(body: CreateSiteBody):
    domain = get_domain_from_url(body.domain) if "://" in body.domain else body.domain
    domain = domain.rstrip("/")
    ensure_site_dir(domain)
    return {"ok": True, "domain": domain}


@router.patch("/api/sites/{site}")
async def api_rename_site(site: str, body: RenameSiteBody):
    domain = get_domain_from_url(body.domain) if "://" in body.domain else body.domain
    domain = domain.rstrip("/")
    if not domain:
        raise HTTPException(400, "Domain is required")
    src = BB_DIR / "sites" / site
    dst = BB_DIR / "sites" / domain
    if not src.is_dir():
        raise HTTPException(404, "Site not found")
    if dst.exists() and dst != src:
        raise HTTPException(409, "Site already exists")
    src.rename(dst)
    return {"ok": True, "domain": domain}


@router.delete("/api/sites/{site}")
async def api_delete_site(site: str):
    if remove_site(site):
        return {"ok": True}
    raise HTTPException(404, "Site not found")


@router.get("/api/llm-api-presets")
async def api_llm_api_presets():
    from browser_bot.api_presets import get_llm_api_presets

    return get_llm_api_presets()


@router.get("/api/sites/{site}/auth-status")
async def api_auth_status_site(site: str):
    """Legacy site-level auth status (no component fallback chain)."""
    return auth_status_payload(site, component=None)


@router.get("/api/sites/{site}/{component}/auth-status")
async def api_auth_status(site: str, component: str):
    ensure_component_dir(site, component)
    return auth_status_payload(site, component)


class AuthReuseBody(BaseModel):
    source: str  # "site" | "component"
    source_component: str = ""


@router.post("/api/sites/{site}/{component}/auth/reuse")
async def api_reuse_auth(site: str, component: str, body: AuthReuseBody):
    """Copy configured auth from site or sibling component into this component."""
    ensure_component_dir(site, component)
    try:
        path = copy_auth_to_component(
            site,
            component,
            source=body.source,
            source_component=body.source_component.strip() or None,
        )
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    payload = auth_status_payload(site, component)
    payload["ok"] = True
    payload["path"] = str(path)
    return payload


class TargetApiKeyBody(BaseModel):
    api_key: str = ""
    header_name: str = "Authorization"
    scheme: str = "Bearer"
    use_bearer: bool | None = None
    query_param_name: str = ""


def _auth_scope(component: str | None) -> str:
    return "component" if component is not None else "site"


def _init_public_auth(site: str, component: str | None = None) -> dict:
    path = save_public_auth(site, component=component)
    return {"ok": True, "mode": "none", "path": str(path), "scope": _auth_scope(component)}


def _save_target_api_key(site: str, body: TargetApiKeyBody, component: str | None = None) -> dict:
    try:
        path = save_api_key_auth(
            site,
            body.api_key,
            component=component,
            header_name=body.header_name,
            scheme=body.scheme,
            use_bearer=body.use_bearer,
            query_param_name=body.query_param_name,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {
        "ok": True,
        "mode": "api_key",
        "path": str(path),
        "has_api_key": True,
        "scope": _auth_scope(component),
    }


def _clear_auth(site: str, component: str | None = None) -> dict:
    path = clear_auth_config(site, component=component)
    return {"ok": True, "path": str(path), "scope": _auth_scope(component)}


@router.post("/api/sites/{site}/auth/public")
async def api_init_public_auth_site(site: str):
    return _init_public_auth(site)


@router.post("/api/sites/{site}/{component}/auth/public")
async def api_init_public_auth(site: str, component: str):
    """Initialize auth.json for targets that do not require login."""
    return _init_public_auth(site, component)


@router.post("/api/sites/{site}/auth/api-key")
async def api_save_target_api_key_site(site: str, body: TargetApiKeyBody):
    return _save_target_api_key(site, body)


@router.post("/api/sites/{site}/{component}/auth/api-key")
async def api_save_target_api_key(site: str, component: str, body: TargetApiKeyBody):
    """Store target API key in .env; auth.json keeps header/query metadata only."""
    return _save_target_api_key(site, body, component)


@router.delete("/api/sites/{site}/auth")
async def api_clear_auth_site(site: str):
    return _clear_auth(site)


@router.delete("/api/sites/{site}/{component}/auth")
async def api_clear_auth(site: str, component: str):
    """Reset component auth so the user can choose login vs public access again."""
    return _clear_auth(site, component)


@router.get("/api/sites/{site}/components")
async def api_list_components(site: str):
    return list_components(site)


class CreateComponentBody(BaseModel):
    name: str


class RenameComponentBody(BaseModel):
    name: str


@router.post("/api/sites/{site}/components")
async def api_create_component(site: str, body: CreateComponentBody):
    name = "".join(c if c.isalnum() or c in "-_" else "_" for c in body.name).strip("_") or "default"
    ensure_component_dir(site, name)
    return {"ok": True, "name": name}


@router.patch("/api/sites/{site}/components/{component}")
async def api_rename_component(site: str, component: str, body: RenameComponentBody):
    name = "".join(c if c.isalnum() or c in "-_" else "_" for c in body.name).strip("_")
    if not name:
        raise HTTPException(400, "Component name is required")
    src = get_component_path(site, component)
    dst = get_component_path(site, name)
    if not src.is_dir():
        raise HTTPException(404, "Component not found")
    if dst.exists() and dst != src:
        raise HTTPException(409, "Component already exists")
    src.rename(dst)
    return {"ok": True, "name": name}


@router.delete("/api/sites/{site}/components/{component}")
async def api_delete_component(site: str, component: str):
    import shutil

    p = get_component_path(site, component)
    if not p.is_dir():
        raise HTTPException(404, "Component not found")
    shutil.rmtree(p)
    return {"ok": True}


@router.get("/api/sites/{site}/{component}/config")
def api_component_config(site: str, component: str):
    return load_component_config_raw(site, component)


@router.get("/api/sites/{site}/{component}/config/status")
async def api_component_config_status(site: str, component: str):
    ensure_component_dir(site, component)
    return config_status_payload(site, component)


class ConfigReuseBody(BaseModel):
    source_component: str = ""


@router.post("/api/sites/{site}/{component}/config/reuse")
async def api_reuse_component_config(site: str, component: str, body: ConfigReuseBody):
    """Copy submission config from a sibling component into this component."""
    ensure_component_dir(site, component)
    try:
        path = copy_config_to_component(
            site,
            component,
            source_component=body.source_component.strip(),
        )
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    payload = config_status_payload(site, component)
    payload["ok"] = True
    payload["path"] = path
    return payload


class SaveComponentConfigBody(BaseModel):
    config: dict

@router.post("/api/sites/{site}/{component}/config")
async def api_save_component_config(site: str, component: str, body: SaveComponentConfigBody):
    save_component_config(site, component, body.config)
    return {"ok": True}

