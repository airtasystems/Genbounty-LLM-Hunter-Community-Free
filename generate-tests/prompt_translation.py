"""Translate test-suite prompts to other human languages via Gemini (faithful, single-line)."""

from __future__ import annotations

import json
from pathlib import Path

from payloads.text_utils import normalize_prompt_text, parse_llm_json_string_array
from pipeline.llm import complete

_GEN_DIR = Path(__file__).resolve().parent
if str(_GEN_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_GEN_DIR))
from strategies.security_common import prompt_transform_system_prompt  # noqa: E402
from prompt_suite_backup import (
    ATTRIBUTES_KEY,
    CIPHER_KEY,
    CONTROL_CODE_KEY,
    CODE_KEY,
    EMOTION_KEY,
    IQ_KEY,
    FRAME_KEY,
    NATIVE_KEY,
    TECHNIQUE_KEY,
    TRANSLATION_KEY,
    apply_text_to_entry,
    capture_plain_source,
    collect_plain_text_entries,
    plain_text_for_entry,
)

_ROOT = Path(__file__).resolve().parent.parent

# Human natural languages: (UI label, translation target name for the LLM).
TRANSLATION_LANGUAGES: dict[str, tuple[str, str]] = {
    "spanish": ("Spanish", "Spanish"),
    "french": ("French", "French"),
    "german": ("German", "German"),
    "italian": ("Italian", "Italian"),
    "latin": ("Latin", "Latin"),
    "japanese": ("Japanese", "Japanese"),
    "mandarin": ("Classical Mandarin", "Classical Mandarin Chinese"),
    "cantonese": ("Cantonese", "Cantonese (Traditional)"),
    "korean": ("Korean", "Korean"),
    "arabic": ("Classical Arabic", "Classical Arabic"),
    "russian": ("Russian", "Russian"),
    "hindi": ("Hindi", "Hindi"),
}

UI_LANGUAGES = tuple(TRANSLATION_LANGUAGES.keys())
_BATCH_SIZE = 12


def list_languages() -> list[dict[str, str]]:
    return [{"slug": slug, "label": TRANSLATION_LANGUAGES[slug][0]} for slug in UI_LANGUAGES]


def _build_translate_user_prompt(texts: list[str], language_slug: str) -> str:
    payload = json.dumps(texts, ensure_ascii=False)
    _, target = TRANSLATION_LANGUAGES[language_slug]
    return (
        f"Translate each string into {target}.\n"
        "Rules:\n"
        "- Preserve exact meaning and intent (these are security red-team test prompts).\n"
        "- Keep tool names, API field names, JSON keys, file paths, and code identifiers "
        "in their original form.\n"
        "- Do not add explanations, prefixes, or markdown.\n"
        "- Each output string must be a single line with no newline characters.\n"
        "- Return ONLY a JSON array of translated strings in the same order as the input.\n\n"
        f"Input:\n{payload}"
    )


def translate_texts(texts: list[str], language_slug: str) -> list[str]:
    slug = (language_slug or "").strip().lower()
    if slug not in UI_LANGUAGES:
        raise ValueError(f"Unknown translation language: {language_slug}")
    if not texts:
        return []

    prompt = _build_translate_user_prompt(texts, slug)

    text = complete(
        "prompt_transforms",
        system=prompt_transform_system_prompt(),
        user=prompt,
    ).text
    translated = parse_llm_json_string_array(text, len(texts), context="Translation")
    return translated


def translate_suite(data: dict, language: str) -> tuple[dict, int]:
    import copy

    slug = (language or "").strip().lower()
    if slug not in UI_LANGUAGES:
        raise ValueError(f"Unknown translation language: {language}")

    suite = copy.deepcopy(data)
    entries = collect_plain_text_entries(suite)
    if not entries:
        return suite, 0

    sources = [normalize_prompt_text(plain_text_for_entry(prompt, kind, idx)) for prompt, kind, idx, _ in entries]
    translated_all: list[str] = []
    for start in range(0, len(sources), _BATCH_SIZE):
        batch = sources[start : start + _BATCH_SIZE]
        translated_all.extend(translate_texts(batch, slug))

    for (prompt, kind, idx, _), text in zip(entries, translated_all):
        apply_text_to_entry(prompt, kind, idx, text)
        capture_plain_source(prompt)
        prompt[TRANSLATION_KEY] = slug
        prompt.pop(NATIVE_KEY, None)
        prompt.pop(FRAME_KEY, None)
        prompt.pop(TECHNIQUE_KEY, None)
        prompt.pop(CODE_KEY, None)
        prompt.pop(CIPHER_KEY, None)
        prompt.pop(CONTROL_CODE_KEY, None)
        prompt.pop(IQ_KEY, None)
        prompt.pop(EMOTION_KEY, None)
        prompt.pop(ATTRIBUTES_KEY, None)

    return suite, len(entries)
