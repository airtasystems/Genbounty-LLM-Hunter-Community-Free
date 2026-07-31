"""Aggregate prompt filter drops during suite generation for empty-suite diagnosis."""

from __future__ import annotations

import threading
from collections import Counter
from typing import Any

_lock = threading.Lock()
_active: DropDiagnostics | None = None


class DropDiagnostics:
    """Thread-safe collector for generation filter statistics."""

    def __init__(self) -> None:
        self.context: dict[str, Any] = {}
        self.drop_counts: Counter[tuple[str, str]] = Counter()
        self.parsed_total = 0
        self.category_kept: dict[str, int] = {}
        self.skipped_categories: list[tuple[str, str]] = []
        self.category_errors: list[tuple[str, str]] = []
        self.dedup_removed = 0

    def record_parsed(self, count: int) -> None:
        if count <= 0:
            return
        with _lock:
            self.parsed_total += int(count)

    def record_drops(self, stage: str, dropped: list[tuple[str, list[str]]]) -> None:
        if not dropped:
            return
        with _lock:
            for _pid, reasons in dropped:
                for reason in reasons:
                    self.drop_counts[(stage, str(reason))] += 1

    def record_drop(self, stage: str, reason: str) -> None:
        reason = str(reason or "").strip()
        if not reason:
            return
        with _lock:
            self.drop_counts[(stage, reason)] += 1

    def record_category_kept(self, name: str, kept: int) -> None:
        with _lock:
            self.category_kept[str(name or "Unknown")] = max(0, int(kept))

    def record_skipped_category(self, name: str, reason: str) -> None:
        with _lock:
            self.skipped_categories.append((str(name or "Unknown"), str(reason or "")))

    def record_category_error(self, name: str, error: str) -> None:
        with _lock:
            self.category_errors.append((str(name or "Unknown"), str(error or "")))

    def record_dedup(self, removed: int) -> None:
        if removed <= 0:
            return
        with _lock:
            self.dedup_removed += int(removed)

    @property
    def total_dropped(self) -> int:
        with _lock:
            return int(sum(self.drop_counts.values()))

    def snapshot(self) -> dict[str, Any]:
        with _lock:
            return {
                "context": dict(self.context),
                "drop_counts": dict(self.drop_counts),
                "parsed_total": self.parsed_total,
                "category_kept": dict(self.category_kept),
                "skipped_categories": list(self.skipped_categories),
                "category_errors": list(self.category_errors),
                "dedup_removed": self.dedup_removed,
            }


def begin_diagnostics(**context: Any) -> DropDiagnostics:
    """Start collecting diagnostics for one generate_attack_suite run."""
    global _active
    diag = DropDiagnostics()
    diag.context = dict(context)
    with _lock:
        _active = diag
    return diag


def end_diagnostics() -> DropDiagnostics | None:
    global _active
    with _lock:
        diag = _active
        _active = None
    return diag


def active_diagnostics() -> DropDiagnostics | None:
    with _lock:
        return _active


def track_parsed(count: int) -> None:
    diag = active_diagnostics()
    if diag is not None:
        diag.record_parsed(count)


def track_drops(stage: str, dropped: list[tuple[str, list[str]]]) -> None:
    diag = active_diagnostics()
    if diag is not None:
        diag.record_drops(stage, dropped)


def track_drop(stage: str, reason: str) -> None:
    diag = active_diagnostics()
    if diag is not None:
        diag.record_drop(stage, reason)


def _capability_lines(cap_flags: dict[str, bool] | None) -> list[str]:
    if not cap_flags:
        return []
    keys = (
        "code_execution",
        "tool_use",
        "file_upload",
        "web_browse",
        "memory",
        "retrieval",
    )
    lines: list[str] = []
    for key in keys:
        if key not in cap_flags:
            continue
        state = "CONFIRMED" if cap_flags.get(key) else "NOT CONFIRMED"
        lines.append(f"  - {key}: {state}")
    return lines


def _suggest_fixes(
    top: list[tuple[tuple[str, str], int]],
    *,
    cap_flags: dict[str, bool] | None,
    play_category: str,
    strategy: str,
) -> list[str]:
    hints: list[str] = []
    _ = play_category  # reserved for leaf-specific hints (taxonomy is mission.hunt only)
    reasons = {reason.lower() for (_stage, reason), _n in top}
    stages = {stage for (stage, _reason), _n in top}

    code_blocked = any(
        "code execution" in r or "tools not confirmed" in r for r in reasons
    )
    url_blocked = any("url" in r for r in reasons)
    upload_blocked = any("upload" in r or "ocr" in r or "attachment" in r for r in reasons)
    objective_blocked = any("attack_objective" in r for r in reasons)
    delivery_blocked = any(
        "script" in r or "run/execute" in r or "run step" in r for r in reasons
    ) or ("playbook" in stages and any("missing" in r for r in reasons))

    if code_blocked or (
        cap_flags
        and not (cap_flags.get("code_execution") or cap_flags.get("tool_use"))
        and any(
            token in " ".join(reasons)
            for token in ("sandbox", "interpreter", "subprocess", "code runtime")
        )
    ):
        hints.append(
            "This play likely needs code execution, but recon did not confirm "
            "code_execution/tool_use. Run Recon on a target with a code interpreter, "
            "update recon capabilities, or pick a play that matches a text-only chat surface."
        )
    if url_blocked:
        hints.append(
            "Prompts contained URLs, which text-only strategies cannot run. "
            "Regenerate, or edit seeds to paste content inline instead of linking."
        )
    if upload_blocked:
        hints.append(
            "Prompts referenced uploads/OCR/images without a multimodal harness. "
            "Use the multimodal strategy for file-based categories, or keep payloads inline."
        )
    if objective_blocked:
        hints.append(
            "Set or update Attack objective on the play, save, then regenerate so "
            "seeds include the required objective tokens/phrasing."
        )
    if delivery_blocked and strategy.replace("-", "_") != "adaptive":
        hints.append(
            "Delivery rules require script write + run steps in each seed. Try the "
            "adaptive strategy (short openers + runtime follow-ups), or regenerate "
            "after tightening playbook seed guidance."
        )
    if not hints:
        hints.append(
            "Scroll up in this output for per-prompt `[filter]`, `[capability]`, "
            "and `[playbook]` drop lines, then fix recon/play/strategy alignment."
        )
    return hints


def format_empty_suite_report(diag: DropDiagnostics | None) -> list[str]:
    """Human-readable diagnosis when a suite ends with zero runnable prompts."""
    if diag is None:
        return [
            "[!] Generation produced 0 runnable prompts.",
            "[!] No filter diagnostics were captured - check LLM API keys and generation logs above.",
        ]

    snap = diag.snapshot()
    ctx = snap.get("context") or {}
    playbook_id = str(ctx.get("playbook_id") or "?")
    strategy = str(ctx.get("strategy") or "?")
    play_category = str(ctx.get("play_category") or "")
    cap_flags = ctx.get("capability_flags")

    category_kept: dict[str, int] = snap.get("category_kept") or {}
    attempted = len(category_kept)
    with_prompts = sum(1 for n in category_kept.values() if n > 0)
    parsed_total = int(snap.get("parsed_total") or 0)
    total_dropped = int(sum((snap.get("drop_counts") or {}).values()))
    dedup_removed = int(snap.get("dedup_removed") or 0)

    lines = [
        f"[!] Generation produced 0 runnable prompts for {playbook_id}/{strategy}.",
        "[!] Diagnosis:",
        f"  Categories attempted: {attempted}; with prompts kept: {with_prompts}",
    ]

    if parsed_total:
        lines.append(f"  LLM parsed (before filters): {parsed_total} prompt(s)")
    else:
        lines.append(
            "  LLM parsed (before filters): 0 - judge may have returned nothing parseable "
            "(check API key, rate limits, or enable GENERATION_DEBUG=1)."
        )

    if total_dropped:
        lines.append(f"  Filtered out: {total_dropped} prompt(s)")
    if dedup_removed:
        lines.append(f"  Cross-category dedup removed: {dedup_removed} prompt(s)")

    skipped = snap.get("skipped_categories") or []
    if skipped:
        lines.append(f"  Skipped categories (strategy mismatch): {len(skipped)}")
        for name, reason in skipped[:3]:
            lines.append(f"    - {name}: {reason}")

    errors = snap.get("category_errors") or []
    if errors:
        lines.append(f"  Category generation errors: {len(errors)}")
        for name, err in errors[:2]:
            lines.append(f"    - {name}: {err[:120]}")

    drop_counts: dict[tuple[str, str], int] = snap.get("drop_counts") or {}
    if drop_counts:
        lines.append("[!] Top filter reasons:")
        top = sorted(drop_counts.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1]))[:8]
        for (stage, reason), count in top:
            lines.append(f"  - {count}x [{stage}] {reason}")

        cap_lines = _capability_lines(cap_flags if isinstance(cap_flags, dict) else None)
        if cap_lines:
            lines.append("[!] Target capabilities (from recon):")
            lines.extend(cap_lines)

        hints = _suggest_fixes(
            top,
            cap_flags=cap_flags if isinstance(cap_flags, dict) else None,
            play_category=play_category,
            strategy=strategy,
        )
        lines.append("[!] Likely fix:")
        for hint in hints[:3]:
            lines.append(f"  - {hint}")
    elif parsed_total == 0:
        lines.append(
            "[!] Likely fix: verify GEMINI_API_KEY (or the provider for generation roles in "
            "llm.yaml), then regenerate with GENERATION_DEBUG=1 to inspect judge output."
        )
    else:
        lines.append(
            "[!] Likely fix: prompts were removed after parsing but drop reasons were not "
            "recorded - regenerate and inspect `[filter]` / `[capability]` lines above."
        )

    return lines
