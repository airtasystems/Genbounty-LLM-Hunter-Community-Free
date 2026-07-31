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

from web.jobs import (
    cancel_job,
    get_job,
    list_jobs,
    respond_to_enhance_theory,
    send_stdin,
    start_job,
    stream_job,
)

@router.get("/api/jobs")
async def api_list_jobs():
    return list_jobs()


class StartJobBody(BaseModel):
    type: str
    site: str = ""
    component: str = ""
    params: dict = {}

@router.post("/api/jobs")
async def api_start_job(body: StartJobBody):
    job = await start_job(body.type, body.site, body.component, body.params)
    return job.to_dict()


@router.get("/api/jobs/{job_id}")
async def api_get_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    d = job.to_dict()
    d["output"] = job.output
    return d


@router.get("/api/jobs/{job_id}/stream")
async def api_stream_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return StreamingResponse(stream_job(job_id), media_type="text/event-stream")


@router.get("/api/jobs/{job_id}/preview")
@router.get("/api/jobs/{job_id}/preview/{slot}")
async def api_job_preview(
    job_id: str,
    slot: int = 0,
    seq: int | None = None,
    site: str = "",
    component: str = "",
):
    from browser_bot.live_preview import find_preview_path, preview_path

    job = get_job(job_id)
    resolved_site = (job.site if job else site) or None
    resolved_component = (job.component if job else component) or None
    run_log_dir = (job.run_log_dir if job else None) or None

    path = None
    if seq is not None and seq >= 0:
        candidate = preview_path(
            job_id,
            slot,
            run_log_dir=run_log_dir,
            sequence=seq,
        )
        if candidate.is_file():
            path = candidate

    if path is None:
        path = find_preview_path(
            job_id,
            slot,
            run_log_dir=run_log_dir,
            site=resolved_site,
            component=resolved_component,
        )

    if not path or not path.is_file():
        raise HTTPException(404, "Preview not found")
    return FileResponse(
        str(path.resolve()),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


class StdinBody(BaseModel):
    text: str = "\n"


class TheoryDecisionBody(BaseModel):
    reason: str = ""


@router.post("/api/jobs/{job_id}/theory/accept")
async def api_accept_enhance_theory(job_id: str):
    ok = await respond_to_enhance_theory(job_id, accept=True)
    if not ok:
        raise HTTPException(400, "Job is not awaiting theory confirmation")
    return {"ok": True}


@router.post("/api/jobs/{job_id}/theory/reject")
async def api_reject_enhance_theory(job_id: str, body: TheoryDecisionBody):
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(422, "Rejection reason is required")
    ok = await respond_to_enhance_theory(job_id, accept=False, reason=reason)
    if not ok:
        raise HTTPException(400, "Job is not awaiting theory confirmation")
    return {"ok": True}


@router.post("/api/jobs/{job_id}/stdin")
async def api_send_stdin(job_id: str, body: StdinBody):
    ok = await send_stdin(job_id, body.text)
    if not ok:
        raise HTTPException(400, "Cannot send stdin")
    return {"ok": True}


@router.delete("/api/jobs/{job_id}")
async def api_cancel_job(job_id: str):
    ok = await cancel_job(job_id)
    if not ok:
        raise HTTPException(400, "Cannot cancel job")
    return {"ok": True}


@router.get("/api/jobs/{job_id}/export-result")
async def api_export_result(job_id: str):
    """Return a structured summary of a completed export job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status not in ("done", "error"):
        raise HTTPException(409, "Job not finished")

    # Parse result lines from output for a structured summary
    created = failed = total = 0
    batches: list[dict] = []
    errors: list[str] = []
    for line in job.output:
        import re as _re2
        m = _re2.search(r"total=(\d+).*?created=(\d+).*?failed=(\d+)", line)
        if m:
            total += int(m.group(1))
            created += int(m.group(2))
            failed += int(m.group(3))
        if line.startswith("[!]"):
            errors.append(line)

    return {
        "status": job.status,
        "total": total,
        "created": created,
        "failed": failed,
        "errors": errors,
    }

