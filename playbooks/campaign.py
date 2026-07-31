"""Capability-aware strategy gating for play × strategy runs."""

from __future__ import annotations

from typing import Any

from playbooks.registry import count_channels, normalize_playbook_id

ALL_STRATEGIES = (
    "zero_shot", "adaptive", "multi_shot", "few_shot", "iterative", "chain_of_thought",
    "prompt_chaining", "tree_of_thoughts", "self_consistency", "self_reflection",
    "directional_stimulus", "jailbreak", "multimodal",
)

# Strategies that drive a genuine multi-message conversation with the target and so
# require a stateful, multi-turn harness (UI chat history or API ``{{messages}}``).
# Gated out when the target is single-turn / stateless API. ``few_shot`` and
# ``tree_of_thoughts`` are NOT here - they pack priming / ToT framing into one request.
MULTI_TURN_STRATEGIES = frozenset({
    "multi_shot",
    "iterative",
    "prompt_chaining",
    "adaptive",
})


def strategy_requires_multi_turn(strategy: str) -> bool:
    """True when ``strategy`` needs target-side conversation history."""
    slug = (strategy or "").strip().lower().replace("-", "_")
    return slug in MULTI_TURN_STRATEGIES


def detect_capabilities(site: str = "", component: str = "", playbook_id: str = "") -> dict[str, bool]:
    """Infer target harness capabilities from recon (when confirmed) + config fallback."""
    from pipeline.recon_context import detect_capabilities as _detect

    return _detect(site, component, playbook_id)


def _filter_strategies_by_capabilities(
    strategies: list[str],
    capabilities: dict[str, bool],
    channels: dict[str, int],
) -> tuple[list[str], list[dict[str, str]]]:
    """Apply target capability gates to a strategy list."""
    kept: list[str] = []
    skipped: list[dict[str, str]] = []
    multi_turn_ok = capabilities.get("multi_turn", True)
    for strat in strategies:
        if strat == "multimodal":
            if not capabilities.get("file_upload"):
                skipped.append({
                    "strategy": strat,
                    "reason": "no file upload in component config",
                })
                continue
            if channels.get("artifact", 0) <= 0:
                skipped.append({
                    "strategy": strat,
                    "reason": "play has no artifact categories",
                })
                continue
        if strat in MULTI_TURN_STRATEGIES and not multi_turn_ok:
            skipped.append({
                "strategy": strat,
                "reason": (
                    "target has no conversation history "
                    "(stateless API / multi_turn disabled) - use zero_shot, "
                    "few_shot, or Enhance instead"
                ),
            })
            continue
        kept.append(strat)
    return kept, skipped


def resolve_generate_strategies(strategy_param: str, playbook_id: str, site: str = "", component: str = "") -> list[str]:
    """Map UI/job strategy param to a concrete strategy list.

    Supports a concrete strategy slug or ``__all__``. Former campaign sentinels
    (``__campaign__`` / ``__recommended__`` / empty) return no strategies.
    """
    strat = (strategy_param or "").strip()
    if strat in ("__campaign__", "__recommended__", ""):
        return []
    if strat == "__all__":
        capabilities = detect_capabilities(site, component, playbook_id=playbook_id)
        channels = count_channels(normalize_playbook_id(playbook_id)) if playbook_id else {}
        kept, _ = _filter_strategies_by_capabilities(
            list(ALL_STRATEGIES), capabilities, channels
        )
        try:
            from pipeline.edition import filter_community_strategies

            kept = filter_community_strategies(kept)
        except ImportError:
            kept = [s for s in kept if str(s).lower().replace("-", "_") != "adaptive"]
        return kept
    return [strat]


def assert_strategy_allowed_for_target(
    strategy: str,
    *,
    site: str = "",
    component: str = "",
    playbook_id: str = "",
) -> str | None:
    """Return an error message when ``strategy`` is blocked for this target, else None."""
    slug = (strategy or "").strip().lower().replace("-", "_")
    try:
        from pipeline.edition import is_premium_strategy, premium_error_message

        if is_premium_strategy(slug):
            return premium_error_message("adaptive")
    except ImportError:
        if slug == "adaptive":
            return (
                "Adaptive strategy is available in Genbounty LLM Hunter Premium. "
                "See https://genbounty.com/llm-hunter"
            )
    if slug in ("", "__all__", "__campaign__", "__recommended__", "multimodal"):
        # multimodal has its own file_upload gate; all is pre-filtered.
        if slug == "multimodal":
            caps = detect_capabilities(site, component, playbook_id=playbook_id)
            if not caps.get("file_upload"):
                return "multimodal requires file upload on this target"
        if slug in ("__campaign__", "__recommended__", ""):
            return (
                "Select a concrete strategy or All strategies "
                "(recommended campaigns were removed)."
            )
        return None
    if not strategy_requires_multi_turn(slug):
        return None
    caps = detect_capabilities(site, component, playbook_id=playbook_id)
    if caps.get("multi_turn", True):
        return None
    return (
        f"{slug} requires conversation history, but this target is single-turn "
        "(stateless API or multi_turn disabled). Use zero_shot, few_shot, jailbreak, "
        "or Enhance instead."
    )


def _play_category_parts(play_category: str) -> tuple[str, str]:
    parts = [p for p in str(play_category or "").strip().split(".") if p]
    if len(parts) >= 2:
        return parts[0], parts[1]
    if len(parts) == 1:
        return parts[0], ""
    return "", ""


def play_applicable_for_target(
    playbook_id: str,
    *,
    site: str = "",
    component: str = "",
    capabilities: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Whether a play's L1.L2 leaf is applicable on this target's capabilities."""
    from pipeline.recon_context import capability_requirements_satisfied
    from playbooks.category_presets import resolve_category_preset
    from playbooks.categories import normalize_play_category
    from playbooks.registry import load_playbook

    pid = normalize_playbook_id(playbook_id)
    playbook = load_playbook(pid)
    if not playbook:
        return {
            "applicable": False,
            "playbook_id": pid,
            "play_category": "",
            "l1": "",
            "l2": "",
            "reason": f"playbook not found: {pid}",
            "capabilities": dict(capabilities or {}),
        }

    play_cat = normalize_play_category(str(playbook.get("play_category", "")))
    l1, l2 = _play_category_parts(play_cat)
    caps = dict(
        capabilities
        if capabilities is not None
        else detect_capabilities(site, component, playbook_id=pid)
    )
    play_title = str(playbook.get("playbook", "")).strip() or pid

    if not l1 or not l2:
        return {
            "applicable": False,
            "playbook_id": pid,
            "playbook": play_title,
            "play_category": play_cat,
            "l1": l1,
            "l2": l2,
            "reason": "play has no exact L1.L2 category leaf",
            "capabilities": caps,
        }

    try:
        preset = resolve_category_preset(l1, l2, capabilities=caps)
    except ValueError as exc:
        return {
            "applicable": False,
            "playbook_id": pid,
            "playbook": play_title,
            "play_category": play_cat,
            "l1": l1,
            "l2": l2,
            "reason": str(exc),
            "capabilities": caps,
        }

    required = list(preset.required_capabilities)
    if required and not capability_requirements_satisfied(required, caps):
        return {
            "applicable": False,
            "playbook_id": pid,
            "playbook": play_title,
            "play_category": play_cat,
            "l1": l1,
            "l2": l2,
            "reason": (
                f"L1/L2 leaf {play_cat} requires "
                f"{', '.join(required)} (not confirmed by recon)"
            ),
            "required_capabilities": required,
            "capabilities": caps,
        }

    return {
        "applicable": True,
        "playbook_id": pid,
        "playbook": play_title,
        "play_category": play_cat,
        "l1": l1,
        "l2": l2,
        "reason": "",
        "capabilities": caps,
    }
