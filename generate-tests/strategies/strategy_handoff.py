"""Playbook-scoped strategy handoff for All-strategies cross-lane elite carry-forward.

Deterministic artifact only (no manager LLM). Written when a Bug Bounty / Open Hunt
enhance loop ends; applied when the next strategy's elite file is empty so mutate-first
can fire after pipeline clean-lane wipe.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent
_HANDOFF_CAP = 8
_DROP_RAILS_CAP = 24

_VALID_REASONS = frozenset(
    {"soft_advance", "max_rounds", "bounty_stop", "cancelled_skip", "hit"}
)


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _as_channel_proof(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, (int, float)) and value == 1:
        return True
    if isinstance(value, str) and value.strip().lower() in ("true", "1", "yes"):
        return True
    return False


def handoff_dir(site: str, component: str) -> Path:
    return _ROOT / "browser-bot" / "sites" / site / component / "strategy_handoff"


def handoff_path(site: str, component: str, playbook_id: str) -> Path:
    pid = _norm(playbook_id)
    return handoff_dir(site, component) / f"{pid}.json"


def compact_elite_seed(genome: dict[str, Any] | None) -> dict[str, Any] | None:
    """Compact elite genome fields for handoff elite_seeds.

    Prompt length matches elite store (8000) so mutate parents keep winning wording.
    """
    if not isinstance(genome, dict):
        return None
    prompt = str(genome.get("prompt") or "").strip()
    gid = str(genome.get("id") or "").strip()
    if not prompt or not gid:
        return None
    bucket = str(genome.get("bucket") or "").strip().lower()
    if bucket not in ("exploited", "partial"):
        outcome = str(genome.get("outcome") or "").strip().lower()
        if outcome in ("exploited", "partial"):
            bucket = outcome
        else:
            bucket = "partial"
    seed: dict[str, Any] = {
        "id": gid[:64],
        "prompt": prompt[:8000],
        "bucket": bucket,
        "mechanism_family": str(genome.get("mechanism_family") or "").strip(),
        "ask_pattern": str(genome.get("ask_pattern") or "").strip(),
        "phase": str(genome.get("phase") or "phase1").strip() or "phase1",
        "channel_proof": _as_channel_proof(genome.get("channel_proof")),
    }
    cat = str(genome.get("category") or "").strip()
    if cat:
        seed["category"] = cat[:200]
    tech = str(genome.get("technique") or "").strip()
    if tech:
        seed["technique"] = tech[:200]
    resp = str(genome.get("response") or "").strip()
    if resp:
        seed["response"] = resp[:800]
    risk = str(genome.get("risk_level") or "").strip()
    if risk:
        seed["risk_level"] = risk
    return seed


def _seed_sort_key(seed: dict[str, Any]) -> tuple[int, int, str]:
    """Prefer channel_proof, then exploited, then partial."""
    cp = 0 if _as_channel_proof(seed.get("channel_proof")) else 1
    bucket = str(seed.get("bucket") or "").strip().lower()
    br = 0 if bucket == "exploited" else (1 if bucket == "partial" else 9)
    return (cp, br, str(seed.get("id") or ""))


def _merge_elite_seeds(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    *,
    cap: int = _HANDOFF_CAP,
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for row in list(existing or []) + list(incoming or []):
        seed = compact_elite_seed(row if isinstance(row, dict) else None)
        if not seed:
            continue
        gid = str(seed["id"])
        prev = by_id.get(gid)
        if prev is None or _seed_sort_key(seed) < _seed_sort_key(prev):
            by_id[gid] = seed
    merged = sorted(by_id.values(), key=_seed_sort_key)
    limit = max(0, int(cap))
    return merged[:limit]


def _preferred_from_seeds(
    seeds: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    asks: list[str] = []
    fams: list[str] = []
    seen_a: set[str] = set()
    seen_f: set[str] = set()
    for s in seeds:
        ask = str(s.get("ask_pattern") or "").strip()
        fam = str(s.get("mechanism_family") or "").strip()
        if ask and ask not in seen_a:
            seen_a.add(ask)
            asks.append(ask)
        if fam and fam not in seen_f:
            seen_f.add(fam)
            fams.append(fam)
    return asks, fams


def _normalize_drop_rails(raw: list[Any] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in raw or []:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text[:240])
        if len(out) >= _DROP_RAILS_CAP:
            break
    return out


def load_strategy_handoff(
    site: str,
    component: str,
    playbook_id: str,
) -> dict[str, Any] | None:
    path = handoff_path(site, component, playbook_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    seeds = _merge_elite_seeds([], list(data.get("elite_seeds") or []), cap=_HANDOFF_CAP)
    drop_rails = _normalize_drop_rails(data.get("drop_rails"))
    asks_pref, fams_pref = _preferred_from_seeds(seeds)
    raw_asks = data.get("preferred_ask_patterns")
    raw_fams = data.get("preferred_mechanism_families")
    if isinstance(raw_asks, list):
        asks = [str(a).strip() for a in raw_asks if str(a or "").strip()]
    else:
        asks = []
    if isinstance(raw_fams, list):
        fams = [str(f).strip() for f in raw_fams if str(f or "").strip()]
    else:
        fams = []
    # Stale/empty preference lists must not blank DNA derived from seeds.
    if not asks and asks_pref:
        asks = asks_pref
    if not fams and fams_pref:
        fams = fams_pref
    return {
        "version": int(data.get("version") or 1),
        "site": str(data.get("site") or site),
        "component": str(data.get("component") or component),
        "playbook_id": _norm(data.get("playbook_id") or playbook_id),
        "from_strategy": _norm(data.get("from_strategy") or ""),
        "written_at": str(data.get("written_at") or ""),
        "reason": str(data.get("reason") or "").strip() or "max_rounds",
        "mutate_first": bool(seeds),
        "elite_seeds": seeds,
        "preferred_ask_patterns": asks,
        "preferred_mechanism_families": fams,
        "drop_rails": drop_rails,
        "usefulness": data.get("usefulness")
        if isinstance(data.get("usefulness"), dict)
        else {},
    }


def write_strategy_handoff(
    site: str,
    component: str,
    playbook_id: str,
    from_strategy: str,
    *,
    elite_seeds: list[dict[str, Any]] | None = None,
    drop_rails: list[Any] | None = None,
    reason: str = "max_rounds",
    usefulness: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Write or merge playbook handoff. Returns written payload or None if skipped.

    Merge rules:
    - Skip entirely when both new elite_seeds and drop_rails are empty (do not wipe).
    - When new elites are empty but prior handoff has elites, keep prior elite_seeds
      and from_strategy; merge drop_rails.
    - When new elites exist, merge with prior (prefer channel_proof / exploited) and
      set from_strategy to the finishing strategy.
    """
    site_s = str(site or "").strip()
    comp_s = str(component or "").strip()
    pid = _norm(playbook_id)
    strat = _norm(from_strategy)
    if not (site_s and comp_s and pid and strat):
        return None

    incoming_seeds = _merge_elite_seeds([], list(elite_seeds or []), cap=_HANDOFF_CAP)
    incoming_drops = _normalize_drop_rails(drop_rails)
    if not incoming_seeds and not incoming_drops:
        return None

    prior = load_strategy_handoff(site_s, comp_s, pid)
    prior_seeds = list((prior or {}).get("elite_seeds") or [])
    prior_drops = list((prior or {}).get("drop_rails") or [])
    prior_from = _norm((prior or {}).get("from_strategy") or "")

    prior_reason = str((prior or {}).get("reason") or "").strip()
    prior_usefulness = (
        (prior or {}).get("usefulness")
        if isinstance((prior or {}).get("usefulness"), dict)
        else {}
    )
    new_usefulness = usefulness if isinstance(usefulness, dict) else {}

    if incoming_seeds:
        merged_seeds = _merge_elite_seeds(prior_seeds, incoming_seeds, cap=_HANDOFF_CAP)
        out_from = strat
        reason_s = str(reason or "").strip()
        out_usefulness = new_usefulness or prior_usefulness or {}
    else:
        # Barren strategy: keep prior elite DNA / authorship / win reason.
        merged_seeds = prior_seeds[:_HANDOFF_CAP]
        out_from = prior_from or strat
        if prior_seeds:
            reason_s = prior_reason or str(reason or "").strip()
            out_usefulness = prior_usefulness or new_usefulness or {}
        else:
            reason_s = str(reason or "").strip()
            out_usefulness = new_usefulness or {}

    merged_drops = _normalize_drop_rails(list(prior_drops) + list(incoming_drops))
    if not merged_seeds and not merged_drops:
        return None

    asks, fams = _preferred_from_seeds(merged_seeds)
    if reason_s not in _VALID_REASONS:
        reason_s = "max_rounds"

    payload: dict[str, Any] = {
        "version": 1,
        "site": site_s,
        "component": comp_s,
        "playbook_id": pid,
        "from_strategy": out_from,
        "written_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reason": reason_s,
        "mutate_first": bool(merged_seeds),
        "elite_seeds": merged_seeds,
        "preferred_ask_patterns": asks,
        "preferred_mechanism_families": fams,
        "drop_rails": merged_drops,
        "usefulness": out_usefulness,
    }
    path = handoff_path(site_s, comp_s, pid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload


def apply_strategy_handoff_elite(
    site: str,
    component: str,
    playbook_id: str,
    to_strategy: str,
) -> int:
    """Seed destination elite from handoff when empty and from_strategy differs.

    Returns number of genomes imported (0 when skipped).
    """
    from strategies.elite_genomes import import_elite_genomes, load_elite_genomes

    site_s = str(site or "").strip()
    comp_s = str(component or "").strip()
    pid = _norm(playbook_id)
    dest = _norm(to_strategy)
    if not (site_s and comp_s and pid and dest):
        return 0
    if load_elite_genomes(site_s, comp_s, pid, dest):
        return 0
    ho = load_strategy_handoff(site_s, comp_s, pid)
    if not ho:
        return 0
    src = _norm(ho.get("from_strategy") or "")
    if not src or src == dest:
        return 0
    seeds = list(ho.get("elite_seeds") or [])
    if not seeds:
        return 0
    return import_elite_genomes(
        site_s,
        comp_s,
        pid,
        dest,
        seeds,
        replace_empty_only=True,
    )


def handoff_theory_block(
    site: str,
    component: str,
    playbook_id: str,
    strategy: str,
) -> dict[str, Any]:
    """Compact CONTEXT object for enhance theory (empty dict when irrelevant)."""
    ho = load_strategy_handoff(site, component, playbook_id)
    if not ho:
        return {}
    src = _norm(ho.get("from_strategy") or "")
    dest = _norm(strategy)
    seeds = list(ho.get("elite_seeds") or [])
    drops = list(ho.get("drop_rails") or [])
    if not seeds and not drops:
        return {}
    # Same-strategy re-entry: still expose drop_rails; mutate_first only when
    # seeds came from a different strategy (cross-lane carry).
    cross = bool(src and dest and src != dest and seeds)
    out: dict[str, Any] = {
        "from_strategy": src,
        "mutate_first": cross,
        "preferred_ask_patterns": list(ho.get("preferred_ask_patterns") or [])[:8],
        "preferred_mechanism_families": list(
            ho.get("preferred_mechanism_families") or []
        )[:8],
        "drop_rails": drops[:12],
        "elite_seed_count": len(seeds),
        "reason": str(ho.get("reason") or ""),
    }
    return out


def maybe_write_handoff_after_enhance(
    site: str,
    component: str,
    playbook_id: str,
    strategy: str,
    *,
    reason: str = "max_rounds",
    usefulness: dict[str, Any] | None = None,
    drop_rails: list[Any] | None = None,
) -> dict[str, Any] | None:
    """Load current-lane elites (+ optional drops) and write playbook handoff."""
    from strategies.elite_genomes import load_elite_genomes

    compact = [
        s
        for g in load_elite_genomes(site, component, playbook_id, strategy)
        for s in [compact_elite_seed(g)]
        if s
    ]
    seeds = sorted(compact, key=_seed_sort_key)[:_HANDOFF_CAP]
    drops = list(drop_rails or [])
    if not drops:
        try:
            from strategies.prior_results import (
                extract_burned_wrapper_families,
                load_prior_results,
            )

            prior = load_prior_results(
                site,
                component,
                playbook_id,
                strategy=strategy,
                require_feedback=False,
            )
            refused = list(getattr(prior, "refused_prompts", None) or [])
            drops = list(extract_burned_wrapper_families(refused) or [])
        except Exception:
            drops = []
    return write_strategy_handoff(
        site,
        component,
        playbook_id,
        strategy,
        elite_seeds=seeds,
        drop_rails=drops,
        reason=reason,
        usefulness=usefulness,
    )
