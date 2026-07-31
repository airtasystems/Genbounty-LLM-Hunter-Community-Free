"""Generation-time encoding / multilingual / cipher variants and playbook delivery.

The prompt transforms (``prompt_translation``, ``prompt_cipher``,
``prompt_obfuscation``, ``prompt_code_embed``) historically only ran as manual,
post-hoc UI actions, so encoding and multilingual bypasses were never part of an
automated campaign. This module folds those transforms into generation in two ways:

1. **Env variants** (``GENBOUNTY_GEN_TRANSFORMS``): append a bounded set of
   transformed copies of base prompts (opt-in).
2. **Playbook delivery** (``generation.delivery_transforms``): encode cleartext
   seeds for plays that use obfuscation as the delivery channel (e.g. INST02).
   ``mode=replace`` rewrites each seed in place; ``mode=variant`` appends copies.

Opt-in and fail-safe:
  - Env variants off unless ``GENBOUNTY_GEN_TRANSFORMS`` names transforms.
  - Playbook delivery runs only when the playbook configures ``delivery_transforms``.
  - Any transform error skips just that prompt; the base suite is never lost.
  - Env variants bounded by ``GENBOUNTY_GEN_TRANSFORM_PER_CATEGORY`` (default 1).

``GENBOUNTY_GEN_TRANSFORMS`` is a comma-separated list of ``kind:name`` specs, e.g.::

    translation:spanish,native:llm_native,frame:persona,cipher:atbash,obfuscation:base58,code_embed:python,control_code:ctrl_padded,control_code:glossary_then_payload

``kind`` is one of ``translation``, ``native``, ``frame``, ``cipher``, ``obfuscation``, ``code_embed``, ``control_code``.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any, Callable

_GEN_DIR = Path(__file__).resolve().parent.parent
if str(_GEN_DIR) not in sys.path:
    sys.path.insert(0, str(_GEN_DIR))

_VALID_KINDS = (
    "translation",
    "native",
    "frame",
    "cipher",
    "obfuscation",
    "code_embed",
    "control_code",
)


_GEN_TRANSFORM_PER_CATEGORY = 1
_GEN_TRANSFORMS = ""


def _per_category() -> int:
    return _GEN_TRANSFORM_PER_CATEGORY


def parse_transform_specs(raw: str | None = None) -> list[tuple[str, str]]:
    """Parse transform specs into ``(kind, name)`` pairs."""
    text = raw if raw is not None else _GEN_TRANSFORMS
    specs: list[tuple[str, str]] = []
    for chunk in (text or "").split(","):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        kind, _, name = chunk.partition(":")
        kind = kind.strip().lower()
        name = name.strip().lower()
        if kind in _VALID_KINDS and name:
            specs.append((kind, name))
    return specs


def variants_enabled() -> bool:
    return bool(parse_transform_specs())


def _text_transformer(kind: str, name: str) -> Callable[[str], str] | None:
    """Return a single-string transform fn for ``(kind, name)`` or ``None`` if invalid."""
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
    except Exception:
        return None
    return None


def _base_prompts(cat: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """Pick the first ``limit`` untransformed text prompts from a category."""
    out: list[dict[str, Any]] = []
    for row in cat.get("prompts") or []:
        if not isinstance(row, dict):
            continue
        if row.get("transform_variant_of"):
            continue
        # Already surface-transformed on the bounty mutate lane - do not use as
        # a GENBOUNTY_GEN_TRANSFORMS base (avoids double-encoding).
        if row.get("bounty_mutate_transform"):
            continue
        if not str(row.get("prompt") or "").strip():
            continue
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _make_variant(
    base: dict[str, Any],
    kind: str,
    name: str,
    transform: Callable[[str], str],
) -> dict[str, Any] | None:
    original = str(base.get("prompt") or "").strip()
    if not original:
        return None
    try:
        transformed = transform(original)
    except Exception:
        return None
    transformed = (transformed or "").strip()
    if not transformed or transformed == original:
        return None
    variant = copy.deepcopy(base)
    variant["prompt"] = transformed
    variant["plain_prompt"] = original
    variant["transform_kind"] = kind
    variant["transform_name"] = name
    variant["transform_variant_of"] = base.get("id", "")
    base_id = str(base.get("id") or "p")
    variant["id"] = f"{base_id}-x-{kind[:4]}-{name}"
    desc = str(base.get("description") or "").strip()
    tag = f"[{kind}:{name} variant]"
    variant["description"] = f"{tag} {desc}".strip()
    return variant


def augment_suite_with_variants(
    suite: dict[str, Any],
    specs: list[tuple[str, str]] | None = None,
) -> int:
    """Append transformed variant prompts to each category in ``suite`` in place.

    Returns the number of variant prompts added. No-op (returns 0) when no valid
    transforms are configured or the suite has no categories.
    """
    specs = specs if specs is not None else parse_transform_specs()
    if not specs:
        return 0
    categories = suite.get("categories")
    if not isinstance(categories, list):
        return 0

    transformers: list[tuple[str, str, Callable[[str], str]]] = []
    for kind, name in specs:
        fn = _text_transformer(kind, name)
        if fn is not None:
            transformers.append((kind, name, fn))
    if not transformers:
        return 0

    per_cat = _per_category()
    added = 0
    for cat in categories:
        if not isinstance(cat, dict):
            continue
        bases = _base_prompts(cat, per_cat)
        if not bases:
            continue
        new_rows: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for kind, name, fn in transformers:
            for base in bases:
                variant = _make_variant(base, kind, name, fn)
                if variant is None:
                    continue
                vid = variant["id"]
                if vid in seen_ids:
                    continue
                seen_ids.add(vid)
                new_rows.append(variant)
        if new_rows:
            cat.setdefault("prompts", []).extend(new_rows)
            added += len(new_rows)
    return added


def _stamp_structural_transform(prompt: dict[str, Any], kind: str, name: str) -> None:
    """Mark suite metadata so attributes / Restore treat the payload as structural."""
    prompt["transform_kind"] = kind
    prompt["transform_name"] = name
    prompt["delivery_transform"] = f"{kind}:{name}"
    if kind == "obfuscation":
        try:
            from prompt_suite_backup import TECHNIQUE_KEY

            prompt[TECHNIQUE_KEY] = name
        except Exception:
            pass
    elif kind == "cipher":
        try:
            from prompt_suite_backup import CIPHER_KEY

            prompt[CIPHER_KEY] = name
        except Exception:
            pass
    elif kind == "code_embed":
        try:
            from prompt_suite_backup import CODE_KEY

            prompt[CODE_KEY] = name
        except Exception:
            pass
    elif kind == "control_code":
        try:
            from prompt_suite_backup import CONTROL_CODE_KEY

            prompt[CONTROL_CODE_KEY] = name
        except Exception:
            pass


def _replace_prompt_with_transform(
    prompt: dict[str, Any],
    kind: str,
    name: str,
    transform: Callable[[str], str],
) -> bool:
    """Encode live prompt text in place; preserve plain backup. Returns True on change."""
    original = str(prompt.get("prompt") or "").strip()
    if not original:
        return False
    if prompt.get("delivery_transform") or prompt.get("transform_variant_of"):
        return False
    # Keep any pre-existing cleartext (e.g. bounty mutate lane) - do not clobber
    # it with an already surface-transformed ``prompt``.
    prior_plain = str(prompt.get("plain_prompt") or "").strip()
    try:
        from prompt_suite_backup import capture_plain_source

        capture_plain_source(prompt)
    except Exception:
        pass
    try:
        transformed = transform(original)
    except Exception:
        return False
    transformed = (transformed or "").strip()
    if not transformed or transformed == original:
        return False
    prompt["prompt"] = transformed
    prompt["plain_prompt"] = prior_plain or original
    _stamp_structural_transform(prompt, kind, name)
    desc = str(prompt.get("description") or "").strip()
    tag = f"[{kind}:{name} delivery]"
    if tag not in desc:
        prompt["description"] = f"{tag} {desc}".strip()
    return True


def apply_playbook_delivery_transforms(
    suite: dict[str, Any],
    playbook: dict[str, Any] | None,
) -> int:
    """Apply playbook ``generation.delivery_transforms`` to suite prompts.

    ``mode=replace`` (default): encode each cleartext seed in place (round-robin
    across configured transforms). ``mode=variant``: append encoded copies like
    ``GENBOUNTY_GEN_TRANSFORMS`` variants.

    Returns the number of prompts transformed or variants added.
    """
    try:
        from playbooks.playbook_config import get_delivery_transforms
    except Exception:
        return 0

    cfg = get_delivery_transforms(playbook)
    if not cfg:
        return 0
    mode = str(cfg.get("mode") or "replace")
    specs = [
        (str(row["kind"]), str(row["name"]))
        for row in cfg.get("transforms") or []
        if isinstance(row, dict)
    ]
    transformers: list[tuple[str, str, Callable[[str], str]]] = []
    for kind, name in specs:
        fn = _text_transformer(kind, name)
        if fn is not None:
            transformers.append((kind, name, fn))
    if not transformers:
        return 0

    categories = suite.get("categories")
    if not isinstance(categories, list):
        return 0

    changed = 0
    if mode == "variant":
        return augment_suite_with_variants(suite, specs)

    # replace: cycle techniques across prompts so the suite covers each channel.
    tech_i = 0
    for cat in categories:
        if not isinstance(cat, dict):
            continue
        for prompt in cat.get("prompts") or []:
            if not isinstance(prompt, dict):
                continue
            kind, name, fn = transformers[tech_i % len(transformers)]
            tech_i += 1
            if _replace_prompt_with_transform(prompt, kind, name, fn):
                changed += 1
    return changed
