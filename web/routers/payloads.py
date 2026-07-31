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

class PayloadGenerateBody(BaseModel):
    generator: str | None = None
    args: dict = {}
    out_dir: str | None = None
    asset_type: str | None = None
    content: str | None = None
    # Allow extra DVAIA flat fields via model_config


@router.get("/api/payloads/types")
async def api_payloads_types():
    import shutil

    from payloads.type_schemas import PAYLOAD_TYPE_SCHEMAS

    return {
        "types": PAYLOAD_TYPE_SCHEMAS,
        "ffmpeg_available": bool(shutil.which("ffmpeg")),
    }


@router.get("/api/payloads/background-assets")
async def api_payloads_background_assets():
    from payloads.api_handlers import list_background_assets

    return list_background_assets()


@router.get("/api/payloads/list")
async def api_payloads_list():
    from payloads.api_handlers import list_payload_files

    return {"files": list_payload_files()}


@router.get("/api/payloads/file/{relative_path:path}")
async def api_payloads_file(relative_path: str):
    from payloads.api_handlers import _safe_relative_path

    try:
        full = _safe_relative_path(relative_path)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not full.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(full, filename=full.name)


class MaterializeSuiteBody(BaseModel):
    suite_path: str


@router.post("/api/payloads/materialize-suite")
async def api_payloads_materialize_suite(body: MaterializeSuiteBody):
    from payloads.api_handlers import materialize_suite_path

    try:
        return materialize_suite_path(body.suite_path)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/api/payloads/artifact-status")
async def api_payloads_artifact_status(suite_path: str):
    from payloads.api_handlers import artifact_status

    try:
        return {"prompts": artifact_status(suite_path)}
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/payloads/generate")
async def api_payloads_generate(request: Request):
    """Generate a multimodal payload (JSON or multipart; DVAIA asset_type shape).

    Community: Premium-gated (standalone Multimodal builder).
    """
    from pipeline.edition import raise_premium

    raise_premium("multimodal_generate")

