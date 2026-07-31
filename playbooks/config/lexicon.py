"""Objective lexicon normalize / expand / wrap helpers."""
from __future__ import annotations

import re
from typing import Any

from playbooks.config.accessors import get_generation_section
from playbooks.config.constants import (
    OBJECTIVE_LEXICON_KEY_RE,
    OBJECTIVE_LEXICON_MAX_KEYS,
    OBJECTIVE_LEXICON_TOKEN_RE,
    _truncate,
)

def get_attack_objective(playbook: dict[str, Any] | None) -> str:
    """Attack objective template for generation LLMs (bare lexicon keys wrapped as ``{{KEY}}``).

    Sensitive lexicon *values* stay out of this string. Use
    :func:`get_attack_objective_expanded` for fidelity, suite stamps, and anything
    sent to the target under test.
    """
    if not isinstance(playbook, dict):
        return ""
    raw = _truncate(str(get_generation_section(playbook).get("attack_objective") or "").strip(), 800)
    if not raw:
        return ""
    return wrap_bare_lexicon_keys(raw, get_objective_lexicon(playbook))


def normalize_objective_text(text: str) -> str:
    """Normalize attack_objective for equality checks across playbook and suite stamps."""
    return " ".join(str(text or "").strip().lower().split())


def normalize_objective_lexicon(raw: Any) -> dict[str, str]:
    """Normalize lexicon from JSON object or ``KEY=value`` lines into a stable map."""
    out: dict[str, str] = {}
    if isinstance(raw, dict):
        items = list(raw.items())
    elif isinstance(raw, str):
        items = []
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            items.append((key.strip(), value.strip()))
    elif isinstance(raw, list):
        items = []
        for row in raw:
            if isinstance(row, dict):
                key = str(row.get("key") or row.get("name") or "").strip()
                value = str(row.get("value") or row.get("term") or "").strip()
                if key:
                    items.append((key, value))
            elif isinstance(row, str) and "=" in row:
                key, _, value = row.partition("=")
                items.append((key.strip(), value.strip()))
    else:
        return out

    for key_raw, value_raw in items:
        key = str(key_raw or "").strip().upper()
        value = str(value_raw or "").strip()
        if not key or not value:
            continue
        if not OBJECTIVE_LEXICON_KEY_RE.match(key):
            continue
        if "{{" in value:
            continue
        if key not in out:
            out[key] = value
        if len(out) >= OBJECTIVE_LEXICON_MAX_KEYS:
            break
    return out


def get_objective_lexicon(playbook: dict[str, Any] | None) -> dict[str, str]:
    """Placeholder key → real term map from ``generation.objective_lexicon``."""
    if not isinstance(playbook, dict):
        return {}
    return normalize_objective_lexicon(get_generation_section(playbook).get("objective_lexicon"))


def expand_lexicon_text(text: str, lexicon: dict[str, str] | None) -> str:
    """Replace lexicon placeholders with real terms.

    Matches both ``{{KEY}}`` and bare ``KEY`` tokens (whole-token, longest keys
    first). Generation models often drop the braces and emit ``V1 N1``; both forms
    must expand before fidelity / suite write / target send.
    """
    source = str(text or "")
    if not source or not lexicon:
        return source

    def _braced_repl(match: re.Match[str]) -> str:
        key = match.group(1)
        return lexicon.get(key, match.group(0))

    out = OBJECTIVE_LEXICON_TOKEN_RE.sub(_braced_repl, source)
    # Bare KEY (e.g. "V1") - avoid matching inside already-expanded words or leftovers.
    for key in sorted(lexicon.keys(), key=len, reverse=True):
        value = lexicon[key]
        out = re.sub(
            rf"(?<![A-Za-z0-9_{{]){re.escape(key)}(?![A-Za-z0-9_}}])",
            value,
            out,
        )
    return out


def wrap_bare_lexicon_keys(text: str, lexicon: dict[str, str] | None) -> str:
    """Rewrite bare lexicon KEY tokens as ``{{KEY}}`` (idempotent for braced form)."""
    source = str(text or "")
    if not source or not lexicon:
        return source
    out = source
    for key in sorted(lexicon.keys(), key=len, reverse=True):
        # Skip spans already written as {{KEY}}.
        out = re.sub(
            rf"(?<!\{{\{{)(?<![A-Za-z0-9_]){re.escape(key)}(?![A-Za-z0-9_])(?!\}}\}})",
            f"{{{{{key}}}}}",
            out,
        )
    return out


def get_attack_objective_expanded(playbook: dict[str, Any] | None) -> str:
    """Attack objective with lexicon tokens expanded (for fidelity / suite stamp)."""
    return expand_lexicon_text(get_attack_objective(playbook), get_objective_lexicon(playbook))


def canonicalize_attack_objective_tokens(playbook: dict[str, Any] | None) -> str:
    """Return attack_objective with bare lexicon keys wrapped as ``{{KEY}}``."""
    return wrap_bare_lexicon_keys(get_attack_objective(playbook), get_objective_lexicon(playbook))


def expand_prompt_row_lexicon(row: dict[str, Any], lexicon: dict[str, str]) -> dict[str, Any]:
    """Expand lexicon tokens in a prompt row's ``prompt``, description, and messages."""
    if not lexicon or not isinstance(row, dict):
        return row
    out = dict(row)
    for field in ("prompt", "description"):
        if field in out:
            out[field] = expand_lexicon_text(str(out.get(field) or ""), lexicon)
    messages = out.get("messages")
    if isinstance(messages, list):
        expanded_msgs: list[Any] = []
        for msg in messages:
            if isinstance(msg, dict):
                m = dict(msg)
                if "content" in m:
                    m["content"] = expand_lexicon_text(str(m.get("content") or ""), lexicon)
                if "text" in m:
                    m["text"] = expand_lexicon_text(str(m.get("text") or ""), lexicon)
                expanded_msgs.append(m)
            elif isinstance(msg, str):
                expanded_msgs.append(expand_lexicon_text(msg, lexicon))
            else:
                expanded_msgs.append(msg)
        out["messages"] = expanded_msgs
    prompts = out.get("prompts")
    if isinstance(prompts, list):
        out["prompts"] = [
            expand_lexicon_text(str(p), lexicon) if isinstance(p, str) else p for p in prompts
        ]
    return out


def expand_prompts_lexicon(
    prompts: list[dict[str, Any]],
    playbook: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Expand lexicon tokens across a batch of prompt rows."""
    lexicon = get_objective_lexicon(playbook)
    if not lexicon:
        return list(prompts or [])
    return [expand_prompt_row_lexicon(row, lexicon) if isinstance(row, dict) else row for row in (prompts or [])]


def expand_lexicon_in_value(value: Any, lexicon: dict[str, str] | None) -> Any:
    """Recursively expand ``{{KEY}}`` tokens in strings inside nested dict/list structures."""
    if not lexicon:
        return value
    if isinstance(value, str):
        return expand_lexicon_text(value, lexicon)
    if isinstance(value, list):
        return [expand_lexicon_in_value(item, lexicon) for item in value]
    if isinstance(value, dict):
        return {k: expand_lexicon_in_value(v, lexicon) for k, v in value.items()}
    return value


