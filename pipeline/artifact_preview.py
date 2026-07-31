"""Build short injection previews from suite payload specs for assessors."""

from __future__ import annotations

from typing import Any


def _clip(text: str, limit: int = 800) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[:limit] + "\n[truncated]"


def preview_from_payload(payload: dict[str, Any] | None) -> str:
    """Extract hidden/injection text from a materialized or spec payload for judge context."""
    if not isinstance(payload, dict):
        return ""
    args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
    if not args:
        return ""

    parts: list[str] = []
    for key in (
        "hidden_text",
        "hidden_content",
        "subject",
        "author",
        "content",
        "text",
        "data",
        "injection",
    ):
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(f"{key}: {val.strip()}")

    lines = args.get("text_lines")
    if isinstance(lines, list):
        for line in lines:
            if isinstance(line, dict) and line.get("text"):
                parts.append(f"text_line: {line['text']}")

    return _clip("\n".join(parts))


def preview_from_suite_prompt(prompt_row: dict[str, Any] | None) -> str:
    if not isinstance(prompt_row, dict):
        return ""
    payload = prompt_row.get("payload")
    return preview_from_payload(payload if isinstance(payload, dict) else None)
