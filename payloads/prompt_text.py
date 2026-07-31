"""Plain-text prompt normalization for UI submit harnesses."""
from __future__ import annotations

from typing import Any

from payloads.text_utils import normalize_prompt_text

__all__ = ["normalize_prompt_text", "normalize_prompt_row", "normalize_prompt_rows"]


def normalize_prompt_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a suite prompt row with single-line prompt strings."""
    if not isinstance(row, dict):
        return row
    out = dict(row)
    if "prompt" in out and out["prompt"] is not None:
        out["prompt"] = normalize_prompt_text(str(out["prompt"]))
    prompts = out.get("prompts")
    if isinstance(prompts, list):
        out["prompts"] = [
            normalize_prompt_text(str(p)) if p is not None else ""
            for p in prompts
        ]
    return out


def normalize_prompt_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalize_prompt_row(r) for r in rows if isinstance(r, dict)]
