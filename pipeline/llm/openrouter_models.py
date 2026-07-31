"""Validate OpenRouter model slugs against the live OpenRouter catalog.

Used on Settings → LLM Profiles save (fail-closed when the catalog is reachable)
and at web app startup (fail-closed: unknown slugs or catalog fetch failure abort
boot) so deprecated/removed slugs like ``x-ai/grok-4-fast`` cannot run until fixed.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

_LOG = logging.getLogger(__name__)

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_CACHE_TTL_SEC = 3600.0

_CACHE_LOCK = threading.Lock()
_CACHE_IDS: set[str] | None = None
_CACHE_FETCHED_AT: float = 0.0
_CACHE_ERROR: str | None = None


@dataclass
class OpenRouterValidationResult:
    """Outcome of checking llm.yaml OpenRouter profile models."""

    checked: bool = False
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unknown_models: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "ok": self.ok,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "unknown_models": [dict(row) for row in self.unknown_models],
        }


def reset_openrouter_model_cache() -> None:
    """Test hook: clear the in-process OpenRouter model catalog cache."""
    global _CACHE_IDS, _CACHE_FETCHED_AT, _CACHE_ERROR
    with _CACHE_LOCK:
        _CACHE_IDS = None
        _CACHE_FETCHED_AT = 0.0
        _CACHE_ERROR = None


def _api_key() -> str:
    return (os.getenv("OPENROUTER_API_KEY") or "").strip()


def fetch_openrouter_model_ids(
    *,
    api_key: str | None = None,
    timeout: float = 15.0,
    force: bool = False,
) -> set[str]:
    """Return the set of live OpenRouter model ids (cached ~1h).

    Raises ``RuntimeError`` when the catalog cannot be fetched.
    """
    global _CACHE_IDS, _CACHE_FETCHED_AT, _CACHE_ERROR
    now = time.monotonic()
    with _CACHE_LOCK:
        if (
            not force
            and _CACHE_IDS is not None
            and (now - _CACHE_FETCHED_AT) < _CACHE_TTL_SEC
        ):
            return set(_CACHE_IDS)

    key = (api_key if api_key is not None else _api_key()).strip()
    headers = {
        "Accept": "application/json",
        "User-Agent": "Genbounty-LLM-Hunter/1.0",
    }
    if key:
        headers["Authorization"] = f"Bearer {key}"

    req = urllib.request.Request(OPENROUTER_MODELS_URL, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        raise RuntimeError(
            f"OpenRouter models catalog HTTP {exc.code}: {body or exc.reason}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenRouter models catalog unreachable: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError("OpenRouter models catalog request timed out") from exc

    try:
        import json

        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("OpenRouter models catalog returned invalid JSON") from exc

    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("OpenRouter models catalog missing data[]")

    ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        mid = str(row.get("id") or "").strip()
        if mid:
            ids.add(mid)
    if not ids:
        raise RuntimeError("OpenRouter models catalog returned zero model ids")

    with _CACHE_LOCK:
        _CACHE_IDS = set(ids)
        _CACHE_FETCHED_AT = time.monotonic()
        _CACHE_ERROR = None
    return set(ids)


def collect_openrouter_assignments(
    profiles: dict[str, Any] | None = None,
) -> list[tuple[str, str]]:
    """Return ``(profile_name, model_id)`` for every OpenRouter profile."""
    if profiles is None:
        from pipeline.llm.config import load_llm_yaml

        cfg = load_llm_yaml()
        raw = cfg.get("profiles") if isinstance(cfg.get("profiles"), dict) else {}
    else:
        raw = profiles
    out: list[tuple[str, str]] = []
    if not isinstance(raw, dict):
        return out
    for name, prof in raw.items():
        if not isinstance(prof, dict):
            continue
        provider = str(prof.get("provider") or "").strip().lower()
        if provider != "openrouter":
            continue
        model = str(prof.get("model") or "").strip()
        if not model:
            out.append((str(name), ""))
            continue
        out.append((str(name), model))
    return out


def validate_openrouter_assignments(
    profiles: dict[str, Any] | None = None,
    *,
    catalog: set[str] | None = None,
    require_catalog: bool = False,
    timeout: float = 15.0,
) -> OpenRouterValidationResult:
    """Check OpenRouter profile model ids against the live catalog.

    When ``require_catalog`` is True, catalog fetch failures become errors
    (startup / Settings save when hard-gated). Otherwise they are warnings
    (GET ``/api/llm-config`` status).
    """
    result = OpenRouterValidationResult()
    assignments = collect_openrouter_assignments(profiles)
    if not assignments:
        result.checked = True
        result.ok = True
        return result

    ids = catalog
    if ids is None:
        try:
            ids = fetch_openrouter_model_ids(timeout=timeout)
        except Exception as exc:
            msg = str(exc)
            if require_catalog:
                result.checked = False
                result.ok = False
                result.errors.append(
                    "Could not verify OpenRouter model ids "
                    f"(catalog fetch failed: {msg}). Fix network/OPENROUTER_API_KEY "
                    "or retry; refusing to save unverified OpenRouter profiles."
                )
            else:
                result.checked = False
                result.ok = True
                result.warnings.append(
                    f"OpenRouter model catalog unavailable ({msg}); "
                    "skipped live slug validation."
                )
            return result

    result.checked = True
    for name, model in assignments:
        if not model:
            result.ok = False
            err = f"OpenRouter profile {name!r} has an empty model id"
            result.errors.append(err)
            result.unknown_models.append({"profile": name, "model": ""})
            continue
        if model not in ids:
            result.ok = False
            err = (
                f"OpenRouter profile {name!r} model {model!r} is not in the "
                "live OpenRouter catalog (removed, renamed, or deprecated). "
                "Update llm.yaml / Settings → LLM Profiles."
            )
            result.errors.append(err)
            result.unknown_models.append({"profile": name, "model": model})
    return result


def format_openrouter_startup_failure(result: OpenRouterValidationResult) -> str:
    """Human-readable multi-line message for a failed OpenRouter model check."""
    lines = [
        "OpenRouter model validation failed - refusing to start.",
        "Fix provider: openrouter model ids in llm.yaml (or Settings → Configure LLMs),",
        "then restart. Live catalog: https://openrouter.ai/api/v1/models",
        "",
    ]
    for err in result.errors:
        lines.append(f"  • {err}")
    for warn in result.warnings:
        lines.append(f"  • {warn}")
    if result.unknown_models:
        lines.append("")
        lines.append("Unknown profile → model:")
        for row in result.unknown_models:
            lines.append(f"  • {row.get('profile', '?')}: {row.get('model', '')!r}")
    return "\n".join(lines)


def require_valid_openrouter_models(*, timeout: float = 15.0) -> OpenRouterValidationResult:
    """Startup gate: abort if any OpenRouter profile model is missing from the catalog.

    Always fetches the live catalog when OpenRouter profiles exist. Raises
    ``RuntimeError`` with a clear message on unknown/empty slugs or catalog
    fetch failure. Never raises when there are no OpenRouter profiles.
    """
    try:
        result = validate_openrouter_assignments(require_catalog=True, timeout=timeout)
    except Exception as exc:
        msg = (
            "OpenRouter model validation failed - refusing to start.\n"
            f"  • Unexpected error during catalog check: {exc}"
        )
        print(f"[llm] {msg}", flush=True)
        _LOG.error(msg)
        raise RuntimeError(msg) from exc

    if not result.ok or result.errors:
        msg = format_openrouter_startup_failure(result)
        print(f"[llm] {msg}", flush=True)
        _LOG.error(msg)
        raise RuntimeError(msg)

    for line in result.warnings:
        print(f"[llm] {line}", flush=True)
        _LOG.warning(line)
    if result.checked and collect_openrouter_assignments():
        print("[llm] OpenRouter profile model ids match the live catalog.", flush=True)
    return result


def warn_invalid_openrouter_models(*, timeout: float = 10.0) -> OpenRouterValidationResult:
    """Soft check: log unknown OpenRouter slugs; never raises (GET status / tests)."""
    try:
        result = validate_openrouter_assignments(require_catalog=False, timeout=timeout)
    except Exception as exc:
        _LOG.warning("OpenRouter model validation skipped: %s", exc)
        out = OpenRouterValidationResult(checked=False, ok=True)
        out.warnings.append(str(exc))
        return out
    for line in result.warnings:
        print(f"[llm] {line}", flush=True)
        _LOG.warning(line)
    for line in result.errors:
        print(f"[llm] WARNING: {line}", flush=True)
        _LOG.warning(line)
    if result.checked and result.ok and collect_openrouter_assignments():
        print("[llm] OpenRouter profile model ids match the live catalog.", flush=True)
    return result
