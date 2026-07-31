"""SPA helpers: cached static files and index.html assembly from partials."""

from __future__ import annotations

import os
import re as _re
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from web.paths import STATIC_DIR

router = APIRouter()


class CachedStaticFiles(StaticFiles):
    """StaticFiles that adds a long Cache-Control for immutable image assets."""

    def __init__(self, *args, cache_control: str, **kwargs):
        super().__init__(*args, **kwargs)
        self._cache_control = cache_control

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers.setdefault("Cache-Control", self._cache_control)
        return resp


_PARTIALS_DIR = STATIC_DIR / "partials"
_INDEX_TEMPLATE = STATIC_DIR / "index.template.html"
_INCLUDE_RE = _re.compile(r"<!--\s*@include\s+([\w./-]+)\s*-->")
_index_cache: str | None = None
_index_cache_mtime: float = 0.0


def _index_sources_mtime() -> float:
    """Newest mtime across the template, partials, and cache-busted static assets.

    JS/CSS must be included so editing ``web/static/js/*`` invalidates the assembled
    HTML (and its ``?v=`` query strings). Otherwise browsers keep stale module URLs.
    """
    newest = _INDEX_TEMPLATE.stat().st_mtime if _INDEX_TEMPLATE.is_file() else 0.0
    if _PARTIALS_DIR.is_dir():
        for path in _PARTIALS_DIR.rglob("*"):
            if path.is_file():
                newest = max(newest, path.stat().st_mtime)
    for name in ("style.css", "app.js", "payload-editor.js"):
        path = STATIC_DIR / name
        if path.is_file():
            newest = max(newest, path.stat().st_mtime)
    js_dir = STATIC_DIR / "js"
    if js_dir.is_dir():
        for path in js_dir.rglob("*.js"):
            newest = max(newest, path.stat().st_mtime)
    return newest


def _resolve_includes(path: Path, seen: set[Path]) -> str:
    real = path.resolve()
    allowed = real == _INDEX_TEMPLATE.resolve() or _PARTIALS_DIR.resolve() in real.parents
    if not allowed:
        raise RuntimeError(f"illegal include outside partials/: {path}")
    if real in seen:
        raise RuntimeError(f"circular include: {path}")
    seen.add(real)
    text = real.read_text(encoding="utf-8")
    return _INCLUDE_RE.sub(
        lambda m: _resolve_includes(_PARTIALS_DIR / m.group(1), set(seen)),
        text,
    )


def _build_index() -> str:
    html = _resolve_includes(_INDEX_TEMPLATE, set())
    # Bust browser caches for JS/CSS whenever those files change.
    bust_names = ["style.css", "app.js", "payload-editor.js"]
    js_dir = STATIC_DIR / "js"
    if js_dir.is_dir():
        bust_names.extend(
            sorted(f"js/{p.relative_to(js_dir).as_posix()}" for p in js_dir.rglob("*.js"))
        )
    for name in bust_names:
        path = STATIC_DIR / name
        if path.is_file():
            ver = str(int(path.stat().st_mtime))
            html = html.replace(f"/static/{name}", f"/static/{name}?v={ver}")
    return html


@router.get("/", response_class=HTMLResponse)
def index():
    global _index_cache, _index_cache_mtime
    if os.environ.get("GENBOUNTY_DEV_NO_CACHE"):
        return HTMLResponse(_build_index(), headers={"Cache-Control": "no-store"})
    newest = _index_sources_mtime()
    if _index_cache is None or newest > _index_cache_mtime:
        _index_cache = _build_index()
        _index_cache_mtime = newest
    return HTMLResponse(_index_cache, headers={"Cache-Control": "no-store"})

