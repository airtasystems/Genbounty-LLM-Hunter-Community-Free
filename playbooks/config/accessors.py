"""Playbook config section getters and prompt filter helpers."""
from __future__ import annotations

import copy
import re
from typing import Any

from playbooks.config.constants import (
    CANONICAL_ADAPTIVE_SEED_GUIDANCE,
    CANONICAL_DELIVERY_PROMPT_RULES,
    CONFIG_KEY,
    ENHANCEMENT_THESIS_VALUES,
    _META_LEAKAGE_NEEDLES,
    _VALID_DELIVERY_TRANSFORM_KINDS,
    _VALID_DELIVERY_TRANSFORM_MODES,
    _VALID_PROBE_PRIORITIES,
    _as_dict,
    _batch_keep_floor,
    _delivery_from_play_prose,
    _distinctive_content_words,
    _strategy_is_adaptive,
    _truncate,
)

def normalized_playbook_config(playbook: dict[str, Any] | None) -> dict[str, Any]:
    """Return playbook_config with legacy top-level fields merged in."""
    if not isinstance(playbook, dict):
        return {}

    raw = playbook.get(CONFIG_KEY)
    cfg = copy.deepcopy(raw) if isinstance(raw, dict) else {}

    adaptive = _as_dict(cfg.get("adaptive"))
    if str(playbook.get("adaptive_delivery") or "").strip() and not adaptive.get("delivery_constraints"):
        adaptive["delivery_constraints"] = str(playbook.get("adaptive_delivery") or "").strip()
    if adaptive:
        cfg["adaptive"] = adaptive

    recon = _as_dict(cfg.get("recon"))
    legacy_hints = playbook.get("recon_probe_hints")
    if isinstance(legacy_hints, list) and legacy_hints and not recon.get("probe_hints"):
        recon["probe_hints"] = copy.deepcopy(legacy_hints)
    if recon:
        cfg["recon"] = recon

    return cfg


def get_playbook_config(playbook: dict[str, Any] | None) -> dict[str, Any]:
    return normalized_playbook_config(playbook)


def get_adaptive_section(playbook: dict[str, Any] | None) -> dict[str, Any]:
    return _as_dict(get_playbook_config(playbook).get("adaptive"))


def get_recon_section(playbook: dict[str, Any] | None) -> dict[str, Any]:
    return _as_dict(get_playbook_config(playbook).get("recon"))


def get_generation_section(playbook: dict[str, Any] | None) -> dict[str, Any]:
    return _as_dict(get_playbook_config(playbook).get("generation"))


def get_enhancement_section(playbook: dict[str, Any] | None) -> dict[str, Any]:
    return _as_dict(get_playbook_config(playbook).get("enhancement"))


def get_assessment_section(playbook: dict[str, Any] | None) -> dict[str, Any]:
    return _as_dict(get_playbook_config(playbook).get("assessment"))


def get_assessment_oracles(playbook: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return explicitly configured oracle definitions without mutating the playbook."""
    raw = get_assessment_section(playbook).get("oracles")
    if not isinstance(raw, list):
        return []
    return [copy.deepcopy(row) for row in raw if isinstance(row, dict)]


def apply_delivery_to_seeds(
    playbook: dict[str, Any] | None,
    *,
    strategy: str = "",
) -> bool:
    """Whether delivery_constraints must appear in generated seed prompts.

    Adaptive seeds are short openers; delivery rails apply at runtime follow-ups
    only, so adaptive generation always returns False here.
    """
    if _strategy_is_adaptive(strategy):
        return False
    if not isinstance(playbook, dict):
        return False
    generation = get_generation_section(playbook)
    explicit = generation.get("apply_delivery_to_seeds")
    if explicit is False:
        return False
    if explicit is True:
        return True
    return bool(get_adaptive_delivery_constraints(playbook))


def get_generation_mandatory_directives(playbook: dict[str, Any] | None) -> list[str]:
    if not isinstance(playbook, dict):
        return []
    raw = get_generation_section(playbook).get("mandatory_directives")
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def get_escalation_payload(playbook: dict[str, Any] | None) -> str:
    """Optional post-canary harmful ask for Enhance / Auto-run escalation.

    Kept separate from :func:`get_attack_objective` so first-suite seeds can prove
    delivery with a canary/marker without embedding the full leaf harmful ask.
    """
    return _truncate(
        str(get_generation_section(playbook).get("escalation_payload") or "").strip(),
        1200,
    )


def get_escalation_payload_expanded(playbook: dict[str, Any] | None) -> str:
    """Lexicon-expanded escalation payload (empty when unset)."""
    from playbooks.config.lexicon import expand_lexicon_text, get_objective_lexicon
    return expand_lexicon_text(get_escalation_payload(playbook), get_objective_lexicon(playbook))


def get_delivery_transforms(playbook: dict[str, Any] | None) -> dict[str, Any]:
    """Normalized ``generation.delivery_transforms`` or empty dict when unset/invalid."""
    if not isinstance(playbook, dict):
        return {}
    raw = get_generation_section(playbook).get("delivery_transforms")
    if not isinstance(raw, dict):
        return {}
    mode = str(raw.get("mode") or "replace").strip().lower() or "replace"
    if mode not in _VALID_DELIVERY_TRANSFORM_MODES:
        mode = "replace"
    transforms: list[dict[str, str]] = []
    for row in raw.get("transforms") or []:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind") or "").strip().lower()
        name = str(row.get("name") or "").strip().lower()
        if kind in _VALID_DELIVERY_TRANSFORM_KINDS and name:
            transforms.append({"kind": kind, "name": name})
    if not transforms:
        return {}
    return {"mode": mode, "transforms": transforms}


def prompt_embeds_phrase(prompt: str, phrase: str) -> bool:
    """True when a prompt embeds ``phrase`` verbatim or via distinctive content words.

    Soft match requires at least two distinctive words from the phrase (not every
    word). Requiring *all* distinctive words was wiping most of a batch when the
    model paraphrased the ask.
    """
    text = str(prompt or "").strip().lower()
    needle = str(phrase or "").strip().lower()
    if not text or not needle:
        return False
    if needle in text:
        return True
    words = _distinctive_content_words(needle)
    if len(words) < 2:
        return bool(words) and words[0] in text
    hits = sum(1 for w in words if w in text)
    return hits >= 2


def row_prompt_blob(row: dict[str, Any] | None) -> str:
    """Join single-turn ``prompt`` plus multi-turn ``prompts[]`` (and description).

    Tree-of-thoughts / multi-shot rows store turns in ``prompts`` only; filters that
    inspect ``prompt`` alone treat those rows as empty and can wipe a whole batch.
    """
    if not isinstance(row, dict):
        return ""
    parts = [
        str(row.get("prompt") or ""),
        str(row.get("description") or ""),
    ]
    prompts = row.get("prompts")
    if isinstance(prompts, list):
        parts.extend(str(p) for p in prompts if p is not None)
    return "\n".join(parts)


def prompt_embeds_attack_objective(prompt: str, playbook: dict[str, Any] | None) -> bool:
    """True when a prompt concretely demands the expanded attack_objective.

    Callers that generate with ``{{KEY}}`` tokens must expand prompts via
    :func:`expand_prompts_lexicon` before this check. When a lexicon is set,
    presence of every lexicon *value* also counts (paraphrase-tolerant).
    """
    from playbooks.config.lexicon import get_attack_objective_expanded, get_objective_lexicon
    if prompt_embeds_phrase(prompt, get_attack_objective_expanded(playbook)):
        return True
    lexicon = get_objective_lexicon(playbook)
    if not lexicon:
        return False
    text = str(prompt or "").strip().lower()
    values = [str(v).strip().lower() for v in lexicon.values() if str(v).strip()]
    return bool(values) and all(v in text for v in values)


def filter_prompts_missing_attack_objective(
    prompts: list[dict[str, Any]],
    playbook: dict[str, Any] | None,
    *,
    n: int | None = None,
) -> tuple[list[dict[str, Any]], list[tuple[str, list[str]]]]:
    """Drop prompts that do not concretely demand attack_objective when it is set.

    Expects prompts already lexicon-expanded when ``objective_lexicon`` is set.
    Preferentially drops non-matching rows first (from the end) down to
    :func:`batch_keep_floor`, so wrapper-only paraphrases lose to objective-bearing
    prompts instead of being kept because they appeared early in the batch.
    """
    from playbooks.config.lexicon import get_attack_objective

    if not get_attack_objective(playbook):
        return list(prompts or []), []
    expected = n if n is not None else len(prompts or [])
    floor = _batch_keep_floor(expected)
    working = [row for row in (prompts or []) if isinstance(row, dict)]
    match_flags = [
        prompt_embeds_attack_objective(row_prompt_blob(row).strip(), playbook)
        for row in working
    ]
    kept = list(working)
    flags = list(match_flags)
    dropped: list[tuple[str, list[str]]] = []
    # Drop non-matching from the end while above the keep floor.
    for i in range(len(kept) - 1, -1, -1):
        if len(kept) <= floor:
            break
        if flags[i]:
            continue
        pid = str(kept[i].get("id") or "?")
        dropped.append((pid, ["missing attack_objective"]))
        kept.pop(i)
        flags.pop(i)
    return kept, dropped


def prompt_has_meta_leakage(prompt: str) -> bool:
    """True when a prompt leaks enhance/theory meta key names or markers."""
    text = str(prompt or "").strip().lower()
    if not text:
        return False
    return any(needle in text for needle in _META_LEAKAGE_NEEDLES)


def filter_prompts_meta_leakage(
    prompts: list[dict[str, Any]],
    *,
    n: int | None = None,
) -> tuple[list[dict[str, Any]], list[tuple[str, list[str]]]]:
    """Soft-drop prompts that embed enhance meta tokens (never skip on auto_escalate).

    Never drops below :func:`_batch_keep_floor` of the expected batch size.
    """
    expected = n if n is not None else len(prompts or [])
    floor = _batch_keep_floor(expected)
    kept: list[dict[str, Any]] = []
    dropped: list[tuple[str, list[str]]] = []
    working = list(prompts or [])
    for i, row in enumerate(working):
        if not isinstance(row, dict):
            continue
        text = row_prompt_blob(row).strip()
        pid = str(row.get("id") or "?")
        if not prompt_has_meta_leakage(text):
            kept.append(row)
            continue
        future = sum(
            1 for j in range(i + 1, len(working)) if isinstance(working[j], dict)
        )
        if len(kept) + future >= floor:
            dropped.append((pid, ["meta leakage (enhance key/marker)"]))
        else:
            kept.append(row)
    return kept, dropped


def prompt_embeds_escalation_payload(
    prompt: str,
    playbook: dict[str, Any] | None,
) -> bool:
    """True when a prompt pastes the play's escalation_payload (phase-two ask)."""
    esc = str(
        get_escalation_payload_expanded(playbook) or get_escalation_payload(playbook) or ""
    ).strip()
    if len(esc) < 24:
        return False
    text = str(prompt or "").strip().lower()
    if not text:
        return False
    needle = esc.lower()
    if needle in text:
        return True
    # Substantial leading chunk still counts (model may truncate trailing clauses).
    chunk = needle[:96].strip()
    return len(chunk) >= 40 and chunk in text


def filter_prompts_embedding_escalation_payload(
    prompts: list[dict[str, Any]],
    playbook: dict[str, Any] | None,
    *,
    n: int | None = None,
) -> tuple[list[dict[str, Any]], list[tuple[str, list[str]]]]:
    """Soft-drop phase-one seeds that embed the escalate replacement text.

    Callers must skip this filter when Auto-run escalation (or open-broaden with a
    replacement ask) is active. Never drops below the batch keep floor.
    """
    if not get_escalation_payload(playbook):
        return list(prompts or []), []
    expected = n if n is not None else len(prompts or [])
    floor = _batch_keep_floor(expected)
    kept: list[dict[str, Any]] = []
    dropped: list[tuple[str, list[str]]] = []
    working = list(prompts or [])
    for i, row in enumerate(working):
        if not isinstance(row, dict):
            continue
        text = row_prompt_blob(row).strip()
        pid = str(row.get("id") or "?")
        if not prompt_embeds_escalation_payload(text, playbook):
            kept.append(row)
            continue
        future = sum(
            1 for j in range(i + 1, len(working)) if isinstance(working[j], dict)
        )
        if len(kept) + future >= floor:
            dropped.append((pid, ["escalation_in_phase_one"]))
        else:
            kept.append(row)
    return kept, dropped


def _derived_delivery_prompt_rules(
    playbook: dict[str, Any] | None,
    *,
    strategy: str = "",
) -> list[dict[str, str]]:
    """Canonical regex checks for script write → run delivery rails (not user-editable)."""
    if not isinstance(playbook, dict):
        return []
    if not apply_delivery_to_seeds(playbook, strategy=strategy):
        return []
    delivery = get_adaptive_delivery_constraints(playbook).lower()
    if "run the script" in delivery or "run the script using" in delivery:
        return [dict(rule) for rule in CANONICAL_DELIVERY_PROMPT_RULES]
    return []


def get_prompt_requirement_rules(
    playbook: dict[str, Any] | None,
    *,
    strategy: str = "",
) -> list[dict[str, str]]:
    """Regex rules that every generated prompt must satisfy (all rules must match)."""
    if _strategy_is_adaptive(strategy):
        return []
    derived = _derived_delivery_prompt_rules(playbook, strategy=strategy)
    if derived:
        return derived
    if not isinstance(playbook, dict):
        return []
    generation = get_generation_section(playbook)
    reqs = generation.get("prompt_requirements")
    if isinstance(reqs, dict):
        rules = reqs.get("rules")
        if isinstance(rules, list):
            return _normalize_prompt_rules(rules)
    if isinstance(reqs, list):
        return _normalize_prompt_rules(reqs)
    return []


def _normalize_prompt_rules(rules: list[Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rules:
        if not isinstance(row, dict):
            continue
        pattern = str(row.get("pattern") or "").strip()
        if not pattern:
            continue
        out.append(
            {
                "label": str(row.get("label") or "requirement")[:80],
                "pattern": pattern,
            }
        )
    return out


def prompt_meets_playbook_requirements(
    prompt: str,
    playbook: dict[str, Any] | None,
    *,
    strategy: str = "",
) -> tuple[bool, list[str]]:
    """Return (ok, missing_rule_labels)."""
    text = str(prompt or "").strip()
    rules = get_prompt_requirement_rules(playbook, strategy=strategy)
    if not text or not rules:
        return True, []
    missing: list[str] = []
    for rule in rules:
        try:
            if not re.search(rule["pattern"], text):
                missing.append(rule["label"])
        except re.error:
            continue
    return not missing, missing


def get_adaptive_delivery_constraints(playbook: dict[str, Any] | None) -> str:
    """Structured delivery rail, else operational tail extracted from play prose."""
    if not isinstance(playbook, dict):
        return ""
    explicit = str(get_adaptive_section(playbook).get("delivery_constraints") or "").strip()
    if explicit:
        return _truncate(explicit, 2000)
    return _delivery_from_play_prose(playbook)


def get_adaptive_seed_guidance(playbook: dict[str, Any] | None) -> str:
    """Opening-seed instructions for adaptive generation.

    Prefer authored ``generation.strategies.adaptive.seed_guidance`` (reasoning hunts
    store phase-1 rails there). Fall back to canonical short-opener when a delivery
    rail exists, then legacy top-level adaptive.seed_guidance.
    """
    if not isinstance(playbook, dict):
        return ""
    strategy_seed = _strategy_seed_guidance(playbook, "adaptive")
    if strategy_seed:
        return _truncate(strategy_seed)
    # Prefer short-opener canonical guidance whenever a delivery rail exists
    # (rail is completed at runtime, not in the seed).
    if get_adaptive_delivery_constraints(playbook):
        return CANONICAL_ADAPTIVE_SEED_GUIDANCE
    adaptive = get_adaptive_section(playbook)
    direct = str(adaptive.get("seed_guidance") or "").strip()
    if direct:
        return _truncate(direct)
    return ""


def _coerce_mandatory_directives(raw: Any) -> list[str] | None:
    """Normalize LLM/operator mandatory_directives to a string list (or None to drop)."""
    if raw is None:
        return None
    if isinstance(raw, list):
        out = [str(item).strip() for item in raw if str(item).strip()]
        return out
    if isinstance(raw, str):
        lines: list[str] = []
        for line in raw.splitlines():
            item = re.sub(r"^[-*•]\s+", "", line.strip()).strip()
            if item:
                lines.append(item)
        if not lines and raw.strip():
            lines = [raw.strip()]
        return lines
    return None


def _coerce_int_field(raw: Any, *, minimum: int) -> int | None:
    """Coerce int or digit-string adaptive limits; return None when invalid."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw >= minimum else None
    if isinstance(raw, float) and raw.is_integer():
        value = int(raw)
        return value if value >= minimum else None
    if isinstance(raw, str):
        text = raw.strip()
        if text.isdigit():
            value = int(text)
            return value if value >= minimum else None
    return None


def _coerce_probe_hints(raw: Any) -> list[dict[str, Any]]:
    """Normalize recon.probe_hints rows; drop entries that still lack ``need``."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        need = str(row.get("need") or "").strip()
        if not need:
            for alt in ("description", "question", "gap", "ask", "hint"):
                need = str(row.get(alt) or "").strip()
                if need:
                    break
        if not need:
            topic = str(row.get("topic") or "").strip()
            if topic:
                need = f"Clarify target behavior for {topic}"
        if not need:
            continue
        priority = str(row.get("priority") or "medium").strip().lower() or "medium"
        if priority not in _VALID_PROBE_PRIORITIES:
            priority = "medium"
        topic = str(row.get("topic") or "").strip()
        if not topic:
            topic = re.sub(r"[^a-z0-9]+", "_", need.lower())[:32] or "recon_gap"
        hint = str(row.get("hint") or "").strip()
        if not hint:
            hint = (
                "Ask a professional analyst question that closes this gap "
                "without exploit framing."
            )
        out.append(
            {
                "priority": priority,
                "topic": topic[:40],
                "need": need[:320],
                "hint": hint[:400],
            }
        )
    return out


def _coerce_enhancement_thesis(enhancement: dict[str, Any]) -> None:
    """Keep enhancement.thesis as harm|mechanism, or drop so missions default to harm."""
    if "thesis" not in enhancement:
        return
    raw = enhancement.get("thesis")
    if raw is None:
        enhancement.pop("thesis", None)
        return
    text = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not text:
        enhancement.pop("thesis", None)
        return
    if text in ENHANCEMENT_THESIS_VALUES:
        enhancement["thesis"] = text
        return
    # Common author-LLM near-misses.
    if text in {"harmful", "harm_based", "payload", "prohibited_ask", "ask"}:
        enhancement["thesis"] = "harm"
        return
    if text in {
        "mech",
        "channel",
        "mechanism_based",
        "control",
        "instruction_control",
        "ack",
    }:
        enhancement["thesis"] = "mechanism"
        return
    enhancement.pop("thesis", None)


def _coerce_delivery_transforms(generation: dict[str, Any]) -> None:
    """Drop empty/invalid delivery_transforms stubs (runtime treats them as unset)."""
    raw = generation.get("delivery_transforms")
    if raw is None:
        return
    if not isinstance(raw, dict):
        generation.pop("delivery_transforms", None)
        return
    mode = str(raw.get("mode") or "replace").strip().lower() or "replace"
    if mode not in _VALID_DELIVERY_TRANSFORM_MODES:
        generation.pop("delivery_transforms", None)
        return
    transforms: list[dict[str, str]] = []
    for row in raw.get("transforms") or []:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind") or "").strip().lower()
        name = str(row.get("name") or "").strip().lower()
        if kind in _VALID_DELIVERY_TRANSFORM_KINDS and name:
            transforms.append({"kind": kind, "name": name})
    if not transforms:
        generation.pop("delivery_transforms", None)
        return
    generation["delivery_transforms"] = {"mode": mode, "transforms": transforms}


def canonicalize_playbook_config_storage(data: dict[str, Any]) -> None:
    """Drop derived fields and coerce common LLM shape quirks for storage."""
    cfg = data.get(CONFIG_KEY)
    if not isinstance(cfg, dict):
        return

    generation = cfg.get("generation")
    if not isinstance(generation, dict):
        generation = {}
        # Keep a local handle only when we need to migrate adaptive seed guidance.
    else:
        generation.pop("seed_guidance", None)
        generation.pop("prompt_requirements", None)
        if "mandatory_directives" in generation:
            coerced = _coerce_mandatory_directives(generation.get("mandatory_directives"))
            if coerced:
                generation["mandatory_directives"] = coerced
            else:
                generation.pop("mandatory_directives", None)
        _coerce_delivery_transforms(generation)
        # Normalize optional prompt envelope fields (drop empties).
        for key in ("prompt_template", "prompt_task", "prompt_format"):
            if key not in generation:
                continue
            val = str(generation.get(key) or "").strip()
            if val:
                generation[key] = val
            else:
                generation.pop(key, None)
        strategies = generation.get("strategies")
        if strategies is not None and not isinstance(strategies, dict):
            generation.pop("strategies", None)
            strategies = None
        if isinstance(strategies, dict) and not strategies:
            generation.pop("strategies", None)

    adaptive = cfg.get("adaptive")
    if isinstance(adaptive, dict):
        # Migrate legacy top-level adaptive.seed_guidance into strategies.adaptive
        # before dropping the derived top-level field.
        legacy_seed = str(adaptive.pop("seed_guidance", None) or "").strip()
        if legacy_seed:
            if not isinstance(cfg.get("generation"), dict):
                cfg["generation"] = generation if generation else {}
                generation = cfg["generation"]
            strategies = generation.get("strategies")
            if not isinstance(strategies, dict):
                strategies = {}
                generation["strategies"] = strategies
            entry = strategies.get("adaptive")
            if not isinstance(entry, dict):
                entry = {}
                strategies["adaptive"] = entry
            if not str(entry.get("seed_guidance") or "").strip():
                entry["seed_guidance"] = legacy_seed
        for key, minimum in (("max_turns", 2), ("max_llm_calls", 1)):
            if key not in adaptive:
                continue
            coerced_int = _coerce_int_field(adaptive.get(key), minimum=minimum)
            if coerced_int is None:
                adaptive.pop(key, None)
            else:
                adaptive[key] = coerced_int

    recon = cfg.get("recon")
    if isinstance(recon, dict) and "probe_hints" in recon:
        coerced_hints = _coerce_probe_hints(recon.get("probe_hints"))
        recon["probe_hints"] = coerced_hints if coerced_hints else []

    enhancement = cfg.get("enhancement")
    if isinstance(enhancement, dict):
        _coerce_enhancement_thesis(enhancement)


def get_adaptive_followup_guidance(playbook: dict[str, Any] | None) -> str:
    return _truncate(str(get_adaptive_section(playbook).get("followup_guidance") or "").strip())


def get_adaptive_runtime_limits(playbook: dict[str, Any] | None) -> tuple[int | None, int | None]:
    adaptive = get_adaptive_section(playbook)
    max_turns = adaptive.get("max_turns")
    max_llm = adaptive.get("max_llm_calls")
    turns = int(max_turns) if isinstance(max_turns, int) and max_turns >= 2 else None
    calls = int(max_llm) if isinstance(max_llm, int) and max_llm >= 1 else None
    return turns, calls


def _strategy_seed_guidance(playbook: dict[str, Any] | None, strategy: str) -> str:
    generation = get_generation_section(playbook)
    strategies = _as_dict(generation.get("strategies"))
    block = _as_dict(strategies.get(strategy))
    return str(block.get("seed_guidance") or "").strip()


def get_generation_expert_guidance(playbook: dict[str, Any] | None) -> str:
    return _truncate(str(get_generation_section(playbook).get("expert_guidance") or "").strip())


def get_enhancement_theory_guidance(playbook: dict[str, Any] | None) -> str:
    return _truncate(str(get_enhancement_section(playbook).get("theory_guidance") or "").strip())


def _playbook_family_prefix(playbook: dict[str, Any] | None) -> str:
    """Return L1 family id from play_category or playbook_id (e.g. data, other)."""
    if not isinstance(playbook, dict):
        return ""
    cat = str(playbook.get("play_category") or "").strip().lower()
    if cat:
        return cat.split(".", 1)[0]
    pid = str(playbook.get("playbook_id") or "").strip().lower()
    if not pid:
        return ""
    return pid.split("_", 1)[0]


def get_enhancement_thesis(playbook: dict[str, Any] | None) -> str:
    """Return enhancement thesis: explicit ``mechanism``/``harm``, else ``harm``.

    Missions default to harm thesis when ``enhancement.thesis`` is unset.
    """
    if not isinstance(playbook, dict):
        return ""
    raw = get_enhancement_section(playbook).get("thesis")
    if isinstance(raw, str):
        explicit = raw.strip().lower()
        if explicit in ENHANCEMENT_THESIS_VALUES:
            return explicit
    family = _playbook_family_prefix(playbook)
    if not family:
        return ""
    return "harm"


def get_recon_probe_hints(playbook: dict[str, Any] | None) -> list[dict[str, str]]:
    recon = get_recon_section(playbook)
    raw = recon.get("probe_hints")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        need = str(row.get("need") or "").strip()
        if not need:
            continue
        priority = str(row.get("priority") or "medium").strip().lower()
        if priority not in _VALID_PROBE_PRIORITIES:
            priority = "medium"
        topic = str(row.get("topic") or "").strip() or re.sub(r"[^a-z0-9]+", "_", need.lower())[:32]
        out.append(
            {
                "priority": priority,
                "topic": topic[:40],
                "need": need[:320],
                "hint": str(row.get("hint") or "").strip()[:400]
                or "Ask a professional analyst question that closes this gap without exploit framing.",
            }
        )
    return out


