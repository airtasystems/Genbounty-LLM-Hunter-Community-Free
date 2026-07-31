"""Community vs Premium edition gates.

Community ships the full tree but rejects Premium-only capabilities at the
API/CLI/runtime boundary. Upsell: https://genbounty.com/llm-hunter
"""
from __future__ import annotations

from typing import Any, NoReturn

EDITION = "community"
PREMIUM_URL = "https://genbounty.com/llm-hunter"

FEATURE_LABELS: dict[str, str] = {
    "start_battle": "Start Battle (Run pipeline)",
    "adaptive": "Adaptive strategy",
    "multimodal_generate": "Manual multimodal generation",
    "intel": "Intel",
    "open_hunt": "Open Hunt",
}

# Generation / run strategy slugs gated in Community.
PREMIUM_STRATEGIES = frozenset({"adaptive"})


def is_community() -> bool:
    return EDITION == "community"


def is_premium_feature(_feature: str) -> bool:
    """In Community, every known Premium feature is gated."""
    return is_community()


def _norm_strategy(name: str) -> str:
    return str(name or "").strip().lower().replace("-", "_")


def is_premium_strategy(name: str) -> bool:
    return is_community() and _norm_strategy(name) in PREMIUM_STRATEGIES


def filter_community_strategies(strategies: list[str] | tuple[str, ...]) -> list[str]:
    return [s for s in strategies if not is_premium_strategy(s)]


def premium_detail(feature: str) -> str:
    label = FEATURE_LABELS.get(feature, feature.replace("_", " ").title())
    if feature == "start_battle":
        return (
            f"{label} is available in Genbounty LLM Hunter Premium. "
            "In Community, use Run and Enhance (Auto-run) on the Attack tab. "
            f"See {PREMIUM_URL}"
        )
    return (
        f"{label} is available in Genbounty LLM Hunter Premium. "
        f"See {PREMIUM_URL}"
    )


def premium_payload(feature: str, *, detail: str | None = None) -> dict[str, Any]:
    return {
        "premium": True,
        "feature": feature,
        "url": PREMIUM_URL,
        "detail": detail or premium_detail(feature),
    }


def raise_premium(feature: str, *, detail: str | None = None) -> NoReturn:
    """Raise FastAPI HTTPException 403 with a premium payload."""
    from fastapi import HTTPException

    raise HTTPException(status_code=403, detail=premium_payload(feature, detail=detail))


def premium_error_message(feature: str) -> str:
    return premium_detail(feature)


def exit_premium(feature: str, *, code: int = 2) -> NoReturn:
    """Print premium message to stderr and exit (CLI)."""
    import sys

    print(premium_error_message(feature), file=sys.stderr)
    raise SystemExit(code)


def fail_job_premium(job: Any, feature: str) -> None:
    """Mark an async Job failed with a premium detail line."""
    detail = premium_error_message(feature)
    try:
        job.output.append(f"[!] {detail}")
    except Exception:
        pass
    job.status = "failed"
    if hasattr(job, "_event") and job._event is not None:
        try:
            job._event.set()
        except Exception:
            pass


def adaptive_suite_premium_block_message(suite_path: Any) -> str | None:
    """Return premium error text when ``suite_path`` is an adaptive suite in Community."""
    if not is_community() or not is_premium_strategy("adaptive"):
        return None

    from pathlib import Path

    path = Path(str(suite_path or ""))
    # Path heuristic works even when the suite file is missing (is_adaptive_suite
    # returns False for non-files before checking strategy folder names).
    parts = path.parts
    if "tests" in parts:
        idx = parts.index("tests")
        if idx + 1 < len(parts) and str(parts[idx + 1]).replace("-", "_") == "adaptive":
            return premium_error_message("adaptive")

    try:
        from browser_bot.submit import is_adaptive_suite
    except ImportError:
        return None
    if is_adaptive_suite(suite_path):
        return premium_error_message("adaptive")
    return None
