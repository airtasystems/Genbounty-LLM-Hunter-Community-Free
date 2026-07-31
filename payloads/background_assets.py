"""Resolve stock background PDFs and images from repo assets/ for multimodal tests."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

_REPO_ROOT = Path(__file__).resolve().parent.parent

_PDF_DIRS = (
    _REPO_ROOT / "assets" / "background-pdf",
    _REPO_ROOT / "assets" / "Background-pdf",
)
_IMAGE_DIRS = (
    _REPO_ROOT / "assets" / "background-img",
)


def _find_in_dirs(name: str, dirs: tuple[Path, ...]) -> Path | None:
    stem = Path(name).name
    if not stem:
        return None
    for directory in dirs:
        if not directory.is_dir():
            continue
        direct = directory / stem
        if direct.is_file():
            return direct.resolve()
        lower = stem.lower()
        for candidate in directory.iterdir():
            if candidate.is_file() and candidate.name.lower() == lower:
                return candidate.resolve()
    return None


def list_background_pdfs() -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for directory in _PDF_DIRS:
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.is_file() and path.suffix.lower() == ".pdf":
                if path.name not in seen:
                    seen.add(path.name)
                    names.append(path.name)
    return names


def list_background_images() -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for directory in _IMAGE_DIRS:
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                if path.name not in seen:
                    seen.add(path.name)
                    names.append(path.name)
    return names


def resolve_background_pdf(filename: str) -> Path:
    path = _find_in_dirs(filename, _PDF_DIRS)
    if path is None:
        raise FileNotFoundError(
            f"Background PDF not found: {filename!r} (searched {[str(d) for d in _PDF_DIRS]})"
        )
    return path


def resolve_background_image(filename: str) -> Path:
    path = _find_in_dirs(filename, _IMAGE_DIRS)
    if path is None:
        raise FileNotFoundError(
            f"Background image not found: {filename!r} (searched {[str(d) for d in _IMAGE_DIRS]})"
        )
    return path


def resolve_background_asset(
    filename: str,
    kind: Literal["pdf", "image"] | None = None,
) -> Path:
    """Resolve by extension or explicit kind."""
    if kind == "pdf":
        return resolve_background_pdf(filename)
    if kind == "image":
        return resolve_background_image(filename)
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return resolve_background_pdf(filename)
    if ext in {".jpg", ".jpeg", ".png", ".webp"}:
        return resolve_background_image(filename)
    raise ValueError(f"Cannot infer background asset kind for {filename!r}")
