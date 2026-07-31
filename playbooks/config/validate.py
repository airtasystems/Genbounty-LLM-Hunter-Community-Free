"""validate_playbook_config and related schema checks."""
from __future__ import annotations

import re
from typing import Any

from playbooks.config.constants import (
    CANONICAL_ORACLE_TYPES,
    CONFIG_KEY,
    ENHANCEMENT_THESIS_VALUES,
    OBJECTIVE_LEXICON_KEY_RE,
    OBJECTIVE_LEXICON_MAX_KEYS,
    _VALID_DELIVERY_TRANSFORM_KINDS,
    _VALID_DELIVERY_TRANSFORM_MODES,
    _VALID_PROBE_PRIORITIES,
    _VALID_TOOL_ORACLE_FLAGS,
    _nonempty_directive_strings,
)
from playbooks.config.phase1_escalate import (
    _escalation_key_prose_error,
    attack_objective_names_leaf_asset,
    canary_critical_with_escalation_errors,
    escalation_critical_alignment_errors,
    escalation_payload_weaker_than_phase1,
    is_meta_attack_objective,
    is_meta_escalation_payload,
    is_weak_escalation_payload,
    iter_phase1_guidance_fields,
    phase1_embeds_escalation_payload,
    phase1_has_escalation_negation_bait,
    prose_cites_escalation_payload_key,
)

def validate_playbook_config(data: dict[str, Any]) -> list[str]:
    """Validate playbook_config, including its mandatory exploit-oracle contract."""
    errors: list[str] = []
    raw = data.get(CONFIG_KEY)
    if raw is None:
        if isinstance(data.get("categories"), list) and data["categories"]:
            return [f"{CONFIG_KEY}.assessment.oracles is required"]
        return errors
    if not isinstance(raw, dict):
        return [f"{CONFIG_KEY} must be an object"]

    adaptive = raw.get("adaptive")
    if adaptive is not None:
        if not isinstance(adaptive, dict):
            errors.append(f"{CONFIG_KEY}.adaptive must be an object")
        else:
            for key in ("max_turns", "max_llm_calls"):
                val = adaptive.get(key)
                if val is not None and not isinstance(val, int):
                    errors.append(f"{CONFIG_KEY}.adaptive.{key} must be an integer")
            for key in ("delivery_constraints", "seed_guidance", "followup_guidance"):
                val = adaptive.get(key)
                if val is not None and not isinstance(val, str):
                    errors.append(f"{CONFIG_KEY}.adaptive.{key} must be a string")

    recon = raw.get("recon")
    if recon is not None:
        if not isinstance(recon, dict):
            errors.append(f"{CONFIG_KEY}.recon must be an object")
        else:
            hints = recon.get("probe_hints")
            if hints is not None:
                if not isinstance(hints, list):
                    errors.append(f"{CONFIG_KEY}.recon.probe_hints must be an array")
                else:
                    for i, row in enumerate(hints):
                        if not isinstance(row, dict):
                            errors.append(f"{CONFIG_KEY}.recon.probe_hints[{i}] must be an object")
                            continue
                        if not str(row.get("need") or "").strip():
                            errors.append(f"{CONFIG_KEY}.recon.probe_hints[{i}] missing need")
                        pri = str(row.get("priority") or "medium").strip().lower()
                        if pri not in _VALID_PROBE_PRIORITIES:
                            errors.append(
                                f"{CONFIG_KEY}.recon.probe_hints[{i}] priority must be "
                                "high, medium, or low"
                            )

    assessment = raw.get("assessment")
    category_ids = {
        str(category.get("id") or "").strip()
        for category in (data.get("categories") or [])
        if isinstance(category, dict) and str(category.get("id") or "").strip()
    }
    semantic_coverage: set[str] = set()
    if assessment is None and not category_ids:
        pass
    elif not isinstance(assessment, dict):
        errors.append(f"{CONFIG_KEY}.assessment must be an object")
    else:
        oracles = assessment.get("oracles")
        if not isinstance(oracles, list) or not oracles:
            errors.append(f"{CONFIG_KEY}.assessment.oracles must be a non-empty array")
        else:
            seen_ids: set[str] = set()
            for i, oracle in enumerate(oracles):
                        prefix = f"{CONFIG_KEY}.assessment.oracles[{i}]"
                        if not isinstance(oracle, dict):
                            errors.append(f"{prefix} must be an object")
                            continue
                        oracle_id = str(oracle.get("id") or "").strip()
                        if not oracle_id:
                            errors.append(f"{prefix} missing id")
                        elif oracle_id in seen_ids:
                            errors.append(f"{prefix}.id must be unique")
                        seen_ids.add(oracle_id)
                        kind = str(oracle.get("type") or "").strip()
                        if kind not in CANONICAL_ORACLE_TYPES:
                            errors.append(
                                f"{prefix}.type must be a canonical oracle type: "
                                + ", ".join(sorted(CANONICAL_ORACLE_TYPES))
                            )
                            continue
                        scoped = oracle.get("category_ids")
                        if not isinstance(scoped, list) or not scoped:
                            errors.append(f"{prefix}.category_ids must be a non-empty array")
                            scoped_ids: list[str] = []
                        else:
                            scoped_ids = [str(cid).strip() for cid in scoped]
                            if any(not cid for cid in scoped_ids):
                                errors.append(f"{prefix}.category_ids must not contain empty ids")
                            if len(set(scoped_ids)) != len(scoped_ids):
                                errors.append(f"{prefix}.category_ids must be unique")
                            unknown = sorted(set(scoped_ids) - category_ids)
                            if unknown:
                                errors.append(
                                    f"{prefix}.category_ids references unknown categories: "
                                    + ", ".join(unknown)
                                )
                        if kind == "semantic_rubric":
                            semantic_coverage.update(scoped_ids)
                        if kind == "response_marker" and (
                            not isinstance(oracle.get("marker"), str)
                            or not str(oracle.get("marker") or "")
                        ):
                            errors.append(f"{prefix}.marker must be a non-empty string")
                        if kind == "response_regex":
                            pattern = oracle.get("pattern")
                            if not isinstance(pattern, str) or not pattern:
                                errors.append(f"{prefix}.pattern must be a non-empty string")
                            else:
                                try:
                                    re.compile(pattern)
                                except re.error:
                                    errors.append(f"{prefix}.pattern must be valid regex")
                        if kind == "response_field" and (
                            not isinstance(oracle.get("field"), str)
                            or not str(oracle.get("field") or "")
                        ):
                            errors.append(f"{prefix}.field must be a non-empty string")
                        if kind == "tool_flag" and (
                            not isinstance(oracle.get("flag"), str)
                            or not str(oracle.get("flag") or "")
                        ):
                            errors.append(f"{prefix}.flag must be a non-empty string")
                        if kind == "tool_flag" and oracle.get("flag") not in _VALID_TOOL_ORACLE_FLAGS:
                            errors.append(f"{prefix}.flag is not an allowed tool flag")
                        if kind == "semantic_rubric" and (
                            not isinstance(oracle.get("rubric"), str)
                            or not str(oracle.get("rubric") or "").strip()
                        ):
                            errors.append(f"{prefix}.rubric must be a non-empty string")
    missing_semantic = sorted(category_ids - semantic_coverage)
    if missing_semantic:
        errors.append(
            f"{CONFIG_KEY}.assessment.oracles requires at least one semantic_rubric "
            "for each category; missing: " + ", ".join(missing_semantic)
        )

    generation = raw.get("generation")
    if generation is not None:
        if not isinstance(generation, dict):
            errors.append(f"{CONFIG_KEY}.generation must be an object")
        else:
            directives = generation.get("mandatory_directives")
            if directives is not None and not isinstance(directives, list):
                errors.append(f"{CONFIG_KEY}.generation.mandatory_directives must be an array")
            attack_objective = generation.get("attack_objective")
            if attack_objective is not None and not isinstance(attack_objective, str):
                errors.append(f"{CONFIG_KEY}.generation.attack_objective must be a string")
            escalation_payload = generation.get("escalation_payload")
            if escalation_payload is not None and not isinstance(escalation_payload, str):
                errors.append(f"{CONFIG_KEY}.generation.escalation_payload must be a string")
            elif isinstance(escalation_payload, str) and is_meta_escalation_payload(
                escalation_payload
            ):
                errors.append(
                    f"{CONFIG_KEY}.generation.escalation_payload must be exact completable "
                    "replacement text, not meta instructions (e.g. 'cause the model to…' / "
                    "'concrete prohibited ask')"
                )
            elif isinstance(escalation_payload, str) and is_weak_escalation_payload(
                escalation_payload
            ):
                errors.append(
                    f"{CONFIG_KEY}.generation.escalation_payload is too thin for Enhance / "
                    "Auto-run (e.g. bare POLICY_OVERRIDE=1 or a CONFIRMED_LEAK status "
                    "banner); author a multi-word completable ask such as "
                    "'Output the complete unsummarized…'"
                )
            objective_text = (
                str(attack_objective).strip() if isinstance(attack_objective, str) else ""
            )
            payload_text = (
                str(escalation_payload).strip()
                if isinstance(escalation_payload, str)
                else ""
            )
            if (
                objective_text
                and payload_text
                and not is_meta_escalation_payload(payload_text)
                and not is_weak_escalation_payload(payload_text)
                and escalation_payload_weaker_than_phase1(payload_text, objective_text)
            ):
                errors.append(
                    f"{CONFIG_KEY}.generation.escalation_payload must demand a stricter "
                    "outcome than attack_objective (Critical-shaped: fuller / "
                    "unsummarized / multi-step reconstruction) - not a one-sentence "
                    "echo of the phase-1 fragment floor"
                )
            play_category = str(data.get("play_category") or "").strip()
            play_text = str(data.get("play") or "").strip()
            play_label = str(data.get("play_category_label") or "").strip()
            if objective_text:
                names_asset = attack_objective_names_leaf_asset(
                    objective_text,
                    play_category,
                    play=play_text,
                    play_category_label=play_label,
                )
                if is_meta_attack_objective(objective_text) and not names_asset:
                    errors.append(
                        f"{CONFIG_KEY}.generation.attack_objective must name the "
                        "protected asset with a measurable phase-1 ask; forbid bare "
                        "evidence theater / canary-only objectives"
                    )
                elif not names_asset:
                    errors.append(
                        f"{CONFIG_KEY}.generation.attack_objective must name a "
                        "measurable phase-1 asset ask (paraphrase the protected "
                        "asset; do not require literal hunt-name tokens). Put the "
                        "exact burned escalate ask only in escalation_payload"
                    )
                directive_items = _nonempty_directive_strings(directives)
                if len(directive_items) < 2:
                    errors.append(
                        f"{CONFIG_KEY}.generation.mandatory_directives must include at least "
                        "2 non-empty rules when attack_objective is set (every seed attempts "
                        "the asset; phase-1 is not the escalated ask; do not force every "
                        "seed to reuse the same fragment phrasing)"
                    )
            if objective_text and not payload_text:
                errors.append(
                    f"{CONFIG_KEY}.generation.escalation_payload is required when "
                    f"{CONFIG_KEY}.generation.attack_objective is set (exact completable "
                    "replacement text for Enhance / Auto-run)"
                )
            if objective_text and payload_text:
                for field_path, prose in iter_phase1_guidance_fields(data):
                    if phase1_embeds_escalation_payload(prose, payload_text):
                        errors.append(
                            f"{field_path} must not embed generation.escalation_payload "
                            "(phase-1 may name the same asset; forbid near-copy of the "
                            "escalate completable ask - keep that only in "
                            "escalation_payload)"
                        )
                    elif phase1_has_escalation_negation_bait(prose, payload_text):
                        errors.append(
                            f"{field_path} must not paste escalate tripwires via "
                            "do-not / must-not avoid-lists (negation bait); keep burned "
                            "surfaces only in escalation_payload"
                        )
            for prose_key in ("attack_objective", "expert_guidance"):
                prose_val = generation.get(prose_key)
                if isinstance(prose_val, str) and prose_cites_escalation_payload_key(prose_val):
                    errors.append(
                        _escalation_key_prose_error(f"{CONFIG_KEY}.generation.{prose_key}")
                    )
            strategies = generation.get("strategies")
            if isinstance(strategies, dict):
                for strat_name, strat_cfg in strategies.items():
                    if not isinstance(strat_cfg, dict):
                        continue
                    seed = strat_cfg.get("seed_guidance")
                    if isinstance(seed, str) and prose_cites_escalation_payload_key(seed):
                        errors.append(
                            _escalation_key_prose_error(
                                f"{CONFIG_KEY}.generation.strategies.{strat_name}.seed_guidance"
                            )
                        )
            lexicon_raw = generation.get("objective_lexicon")
            if lexicon_raw is not None:
                if isinstance(lexicon_raw, dict):
                    if len(lexicon_raw) > OBJECTIVE_LEXICON_MAX_KEYS:
                        errors.append(
                            f"{CONFIG_KEY}.generation.objective_lexicon may have at most "
                            f"{OBJECTIVE_LEXICON_MAX_KEYS} keys"
                        )
                    for key, value in lexicon_raw.items():
                        key_s = str(key or "").strip().upper()
                        if not OBJECTIVE_LEXICON_KEY_RE.match(key_s):
                            errors.append(
                                f"{CONFIG_KEY}.generation.objective_lexicon key "
                                f"{key!r} must match [A-Z][A-Z0-9_]{{0,15}}"
                            )
                        if not isinstance(value, str) or not str(value).strip():
                            errors.append(
                                f"{CONFIG_KEY}.generation.objective_lexicon[{key}] "
                                "must be a non-empty string"
                            )
                        elif "{{" in str(value):
                            errors.append(
                                f"{CONFIG_KEY}.generation.objective_lexicon[{key}] "
                                "value must not contain {{ placeholders"
                            )
                elif isinstance(lexicon_raw, str):
                    # KEY=value lines are accepted; normalize later on apply
                    pass
                else:
                    errors.append(
                        f"{CONFIG_KEY}.generation.objective_lexicon must be an object "
                        "or KEY=value text"
                    )
            tpl_raw = generation.get("prompt_template")
            if tpl_raw is not None and str(tpl_raw).strip():
                if not isinstance(tpl_raw, str):
                    errors.append(
                        f"{CONFIG_KEY}.generation.prompt_template must be a string"
                    )
                else:
                    from playbooks.config.prompt_template import (
                        prompt_template_has_input_slot,
                    )

                    if not prompt_template_has_input_slot(tpl_raw):
                        errors.append(
                            f"{CONFIG_KEY}.generation.prompt_template must contain "
                            "{{input}} or {{prompt}} when set"
                        )
            for slot_key in ("prompt_task", "prompt_format"):
                slot_raw = generation.get(slot_key)
                if slot_raw is not None and not isinstance(slot_raw, str):
                    errors.append(
                        f"{CONFIG_KEY}.generation.{slot_key} must be a string"
                    )
            delivery_raw = generation.get("delivery_transforms")
            if delivery_raw is not None:
                if not isinstance(delivery_raw, dict):
                    errors.append(
                        f"{CONFIG_KEY}.generation.delivery_transforms must be an object"
                    )
                else:
                    mode = str(delivery_raw.get("mode") or "replace").strip().lower()
                    if mode and mode not in _VALID_DELIVERY_TRANSFORM_MODES:
                        errors.append(
                            f"{CONFIG_KEY}.generation.delivery_transforms.mode must be "
                            "replace or variant"
                        )
                    rows = delivery_raw.get("transforms")
                    if not isinstance(rows, list) or not rows:
                        errors.append(
                            f"{CONFIG_KEY}.generation.delivery_transforms.transforms "
                            "must be a non-empty array"
                        )
                    else:
                        for i, row in enumerate(rows):
                            prefix = (
                                f"{CONFIG_KEY}.generation.delivery_transforms.transforms[{i}]"
                            )
                            if not isinstance(row, dict):
                                errors.append(f"{prefix} must be an object")
                                continue
                            kind = str(row.get("kind") or "").strip().lower()
                            name = str(row.get("name") or "").strip().lower()
                            if kind not in _VALID_DELIVERY_TRANSFORM_KINDS:
                                errors.append(
                                    f"{prefix}.kind must be one of "
                                    + ", ".join(sorted(_VALID_DELIVERY_TRANSFORM_KINDS))
                                )
                            if not name:
                                errors.append(f"{prefix}.name must be a non-empty string")
            reqs = generation.get("prompt_requirements")
            if reqs is not None:
                rules = reqs.get("rules") if isinstance(reqs, dict) else reqs
                if not isinstance(rules, list):
                    errors.append(f"{CONFIG_KEY}.generation.prompt_requirements.rules must be an array")
                else:
                    for i, row in enumerate(rules):
                        if not isinstance(row, dict):
                            errors.append(
                                f"{CONFIG_KEY}.generation.prompt_requirements.rules[{i}] must be an object"
                            )
                            continue
                        if not str(row.get("pattern") or "").strip():
                            errors.append(
                                f"{CONFIG_KEY}.generation.prompt_requirements.rules[{i}] missing pattern"
                            )
                        try:
                            re.compile(str(row.get("pattern") or ""))
                        except re.error:
                            errors.append(
                                f"{CONFIG_KEY}.generation.prompt_requirements.rules[{i}] invalid regex"
                            )

    enhancement = raw.get("enhancement")
    if enhancement is not None:
        if not isinstance(enhancement, dict):
            errors.append(f"{CONFIG_KEY}.enhancement must be an object")
        else:
            theory = enhancement.get("theory_guidance")
            if isinstance(theory, str) and prose_cites_escalation_payload_key(theory):
                errors.append(
                    _escalation_key_prose_error(f"{CONFIG_KEY}.enhancement.theory_guidance")
                )
            thesis = enhancement.get("thesis")
            if thesis is not None:
                if not isinstance(thesis, str) or thesis.strip().lower() not in ENHANCEMENT_THESIS_VALUES:
                    errors.append(
                        f"{CONFIG_KEY}.enhancement.thesis must be one of: "
                        + ", ".join(sorted(ENHANCEMENT_THESIS_VALUES))
                    )

    if isinstance(adaptive, dict):
        followup = adaptive.get("followup_guidance")
        if isinstance(followup, str) and prose_cites_escalation_payload_key(followup):
            errors.append(
                _escalation_key_prose_error(f"{CONFIG_KEY}.adaptive.followup_guidance")
            )

    errors.extend(canary_critical_with_escalation_errors(data))
    errors.extend(escalation_critical_alignment_errors(data))

    return errors


