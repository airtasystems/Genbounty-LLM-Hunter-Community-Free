"""Playbook authoring service: generate + save orchestration for the web API."""

from __future__ import annotations

import asyncio
import contextlib
import threading

from fastapi import HTTPException, Request
from pydantic import BaseModel

from web.paths import ROOT, ensure_generate_tests_path


class PlaybookConfigBody(BaseModel):
    delivery_constraints: str = ""
    apply_delivery_to_seeds: bool | None = None
    mandatory_directives: str = ""
    expert_guidance: str = ""
    followup_guidance: str = ""
    theory_guidance: str = ""
    attack_objective: str = ""
    # Dict map or KEY=value lines; normalized in playbook_generator / playbook_config.
    # Legacy: still accepted for old clients / on-disk plays; Plan Mission UX uses
    # prompt_template instead.
    objective_lexicon: dict[str, str] | str | None = None
    # None = leave existing value alone on regenerate; "" = clear; non-empty = set.
    prompt_template: str | None = None
    prompt_task: str | None = None
    prompt_format: str | None = None


class GeneratePlaybookBody(BaseModel):
    name: str
    play: str
    play_category: str = ""
    play_category_path: list[str] = []
    play_category_label: str = ""
    success_rules: str = ""
    failure_rules: str = ""
    stop_words: str = ""
    playbook_id: str = ""
    overwrite: bool = False
    # UI Regenerate: rebuild categories/triggers/guidance from attack_objective + play.
    # Skips category-preset rule refill and ignores stale objective-coupled guidance.
    rebuild_from_objective: bool = False
    # Create-play wizard: "ai" injects structure-only gold craft into the author prompt.
    authoring_mode: str = "human"
    # When True with authoring_mode "ai", keep the operator Mission brief verbatim
    # (no bounty-claim rewrite in author/critic prompts or post-processing).
    keep_play_verbatim: bool = False
    # Optional exact canary string → locked success/fail + response_marker + phase-1 ask.
    exact_canary: str = ""
    site: str = ""
    component: str = ""
    playbook_config: PlaybookConfigBody | None = None


def playbook_contract_detail(errors: list[str]) -> dict:
    """Stable 422 body for leaf, capability, oracle, and vector failures."""
    rows = []
    for error in errors:
        low = error.lower()
        if "oracle" in low or "assessment" in low:
            code = "oracle_contract"
        elif "vector" in low or "delivery" in low or "artifact" in low:
            code = "vector_contract"
        elif "capabilit" in low:
            code = "capability_contract"
        elif "category" in low or "play_category" in low:
            code = "leaf_contract"
        else:
            code = "playbook_contract"
        rows.append({"code": code, "message": error})
    return {"code": "invalid_playbook_contract", "errors": rows}


async def generate_and_save(body: GeneratePlaybookBody, request: Request) -> dict:
    ensure_generate_tests_path()
    from playbook_generator import (
        PlaybookGenerationCancelled,
        exact_canary_attack_objective,
        exact_canary_failure_rule,
        exact_canary_success_rule,
        extract_exact_canary_from_playbook,
        generate_playbook_json,
        save_playbook,
        slugify_playbook_id,
        validate_playbook,
    )
    from playbooks.categories import resolve_play_category

    display_name = body.name.strip()
    if not display_name:
        raise HTTPException(400, "name is required")
    play = body.play.strip()
    if len(play) < 15:
        raise HTTPException(400, "play must be at least 15 characters")
    playbook_id = slugify_playbook_id(body.playbook_id or display_name)
    if not playbook_id or playbook_id.startswith("_"):
        raise HTTPException(400, "Invalid playbook_id")

    cat_label = body.play_category_label.strip()
    cat_path = [str(p).strip() for p in (body.play_category_path or []) if str(p).strip()]
    play_category = body.play_category.strip()
    if cat_path:
        try:
            resolved = resolve_play_category(cat_path, play_category_label=cat_label)
            play_category = resolved["play_category"]
            cat_path = resolved["play_category_path"]
            cat_label = resolved["play_category_label"]
        except ValueError as exc:
            raise HTTPException(
                422,
                playbook_contract_detail([str(exc)]),
            ) from exc
    elif not play_category:
        raise HTTPException(
            422,
            playbook_contract_detail(
                ["play_category_path or play_category is required"]
            ),
        )

    target_recon_context = ""
    target_capabilities: dict | None = None
    site = body.site.strip()
    component = body.component.strip()
    if site and component:
        from pipeline.recon_context import (
            capabilities_from_config,
            capabilities_from_recon,
            format_recon_for_play_authoring,
            load_effective_recon,
        )

        recon = load_effective_recon(site, component, playbook_id)
        config_caps = capabilities_from_config(site, component)
        target_capabilities = capabilities_from_recon(recon, config_caps)
        if recon:
            target_recon_context = format_recon_for_play_authoring(recon)

    cfg = body.playbook_config or PlaybookConfigBody()
    rebuild = bool(body.rebuild_from_objective)

    success_rules = body.success_rules.strip()
    failure_rules = body.failure_rules.strip()
    delivery_constraints = cfg.delivery_constraints.strip()
    exact_canary = body.exact_canary.strip()
    attack_objective = cfg.attack_objective.strip()

    if body.overwrite and not exact_canary:
        existing_path = ROOT / "playbooks" / f"{playbook_id}.json"
        if existing_path.is_file():
            try:
                import json

                existing = json.loads(existing_path.read_text(encoding="utf-8"))
                exact_canary = extract_exact_canary_from_playbook(existing)
            except Exception:
                exact_canary = ""

    # Exact canary locks success/fail prose and phase-1 ask (authoritative over preset).
    if exact_canary:
        success_rules = exact_canary_success_rule(exact_canary)
        failure_rules = exact_canary_failure_rule(exact_canary)
        if not attack_objective:
            attack_objective = exact_canary_attack_objective(exact_canary)

    # Create / CLI: when the client omits locked rules, adopt the category
    # preset. Rebuild-from-objective must NOT refill success/failure rules - empty means
    # the author LLM writes fresh triggers for the current attack_objective.
    if cat_path and (not success_rules or not failure_rules or not delivery_constraints):
        from playbooks.category_presets import resolve_category_preset

        preset = resolve_category_preset(
            cat_path[0],
            cat_path[1] if len(cat_path) > 1 else "",
            play_category_label=cat_label,
            capabilities=target_capabilities,
        )
        if not rebuild:
            if not success_rules and preset.success_rules:
                success_rules = "\n".join(preset.success_rules)
            if not failure_rules and preset.failure_rules:
                failure_rules = "\n".join(preset.failure_rules)
        if not delivery_constraints and preset.delivery_constraints:
            delivery_constraints = preset.delivery_constraints
    # Rebuild: keep structural rails + attack_objective only. Ignore any
    # stale expert_guidance / directives / followup / theory the client may still send.
    if rebuild:
        mandatory_directives = ""
        expert_guidance = ""
        followup_guidance = ""
        theory_guidance = ""
    else:
        mandatory_directives = cfg.mandatory_directives.strip()
        expert_guidance = cfg.expert_guidance.strip()
        followup_guidance = cfg.followup_guidance.strip()
        theory_guidance = cfg.theory_guidance.strip()

    # Authoring is sync LLM I/O. Run it off the event loop so Cancel / other UI
    # requests keep port 8000 responsive; abort when the client disconnects.
    cancel_event = threading.Event()

    async def _watch_disconnect() -> None:
        try:
            while not cancel_event.is_set():
                if await request.is_disconnected():
                    cancel_event.set()
                    return
                await asyncio.sleep(0.25)
        except asyncio.CancelledError:
            return

    watcher = asyncio.create_task(_watch_disconnect())
    try:
        data, generation_attempts = await asyncio.to_thread(
            generate_playbook_json,
            play=play,
            display_name=display_name,
            play_category=play_category,
            play_category_path=cat_path,
            play_category_label=cat_label,
            playbook_id=playbook_id,
            success_rules=success_rules,
            failure_rules=failure_rules,
            stop_words=body.stop_words.strip(),
            target_recon_context=target_recon_context,
            target_capabilities=target_capabilities,
            delivery_constraints=delivery_constraints,
            apply_delivery_to_seeds=cfg.apply_delivery_to_seeds,
            mandatory_directives=mandatory_directives,
            expert_guidance=expert_guidance,
            followup_guidance=followup_guidance,
            theory_guidance=theory_guidance,
            attack_objective=attack_objective,
            objective_lexicon=cfg.objective_lexicon,
            # None (field omitted) → leave alone; "" clears; string sets.
            **{
                k: v
                for k, v in {
                    "prompt_template": cfg.prompt_template,
                    "prompt_task": cfg.prompt_task,
                    "prompt_format": cfg.prompt_format,
                }.items()
                if v is not None
            },
            rebuild_from_objective=rebuild,
            cancel_check=cancel_event.is_set,
            authoring_mode=(body.authoring_mode or "human").strip().lower() or "human",
            keep_play_verbatim=bool(body.keep_play_verbatim),
            exact_canary=exact_canary,
        )
    except PlaybookGenerationCancelled as exc:
        raise HTTPException(499, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        from playbook_generator import PlaybookContractError

        if isinstance(exc, PlaybookContractError):
            raise HTTPException(
                422,
                {
                    "code": "invalid_playbook_contract",
                    "message": str(exc),
                    "errors": exc.details,
                },
            ) from exc
        if isinstance(exc, ValueError):
            raise HTTPException(
                422,
                playbook_contract_detail([str(exc)]),
            ) from exc
        raise
    finally:
        cancel_event.set()
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher

    errors = validate_playbook(data, playbook_id)
    if errors:
        raise HTTPException(422, playbook_contract_detail(errors[:8]))

    dest = ROOT / "playbooks" / f"{playbook_id}.json"
    if dest.exists() and not body.overwrite:
        raise HTTPException(409, f"Playbook already exists: {playbook_id}")

    try:
        path = save_playbook(data, overwrite=body.overwrite)
    except FileExistsError as exc:
        raise HTTPException(409, str(exc)) from exc

    invalidated_suites: list[str] = []
    # Full Create-from-play regenerate uses overwrite without rebuild_from_objective;
    # still drop cached probe suites so Run cannot reuse prompts from a prior ask.
    if dest.exists() and body.overwrite:
        from playbooks.suite_cache import invalidate_cached_test_suites

        invalidated_suites = invalidate_cached_test_suites(
            playbook_id,
            ROOT,
            site=site,
            component=component,
            all_targets=True,
        )

    return {
        "ok": True,
        "playbook_id": playbook_id,
        "playbook": data.get("playbook", playbook_id),
        "path": str(path.relative_to(ROOT)),
        "category_count": len(data.get("categories") or []),
        "generation_attempts": generation_attempts,
        "invalidated_test_suites": invalidated_suites,
    }
