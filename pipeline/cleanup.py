"""Housekeeping helpers for cache and bytecode cleanup."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

# Do not walk package trees inside local virtualenvs / VCS / frontend deps.
_SKIP_DIR_NAMES = frozenset({
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "genbounty-venv",
    "airta-venv",  # legacy local venv name
    ".venv",
    "venv",
    "env",
    ".tox",
    ".nox",
    ".direnv",
})

# Directory basenames removed under the project root (venv trees skipped).
_CACHE_DIR_NAMES = frozenset({
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".pytype",
    ".hypothesis",
    ".cache",
    "htmlcov",
    ".ipynb_checkpoints",
})


def _should_skip_dir(path: Path, root: Path) -> bool:
    """True when ``path`` is under a skipped dependency/VCS tree."""
    try:
        rel_parts = path.resolve().relative_to(root).parts
    except ValueError:
        return True
    return any(part in _SKIP_DIR_NAMES for part in rel_parts)


def _walk_pruned(root: Path):
    """``os.walk`` that never descends into skipped trees."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES]
        yield Path(dirpath), dirnames, filenames


def iter_project_cache_dirs(root: Path, *, names: frozenset[str] | None = None) -> list[Path]:
    """Return matching cache directories under ``root``, deepest-first."""
    root = root.resolve()
    if not root.is_dir():
        return []
    want = names if names is not None else _CACHE_DIR_NAMES
    found: list[Path] = []
    for base, dirnames, _filenames in _walk_pruned(root):
        if base.name in want and not _should_skip_dir(base, root):
            found.append(base)
            dirnames[:] = []
    found.sort(key=lambda p: len(p.parts), reverse=True)
    return found


def _remove_dirs(dirs: list[Path]) -> tuple[dict[str, int], int]:
    counts: dict[str, int] = {}
    failed = 0
    for cache_dir in dirs:
        if not cache_dir.is_dir():
            continue
        try:
            shutil.rmtree(cache_dir)
            counts[cache_dir.name] = counts.get(cache_dir.name, 0) + 1
        except OSError:
            failed += 1
    return counts, failed


def clear_project_dev_caches(root: Path) -> dict[str, int]:
    """Remove project tool/bytecode caches. Returns counts by directory name.

    Skips ``genbounty-venv`` / ``.venv`` / ``node_modules`` / ``.git`` trees.
    """
    counts, failed = _remove_dirs(iter_project_cache_dirs(root))
    if failed:
        counts["_failed"] = failed
    return counts


def clear_project_pycache(root: Path) -> int:
    """Remove ``__pycache__`` directories under ``root`` (venv trees skipped)."""
    counts, _failed = _remove_dirs(
        iter_project_cache_dirs(root, names=frozenset({"__pycache__"}))
    )
    return int(counts.get("__pycache__", 0))
