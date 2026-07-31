"""Ordered operator transform pipeline for Generate & Enhance auto-apply.

Unlike ``*_suite`` helpers (each rewrites from the plain-English backup and
clears sibling metadata) and ``GENBOUNTY_GEN_TRANSFORMS`` (which appends
variants), this module stacks selected transforms on live prompt text in order.
"""

from __future__ import annotations

import copy
import json
import os
from typing import Any, Callable

from prompt_suite_backup import (
    ATTRIBUTES_KEY,
    CIPHER_KEY,
    CODE_KEY,
    CONTROL_CODE_KEY,
    EMOTION_KEY,
    FRAME_KEY,
    IQ_KEY,
    NATIVE_KEY,
    PIPELINE_KEY,
    TECHNIQUE_KEY,
    TRANSLATION_KEY,
    capture_plain_source,
)

_VALID_KINDS = (
    "obfuscation",
    "translation",
    "native",
    "frame",
    "code_embed",
    "cipher",
    "control_code",
    "iq",
    "emotion",
)


def _env_flag_enabled(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


def normalize_pipeline_steps(raw: Any) -> list[dict[str, str]]:
    """Return cleaned ``[{kind, name}, ...]`` steps; drop invalid entries."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind") or "").strip().lower()
        name = str(row.get("name") or "").strip()
        if kind not in _VALID_KINDS or not name:
            continue
        if kind in ("iq", "emotion"):
            try:
                int(name)
            except (TypeError, ValueError):
                continue
        else:
            name = name.lower()
        out.append({"kind": kind, "name": name})
    return out


def load_gen_transform_pipeline_from_env() -> list[dict[str, str]] | None:
    """Load ordered steps when ``GENBOUNTY_GEN_TRANSFORM_PIPELINE=1``."""
    if not _env_flag_enabled("GENBOUNTY_GEN_TRANSFORM_PIPELINE"):
        return None
    raw = (os.getenv("GENBOUNTY_GEN_TRANSFORM_PIPELINE_JSON") or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    steps = normalize_pipeline_steps(data)
    return steps or None


def _text_transformer(kind: str, name: str) -> Callable[[str], str] | None:
    """Return a single-string transform fn, including IQ / emotion levels."""
    try:
        if kind == "translation":
            from prompt_translation import UI_LANGUAGES, translate_texts

            if name not in UI_LANGUAGES:
                return None
            return lambda text: (translate_texts([text], name) or [text])[0]
        if kind == "native":
            from prompt_native import UI_NATIVE_LANGUAGES, rewrite_texts

            if name not in UI_NATIVE_LANGUAGES:
                return None
            return lambda text: (rewrite_texts([text], name) or [text])[0]
        if kind == "frame":
            from prompt_frame import UI_FRAME_TECHNIQUES, rewrite_texts as frame_rewrite_texts

            if name not in UI_FRAME_TECHNIQUES:
                return None
            return lambda text: (frame_rewrite_texts([text], name) or [text])[0]
        if kind == "cipher":
            from prompt_cipher import UI_CIPHERS, cipher_text

            if name not in UI_CIPHERS:
                return None
            return lambda text: cipher_text(text, name)
        if kind == "obfuscation":
            from prompt_obfuscation import UI_TECHNIQUES, obfuscate_text

            if name not in UI_TECHNIQUES:
                return None
            return lambda text: obfuscate_text(text, name)
        if kind == "code_embed":
            from prompt_code_embed import UI_CODE_LANGUAGES, code_embed_text

            if name not in UI_CODE_LANGUAGES:
                return None
            return lambda text: code_embed_text(text, name)
        if kind == "control_code":
            from prompt_control_code import UI_CONTROL_CODES, control_code_text

            if name not in UI_CONTROL_CODES:
                return None
            return lambda text: control_code_text(text, name)
        if kind == "iq":
            from prompt_iq import normalize_iq, rewrite_texts_for_iq

            level = normalize_iq(int(name))
            return lambda text, _level=level: (rewrite_texts_for_iq([text], _level) or [text])[0]
        if kind == "emotion":
            from prompt_emotion import normalize_emotion, rewrite_texts_for_emotion

            level = normalize_emotion(int(name))
            return lambda text, _level=level: (
                rewrite_texts_for_emotion([text], _level) or [text]
            )[0]
    except Exception:
        return None
    return None


def _stamp_step(prompt: dict[str, Any], kind: str, name: str) -> None:
    if kind == "obfuscation":
        prompt[TECHNIQUE_KEY] = name
    elif kind == "translation":
        prompt[TRANSLATION_KEY] = name
    elif kind == "native":
        prompt[NATIVE_KEY] = name
    elif kind == "frame":
        prompt[FRAME_KEY] = name
    elif kind == "code_embed":
        prompt[CODE_KEY] = name
    elif kind == "cipher":
        prompt[CIPHER_KEY] = name
    elif kind == "control_code":
        prompt[CONTROL_CODE_KEY] = name
    elif kind == "iq":
        prompt[IQ_KEY] = int(name)
    elif kind == "emotion":
        prompt[EMOTION_KEY] = int(name)


def _transform_live_fields(prompt: dict[str, Any], transform: Callable[[str], str]) -> int:
    """Apply ``transform`` to live prompt / turns / examples. Returns fields changed."""
    changed = 0
    if isinstance(prompt.get("prompt"), str) and prompt["prompt"].strip():
        try:
            out = (transform(prompt["prompt"]) or "").strip()
        except Exception:
            out = ""
        if out and out != prompt["prompt"]:
            prompt["prompt"] = out
            changed += 1

    if isinstance(prompt.get("prompts"), list):
        for i, turn in enumerate(prompt["prompts"]):
            if not isinstance(turn, str) or not turn.strip():
                continue
            try:
                out = (transform(turn) or "").strip()
            except Exception:
                continue
            if out and out != turn:
                prompt["prompts"][i] = out
                changed += 1

    if isinstance(prompt.get("examples"), list):
        for ex in prompt["examples"]:
            if not isinstance(ex, dict):
                continue
            src = ex.get("prompt")
            if not isinstance(src, str) or not src.strip():
                continue
            try:
                out = (transform(src) or "").strip()
            except Exception:
                continue
            if out and out != src:
                ex["prompt"] = out
                changed += 1
    return changed


def apply_gen_transform_pipeline(
    data: dict[str, Any],
    steps: list[dict[str, str]] | None,
) -> tuple[dict[str, Any], int]:
    """Stack ``steps`` on every text prompt in order. Returns ``(suite, fields_changed)``."""
    steps = normalize_pipeline_steps(steps)
    if not steps:
        return copy.deepcopy(data), 0

    transformers: list[tuple[str, str, Callable[[str], str]]] = []
    for step in steps:
        fn = _text_transformer(step["kind"], step["name"])
        if fn is not None:
            transformers.append((step["kind"], step["name"], fn))
    if not transformers:
        return copy.deepcopy(data), 0

    suite = copy.deepcopy(data)
    total = 0
    applied_kinds = [{"kind": k, "name": n} for k, n, _ in transformers]

    for cat in suite.get("categories") or []:
        if not isinstance(cat, dict):
            continue
        for prompt in cat.get("prompts") or []:
            if not isinstance(prompt, dict):
                continue
            # Seed plain backup once so Restore English still works after stacking.
            capture_plain_source(prompt)
            prompt_changed = 0
            for kind, name, fn in transformers:
                n = _transform_live_fields(prompt, fn)
                if n:
                    _stamp_step(prompt, kind, name)
                    prompt_changed += n
            if prompt_changed:
                prompt[PIPELINE_KEY] = list(applied_kinds)
                # Attributes rewrite should re-run after a new pipeline pass.
                prompt.pop(ATTRIBUTES_KEY, None)
                total += prompt_changed
    return suite, total
