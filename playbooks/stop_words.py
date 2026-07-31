"""Stop-word helpers: parse playbook config and detect matches in model responses."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# Quoted tokens from exploited_if prose that are not useful as substring stops.
_QUOTED_SKIP = frozenset(
    {
        "the",
        "a",
        "an",
        "model",
        "response",
        "critical",
        "high",
        "medium",
        "low",
        "maps",
        "forbidden",
        "rejected",
        "redacted",
    }
)

_EXPLICIT_STRING_RE = re.compile(
    r"contains the (?:exact )?string:\s*(?:'([^']+)'|\"([^\"]+)\"|(\S+))",
    re.IGNORECASE,
)
_QUOTED_RE = re.compile(r"['\"]([^'\"]{2,48})['\"]")


def parse_stop_words(text: str) -> list[str]:
    """Parse comma-separated stop words from the generate-play form."""
    words: list[str] = []
    for part in (text or "").split(","):
        word = part.strip()
        if word and word not in words:
            words.append(word)
    return words


def normalize_stop_words(raw: Any) -> list[str]:
    """Normalize stop_words from playbook JSON (list or legacy comma string)."""
    return normalize_term_list(raw)


def normalize_term_list(raw: Any) -> list[str]:
    """Normalize a term list from playbook JSON (list or legacy comma string)."""
    if raw is None:
        return []
    if isinstance(raw, list):
        out: list[str] = []
        for item in raw:
            word = str(item or "").strip()
            if word and word not in out:
                out.append(word)
        return out
    if isinstance(raw, str):
        return parse_stop_words(raw)
    return []


def _dedupe_terms(terms: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for term in terms:
        needle = (term or "").strip()
        if not needle:
            continue
        key = needle.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(needle)
    return out


def extract_exploit_patterns_from_exploited_if(exploited_if: list[str] | None) -> list[str]:
    """Extract concrete substring stops from playbook exploited_if bullets."""
    patterns: list[str] = []
    for line in exploited_if or []:
        text = str(line).strip()
        if not text:
            continue
        match = _EXPLICIT_STRING_RE.search(text)
        if match:
            single, double, bare = match.groups()
            if single is not None:
                patterns.append(single)
            elif double is not None:
                patterns.append(double)
            elif bare:
                patterns.append(bare.rstrip(".,;"))
        if re.search(r"FLAG\{", text, re.IGNORECASE):
            patterns.append("FLAG{")
        if re.search(r"WRAITH\{", text, re.IGNORECASE):
            patterns.append("WRAITH{")
        for quoted in _QUOTED_RE.findall(text):
            token = quoted.strip()
            if len(token) < 3:
                continue
            if token.lower() in _QUOTED_SKIP:
                continue
            if token.isascii() and token.replace("_", "").replace("-", "").isalnum():
                patterns.append(token)
    return _dedupe_terms(patterns)


def _category_exploited_if(playbook: dict[str, Any], category: str) -> list[str]:
    needle = (category or "").strip()
    if not needle:
        return []
    for cat in playbook.get("categories") or []:
        if not isinstance(cat, dict):
            continue
        if cat.get("name") == needle or cat.get("id") == needle:
            triggers = cat.get("attack_triggers") or {}
            raw = triggers.get("exploited_if") or []
            return [str(x).strip() for x in raw if str(x).strip()]
    return []


def load_exploit_patterns_for_playbook(
    playbook: dict[str, Any] | None,
    *,
    category: str | None = None,
) -> list[str]:
    """Flag/keyword patterns derived from playbook exploited_if triggers."""
    if not playbook:
        return []
    if category:
        exploited = _category_exploited_if(playbook, category)
        return extract_exploit_patterns_from_exploited_if(exploited)
    patterns: list[str] = []
    for cat in playbook.get("categories") or []:
        if not isinstance(cat, dict):
            continue
        triggers = cat.get("attack_triggers") or {}
        exploited = triggers.get("exploited_if") or []
        patterns.extend(extract_exploit_patterns_from_exploited_if(exploited))
    return _dedupe_terms(patterns)


def resolve_stop_on_exploit(suite: dict[str, Any] | None) -> bool:
    """Whether runtime should stop when exploit keywords appear in any response."""
    if not isinstance(suite, dict):
        return False
    if "stop_on_exploit" in suite:
        return bool(suite.get("stop_on_exploit"))
    return str(suite.get("strategy") or "").replace("-", "_") == "adaptive"


def _load_suite_json(suite_path: Path | str | None) -> dict[str, Any] | None:
    if not suite_path:
        return None
    try:
        raw = json.loads(Path(suite_path).expanduser().read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def _load_playbook_for_suite(suite: dict[str, Any] | None) -> dict[str, Any] | None:
    if not suite:
        return None
    pid = (suite.get("playbook_id") or "").strip()
    if not pid:
        return None
    try:
        from playbooks.registry import load_playbook

        return load_playbook(pid)
    except Exception:
        return None


def load_stop_terms_for_run(
    suite_path: Path | str | None,
    *,
    category: str | None = None,
) -> list[str]:
    """Stop terms for runtime: playbook stop_words plus exploit patterns when enabled."""
    suite = _load_suite_json(suite_path)
    playbook = _load_playbook_for_suite(suite)
    terms: list[str] = []
    if playbook:
        terms.extend(normalize_stop_words(playbook.get("stop_words")))
    if suite and resolve_stop_on_exploit(suite) and playbook:
        terms.extend(load_exploit_patterns_for_playbook(playbook, category=category))
    return _dedupe_terms(terms)


def find_stop_word_match(response: str, stop_words: list[str]) -> str | None:
    """Return the first configured success marker found in response (case-insensitive)."""
    return find_term_match(response, stop_words)


def find_term_match(response: str, terms: list[str]) -> str | None:
    """Return the first configured term found in response (case-insensitive)."""
    if not terms:
        return None
    haystack = response or ""
    if not haystack.strip():
        return None
    lower = haystack.lower()
    for word in terms:
        needle = (word or "").strip()
        if needle and needle.lower() in lower:
            return needle
    return None


def load_stop_words_for_playbook(playbook_id: str) -> list[str]:
    """Load stop_words from a playbook JSON by id."""
    pid = (playbook_id or "").strip().lower().replace("-", "_")
    if not pid:
        return []
    try:
        from playbooks.registry import load_playbook

        playbook = load_playbook(pid)
    except Exception:
        return []
    if not playbook:
        return []
    return normalize_stop_words(playbook.get("stop_words"))


def load_stop_words_for_suite(suite_path: Path | str | None) -> list[str]:
    """Resolve stop_words for a test suite via its playbook_id (legacy alias)."""
    return load_stop_terms_for_run(suite_path)
