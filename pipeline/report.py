"""Shared severity ordering and pipeline-report construction.

Single source of truth for severity comparison and ``pipeline_report.json``
assembly, used by the CLI (``main.py``), the web job manager (``web/jobs.py``),
and the assessment pipeline.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

SEVERITY_ORDER: tuple[str, ...] = (
    "critical",
    "high",
    "medium",
    "low",
    "informational",
    "indeterminate",
)


def _normalize(level: str) -> str:
    from risk_level_agent import normalize_risk_level

    return normalize_risk_level(level)


def severity_index(level: str) -> int:
    """Rank a severity level; lower index is more severe. Unknown -> last."""
    level = _normalize(level)
    return SEVERITY_ORDER.index(level) if level in SEVERITY_ORDER else len(SEVERITY_ORDER)


def category_rollup_from_results(risk_results: list) -> dict[str, str]:
    """Per-category worst (most severe) level across assessed prompts.

    Each category is seeded from its first observed level rather than a
    hardcoded ``low`` floor, so benign categories report their actual level
    (e.g. ``informational`` / ``indeterminate``) instead of being inflated to
    ``low``.
    """
    rollup: dict[str, str] = {}
    for r in risk_results:
        category = r.get("category", "")
        if not category:
            continue
        new_level = _normalize(r.get("risk_level", "indeterminate"))
        current = rollup.get(category)
        if current is None or severity_index(new_level) < severity_index(current):
            rollup[category] = new_level
    return rollup


def build_pipeline_report(
    log_data: dict,
    risk_results: list,
    run_log_dir: str | Path,
    attack_log_path: str | Path,
    *,
    category_rollup: dict[str, str] | None = None,
    timestamp: str | None = None,
) -> dict:
    """Assemble the ``pipeline_report.json`` dict from assessed results."""
    if category_rollup is None:
        category_rollup = category_rollup_from_results(risk_results)
    report = {
        "timestamp": timestamp or datetime.now().strftime("%Y-%m-%dT%H-%M-%S"),
        "playbook": log_data.get("playbook", log_data.get("framework", "")),
        "playbook_id": log_data.get("playbook_id", ""),
        "source_file": log_data.get("source_file", ""),
        "run_log_dir": str(run_log_dir),
        "attack_log": str(attack_log_path),
        "adversarial_results": risk_results,
        "category_rollup": category_rollup,
    }
    if log_data.get("strategy"):
        report["strategy"] = log_data["strategy"]
    oracle_versions = {
        str(row.get("oracle_version") or "")
        for row in risk_results
        if isinstance(row, dict) and row.get("oracle_version")
    }
    oracle_hashes = {
        str(row.get("oracle_hash") or "")
        for row in risk_results
        if isinstance(row, dict) and row.get("oracle_hash")
    }
    if len(oracle_versions) == 1:
        report["oracle_version"] = next(iter(oracle_versions))
    elif oracle_versions:
        report["oracle_versions"] = sorted(oracle_versions)
    if len(oracle_hashes) == 1:
        report["oracle_hash"] = next(iter(oracle_hashes))
    elif oracle_hashes:
        report["oracle_hashes"] = sorted(oracle_hashes)
    configured_values = {
        bool(row.get("oracle_summary", {}).get("configured"))
        for row in risk_results
        if isinstance(row, dict) and isinstance(row.get("oracle_summary"), dict)
    }
    if len(configured_values) == 1:
        report["oracle_configured"] = next(iter(configured_values))
    for key in ("oracle_version", "oracle_hash", "oracle_configured"):
        if key not in report and key in log_data:
            report[key] = log_data[key]
    return report


def delete_adversarial_result(
    report: dict,
    *,
    prompt_id: str = "",
    position: int | None = None,
) -> tuple[dict, dict]:
    """Remove one ``adversarial_results`` entry and refresh ``category_rollup``.

    Prefer matching by ``prompt_id`` when provided; otherwise use ``position``.
    Returns ``(removed_row, updated_report)``. Mutates ``report`` in place.
    """
    results = report.get("adversarial_results")
    if not isinstance(results, list) or not results:
        raise ValueError("Report has no adversarial_results to delete")

    remove_index: int | None = None
    pid = (prompt_id or "").strip()
    if pid:
        for i, row in enumerate(results):
            if isinstance(row, dict) and str(row.get("id") or "").strip() == pid:
                remove_index = i
                break
        if remove_index is None:
            raise KeyError(f"Assessment row not found: id={pid!r}")
    elif position is not None:
        if not isinstance(position, int) or position < 0 or position >= len(results):
            raise KeyError(f"Assessment row not found: position={position!r}")
        remove_index = position
    else:
        raise ValueError("Provide prompt_id or position")

    removed = results.pop(remove_index)
    if not isinstance(removed, dict):
        removed = {"value": removed}
    report["adversarial_results"] = results
    report["category_rollup"] = category_rollup_from_results(
        [r for r in results if isinstance(r, dict)]
    )
    return removed, report
