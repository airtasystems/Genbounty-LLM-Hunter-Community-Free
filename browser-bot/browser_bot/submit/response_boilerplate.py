"""Detect welcome banners, echoed prompts, and other stale UI captured as assistant replies."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from browser_bot.submit.response_filters import (
    _prompt_variants,
    strip_leading_role_markers,
)

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from pipeline.llm import complete

_ASSISTANT_INTRO_RE = re.compile(
    r"\b(?:I'?m|I am)\s+(?:a|an|the)\s+.{0,80}?\bassistant\b",
    re.IGNORECASE,
)
_SEPARATOR_LINE_RE = re.compile(r"^\s*-{3,}\s*$", re.MULTILINE)
# Legacy phrase hints for stale-prompt remainder stripping / optional learning only.
# Primary welcome handling is Configure intro clicks → response_ignore_substrings
# plus pre_submit_chrome snapshots (not these regexes).
_WELCOME_INVITE_RE = re.compile(
    r"\b(?:"
    r"ask me anything|"
    r"how can I help(?:\s+you(?:\s+today)?)?|"
    r"what can I help you with|"
    r"(?:I'?m|I am)\s+here\s+to\s+help|"
    r"here to help you(?:\s+(?:plan|with|today))?"
    r")\b",
    re.IGNORECASE,
)
_WELCOME_COPY_MAX_LEN = 240

_RESPONSE_BOILERPLATE_LLM = True
_RESPONSE_BOILERPLATE_MODEL: str | None = None
_CLASSIFY_CACHE: dict[str, "BoilerplateVerdict"] = {}
_SESSION_IGNORES: dict[tuple[str, str], tuple[str, ...]] = {}


@dataclass(frozen=True)
class BoilerplateVerdict:
    actionable: bool
    kind: str = ""
    block_substring: str = ""


def session_ignore_substrings(site: str, component: str) -> tuple[str, ...]:
    key = ((site or "").strip(), (component or "").strip())
    if not key[0] or not key[1]:
        return ()
    return _SESSION_IGNORES.get(key, ())


def looks_like_assistant_welcome_copy(text: str) -> bool:
    """Legacy phrase hint for stale-prompt remainder checks (not a hard capture reject)."""
    s = (text or "").strip()
    if not s or len(s) > _WELCOME_COPY_MAX_LEN:
        return False
    if _WELCOME_INVITE_RE.search(s):
        return True
    if _ASSISTANT_INTRO_RE.search(s):
        return True
    return False


def looks_like_stale_prompt_surface(text: str, prompt: str) -> bool:
    """True when capture is onboarding/echoed prompt chrome, not a model reply yet."""
    s = (text or "").strip()
    if not s or not (prompt or "").strip():
        return False

    prompt_hit = any(
        cand and (cand in s or s.startswith(cand))
        for cand in _prompt_variants(prompt)
    )
    if not prompt_hit and not _prompt_loosely_present(s, prompt):
        return False

    remainder = _substantive_remainder(s, prompt)
    if not remainder:
        return True

    if len(remainder) <= 160 and (
        looks_like_assistant_welcome_copy(s)
        or _ends_with_separator_only(s)
    ):
        return True

    if _ends_with_separator_only(s) and len(remainder) <= 220:
        return True

    return False


def should_run_llm_boilerplate_check(text: str, prompt: str) -> bool:
    """Cheap gate before a small Gemini classification call."""
    if not _RESPONSE_BOILERPLATE_LLM:
        return False
    s = (text or "").strip()
    if not s or len(s) > 1200:
        return False
    if looks_like_stale_prompt_surface(s, prompt):
        return True
    if _ends_with_separator_only(s):
        return True
    if prompt and _prompt_loosely_present(s, prompt) and len(s) <= 700:
        return True
    return False


def classify_response_boilerplate(
    text: str,
    *,
    prompt: str = "",
    site: str = "",
    component: str = "",
) -> BoilerplateVerdict | None:
    """Return a verdict when LLM classification runs; None when skipped/unavailable."""
    s = (text or "").strip()
    if not s or not should_run_llm_boilerplate_check(s, prompt):
        return None

    cache_key = _cache_key(s, prompt)
    cached = _CLASSIFY_CACHE.get(cache_key)
    if cached is not None:
        return cached

    model_override = _RESPONSE_BOILERPLATE_MODEL

    classify_prompt = f"""You classify text captured from a chat UI during browser automation.

User prompt sent to the chatbot:
{(prompt or "").strip() or "(unknown)"}

Captured text:
{s[:1000]}

Decide whether this capture is a REAL assistant reply to the user prompt, or NON-ACTIONABLE stale UI such as:
- welcome/onboarding banner
- assistant self-introduction
- echoed user message still visible in the thread
- placeholder/separator lines (e.g. ---) with no answer yet
- mixed stale chrome without an actual answer

Return JSON only:
{{"actionable": true|false, "kind": "real_reply"|"welcome"|"echoed_user_message"|"ui_chrome"|"mixed_stale", "block_substring": "8-80 char distinctive phrase from the stale text to ignore next time, or empty when actionable"}}
"""

    try:
        raw = complete(
            "boilerplate_classifier",
            user=classify_prompt,
            json_mode=True,
            model=model_override,
        ).text
        payload = _parse_json_payload(raw)
        actionable = bool(payload.get("actionable"))
        kind = str(payload.get("kind") or "").strip() or ("real_reply" if actionable else "ui_chrome")
        block = _normalize_block_substring(str(payload.get("block_substring") or ""), source=s)
        verdict = BoilerplateVerdict(
            actionable=actionable,
            kind=kind,
            block_substring=block,
        )
    except Exception:
        return None

    _CLASSIFY_CACHE[cache_key] = verdict
    if not verdict.actionable and verdict.block_substring and site and component:
        _remember_block_substring(site, component, verdict.block_substring)
    return verdict


def maybe_learn_response_ignore_substring(
    text: str,
    *,
    site: str,
    component: str,
) -> str | None:
    """Derive and persist a blocklist phrase from obvious stale copy."""
    s = (text or "").strip()
    if not site or not component or not s:
        return None
    for line in s.splitlines():
        line = line.strip()
        if not line or len(line) < 8 or len(line) > 120:
            continue
        if looks_like_assistant_welcome_copy(line) or _ASSISTANT_INTRO_RE.search(line) or _WELCOME_INVITE_RE.search(line):
            if _remember_block_substring(site, component, line):
                return line
    invite = _WELCOME_INVITE_RE.search(s)
    if invite:
        phrase = invite.group(0).strip()
        if 8 <= len(phrase) <= 120 and _remember_block_substring(site, component, phrase):
            return phrase
    intro = _ASSISTANT_INTRO_RE.search(s)
    if intro:
        phrase = intro.group(0).strip()
        if 8 <= len(phrase) <= 120 and _remember_block_substring(site, component, phrase):
            return phrase
    return None


def _remember_block_substring(site: str, component: str, substring: str) -> bool:
    phrase = _normalize_block_substring(substring)
    if not phrase:
        return False
    key = (site.strip(), component.strip())
    existing = set(x.lower() for x in _SESSION_IGNORES.get(key, ()))
    if phrase.lower() in existing:
        return False
    return persist_response_ignore_substring(site, component, phrase)


def persist_response_ignore_substring(site: str, component: str, substring: str) -> bool:
    """Append a substring to submission.response_ignore_substrings in config.yaml."""
    phrase = _normalize_block_substring(substring)
    if not phrase or not site or not component:
        return False
    try:
        from browser_bot.sites import load_component_config_raw, save_component_config
    except Exception:
        return False

    config = load_component_config_raw(site, component)
    sub = config.setdefault("submission", {})
    if not isinstance(sub, dict):
        sub = {}
        config["submission"] = sub
    raw = sub.get("response_ignore_substrings") or []
    items: list[str] = []
    if isinstance(raw, str):
        items = [p.strip() for p in raw.split(",") if p.strip()]
    elif isinstance(raw, list):
        items = [str(x).strip() for x in raw if str(x or "").strip()]
    lower = {x.lower() for x in items}
    if phrase.lower() in lower:
        return False
    items.append(phrase)
    sub["response_ignore_substrings"] = items
    save_component_config(site, component, config)
    key = (site.strip(), component.strip())
    existing = _SESSION_IGNORES.get(key, ())
    if phrase.lower() not in {x.lower() for x in existing}:
        _SESSION_IGNORES[key] = existing + (phrase,)
        print(
            f"[response_filter] learned ignore substring for {site}/{component}: {phrase!r}",
            flush=True,
        )
    return True


def _substantive_remainder(text: str, prompt: str) -> str:
    work = strip_leading_role_markers(text or "")
    for cand in _prompt_variants(prompt):
        if cand:
            work = work.replace(cand, "")
    work = _SEPARATOR_LINE_RE.sub("", work)
    work = re.sub(r"-{3,}", " ", work)
    lines = [ln.strip() for ln in work.splitlines() if ln.strip()]
    kept: list[str] = []
    for line in lines:
        if _ASSISTANT_INTRO_RE.search(line):
            continue
        if _WELCOME_INVITE_RE.search(line) and len(line) <= 120:
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def _ends_with_separator_only(text: str) -> bool:
    s = (text or "").rstrip()
    if not s:
        return False
    if re.search(r"-{3,}\s*$", s):
        tail = re.split(r"-{3,}\s*$", s, maxsplit=1)[0].strip()
        return bool(tail)
    return False


def _prompt_loosely_present(text: str, prompt: str) -> bool:
    prompt = (prompt or "").strip()
    if not prompt:
        return False
    low = text.lower()
    if prompt.lower() in low:
        return True
    for cand in _prompt_variants(prompt):
        if len(cand) >= 12 and cand.lower() in low:
            return True
    return False


def _normalize_block_substring(value: str, *, source: str = "") -> str:
    phrase = (value or "").strip().strip("\"'")
    phrase = re.sub(r"\s+", " ", phrase)
    if len(phrase) < 8 or len(phrase) > 240:
        return ""
    if source and phrase.lower() not in source.lower():
        return ""
    return phrase


def _cache_key(text: str, prompt: str) -> str:
    blob = f"{prompt}\n---\n{text}".encode("utf-8", errors="ignore")
    return hashlib.sha256(blob).hexdigest()


def _parse_json_payload(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if m:
        return json.loads(m.group(1))
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        return json.loads(m.group())
    return json.loads(text)


