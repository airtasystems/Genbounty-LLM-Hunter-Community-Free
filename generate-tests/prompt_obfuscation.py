"""Transform test-suite prompt text with advanced obfuscation techniques."""

from __future__ import annotations

import codecs
import html
from typing import Callable

from payloads.text_utils import normalize_prompt_text
from prompt_suite_backup import (
    ATTRIBUTES_KEY,
    CIPHER_KEY,
    CONTROL_CODE_KEY,
    CODE_KEY,
    EMOTION_KEY,
    IQ_KEY,
    FRAME_KEY,
    NATIVE_KEY,
    PLAIN_KEY,
    TECHNIQUE_KEY,
    TRANSLATION_KEY,
    capture_plain_source,
    restore_prompt_fields,
    restore_suite,
    suite_has_plain_backup,
    suite_transform_meta,
)

# Registry: slug -> (label, transform_fn)
TechniqueFn = Callable[[str], str]

_HOMOGLYPHS: dict[str, str] = {
    "a": "\u0430",
    "c": "\u0441",
    "e": "\u0435",
    "o": "\u043e",
    "p": "\u0440",
    "x": "\u0445",
    "y": "\u0443",
    "A": "\u0410",
    "B": "\u0412",
    "C": "\u0421",
    "E": "\u0415",
    "H": "\u041d",
    "K": "\u041a",
    "M": "\u041c",
    "O": "\u041e",
    "P": "\u0420",
    "T": "\u0422",
    "X": "\u0425",
}

_LEET_MAP: dict[str, str] = {
    "a": "4", "b": "8", "e": "3", "g": "6", "i": "1", "l": "1",
    "o": "0", "s": "5", "t": "7", "z": "2",
}

_MORSE: dict[str, str] = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.",
    "G": "--.", "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..",
    "M": "--", "N": "-.", "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.",
    "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..", "0": "-----", "1": ".----", "2": "..---",
    "3": "...--", "4": "....-", "5": ".....", "6": "-....", "7": "--...",
    "8": "---..", "9": "----.",
}

_ZWSP = "\u200b"
_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _obfuscate_base58(text: str) -> str:
    data = text.encode("utf-8")
    num = int.from_bytes(data, "big")
    if num == 0:
        encoded = _BASE58_ALPHABET[0]
    else:
        chars: list[str] = []
        while num:
            num, rem = divmod(num, 58)
            chars.append(_BASE58_ALPHABET[rem])
        encoded = "".join(reversed(chars))
    pad = 0
    for byte in data:
        if byte == 0:
            pad += 1
        else:
            break
    return (_BASE58_ALPHABET[0] * pad) + encoded


def _obfuscate_uuencode(text: str) -> str:
    raw = codecs.encode(text.encode("utf-8"), "uu").decode("ascii")
    body = [
        line
        for line in raw.splitlines()
        if line and not line.startswith("begin") and line not in {"end", "`"}
    ]
    return "".join(body)


def _obfuscate_rot47(text: str) -> str:
    out: list[str] = []
    for ch in text:
        o = ord(ch)
        if 33 <= o <= 126:
            out.append(chr(33 + ((o - 33 + 47) % 94)))
        else:
            out.append(ch)
    return "".join(out)


def _obfuscate_caesar(text: str) -> str:
    shift = 5

    def shift_char(ch: str) -> str:
        if "a" <= ch <= "z":
            return chr((ord(ch) - ord("a") + shift) % 26 + ord("a"))
        if "A" <= ch <= "Z":
            return chr((ord(ch) - ord("A") + shift) % 26 + ord("A"))
        return ch

    return "".join(shift_char(c) for c in text)


def _obfuscate_hex(text: str) -> str:
    return text.encode("utf-8").hex()


def _obfuscate_binary(text: str) -> str:
    return " ".join(f"{b:08b}" for b in text.encode("utf-8"))


def _obfuscate_leetspeak(text: str) -> str:
    return "".join(_LEET_MAP.get(c, _LEET_MAP.get(c.lower(), c)) if c.lower() in _LEET_MAP else c for c in text)


def _obfuscate_reverse(text: str) -> str:
    return text[::-1]


def _obfuscate_morse(text: str) -> str:
    parts: list[str] = []
    for ch in text.upper():
        if ch == " ":
            parts.append("/")
        elif ch in _MORSE:
            parts.append(_MORSE[ch])
        else:
            parts.append(ch)
    return " ".join(parts)


def _obfuscate_zero_width(text: str) -> str:
    return _ZWSP.join(text)


def _obfuscate_homoglyph(text: str) -> str:
    return "".join(_HOMOGLYPHS.get(c, c) for c in text)


def _obfuscate_html_entities(text: str) -> str:
    return html.escape(text, quote=False)


OBFUSCATION_TECHNIQUES: dict[str, tuple[str, TechniqueFn]] = {
    "base58": ("Base58 encoding", _obfuscate_base58),
    "uuencode": ("Uuencode (Unix)", _obfuscate_uuencode),
    "rot47": ("ROT47", _obfuscate_rot47),
    "caesar": ("Caesar cipher (shift 5)", _obfuscate_caesar),
    "hex": ("Hexadecimal", _obfuscate_hex),
    "binary": ("Binary octets", _obfuscate_binary),
    "leetspeak": ("Leetspeak substitution", _obfuscate_leetspeak),
    "reverse": ("Character reversal", _obfuscate_reverse),
    "morse": ("Morse code", _obfuscate_morse),
    "zero_width": ("Zero-width character insertion", _obfuscate_zero_width),
    "homoglyph": ("Unicode homoglyph substitution", _obfuscate_homoglyph),
    "html_entities": ("HTML entity encoding", _obfuscate_html_entities),
}

UI_TECHNIQUES = tuple(OBFUSCATION_TECHNIQUES.keys())


def list_techniques() -> list[dict[str, str]]:
    return [{"slug": slug, "label": OBFUSCATION_TECHNIQUES[slug][0]} for slug in UI_TECHNIQUES]


def obfuscate_text(text: str, technique: str) -> str:
    slug = (technique or "").strip().lower()
    if slug not in UI_TECHNIQUES:
        raise ValueError(f"Unknown obfuscation technique: {technique}")
    fn = OBFUSCATION_TECHNIQUES[slug][1]
    result = fn(normalize_prompt_text(text))
    if "\n" in result or "\r" in result:
        result = normalize_prompt_text(result)
    return result


def _transform_prompt_fields(prompt: dict, technique: str) -> int:
    plain = capture_plain_source(prompt)
    changed = 0
    slug = technique.strip().lower()

    if isinstance(plain.get("prompt"), str) and plain["prompt"].strip():
        prompt["prompt"] = obfuscate_text(plain["prompt"], slug)
        changed += 1

    if isinstance(plain.get("prompts"), list):
        for i, turn in enumerate(plain["prompts"]):
            if isinstance(turn, str) and turn.strip():
                if not isinstance(prompt.get("prompts"), list):
                    prompt["prompts"] = list(plain["prompts"])
                prompt["prompts"][i] = obfuscate_text(turn, slug)
                changed += 1

    if isinstance(plain.get("examples"), list) and isinstance(prompt.get("examples"), list):
        ex_idx = 0
        for ex in prompt["examples"]:
            if not isinstance(ex, dict):
                continue
            if ex_idx >= len(plain["examples"]):
                break
            source = plain["examples"][ex_idx]
            ex_idx += 1
            if isinstance(source, str) and source.strip():
                ex["prompt"] = obfuscate_text(source, slug)
                changed += 1

    if changed:
        prompt[TECHNIQUE_KEY] = slug
        prompt.pop(TRANSLATION_KEY, None)
        prompt.pop(NATIVE_KEY, None)
        prompt.pop(FRAME_KEY, None)
        prompt.pop(CODE_KEY, None)
        prompt.pop(CIPHER_KEY, None)
        prompt.pop(CONTROL_CODE_KEY, None)
        prompt.pop(IQ_KEY, None)
        prompt.pop(EMOTION_KEY, None)
        prompt.pop(ATTRIBUTES_KEY, None)
    return changed


def obfuscate_suite(data: dict, technique: str) -> tuple[dict, int]:
    import copy

    suite = copy.deepcopy(data)
    total = 0
    for cat in suite.get("categories") or []:
        if not isinstance(cat, dict):
            continue
        for prompt in cat.get("prompts") or []:
            if isinstance(prompt, dict):
                total += _transform_prompt_fields(prompt, technique)
    return suite, total


__all__ = [
    "CODE_KEY",
    "PLAIN_KEY",
    "TECHNIQUE_KEY",
    "TRANSLATION_KEY",
    "list_techniques",
    "obfuscate_suite",
    "obfuscate_text",
    "restore_suite",
    "suite_has_plain_backup",
    "suite_transform_meta",
]
