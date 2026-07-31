"""Shared helpers for payload generators."""
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


STABLE_PAYLOAD_BASENAME = "payload"


def clear_artifact_dir(artifact_dir: Path) -> None:
    """Remove all files in a per-prompt artifact directory."""
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for entry in artifact_dir.iterdir():
        if entry.is_file():
            entry.unlink()


def prune_stale_artifacts(artifact_dir: Path, keep: Path) -> None:
    """Remove other payload files in *artifact_dir*, keeping *keep*."""
    artifact_dir.mkdir(parents=True, exist_ok=True)
    keep_resolved = keep.resolve()
    for entry in artifact_dir.iterdir():
        if entry.is_file() and entry.resolve() != keep_resolved:
            entry.unlink()


def stable_materialize_args(args: dict[str, Any] | None) -> dict[str, Any]:
    """Return generator args using a deterministic payload filename (overwrite on re-run)."""
    out = dict(args or {})
    out.setdefault("filename", STABLE_PAYLOAD_BASENAME)
    return out


def safe_filename(prefix: str = "payload", extension: str = "bin") -> str:
    """Return a safe filename: prefix_timestamp_random.extension (alphanumeric + underscore)."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r"[^\w\-]", "", prefix)[:40] or "payload"
    ext = re.sub(r"[^\w\.]", "", extension).lstrip(".") or "bin"
    return f"{slug}_{ts}.{ext}"


def resolve_output_path(
    filename: Optional[str],
    subdir: str,
    extension: str,
    base_dir: Path,
) -> Path:
    """Resolve output file path: base_dir / subdir / filename (or safe default)."""
    out = base_dir / subdir
    out.mkdir(parents=True, exist_ok=True)
    if filename and filename.strip():
        name = Path(filename).name
        name = re.sub(r"[^\w\.\-]", "_", name) or safe_filename("file", extension)
        if Path(name).suffix:
            ext = Path(name).suffix.lstrip(".").lower()
            if ext != extension.lower():
                name = f"{Path(name).stem}.{extension}"
        elif not name.endswith(f".{extension}"):
            name = f"{name}.{extension}"
    else:
        name = safe_filename("payload", extension)
    return (out / name).resolve()
