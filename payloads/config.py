"""
Payloads output directory from pipeline settings (Settings → Pipeline).
Project root = parent of payloads package. No Flask coupling.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator

# Genbounty repo root (parent of payloads package)
_ROOT = Path(__file__).resolve().parent.parent
_OUTPUT_OVERRIDE: ContextVar[Path | None] = ContextVar("payloads_output_override", default=None)


def get_output_dir() -> Path:
    """
    Directory for generated payload assets.

    Configured in Settings → Pipeline (``pipeline_settings.yaml``).
    Callers may temporarily redirect via :func:`temporary_output_dir`.
    Creates the directory if it does not exist.
    """
    override = _OUTPUT_OVERRIDE.get()
    if override is not None:
        override.mkdir(parents=True, exist_ok=True)
        return override.resolve()

    from pipeline.pipeline_settings import payloads_output_dir

    return payloads_output_dir()


@contextmanager
def temporary_output_dir(path: Path | str) -> Iterator[Path]:
    """Redirect :func:`get_output_dir` for the current context only."""
    target = Path(path).resolve()
    target.mkdir(parents=True, exist_ok=True)
    token = _OUTPUT_OVERRIDE.set(target)
    try:
        yield target
    finally:
        _OUTPUT_OVERRIDE.reset(token)


def get_project_root() -> Path:
    """Project root (parent of payloads package)."""
    return _ROOT
