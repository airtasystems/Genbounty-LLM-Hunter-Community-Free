#!/usr/bin/env python3
"""Offline generation-yield report from pipeline_report.json files.

Joins assessed outcomes back to the parent suite for ``technique`` / ``probe_class``
and infers framing family from prompt text. Prints markdown rate tables.

Examples::

  python scripts/generation_yield_report.py path/to/pipeline_report.json
  python scripts/generation_yield_report.py 'browser-bot/sites/*/chat/logs/probes/*/pipeline_report.json'
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_GEN = _ROOT / "generate-tests"
for p in (str(_ROOT), str(_GEN)):
    if p not in sys.path:
        sys.path.insert(0, p)

from pipeline.flagged_suite import (  # noqa: E402
    _find_prompt_in_suite,
    resolve_parent_suite_path,
)
from strategies.framing_diversity import infer_framing_family  # noqa: E402
from strategies.prior_results import _classify_result  # noqa: E402

_OUTCOMES = ("exploited", "partial", "refused", "inconclusive")


def _expand_inputs(patterns: list[str]) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    for raw in patterns:
        p = Path(raw)
        matches = sorted(_ROOT.glob(raw)) if any(c in raw for c in "*?[") else [p]
        if not matches and p.is_file():
            matches = [p]
        for m in matches:
            resolved = m.resolve()
            if resolved.is_file() and resolved not in seen:
                seen.add(resolved)
                paths.append(resolved)
    return paths


def _load_suite(report: dict[str, Any]) -> dict[str, Any] | None:
    suite_path = resolve_parent_suite_path(
        report,
        site=str(report.get("site") or ""),
        component=str(report.get("component") or ""),
        bb_root=_ROOT / "browser-bot",
    )
    if suite_path is None:
        source = str(report.get("source_file") or "").strip()
        if source:
            candidate = Path(source)
            if not candidate.is_file():
                candidate = _ROOT / source.lstrip("/")
            suite_path = candidate if candidate.is_file() else None
    if suite_path is None:
        return None
    try:
        data = json.loads(suite_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _enrich_row(result: dict[str, Any], suite: dict[str, Any] | None) -> dict[str, Any]:
    prompt_text = str(result.get("prompt") or "")
    technique = str(result.get("technique") or "").strip() or "(unknown)"
    probe_class = str(result.get("probe_class") or "").strip() or "(none)"
    transform_kind = str(result.get("transform_kind") or "").strip() or "(none)"
    if suite:
        found = _find_prompt_in_suite(
            suite,
            prompt_id=str(result.get("id") or ""),
            category_id=str(result.get("category_id") or ""),
            category_name=str(result.get("category") or ""),
        )
        if found:
            _cat, prompt = found
            technique = str(prompt.get("technique") or technique).strip() or "(unknown)"
            probe_class = str(prompt.get("probe_class") or probe_class).strip() or "(none)"
            transform_kind = (
                str(prompt.get("transform_kind") or transform_kind).strip() or "(none)"
            )
            if not prompt_text:
                prompt_text = str(prompt.get("prompt") or "")
    framing = infer_framing_family(prompt_text) if prompt_text else "other"
    outcome = _classify_result(result)
    return {
        "outcome": outcome,
        "technique": technique,
        "framing": framing,
        "category": str(result.get("category") or result.get("category_id") or "(none)"),
        "strategy": str(result.get("strategy") or "(none)"),
        "probe_class": probe_class,
        "transform_kind": transform_kind,
    }


def _collect(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"# skip {path}: {exc}", file=sys.stderr)
            continue
        if not isinstance(report, dict):
            continue
        suite = _load_suite(report)
        results = report.get("adversarial_results") or []
        if not isinstance(results, list):
            continue
        for result in results:
            if isinstance(result, dict):
                rows.append(_enrich_row(result, suite))
    return rows


def _rate_table(rows: list[dict[str, Any]], key: str) -> str:
    buckets: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        buckets[str(row.get(key) or "(none)")][str(row.get("outcome") or "inconclusive")] += 1
    lines = [
        f"| {key} | n | exploited | partial | refused | inconclusive | exploit% |",
        f"|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in sorted(buckets, key=lambda k: (-sum(buckets[k].values()), k)):
        c = buckets[name]
        n = sum(c.values())
        exp = c["exploited"]
        pct = f"{100.0 * exp / n:.0f}%" if n else "-"
        lines.append(
            f"| {name} | {n} | {c['exploited']} | {c['partial']} | "
            f"{c['refused']} | {c['inconclusive']} | {pct} |"
        )
    return "\n".join(lines)


def _summary(rows: list[dict[str, Any]]) -> str:
    c: Counter[str] = Counter(str(r.get("outcome") or "inconclusive") for r in rows)
    n = len(rows)
    parts = [f"n={n}"]
    for o in _OUTCOMES:
        parts.append(f"{o}={c[o]}")
    if n:
        parts.append(f"exploit_rate={100.0 * c['exploited'] / n:.1f}%")
    return ", ".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "reports",
        nargs="+",
        help="pipeline_report.json path(s) or globs relative to repo root",
    )
    args = parser.parse_args(argv)
    paths = _expand_inputs(args.reports)
    if not paths:
        print("No pipeline_report.json files matched.", file=sys.stderr)
        return 1
    rows = _collect(paths)
    print(f"# Generation yield report")
    print()
    print(f"Reports: {len(paths)}")
    print(f"Rows: {_summary(rows)}")
    print()
    for key, title in (
        ("technique", "By technique"),
        ("framing", "By framing family"),
        ("category", "By category"),
        ("strategy", "By strategy"),
        ("probe_class", "By probe class"),
        ("transform_kind", "By transform kind"),
    ):
        print(f"## {title}")
        print()
        print(_rate_table(rows, key))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
