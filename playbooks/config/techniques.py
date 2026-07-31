"""Technique pack names, distinctness, and detection-floor stubs."""
from __future__ import annotations

from typing import Any

from playbooks.config.constants import CONFIG_KEY, _DETECTION_FLOOR_GUIDANCE_RE

def _load_get_techniques():
    """Resilient import of the shared technique registry (may live under generate-tests)."""
    try:
        from strategies.attack_techniques import get_techniques  # type: ignore

        return get_techniques
    except ImportError:
        pass
    try:
        import sys
        from pathlib import Path

        gen = Path(__file__).resolve().parents[2] / "generate-tests"
        if str(gen) not in sys.path:
            sys.path.insert(0, str(gen))
        from strategies.attack_techniques import get_techniques  # type: ignore

        return get_techniques
    except ImportError:
        return None


def _technique_pack_names(play_category: str, *, authored: list | None = None) -> list[str]:
    """Technique names for a leaf (or authored custom pack)."""
    cat = str(play_category or "").strip()
    if not cat:
        return []
    get_techniques = _load_get_techniques()
    if get_techniques is None:
        return []
    try:
        kwargs: dict[str, Any] = {"channel": "text", "limit": None}
        if authored is not None:
            kwargs["authored_techniques"] = authored
        techniques = get_techniques(cat, **kwargs)
    except Exception:
        return []
    names: list[str] = []
    for tech in techniques or []:
        name = str(getattr(tech, "name", "") or "").strip()
        if name:
            names.append(name)
    return names


def pack_has_detection_floor_technique(play_category: str) -> bool:
    """Detection-floor leaf packs are unused; missions use authored techniques only."""
    _ = play_category
    return False


def best_technique_anchor_for_text(text: str, technique_names: list[str]) -> str:
    """Return the longest technique name whose tokens appear in ``text``, or ''."""
    blob = str(text or "").strip().lower()
    if not blob or not technique_names:
        return ""
    best = ""
    for name in sorted(technique_names, key=lambda n: len(n), reverse=True):
        low = name.lower()
        token = low.replace("_", " ")
        if low in blob or token in blob:
            return name
        parts = [p for p in low.split("_") if len(p) >= 4]
        if len(parts) >= 2 and sum(1 for p in parts if p in blob) >= 2:
            if len(name) > len(best):
                best = name
    return best


def category_mechanism_distinctness_errors(data: dict[str, Any] | None) -> list[str]:
    """Reject multi-category plays that do not claim distinct technique-pack anchors."""
    if not isinstance(data, dict):
        return []
    categories = [c for c in (data.get("categories") or []) if isinstance(c, dict)]
    if len(categories) < 2:
        return []
    play_category = str(data.get("play_category") or "").strip()
    if not play_category:
        return []
    # Missions author techniques per category; union across variants for anchors.
    authored: list[Any] = []
    for cat in categories:
        raw = cat.get("attack_techniques")
        if isinstance(raw, list):
            authored.extend(raw)
    pack = _technique_pack_names(play_category, authored=authored or None)
    if len(pack) < 2:
        return []
    claimed: list[str] = []
    errors: list[str] = []
    for i, cat in enumerate(categories):
        blob = " ".join(
            str(cat.get(k) or "") for k in ("name", "focus", "description")
        )
        anchor = best_technique_anchor_for_text(blob, pack)
        if not anchor:
            errors.append(
                f"categories[{i}] must name a distinct attack technique from the leaf "
                "pack in focus/description/name (multi-category plays need mechanism split)"
            )
            continue
        if anchor in claimed:
            errors.append(
                f"categories[{i}] reuses technique anchor {anchor!r}; each category must "
                "claim a different pack mechanism"
            )
        else:
            claimed.append(anchor)
    return errors


def playbook_has_detection_floor_guidance(data: dict[str, Any] | None) -> bool:
    """True when expert/seed/category prose mentions a detection-floor cue."""
    if not isinstance(data, dict):
        return False
    blobs: list[str] = []
    cfg = data.get(CONFIG_KEY) if isinstance(data.get(CONFIG_KEY), dict) else {}
    generation = cfg.get("generation") if isinstance(cfg.get("generation"), dict) else {}
    for key in ("expert_guidance",):
        val = generation.get(key)
        if isinstance(val, str) and val.strip():
            blobs.append(val)
    strategies = generation.get("strategies")
    if isinstance(strategies, dict):
        for strat_cfg in strategies.values():
            if not isinstance(strat_cfg, dict):
                continue
            seed = strat_cfg.get("seed_guidance")
            if isinstance(seed, str) and seed.strip():
                blobs.append(seed)
    for cat in data.get("categories") or []:
        if not isinstance(cat, dict):
            continue
        for key in ("name", "focus", "description"):
            val = cat.get(key)
            if isinstance(val, str) and val.strip():
                blobs.append(val)
    joined = "\n".join(blobs)
    return bool(_DETECTION_FLOOR_GUIDANCE_RE.search(joined))


