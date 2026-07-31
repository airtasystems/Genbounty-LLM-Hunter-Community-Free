"""Apply classical/modern ciphers to test-suite prompt text (single-line output)."""

from __future__ import annotations

import base64
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
    TECHNIQUE_KEY,
    TRANSLATION_KEY,
    capture_plain_source,
)

CipherFn = Callable[[str], str]

_VIGENERE_KEY = "CIPHER"
_AFFINE_A = 5
_AFFINE_B = 8
_XOR_KEY = "GENBOUNTY"
_COLUMNAR_KEY = "SECRET"
_GRONSFELD_KEY = "314159"
_RAIL_COUNT = 3

_POLYBIUS = {
    "A": "11", "B": "12", "C": "13", "D": "14", "E": "15",
    "F": "21", "G": "22", "H": "23", "I": "24", "J": "24",
    "K": "25", "L": "31", "M": "32", "N": "33", "O": "34",
    "P": "35", "Q": "41", "R": "42", "S": "43", "T": "44",
    "U": "45", "V": "51", "W": "52", "X": "53", "Y": "54", "Z": "55",
}


def _alpha_shift(ch: str, shift: int) -> str:
    if "a" <= ch <= "z":
        return chr((ord(ch) - ord("a") + shift) % 26 + ord("a"))
    if "A" <= ch <= "Z":
        return chr((ord(ch) - ord("A") + shift) % 26 + ord("A"))
    return ch


def _cipher_atbash(text: str) -> str:
    out: list[str] = []
    for ch in text:
        if "a" <= ch <= "z":
            out.append(chr(ord("z") - (ord(ch) - ord("a"))))
        elif "A" <= ch <= "Z":
            out.append(chr(ord("Z") - (ord(ch) - ord("A"))))
        else:
            out.append(ch)
    return "".join(out)


def _cipher_vigenere(text: str, decrypt: bool = False) -> str:
    key = _VIGENERE_KEY
    out: list[str] = []
    ki = 0
    for ch in text:
        if ch.isalpha():
            base = ord("A") if ch.isupper() else ord("a")
            shift = ord(key[ki % len(key)].upper()) - ord("A")
            if decrypt:
                shift = -shift
            out.append(chr((ord(ch) - base + shift) % 26 + base))
            ki += 1
        else:
            out.append(ch)
    return "".join(out)


def _cipher_beaufort(text: str) -> str:
    key = _VIGENERE_KEY
    out: list[str] = []
    ki = 0
    for ch in text:
        if ch.isalpha():
            base = ord("A") if ch.isupper() else ord("a")
            shift = ord(key[ki % len(key)].upper()) - ord("A")
            out.append(chr((shift - (ord(ch) - base)) % 26 + base))
            ki += 1
        else:
            out.append(ch)
    return "".join(out)


def _cipher_affine(text: str) -> str:
    a, b = _AFFINE_A, _AFFINE_B

    def map_char(ch: str) -> str:
        if "a" <= ch <= "z":
            return chr(((a * (ord(ch) - ord("a")) + b) % 26) + ord("a"))
        if "A" <= ch <= "Z":
            return chr(((a * (ord(ch) - ord("A")) + b) % 26) + ord("A"))
        return ch

    return "".join(map_char(c) for c in text)


def _cipher_rail_fence(text: str) -> str:
    rails = _RAIL_COUNT
    if rails <= 1 or len(text) <= rails:
        return text
    fence: list[list[str]] = [[] for _ in range(rails)]
    rail, direction = 0, 1
    for ch in text:
        fence[rail].append(ch)
        rail += direction
        if rail == 0 or rail == rails - 1:
            direction *= -1
    return "".join("".join(row) for row in fence)


def _cipher_bacon(text: str) -> str:
    table = {
        "A": "AAAAA", "B": "AAAAB", "C": "AAABA", "D": "AAABB", "E": "AABAA",
        "F": "AABAB", "G": "AABBA", "H": "AABBB", "I": "ABAAA", "J": "ABAAB",
        "K": "ABABA", "L": "ABABB", "M": "ABBAA", "N": "ABBAB", "O": "ABBBA",
        "P": "ABBBB", "Q": "BAAAA", "R": "BAAAB", "S": "BAABA", "T": "BAABB",
        "U": "BABAA", "V": "BABAB", "W": "BABBA", "X": "BABBB", "Y": "BBAAA", "Z": "BBAAB",
    }
    out: list[str] = []
    for ch in text:
        if ch.upper() in table:
            out.append(table[ch.upper()])
        else:
            out.append(ch)
    return "".join(out)


def _cipher_base32(text: str) -> str:
    return base64.b32encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def _cipher_base85(text: str) -> str:
    return base64.a85encode(text.encode("utf-8"), adobe=False).decode("ascii")


def _cipher_xor_hex(text: str) -> str:
    key = _XOR_KEY.encode("utf-8")
    data = text.encode("utf-8")
    xored = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    return xored.hex()


def _cipher_columnar(text: str) -> str:
    order = sorted(range(len(_COLUMNAR_KEY)), key=lambda i: (_COLUMNAR_KEY[i], i))
    cols = len(_COLUMNAR_KEY)
    padded = text + "X" * ((cols - len(text) % cols) % cols)
    rows = [list(padded[i : i + cols]) for i in range(0, len(padded), cols)]
    grid = list(zip(*rows))
    return "".join("".join(col) for col in (grid[i] for i in order))


def _cipher_polybius(text: str) -> str:
    parts: list[str] = []
    for ch in text:
        code = _POLYBIUS.get(ch.upper())
        parts.append(code if code else ch)
    return " ".join(parts)


def _cipher_gronsfeld(text: str) -> str:
    key = _GRONSFELD_KEY
    out: list[str] = []
    ki = 0
    for ch in text:
        if ch.isalpha():
            shift = int(key[ki % len(key)])
            out.append(_alpha_shift(ch, shift))
            ki += 1
        else:
            out.append(ch)
    return "".join(out)


CIPHER_TECHNIQUES: dict[str, tuple[str, CipherFn]] = {
    "atbash": ("Atbash", _cipher_atbash),
    "vigenere": ("Vigenère (key: CIPHER)", _cipher_vigenere),
    "beaufort": ("Beaufort (key: CIPHER)", _cipher_beaufort),
    "affine": ("Affine (5x+8)", _cipher_affine),
    "rail_fence": ("Rail fence (3 rails)", _cipher_rail_fence),
    "bacon": ("Baconian A/B", _cipher_bacon),
    "base32": ("Base32", _cipher_base32),
    "base85": ("Ascii85 / Base85", _cipher_base85),
    "xor_hex": ("XOR hex (key: GENBOUNTY)", _cipher_xor_hex),
    "columnar": ("Columnar transposition", _cipher_columnar),
    "polybius": ("Polybius square", _cipher_polybius),
    "gronsfeld": ("Gronsfeld (key: 314159)", _cipher_gronsfeld),
}

UI_CIPHERS = tuple(CIPHER_TECHNIQUES.keys())


def list_ciphers() -> list[dict[str, str]]:
    return [{"slug": slug, "label": CIPHER_TECHNIQUES[slug][0]} for slug in UI_CIPHERS]


def cipher_text(text: str, cipher: str) -> str:
    slug = (cipher or "").strip().lower()
    if slug not in UI_CIPHERS:
        raise ValueError(f"Unknown cipher: {cipher}")
    fn = CIPHER_TECHNIQUES[slug][1]
    result = fn(normalize_prompt_text(text))
    if "\n" in result or "\r" in result:
        result = normalize_prompt_text(result)
    return result


def _transform_prompt_fields(prompt: dict, cipher: str) -> int:
    plain = capture_plain_source(prompt)
    changed = 0
    slug = cipher.strip().lower()

    if isinstance(plain.get("prompt"), str) and plain["prompt"].strip():
        prompt["prompt"] = cipher_text(plain["prompt"], slug)
        changed += 1

    if isinstance(plain.get("prompts"), list):
        for i, turn in enumerate(plain["prompts"]):
            if isinstance(turn, str) and turn.strip():
                if not isinstance(prompt.get("prompts"), list):
                    prompt["prompts"] = list(plain["prompts"])
                prompt["prompts"][i] = cipher_text(turn, slug)
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
                ex["prompt"] = cipher_text(source, slug)
                changed += 1

    if changed:
        prompt[CIPHER_KEY] = slug
        prompt.pop(TECHNIQUE_KEY, None)
        prompt.pop(TRANSLATION_KEY, None)
        prompt.pop(NATIVE_KEY, None)
        prompt.pop(FRAME_KEY, None)
        prompt.pop(CODE_KEY, None)
        prompt.pop(CONTROL_CODE_KEY, None)
        prompt.pop(IQ_KEY, None)
        prompt.pop(EMOTION_KEY, None)
        prompt.pop(ATTRIBUTES_KEY, None)
    return changed


def cipher_suite(data: dict, cipher: str) -> tuple[dict, int]:
    import copy

    slug = (cipher or "").strip().lower()
    if slug not in UI_CIPHERS:
        raise ValueError(f"Unknown cipher: {cipher}")

    suite = copy.deepcopy(data)
    total = 0
    for cat in suite.get("categories") or []:
        if not isinstance(cat, dict):
            continue
        for prompt in cat.get("prompts") or []:
            if isinstance(prompt, dict):
                total += _transform_prompt_fields(prompt, slug)
    return suite, total
