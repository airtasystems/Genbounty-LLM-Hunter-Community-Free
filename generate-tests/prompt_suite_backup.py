"""Shared plain-English backup for prompt obfuscation and translation."""

from __future__ import annotations

PLAIN_KEY = "_obfuscation_plain"
TECHNIQUE_KEY = "_obfuscation_technique"
TRANSLATION_KEY = "_translation_language"
NATIVE_KEY = "_native_language"
FRAME_KEY = "_frame_technique"
CODE_KEY = "_code_language"
CIPHER_KEY = "_cipher_technique"
CONTROL_CODE_KEY = "_control_code_technique"
IQ_KEY = "_iq_level"
EMOTION_KEY = "_emotion_level"
ATTRIBUTES_KEY = "_prompt_attributes"
PIPELINE_KEY = "_gen_transform_pipeline"


def capture_plain_source(prompt: dict) -> dict:
    """Return stored plain-English backup, seeding it from current fields if needed."""
    existing = prompt.get(PLAIN_KEY)
    if isinstance(existing, dict):
        return existing

    plain: dict = {}
    if isinstance(prompt.get("prompt"), str) and prompt["prompt"].strip():
        plain["prompt"] = prompt["prompt"]
    if isinstance(prompt.get("prompts"), list):
        turns = [t for t in prompt["prompts"] if isinstance(t, str) and t.strip()]
        if turns:
            plain["prompts"] = list(prompt["prompts"])
    if isinstance(prompt.get("examples"), list):
        example_texts: list[str] = []
        for ex in prompt["examples"]:
            if isinstance(ex, dict) and isinstance(ex.get("prompt"), str) and ex["prompt"].strip():
                example_texts.append(ex["prompt"])
        if example_texts:
            plain["examples"] = example_texts
    prompt[PLAIN_KEY] = plain
    return plain


def restore_prompt_fields(prompt: dict) -> int:
    """Restore plain English from backup. Returns count of fields restored."""
    plain = prompt.get(PLAIN_KEY)
    if not isinstance(plain, dict):
        return 0

    restored = 0
    if isinstance(plain.get("prompt"), str):
        prompt["prompt"] = plain["prompt"]
        restored += 1
    if isinstance(plain.get("prompts"), list):
        prompt["prompts"] = list(plain["prompts"])
        restored += len([t for t in plain["prompts"] if isinstance(t, str) and t.strip()])
    if isinstance(plain.get("examples"), list) and isinstance(prompt.get("examples"), list):
        for ex, source in zip(prompt["examples"], plain["examples"]):
            if isinstance(ex, dict) and isinstance(source, str):
                ex["prompt"] = source
                restored += 1

    prompt.pop(PLAIN_KEY, None)
    prompt.pop(TECHNIQUE_KEY, None)
    prompt.pop(TRANSLATION_KEY, None)
    prompt.pop(NATIVE_KEY, None)
    prompt.pop(FRAME_KEY, None)
    prompt.pop(CODE_KEY, None)
    prompt.pop(CIPHER_KEY, None)
    prompt.pop(CONTROL_CODE_KEY, None)
    prompt.pop(IQ_KEY, None)
    prompt.pop(EMOTION_KEY, None)
    prompt.pop(ATTRIBUTES_KEY, None)
    prompt.pop(PIPELINE_KEY, None)
    return restored


def restore_suite(data: dict) -> tuple[dict, int]:
    """Return (suite copy, number of text fields restored to plain English)."""
    import copy

    suite = copy.deepcopy(data)
    total = 0
    for cat in suite.get("categories") or []:
        if not isinstance(cat, dict):
            continue
        for prompt in cat.get("prompts") or []:
            if isinstance(prompt, dict):
                total += restore_prompt_fields(prompt)
    return suite, total


def suite_has_plain_backup(data: dict) -> bool:
    for cat in data.get("categories") or []:
        if not isinstance(cat, dict):
            continue
        for prompt in cat.get("prompts") or []:
            if isinstance(prompt, dict) and isinstance(prompt.get(PLAIN_KEY), dict):
                return True
    return False


def suite_transform_meta(data: dict) -> dict:
    """Return active transform metadata from the first prompt that has any set."""
    technique = None
    language = None
    native_language = None
    frame_technique = None
    code_language = None
    cipher = None
    control_code = None
    iq = None
    emotion = None
    attributes = None
    for cat in data.get("categories") or []:
        if not isinstance(cat, dict):
            continue
        for prompt in cat.get("prompts") or []:
            if not isinstance(prompt, dict):
                continue
            if not technique and prompt.get(TECHNIQUE_KEY):
                technique = prompt[TECHNIQUE_KEY]
            if not language and prompt.get(TRANSLATION_KEY):
                language = prompt[TRANSLATION_KEY]
            if not native_language and prompt.get(NATIVE_KEY):
                native_language = prompt[NATIVE_KEY]
            if not frame_technique and prompt.get(FRAME_KEY):
                frame_technique = prompt[FRAME_KEY]
            if not code_language and prompt.get(CODE_KEY):
                code_language = prompt[CODE_KEY]
            if not cipher and prompt.get(CIPHER_KEY):
                cipher = prompt[CIPHER_KEY]
            if not control_code and prompt.get(CONTROL_CODE_KEY):
                control_code = prompt[CONTROL_CODE_KEY]
            if iq is None and prompt.get(IQ_KEY) is not None:
                iq = prompt[IQ_KEY]
            if emotion is None and prompt.get(EMOTION_KEY) is not None:
                emotion = prompt[EMOTION_KEY]
            if attributes is None and isinstance(prompt.get(ATTRIBUTES_KEY), dict):
                attributes = prompt[ATTRIBUTES_KEY]
    return {
        "technique": technique,
        "language": language,
        "native_language": native_language,
        "frame_technique": frame_technique,
        "code_language": code_language,
        "cipher": cipher,
        "control_code": control_code,
        "iq": iq,
        "emotion": emotion,
        "attributes": attributes,
    }


def collect_plain_text_entries(suite: dict) -> list[tuple[dict, str, int | None, int | None]]:
    """Return [(prompt_dict, field_kind, index, example_index), ...] for plain sources."""
    entries: list[tuple[dict, str, int | None, int | None]] = []
    for cat in suite.get("categories") or []:
        if not isinstance(cat, dict):
            continue
        for prompt in cat.get("prompts") or []:
            if not isinstance(prompt, dict):
                continue
            plain = capture_plain_source(prompt)
            if isinstance(plain.get("prompt"), str) and plain["prompt"].strip():
                entries.append((prompt, "prompt", None, None))
            if isinstance(plain.get("prompts"), list):
                for i, turn in enumerate(plain["prompts"]):
                    if isinstance(turn, str) and turn.strip():
                        entries.append((prompt, "prompts", i, None))
            if isinstance(plain.get("examples"), list):
                for i, source in enumerate(plain["examples"]):
                    if isinstance(source, str) and source.strip():
                        entries.append((prompt, "examples", i, i))
    return entries


def plain_text_for_entry(prompt: dict, field_kind: str, index: int | None) -> str:
    plain = capture_plain_source(prompt)
    if field_kind == "prompt":
        return str(plain.get("prompt") or "")
    if field_kind == "prompts" and index is not None:
        return str(plain["prompts"][index])
    if field_kind == "examples" and index is not None:
        return str(plain["examples"][index])
    return ""


def apply_text_to_entry(prompt: dict, field_kind: str, index: int | None, text: str) -> None:
    if field_kind == "prompt":
        prompt["prompt"] = text
    elif field_kind == "prompts" and index is not None:
        if not isinstance(prompt.get("prompts"), list):
            plain = capture_plain_source(prompt)
            prompt["prompts"] = list(plain.get("prompts") or [])
        prompt["prompts"][index] = text
    elif field_kind == "examples" and index is not None:
        examples = prompt.get("examples")
        if isinstance(examples, list) and index < len(examples) and isinstance(examples[index], dict):
            examples[index]["prompt"] = text
