"""Cached test suites vs playbook attack_objective."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from playbooks.playbook_config import get_attack_objective_expanded, normalize_objective_text


def playbook_suite_filename(playbook_id: str) -> str:
    return f"{str(playbook_id or '').strip().replace('_', '-')}.json"


def _suite_glob(root: Path, playbook_id: str, *, site: str = "", component: str = "") -> list[Path]:
    stem = playbook_suite_filename(playbook_id)
    base = root / "browser-bot" / "sites"
    if site and component:
        return sorted((base / site / component / "tests").glob(f"*/{stem}"))
    return sorted(base.glob(f"*/*/tests/*/{stem}"))


def invalidate_cached_test_suites(
    playbook_id: str,
    root: Path | str,
    *,
    site: str = "",
    component: str = "",
    all_targets: bool = True,
) -> list[str]:
    """Delete cached suite JSON files for a playbook (stale after objective rebuild).

    When ``all_targets`` is true (default), removes suites under every
    ``browser-bot/sites/*/*/tests/*/`` path. Otherwise only the given site/component.
    """
    root_path = Path(root)
    pid = str(playbook_id or "").strip()
    if not pid:
        return []
    paths = (
        _suite_glob(root_path, pid)
        if all_targets or not (site and component)
        else _suite_glob(root_path, pid, site=site, component=component)
    )
    removed: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            rel = str(path.relative_to(root_path))
        except ValueError:
            rel = str(path)
        path.unlink()
        removed.append(rel)
    return removed


def read_suite_attack_objective(path: Path | str) -> str:
    """Return ``playbook_attack_objective`` stamped on a suite file, or ``''``."""
    p = Path(path)
    if not p.is_file():
        return ""
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    return normalize_objective_text(str(data.get("playbook_attack_objective") or ""))


def attack_objectives_match(current: str, cached: str) -> bool:
    """True when cached suite objective matches the playbook (or neither is set)."""
    cur = normalize_objective_text(current)
    old = normalize_objective_text(cached)
    if not cur:
        return True
    if not old:
        return False
    return cur == old


def suite_matches_playbook_objective(suite_path: Path | str, playbook: dict[str, Any]) -> bool:
    current = get_attack_objective_expanded(playbook)
    if not current:
        return True
    cached = read_suite_attack_objective(suite_path)
    return attack_objectives_match(current, cached)


def prior_report_matches_objective(report: dict[str, Any], playbook: dict[str, Any]) -> bool:
    """False when an assessed report's source suite used a different attack_objective."""
    current = get_attack_objective_expanded(playbook)
    if not current:
        return True
    source = str(report.get("source_file") or "").strip()
    if not source:
        return False
    cached = read_suite_attack_objective(source)
    return attack_objectives_match(current, cached)


def prior_results_match_objective(prior: Any, playbook: dict[str, Any]) -> bool:
    """True when every aggregated prior report matches the current attack_objective."""
    current = get_attack_objective_expanded(playbook)
    if not current:
        return True
    paths = getattr(prior, "report_paths", None) or []
    if not paths:
        return False
    for raw in paths:
        path = Path(str(raw))
        if not path.is_file():
            return False
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(report, dict) or not prior_report_matches_objective(report, playbook):
            return False
    return True
