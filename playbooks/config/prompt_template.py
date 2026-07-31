"""Optional operator prompt envelope (wrap generated seed blobs)."""
from __future__ import annotations

import re
from typing import Any

from playbooks.config.accessors import get_generation_section
from playbooks.config.constants import _truncate

# Case-insensitive {{input}} / {{prompt}} / {{task}} / {{format}} (optional spaces).
_PROMPT_SLOT_RE = re.compile(
    r"\{\{\s*(input|prompt|task|format)\s*\}\}",
    re.IGNORECASE,
)
_INPUT_SLOT_RE = re.compile(
    r"\{\{\s*(input|prompt)\s*\}\}",
    re.IGNORECASE,
)

PROMPT_TEMPLATE_MAX_CHARS = 4000
PROMPT_SLOT_FIELD_MAX_CHARS = 500


def get_prompt_template(playbook: dict[str, Any] | None) -> str:
    if not isinstance(playbook, dict):
        return ""
    return _truncate(
        str(get_generation_section(playbook).get("prompt_template") or "").strip(),
        PROMPT_TEMPLATE_MAX_CHARS,
    )


def get_prompt_task(playbook: dict[str, Any] | None) -> str:
    if not isinstance(playbook, dict):
        return ""
    return _truncate(
        str(get_generation_section(playbook).get("prompt_task") or "").strip(),
        PROMPT_SLOT_FIELD_MAX_CHARS,
    )


def get_prompt_format(playbook: dict[str, Any] | None) -> str:
    if not isinstance(playbook, dict):
        return ""
    return _truncate(
        str(get_generation_section(playbook).get("prompt_format") or "").strip(),
        PROMPT_SLOT_FIELD_MAX_CHARS,
    )


def prompt_template_has_input_slot(template: str) -> bool:
    """True when template contains ``{{input}}`` or ``{{prompt}}``."""
    return bool(_INPUT_SLOT_RE.search(str(template or "")))


def normalize_prompt_template_fields(
    *,
    prompt_template: Any = None,
    prompt_task: Any = None,
    prompt_format: Any = None,
) -> dict[str, str]:
    """Normalize operator template fields for storage."""
    out: dict[str, str] = {}
    tpl = _truncate(str(prompt_template or "").strip(), PROMPT_TEMPLATE_MAX_CHARS)
    if tpl:
        out["prompt_template"] = tpl
    task = _truncate(str(prompt_task or "").strip(), PROMPT_SLOT_FIELD_MAX_CHARS)
    if task:
        out["prompt_task"] = task
    fmt = _truncate(str(prompt_format or "").strip(), PROMPT_SLOT_FIELD_MAX_CHARS)
    if fmt:
        out["prompt_format"] = fmt
    return out


def apply_prompt_template(text: str, playbook: dict[str, Any] | None) -> str:
    """Wrap a generated seed blob with the play's prompt_template (no-op if unset)."""
    template = get_prompt_template(playbook)
    if not template:
        return str(text or "")
    blob = str(text or "")
    task = get_prompt_task(playbook)
    fmt = get_prompt_format(playbook)

    def _repl(match: re.Match[str]) -> str:
        key = match.group(1).lower()
        if key in ("input", "prompt"):
            return blob
        if key == "task":
            return task
        if key == "format":
            return fmt
        return match.group(0)

    return _PROMPT_SLOT_RE.sub(_repl, template)


def apply_prompt_row_template(
    row: dict[str, Any], playbook: dict[str, Any] | None
) -> dict[str, Any]:
    """Wrap ``prompt`` / message bodies in a prompt row when a template is set."""
    if not get_prompt_template(playbook) or not isinstance(row, dict):
        return row
    out = dict(row)
    if "prompt" in out:
        out["prompt"] = apply_prompt_template(str(out.get("prompt") or ""), playbook)
    messages = out.get("messages")
    if isinstance(messages, list):
        expanded: list[Any] = []
        for msg in messages:
            if isinstance(msg, dict):
                m = dict(msg)
                if "content" in m:
                    m["content"] = apply_prompt_template(
                        str(m.get("content") or ""), playbook
                    )
                if "text" in m:
                    m["text"] = apply_prompt_template(str(m.get("text") or ""), playbook)
                expanded.append(m)
            elif isinstance(msg, str):
                expanded.append(apply_prompt_template(msg, playbook))
            else:
                expanded.append(msg)
        out["messages"] = expanded
    prompts = out.get("prompts")
    if isinstance(prompts, list):
        out["prompts"] = [
            apply_prompt_template(str(p), playbook) if isinstance(p, str) else p
            for p in prompts
        ]
    return out


def apply_prompts_template(
    prompts: list[dict[str, Any]],
    playbook: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Wrap each prompt row with the play's prompt_template."""
    if not get_prompt_template(playbook):
        return list(prompts or [])
    return [
        apply_prompt_row_template(row, playbook) if isinstance(row, dict) else row
        for row in (prompts or [])
    ]
