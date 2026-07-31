"""Genbounty LLM Hunter - FastAPI backend entrypoint."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# start.py execs this file as a script (python web/app.py), so sys.path has
# web/ rather than the repo root - add the root before any `web.*` imports.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from web.paths import IMG_DIR, STATIC_DIR  # noqa: F401 - also bootstraps BB_DIR
from web.port_reclaim import _port_holder_hint, ensure_preferred_port
from web.spa import CachedStaticFiles, router as spa_router
from web.routers import (
    jobs_api,
    logs_network,
    operator,
    payloads,
    playbooks,
    settings,
    sites,
    target_data,
    tests,
)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Fail-closed: unknown/deprecated OpenRouter slugs (or catalog unreachable) abort boot.
    from pipeline.llm.openrouter_models import require_valid_openrouter_models

    require_valid_openrouter_models()
    yield


app = FastAPI(title="Genbounty LLM Hunter", docs_url="/api/docs", lifespan=_lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# /static keeps StaticFiles' default ETag/304 revalidation (unhashed JS/CSS must
# not be cached long, or clients would serve stale app code).
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
if IMG_DIR.is_dir():
    app.mount(
        "/img",
        CachedStaticFiles(directory=str(IMG_DIR), cache_control="public, max-age=86400"),
        name="img",
    )

app.include_router(spa_router)
app.include_router(sites.router)
app.include_router(target_data.router)
app.include_router(payloads.router)
app.include_router(playbooks.router)
app.include_router(tests.router)
app.include_router(logs_network.router)
app.include_router(settings.router)
app.include_router(jobs_api.router)
app.include_router(operator.router)


if __name__ == "__main__":
    import uvicorn

    host = "127.0.0.1"
    preferred_port = int(os.getenv("PORT", "8000"))
    port = ensure_preferred_port(host, preferred_port)
    if port != preferred_port:
        print(f"Port {preferred_port} is in use; starting on {port} instead.")
        print(_port_holder_hint(preferred_port))
        print(
            "Another non-Genbounty process still owns the preferred port. "
            "Stop it, or set PORT=… to choose a free port."
        )
    reload = os.getenv("GENBOUNTY_DEV_RELOAD", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if reload:
        print("Dev reload enabled (GENBOUNTY_DEV_RELOAD).")
    uvicorn.run(
        "web.app:app",
        host=host,
        port=port,
        reload=reload,
        timeout_graceful_shutdown=5,
    )
