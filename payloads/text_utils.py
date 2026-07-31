"""Shared non-LLM string cleanup for prompts, JSON parsing, and suite transforms."""

from __future__ import annotations

import json
import re
from typing import Any


def normalize_prompt_text(text: str, *, collapse_newlines: bool = True) -> str:
    """Normalize prompt whitespace.

    By default collapses newlines to spaces (browser text-field fill). Pass
    ``collapse_newlines=False`` to keep line structure for acrostics / fences /
    delivery-encoding payloads while still trimming per-line spaces.
    """
    if not text:
        return ""
    raw = str(text)
    if collapse_newlines:
        collapsed = re.sub(r"[\r\n]+", " ", raw)
        return re.sub(r" +", " ", collapsed).strip()
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in normalized.split("\n")]
    return "\n".join(lines).strip()


def strip_json_markdown(text: str) -> str:
    text = text.strip()
    for pattern in (r"^```json\s*", r"^```\s*"):
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def fix_invalid_json_escapes(text: str) -> str:
    return text.replace("\\'", "'")


def _extract_json_array_candidate(text: str) -> str:
    """Prefer fenced JSON arrays; else first balanced ``[...]`` span."""
    raw = strip_json_markdown(text)
    fence = re.search(r"```(?:json)?\s*(\[[\s\S]*\])\s*```", raw, flags=re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    start = raw.find("[")
    if start < 0:
        return raw
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return raw[start : i + 1]
    # Fallback: greedy last-bracket slice (legacy behavior).
    end = raw.rfind("]")
    if end > start:
        return raw[start : end + 1]
    return raw


def _raw_decode_first_json_value(text: str) -> Any | None:
    """Return the first JSON object/array value found in ``text``, else None."""
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch not in "{[":
            continue
        try:
            value, _ = decoder.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, (dict, list)):
            return value
    return None


def _coerce_array_items(parsed: list[Any], expected: int, *, context: str) -> list[Any]:
    if expected == 1 and len(parsed) > 1:
        parsed = parsed[:1]
    if len(parsed) != expected:
        raise ValueError(f"Expected {expected} strings, got {len(parsed)}")
    return parsed


def _repair_unescaped_object_string_array(raw: str, expected: int) -> list[Any] | None:
    """Recover ``["{...}"]`` / ``["[...]"]`` where the model forgot to escape quotes.

    Grok often wraps a peer-packet object in quotes without escaping inner ``"``,
    which yields ``Expecting ',' delimiter: line 1 column 5 (char 4)`` on
    ``["{"key":...}"]``.
    """
    text = raw.strip()
    if not (text.startswith("[") and text.endswith("]")):
        return None
    # Single-item broken quote wrap: ["{...}"] or ["[...]"]
    if expected == 1 and (
        (text.startswith('["{') and text.endswith('}"]'))
        or (text.startswith('["[') and text.endswith(']"]'))
    ):
        inner = text[2:-2]
        try:
            value = json.loads(inner)
        except json.JSONDecodeError:
            value = _raw_decode_first_json_value(inner)
        if isinstance(value, (dict, list, str)):
            return [value]
    # Prefer the first balanced object/array inside the broken payload.
    if expected == 1:
        value = _raw_decode_first_json_value(text)
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list) and value and not (
            len(value) == 1 and isinstance(value[0], str) and str(value[0]).startswith("{")
        ):
            return value
    return None


def parse_llm_json_string_array(
    text: str,
    expected: int,
    *,
    context: str = "LLM",
    collapse_newlines: bool = True,
) -> list[str]:
    """Parse a JSON string array from Gemini-style output (optional markdown fence).

    Array items may be strings or JSON objects/arrays (common when the rewriter
    emits machine/agentic graphs). Non-strings are coerced via ``json.dumps``.

    Also recovers a common Grok failure mode where a JSON object is wrapped as
    ``["{...}"]`` without escaping inner quotes, and bare single objects when
    ``expected == 1``.
    """
    raw = (text or "").strip()
    if not raw:
        raise ValueError(f"{context} returned empty response")

    candidate = _extract_json_array_candidate(raw)
    parsed: Any = None
    err: Exception | None = None
    for attempt in (
        candidate,
        fix_invalid_json_escapes(candidate),
    ):
        try:
            parsed = json.loads(attempt)
            break
        except json.JSONDecodeError as exc:
            err = exc
            repaired = _repair_unescaped_object_string_array(attempt, expected)
            if repaired is not None:
                parsed = repaired
                break
    if parsed is None:
        # Bare object / array when the model omitted the outer string-array wrapper.
        if expected == 1:
            recovered = _raw_decode_first_json_value(strip_json_markdown(raw))
            if isinstance(recovered, dict):
                parsed = [recovered]
            elif isinstance(recovered, list):
                parsed = recovered
        if parsed is None:
            raise ValueError(
                f"{context} returned invalid JSON"
                + (f": {err}" if err else "")
            ) from err

    if isinstance(parsed, dict) and expected == 1:
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise ValueError(f"{context} response must be a JSON array")

    parsed = _coerce_array_items(parsed, expected, context=context)
    out: list[str] = []
    for item in parsed:
        if isinstance(item, str):
            # Second chance: string that is itself a JSON object/array literal.
            stripped = item.strip()
            if stripped[:1] in "{[":
                try:
                    nested = json.loads(stripped)
                except json.JSONDecodeError:
                    nested = None
                if isinstance(nested, (dict, list)):
                    line = json.dumps(nested, ensure_ascii=False, separators=(",", ":"))
                else:
                    line = item
            else:
                line = item
        elif isinstance(item, (dict, list)):
            line = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        else:
            raise ValueError("Each item must be a string")
        line = normalize_prompt_text(line, collapse_newlines=collapse_newlines)
        if not line:
            raise ValueError(f"{context} returned an empty string")
        out.append(line)
    return out
