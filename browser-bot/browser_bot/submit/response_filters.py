"""Response text filters for UI capture: normalize, wait-gate, and post-capture sanitize."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Leading role label like "Assistant\n" (≤30 chars, no spaces, then newline).
# Do not treat markdown fences (``` / ```lang) as role labels - that ate fenced
# prompt echoes during convert_log sanitize and blanked real captures.
_PLAIN_ROLE_RE = re.compile(r"^(?!`)(\S{1,30})\n+", re.UNICODE)
_BRACKET_ROLE_RE = re.compile(
    r"^\s*\[(?:target|assistant|user|bot|ai|system|human)\]\s*[\r\n]*",
    re.IGNORECASE,
)

EMPTY_RESPONSE_MARKERS = frozenset({
    "",
    "the model response will appear here.",
    "loading...",
    "generating...",
    "thinking...",
    "responding...",
})

_PROGRESS_VERBS = (
    "generating",
    "loading",
    "thinking",
    "fetching",
    "preparing",
    "assessing",
    "streaming",
    "responding",
    "processing",
    "analyzing",
    "computing",
    "searching",
    "connecting",
    "waiting",
    "running",
    "working",
)
_WAIT_PHRASES = (
    "please wait",
    "one moment",
    "hold on",
    "just a moment",
    "hang tight",
    "stand by",
)
_PROGRESS_VERB_RE = re.compile(
    r"\b(" + "|".join(re.escape(v) for v in _PROGRESS_VERBS) + r")\b",
    re.IGNORECASE,
)
_PROGRESS_PRESENT_RE = re.compile(r"\b(is|are|was|were)\s+\w+ing\b", re.IGNORECASE)
_KNOWN_LOADER_PHRASES = (
    "target is responding",
    "model is responding",
    "assistant is responding",
    "agent is responding",
    "generating response",
    "loading response",
    "please wait",
)

# Whole-line bracket banners (case-insensitive), max line length for banner match.
_BANNER_LINE_RE = re.compile(
    r"^\s*\[(?:chat history redacted|redacted|welcome)\]\s*$",
    re.IGNORECASE,
)
_CUSTOM_IGNORE_MAX_LEN = 240
_BANNER_SHORT_MAX_LEN = 160
# Short copy already on screen before submit is treated as UI chrome (any app's welcome
# bubble), not as the new model reply. Configure also records welcome/intro clicks into
# response_ignore_substrings - prefer those over phrase guessing.
_PRE_SUBMIT_CHROME_MAX_LEN = 240


@dataclass
class ResponseFilterContext:
    """Inputs for response filter decisions during capture."""

    prompt: str = ""
    ignore_substrings: tuple[str, ...] = field(default_factory=tuple)
    # Short texts visible in the response surface before submit (mutated per probe).
    pre_submit_chrome: list[str] = field(default_factory=list)
    site: str = ""
    component: str = ""


def all_ignore_substrings(ctx: ResponseFilterContext | None) -> tuple[str, ...]:
    if not ctx:
        return ()
    from browser_bot.submit.response_boilerplate import session_ignore_substrings

    learned = session_ignore_substrings(ctx.site, ctx.component)
    if not learned:
        return ctx.ignore_substrings
    merged = list(ctx.ignore_substrings)
    seen = {x.lower() for x in merged}
    for item in learned:
        if item.lower() not in seen:
            merged.append(item)
            seen.add(item.lower())
    return tuple(merged)


def _norm_chrome(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def register_pre_submit_chrome(
    ctx: ResponseFilterContext | None,
    *texts: str,
    persist: bool = True,
) -> None:
    """Record short pre-submit response-surface copy so remounts are not treated as replies."""
    if not ctx:
        return
    seen = {_norm_chrome(x) for x in ctx.pre_submit_chrome}
    for raw in texts:
        s = (raw or "").strip()
        if not s or len(s) > _PRE_SUBMIT_CHROME_MAX_LEN:
            continue
        key = _norm_chrome(s)
        if not key or key in seen:
            continue
        ctx.pre_submit_chrome.append(s)
        seen.add(key)
        if persist and ctx.site and ctx.component:
            from browser_bot.submit.response_boilerplate import (
                persist_response_ignore_substring,
            )

            # Persist whatever was on-screen - wording is app-specific.
            persist_response_ignore_substring(ctx.site, ctx.component, s)


def matches_pre_submit_chrome(text: str, ctx: ResponseFilterContext | None) -> bool:
    """True when capture equals short copy that was already visible before submit."""
    if not ctx or not ctx.pre_submit_chrome:
        return False
    s = (text or "").strip()
    if not s or len(s) > _PRE_SUBMIT_CHROME_MAX_LEN:
        return False
    key = _norm_chrome(s)
    return any(_norm_chrome(chrome) == key for chrome in ctx.pre_submit_chrome)


def filter_context_from_submission(
    submission: dict[str, Any] | None,
    prompt: str = "",
    *,
    site: str = "",
    component: str = "",
) -> ResponseFilterContext:
    """Build filter context from submission config and the prompt being sent."""
    sub = submission or {}
    raw = sub.get("response_ignore_substrings") or []
    ignores: list[str] = []
    if isinstance(raw, str):
        raw = [p.strip() for p in raw.split(",") if p.strip()]
    if isinstance(raw, list):
        for item in raw:
            s = str(item or "").strip()
            if s:
                ignores.append(s)
    return ResponseFilterContext(
        prompt=(prompt or "").strip(),
        ignore_substrings=tuple(ignores),
        site=(site or "").strip(),
        component=(component or "").strip(),
    )


def normalize_dom_text(text: str) -> str:
    """Strip leading UI role labels once at DOM read time."""
    return strip_leading_role_markers(text or "")


def strip_leading_role_markers(text: str) -> str:
    """Remove bracket/plain role prefixes repeatedly from the start."""
    out = (text or "").lstrip("\r\n")
    while True:
        prev = out
        out = _PLAIN_ROLE_RE.sub("", out, count=1)
        out = _BRACKET_ROLE_RE.sub("", out.lstrip("\r\n"), count=1)
        if out == prev:
            break
        out = out.lstrip("\r\n")
    return out


def response_delta(base: str, current: str) -> str:
    """Return the portion of ``current`` that appeared after ``base`` (prefix snapshot)."""
    if base and current.startswith(base):
        return current[len(base) :].lstrip("\r\n")
    return current


def is_empty_response_text(text: str) -> bool:
    return (text or "").strip().lower() in EMPTY_RESPONSE_MARKERS


def line_looks_like_skeleton_loader(raw: str) -> bool:
    """True when a single visible line is transitional loader/spinner text."""
    if len(raw) > 160:
        return False
    low = raw.lower()
    ell = low.endswith(("…", "..."))
    if len(raw) <= 72 and any(w in low for w in _WAIT_PHRASES):
        return True
    if len(raw) <= 140 and any(phrase in low for phrase in _KNOWN_LOADER_PHRASES):
        return True
    if len(raw) <= 100 and _PROGRESS_PRESENT_RE.search(raw) is not None:
        return True
    if ell and len(raw) <= 140 and (
        any(low.startswith(v) for v in _PROGRESS_VERBS)
        or any(low.startswith(w) for w in _WAIT_PHRASES)
        or _PROGRESS_VERB_RE.search(raw) is not None
    ):
        return True
    if len(raw) <= 24 and not low.rstrip(".…").strip():
        return True
    return False


def looks_like_skeleton_progress_line(text: str) -> bool:
    """True when the bubble shows transitional status text, not a finished reply."""
    s = (text or "").strip()
    if not s:
        return False
    if is_empty_response_text(s):
        return True
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    if not lines or any(len(ln) > 240 for ln in lines):
        return False
    if all(line_looks_like_skeleton_loader(ln) for ln in lines):
        return True
    if len(lines) == 1:
        return line_looks_like_skeleton_loader(lines[0])
    last = lines[-1]
    if len(last) <= 100 and line_looks_like_skeleton_loader(last):
        low = last.lower()
        if any(phrase in low for phrase in _KNOWN_LOADER_PHRASES):
            return True
        if low.endswith(("…", "...")):
            return True
    return False


def looks_like_welcome_or_redacted_response(text: str) -> bool:
    """True for static welcome banners, not model replies."""
    s = (text or "").strip()
    if not s:
        return False
    low = s.lower()
    if "chat history redacted" in low:
        return True
    if "chat history" in low and len(s) <= _BANNER_SHORT_MAX_LEN:
        return True
    for line in s.splitlines():
        line = line.strip()
        if line and len(line) <= _BANNER_SHORT_MAX_LEN and _BANNER_LINE_RE.match(line):
            return True
    return False


def matches_custom_ignore_patterns(text: str, ctx: ResponseFilterContext) -> bool:
    """True when short copy matches component-configured ignore substrings."""
    s = (text or "").strip()
    ignores = all_ignore_substrings(ctx)
    if not s or not ignores:
        return False
    low = s.lower()
    if len(s) <= _CUSTOM_IGNORE_MAX_LEN:
        return any(needle.lower() in low for needle in ignores if needle)
    for line in s.splitlines():
        line = line.strip()
        if not line or len(line) > _CUSTOM_IGNORE_MAX_LEN:
            continue
        line_low = line.lower()
        if any(needle.lower() in line_low for needle in ignores if needle):
            return True
    return False


def non_actionable_reason(text: str, ctx: ResponseFilterContext | None = None) -> str | None:
    """Human-readable reject reason, or None when text is actionable."""
    s = (text or "").strip()
    if not s:
        return "empty"
    if is_empty_response_text(s):
        return "empty_placeholder"
    if looks_like_skeleton_progress_line(s):
        return "loader_skeleton"
    if looks_like_welcome_or_redacted_response(s):
        return "welcome_banner"
    if matches_pre_submit_chrome(s, ctx):
        return "pre_submit_chrome"

    from browser_bot.submit.response_boilerplate import (
        classify_response_boilerplate,
        looks_like_stale_prompt_surface,
        maybe_learn_response_ignore_substring,
    )

    # Welcome/intro copy: prefer Configure-recorded response_ignore_substrings and
    # pre_submit_chrome; phrase heuristics are a fallback when Configure was skipped.
    if ctx:
        if matches_custom_ignore_patterns(s, ctx):
            return "custom_ignore"
    from browser_bot.submit.response_boilerplate import (
        classify_response_boilerplate,
        looks_like_assistant_welcome_copy,
        looks_like_stale_prompt_surface,
        maybe_learn_response_ignore_substring,
    )

    if looks_like_assistant_welcome_copy(s):
        if ctx:
            maybe_learn_response_ignore_substring(
                s, site=ctx.site, component=ctx.component
            )
        return "assistant_welcome"
    if ctx:
        if looks_like_stale_prompt_surface(s, ctx.prompt):
            maybe_learn_response_ignore_substring(
                s, site=ctx.site, component=ctx.component
            )
            return "stale_prompt_surface"
        # Short unknown bubbles: ask the classifier when cheap gates fire.
        verdict = classify_response_boilerplate(
            s,
            prompt=ctx.prompt,
            site=ctx.site,
            component=ctx.component,
        )
        if verdict is not None and not verdict.actionable:
            return f"llm_boilerplate:{verdict.kind or 'ui_chrome'}"
        if _matches_submitted_prompt(s, ctx.prompt):
            return "echoed_prompt"
    return None


def is_actionable_response(text: str, ctx: ResponseFilterContext | None = None) -> bool:
    """False for empty, loader, welcome, custom ignore, or echoed prompt - keep polling."""
    return non_actionable_reason(text, ctx) is None


def is_actionable_delta(new_slice: str, ctx: ResponseFilterContext | None = None) -> bool:
    """True when the delta since baseline is a meaningful new reply."""
    s = (new_slice or "").strip()
    if not s:
        return False
    return is_actionable_response(s, ctx)


def _prompt_variants(prompt: str) -> list[str]:
    variants: list[str] = []
    seen: set[str] = set()

    def _add(value: str) -> None:
        v = (value or "").strip()
        if v and v not in seen:
            seen.add(v)
            variants.append(v)

    _add(prompt)
    try:
        from pipeline.convert_log import normalize_submitted_prompt

        _add(normalize_submitted_prompt(prompt))
    except Exception:
        pass
    return variants


def _matches_submitted_prompt(text: str, prompt: str) -> bool:
    if not prompt:
        return False
    work = (text or "").strip()
    for cand in _prompt_variants(prompt):
        if work == cand or work.startswith(cand):
            remainder = work[len(cand) :].strip()
            if not remainder or remainder in ("", "…", "..."):
                return True
    return False


def _strip_echoed_prompt(text: str, prompt: str) -> tuple[str, bool]:
    """Return (text_after_strip, did_strip)."""
    work = (text or "").lstrip("\r\n")
    for cand in _prompt_variants(prompt):
        if work.startswith(cand):
            return work[len(cand) :].lstrip("\r\n"), True
    return work, False


def sanitize_captured_response(
    response: str | None,
    ctx: ResponseFilterContext | None = None,
) -> str | None:
    """Post-capture: strip echo/roles, re-validate; return None if non-actionable."""
    if response is None:
        return None
    text = str(response)
    if not text.strip():
        return response if response == "" else None

    prompt = (ctx.prompt if ctx else "") or ""
    stripped_prompt = False
    work, stripped_prompt = _strip_echoed_prompt(text, prompt)
    work = strip_leading_role_markers(work.lstrip("\r\n"))
    result = work.strip()
    if not result:
        return None if stripped_prompt else (response if str(response).strip() else None)
    if not is_actionable_response(result, ctx):
        return None
    return result


def log_response_filter_rejection(reason: str, *, preview: str = "") -> None:
    """Emit a single debug line when captured response is cleared by filters."""
    snippet = ""
    if preview:
        short = preview.strip().replace("\n", " ")[:80]
        snippet = f" ({short!r})"
    print(f"[response_filter] rejected: {reason}{snippet}", flush=True)


# Backward-compatible private aliases (tests / legacy imports from common.py).
_is_empty_response_text = is_empty_response_text
_looks_like_welcome_or_redacted_response = looks_like_welcome_or_redacted_response
_looks_like_skeleton_progress_line = looks_like_skeleton_progress_line
_is_actionable_response_text = is_actionable_response
_response_delta = response_delta
