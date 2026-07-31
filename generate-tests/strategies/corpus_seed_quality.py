"""Coherence and diversity gates for corpus seed text.

Used at capture time (prior_results), on persist (append_*), on load, and by the
one-time prune script so malformed fragments and near-duplicate template clones
do not fill capped seed stores.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

# Minimum length for a usable attacker-message seed.
_MIN_SEED_CHARS = 40

# Near-duplicate threshold (matches generation dedup but slightly lower for templates).
_DEFAULT_SIMILARITY = 0.88

_JSON_FRAGMENT_START = re.compile(
    r'^\s*"(?:description|type|name|properties|default|enum|items)"\s*:',
    re.IGNORECASE,
)
_JSON_MID_FRAGMENT = re.compile(r'^\s*"\s*,\s*"[a-z_]+"\s*:', re.IGNORECASE)
_WORD_RE = re.compile(r"[a-zA-Z]{3,}")

# Classical cipher/encoding delivery frames are low-yield against modern LLMs and
# must not re-enter learned/breakthrough corpora as mutate-these exemplars.
_LOW_YIELD_ENCODING_FRAME_RE = re.compile(
    r"\b(?:base64|b64|hex(?:adecimal)?|rot13)[- ]?decod(?:e|ing|ed)?\b"
    r"|"
    r"\b(?:base64|b64|hex(?:adecimal)?|rot13)\b"
    r".{0,100}?"
    r"\b(?:decode|decod(?:e|ing|ed)|b64decode|unhexlify|exec(?:ute)?)\b"
    r"|"
    r"\b(?:decode|decod(?:e|ing|ed)|b64decode|unhexlify)\b"
    r".{0,100}?"
    r"\b(?:base64|b64|hex(?:adecimal)?|rot13)\b"
    r"|"
    r"\b(?:morse|octal|ascii\s+binary)\b"
    r".{0,80}?"
    r"\b(?:decode|decod(?:e|ing|ed))\b"
    r"|"
    r"\b(?:decode|decod(?:e|ing|ed))\b"
    r".{0,80}?"
    r"\b(?:morse|octal|ascii\s+binary)\b",
    re.IGNORECASE | re.DOTALL,
)


def strip_legitimising_wrapper(text: str) -> str:
    """Remove common authority/audit prefixes before signature (wrapper-aware dedupe)."""
    try:
        from strategies.framing_diversity import strip_legitimising_wrapper as _strip

        return _strip(text)
    except ImportError:
        return (text or "").strip()


def seed_text_signature(text: str) -> str:
    """Normalized signature for fuzzy dedup (aligned with security_common._normalize_sig_text)."""
    # Collapse compliance/SRE wrappers so mechanism clones collide.
    core = strip_legitimising_wrapper(text or "")
    sig = re.sub(r"[^a-z0-9]+", " ", core.lower()).strip()
    # Drop nonce-only variants so template clones dedupe together.
    sig = re.sub(r"\bnonce\s+\d+\b", "nonce", sig)
    sig = re.sub(r"\s+", " ", sig).strip()
    return sig


def seed_quality_violations(text: str) -> list[str]:
    """Return reasons ``text`` is not a coherent standalone seed; empty means OK."""
    raw = (text or "").strip()
    if len(raw) < _MIN_SEED_CHARS:
        return ["too_short"]
    if _JSON_FRAGMENT_START.match(raw) or _JSON_MID_FRAGMENT.match(raw):
        return ["json_fragment"]
    if raw.startswith('"') and raw.count('"') >= 2 and not _WORD_RE.search(raw[:80]):
        return ["json_fragment"]
    if not _WORD_RE.search(raw):
        return ["no_words"]
    json_chars = sum(raw.count(c) for c in '{}[]":')
    if json_chars / max(len(raw), 1) > 0.22 and len(_WORD_RE.findall(raw)) < 5:
        return ["json_heavy"]
    if raw.endswith((",", "{", "[", "\\")):
        return ["truncated"]
    if _LOW_YIELD_ENCODING_FRAME_RE.search(raw):
        return ["low_yield_encoding_frame"]
    return []


def seed_is_usable(text: str) -> bool:
    return not seed_quality_violations(text)


def seed_dict_usable(seed: dict[str, Any]) -> bool:
    return seed_is_usable(str(seed.get("seed") or ""))


def is_near_duplicate(sig: str, existing_sigs: list[str], *, similarity: float = _DEFAULT_SIMILARITY) -> bool:
    if not sig:
        return True
    for prev in existing_sigs:
        if sig == prev:
            return True
        if SequenceMatcher(None, sig, prev).ratio() >= similarity:
            return True
    return False


def dedupe_seeds_newest_first(
    seeds: list[dict[str, Any]],
    *,
    cap: int | None = None,
    similarity: float = _DEFAULT_SIMILARITY,
) -> list[dict[str, Any]]:
    """Keep newest-first diverse seeds; drop quality failures and near-duplicates."""
    kept: list[dict[str, Any]] = []
    kept_sigs: list[str] = []
    for seed in seeds:
        if not isinstance(seed, dict):
            continue
        text = str(seed.get("seed") or "").strip()
        if not seed_is_usable(text):
            continue
        sig = seed_text_signature(text)
        if is_near_duplicate(sig, kept_sigs, similarity=similarity):
            continue
        kept_sigs.append(sig)
        kept.append(seed)
        if cap is not None and len(kept) >= cap:
            break
    return kept
