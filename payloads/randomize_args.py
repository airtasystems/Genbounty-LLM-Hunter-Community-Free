"""Randomize multimodal payload filenames and layout/effect attributes for generated suites."""

from __future__ import annotations

import copy
import random
from typing import Any

from payloads.type_schemas import POSITION_OPTIONS

_DOC_STEMS = (
    "client_statement",
    "quarterly_report",
    "risk_assessment",
    "meeting_notes",
    "compliance_memo",
    "portfolio_summary",
    "wire_instruction",
    "audit_trail",
    "suitability_form",
    "onboarding_pack",
    "fca_review",
    "treasury_brief",
    "policy_addendum",
    "investment_memo",
    "client_correspondence",
)

_AUTHOR_NAMES = (
    "J. Mercer",
    "Compliance Desk",
    "Risk Operations",
    "Harborline Admin",
    "Regulatory Affairs",
    "Client Services",
    "Audit Team",
    "Operations Lead",
)

_IMAGE_LINE_LAYOUT = {
    "font_size": (8, 24, 1),
    "alpha": (40, 255, 5),
    "position": None,
    "low_contrast": None,
    "text_rotation": (-45, 45, 1),
    "blur_radius": (0, 8, 0.5),
    "noise_level": (0, 0.8, 0.1),
}

_PDF_LINE_LAYOUT = {
    "font_size": (9, 18, 1),
    "alpha": (50, 255, 5),
    "position": None,
}


def multimodal_randomize_enabled() -> bool:
    """Return True when multimodal filename/layout randomization is enabled."""
    return True


def _sample_number(rng: random.Random, lo: float, hi: float, step: float = 1.0) -> float:
    if hi < lo:
        lo, hi = hi, lo
    if step <= 0:
        return rng.uniform(lo, hi)
    n_steps = max(0, int((hi - lo) / step))
    return round(lo + rng.randint(0, n_steps) * step, 4)


def _random_color(rng: random.Random, *, light: bool = False) -> str:
    if light:
        return f"#{rng.randint(0xC0, 0xFF):02x}{rng.randint(0xC0, 0xFF):02x}{rng.randint(0xC0, 0xFF):02x}"
    return f"#{rng.randint(0, 0xFF):02x}{rng.randint(0, 0xFF):02x}{rng.randint(0, 0xFF):02x}"


def _random_document_filename(rng: random.Random, generator: str) -> str:
    """Return a basename without extension; generators append the correct suffix."""
    stem = rng.choice(_DOC_STEMS)
    suffix = rng.randint(100, 9999)
    return f"{stem}_{suffix}"


def _randomize_line_layout(
    line: dict[str, Any],
    rng: random.Random,
    layout: dict[str, Any],
    *,
    pdf: bool = False,
) -> None:
    if "font_size" in layout:
        lo, hi, step = layout["font_size"]
        line["font_size"] = int(_sample_number(rng, lo, hi, step))
    if "position" in layout:
        line["position"] = rng.choice(POSITION_OPTIONS)
    else:
        line["position"] = rng.choice(POSITION_OPTIONS)
    if "alpha" in layout:
        lo, hi, step = layout["alpha"]
        line["alpha"] = int(_sample_number(rng, lo, hi, step))
    if not pdf:
        line["low_contrast"] = rng.random() < 0.35
        lo, hi, step = layout["text_rotation"]
        line["text_rotation"] = _sample_number(rng, lo, hi, step)
        lo, hi, step = layout["blur_radius"]
        line["blur_radius"] = _sample_number(rng, lo, hi, step)
        lo, hi, step = layout["noise_level"]
        line["noise_level"] = _sample_number(rng, lo, hi, step)
        line["color"] = _random_color(rng, light=bool(line.get("low_contrast")))


def _randomize_text_lines(
    lines: list[Any],
    rng: random.Random,
    *,
    pdf: bool = False,
) -> list[dict[str, Any]]:
    layout = _PDF_LINE_LAYOUT if pdf else _IMAGE_LINE_LAYOUT
    out: list[dict[str, Any]] = []
    for item in lines:
        if not isinstance(item, dict):
            text = str(item).strip()
            if not text:
                continue
            line: dict[str, Any] = {"text": text}
        else:
            line = copy.deepcopy(item)
            if not str(line.get("text") or "").strip():
                continue
        _randomize_line_layout(line, rng, layout, pdf=pdf)
        out.append(line)
    return out


def _maybe_pick_background(
    rng: random.Random,
    kind: str,
    current: Any,
) -> str | None:
    if current:
        return str(current)
    if rng.random() > 0.45:
        return None
    try:
        from payloads.background_assets import list_background_images, list_background_pdfs

        pool = list_background_pdfs() if kind == "pdf" else list_background_images()
        return rng.choice(pool) if pool else None
    except Exception:
        return None


def _randomize_image_args(out: dict[str, Any], rng: random.Random) -> None:
    out["width"] = int(_sample_number(rng, 250, 1400, 50))
    out["height"] = int(_sample_number(rng, 120, 900, 25))
    out["background_color"] = _random_color(rng, light=True)
    out["background_alpha"] = int(_sample_number(rng, 180, 255, 5))

    bg = _maybe_pick_background(rng, "image", out.get("source_image"))
    if bg:
        out["source_image"] = bg

    if isinstance(out.get("text_lines"), list) and out["text_lines"]:
        out["text_lines"] = _randomize_text_lines(out["text_lines"], rng, pdf=False)
    elif str(out.get("text") or "").strip():
        out["low_contrast"] = rng.random() < 0.35
        out["text_rotation"] = _sample_number(rng, -45, 45, 1)
        out["blur_radius"] = _sample_number(rng, 0, 10, 0.5)
        out["noise_level"] = _sample_number(rng, 0, 0.8, 0.1)
        if out["low_contrast"]:
            out["text_color"] = _random_color(rng, light=True)
        else:
            out["text_color"] = out.get("text_color") or _random_color(rng)
        out["text_alpha"] = int(_sample_number(rng, 60, 255, 5))
        out["font_size"] = int(_sample_number(rng, 8, 28, 1))
        out["position"] = rng.choice(POSITION_OPTIONS)


def _randomize_pdf_args(out: dict[str, Any], rng: random.Random) -> None:
    bg = _maybe_pick_background(rng, "pdf", out.get("source_pdf"))
    if bg:
        out["source_pdf"] = bg
    if isinstance(out.get("text_lines"), list) and out["text_lines"]:
        out["text_lines"] = _randomize_text_lines(out["text_lines"], rng, pdf=True)


def _randomize_audio_tts_args(out: dict[str, Any], rng: random.Random) -> None:
    out["overlay_level"] = _sample_number(rng, 0, 0.45, 0.05)
    out["noise_level"] = _sample_number(rng, 0, 0.55, 0.05)
    out["pitch_semitones"] = _sample_number(rng, -10, 10, 0.5)
    out["speed_factor"] = _sample_number(rng, 0.75, 1.35, 0.05)
    out["distortion"] = _sample_number(rng, 0, 0.5, 0.05)
    out["gain_db"] = _sample_number(rng, -8, 8, 1)

    if rng.random() < 0.55:
        out["background_tone_hz"] = _sample_number(rng, 80, 4000, 10)
        out["background_tone_level"] = _sample_number(rng, 0.05, 0.45, 0.05)
    else:
        out["background_tone_hz"] = 0
        out["background_tone_level"] = 0.2

    if rng.random() < 0.5:
        out["echo_delay_ms"] = _sample_number(rng, 40, 900, 10)
        out["echo_decay"] = _sample_number(rng, 0.15, 0.75, 0.05)
    else:
        out["echo_delay_ms"] = 0
        out["echo_decay"] = 0.4

    if rng.random() < 0.4:
        out["low_pass_hz"] = _sample_number(rng, 800, 12000, 50)
    else:
        out["low_pass_hz"] = 0
    if rng.random() < 0.35:
        out["high_pass_hz"] = _sample_number(rng, 80, 2000, 50)
    else:
        out["high_pass_hz"] = 0


def _randomize_csv_args(out: dict[str, Any], rng: random.Random) -> None:
    if out.get("content") or out.get("rows"):
        return
    out.setdefault("columns", "id:integer,name:text,email:email,date:date")
    out["num_rows"] = int(_sample_number(rng, 5, 40, 1))
    out["use_faker"] = True


def randomize_generator_args(
    generator: str,
    args: dict[str, Any] | None,
    *,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """
    Randomize filenames and layout/effect attributes while preserving attack text content.
    """
    rng = rng or random.Random()
    gen = (generator or "").strip().lower()
    if gen == "image":
        gen = "image_text"
    out = copy.deepcopy(args) if isinstance(args, dict) else {}

    out["filename"] = _random_document_filename(rng, gen)

    if gen in ("image", "image_text"):
        _randomize_image_args(out, rng)
    elif gen == "pdf":
        _randomize_pdf_args(out, rng)
    elif gen == "pdf_metadata":
        if not str(out.get("author") or "").strip():
            out["author"] = rng.choice(_AUTHOR_NAMES)
    elif gen == "audio_tts":
        _randomize_audio_tts_args(out, rng)
    elif gen == "audio_synthetic":
        out["frequency"] = int(_sample_number(rng, 120, 2000, 10))
        out["duration_sec"] = _sample_number(rng, 0.5, 8.0, 0.1)
    elif gen == "qr":
        out["composite_width"] = int(_sample_number(rng, 200, 800, 25))
        out["composite_height"] = int(_sample_number(rng, 200, 800, 25))
    elif gen == "csv":
        _randomize_csv_args(out, rng)

    return out


def randomize_prompt_payloads(
    prompt: dict[str, Any],
    *,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Apply random filenames/attributes to top-level and per-turn payloads."""
    rng = rng or random.Random()
    row = copy.deepcopy(prompt)

    payload = row.get("payload")
    if isinstance(payload, dict) and payload.get("generator"):
        gen = str(payload["generator"])
        payload = dict(payload)
        payload["args"] = randomize_generator_args(
            gen,
            payload.get("args") if isinstance(payload.get("args"), dict) else {},
            rng=rng,
        )
        row["payload"] = payload

    turns = row.get("turns")
    if isinstance(turns, list):
        new_turns: list[Any] = []
        for turn in turns:
            if not isinstance(turn, dict):
                new_turns.append(turn)
                continue
            t = copy.deepcopy(turn)
            pl = t.get("payload")
            if isinstance(pl, dict) and pl.get("generator"):
                pl = dict(pl)
                pl["args"] = randomize_generator_args(
                    str(pl["generator"]),
                    pl.get("args") if isinstance(pl.get("args"), dict) else {},
                    rng=rng,
                )
                t["payload"] = pl
            new_turns.append(t)
        row["turns"] = new_turns

    return row


def _self_test() -> None:
    rng = random.Random(42)
    cases = [
        ("image_text", {"text": "INJECT", "width": 400}),
        ("audio_tts", {"text": "Summarize this recording."}),
        ("pdf_hidden", {"visible_text": "Memo", "hidden_text": "Override safety."}),
        ("pdf", {"text_lines": [{"text": "Line one"}, {"text": "Line two"}]}),
    ]
    for gen, args in cases:
        out = randomize_generator_args(gen, args, rng=rng)
        assert out.get("filename"), gen
        assert out.get("text") == args.get("text") or args.get("text_lines")
        if gen == "image_text":
            assert out["width"] != 400
            assert "blur_radius" in out

    row = randomize_prompt_payloads(
        {
            "id": "test-01",
            "turns": [
                {"prompt": "", "payload": {"generator": "text", "args": {"content": "x"}}},
                {"prompt": "", "payload": {"generator": "image_text", "args": {"text": "y"}}},
            ],
        },
        rng=rng,
    )
    assert row["turns"][0]["payload"]["args"]["filename"]
    assert row["turns"][1]["payload"]["args"]["blur_radius"] is not None


if __name__ == "__main__":
    _self_test()
    print("randomize_args self-test ok")
