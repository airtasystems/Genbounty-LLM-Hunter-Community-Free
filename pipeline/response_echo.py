"""Strip echoed user prompts and UI role markers from captured model responses."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from browser_bot.submit.response_filters import ResponseFilterContext


def _filters():
    from browser_bot.submit.response_filters import (
        ResponseFilterContext,
        sanitize_captured_response,
        strip_leading_role_markers,
    )

    return ResponseFilterContext, sanitize_captured_response, strip_leading_role_markers


def strip_echoed_prompt_from_response(response: str | None, prompt: str) -> str | None:
    """Remove a leading copy of ``prompt`` and common UI role labels from ``response``."""
    ResponseFilterContext, sanitize_captured_response, _ = _filters()
    ctx = ResponseFilterContext(prompt=(prompt or "").strip())
    return sanitize_captured_response(response, ctx)


def strip_leading_role_markers(text: str) -> str:
    """Remove bracket/plain role prefixes repeatedly from the start."""
    _, _, strip_fn = _filters()
    return strip_fn(text)


def sanitize_run_log(data: dict) -> dict:
    """Return a copy of run_log JSON with echoed prompts removed from responses."""
    if not isinstance(data, dict):
        return data
    out = dict(data)
    entries = out.get("entries")
    if isinstance(entries, list):
        cleaned_entries = []
        for entry in entries:
            if not isinstance(entry, dict):
                cleaned_entries.append(entry)
                continue
            row = dict(entry)
            row["response"] = strip_echoed_prompt_from_response(
                entry.get("response"), str(entry.get("input") or "")
            )
            cleaned_entries.append(row)
        out["entries"] = cleaned_entries

    batches = out.get("batches")
    if isinstance(batches, list):
        cleaned_batches = []
        for batch in batches:
            if not isinstance(batch, dict):
                cleaned_batches.append(batch)
                continue
            batch_row = dict(batch)
            turns = batch.get("turns")
            if isinstance(turns, list):
                batch_row["turns"] = []
                for turn in turns:
                    if not isinstance(turn, dict):
                        batch_row["turns"].append(turn)
                        continue
                    turn_row = dict(turn)
                    turn_row["response"] = strip_echoed_prompt_from_response(
                        turn.get("response"), str(turn.get("input") or "")
                    )
                    batch_row["turns"].append(turn_row)
            cleaned_batches.append(batch_row)
        out["batches"] = cleaned_batches
    return out
