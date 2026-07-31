"""
Convert browser-bot run logs into attack_log.json for security-assess.

browser-bot run logs have shape:
  Single: { site, component, timestamp, mode: "single", entries: [{ input, response }] }
  Multi:  { site, component, timestamp, mode: "multi",  batches: [{ turns: [{ input, response }] }] }

Generated suite JSON has shape:
  { playbook, playbook_id, categories: [{ name, prompts: [...] }] }
"""
import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from pipeline.response_echo import strip_echoed_prompt_from_response
from payloads.resolve import infer_strategy_from_suite_path

# Keep in sync with browser_bot.submit.common.TEST_PROMPT_DELIMITER
_RUN_PROMPT_SUFFIX = "" # \n[TEXT ONLY. NO HTML OR MARKUP. MAX 600 CHARS]


def _resolved_convert_response(
    response: Any,
    submitted: Any,
) -> tuple[str, bool]:
    """Sanitize for display but never blank a non-empty raw capture.

    Capture-time sanitize returns None for echoes/boilerplate (UI wait-gate).
    Convert used to collapse that to "" + ok=False, which assess treated as a
    harness miss. Preserve the raw reply so assessment can score model behavior
    (usually Low / echo / filler) instead of indeterminate capture failure.

    Returns (response_text, sanitize_blanked).
    """
    raw = "" if response is None else str(response)
    cleaned = strip_echoed_prompt_from_response(response, str(submitted or ""))
    if cleaned is not None and str(cleaned).strip():
        return str(cleaned), False
    if raw.strip():
        # Sanitize cleared actionable text but a real capture exists.
        return raw, cleaned is None or not str(cleaned or "").strip()
    return "", False


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _suite_categories(suite: dict) -> list:
    cats = suite.get("categories")
    if isinstance(cats, list):
        return cats
    return suite.get("mandates") or []


def _category_name(cat: dict) -> str:
    return cat.get("name", cat.get("mandate", ""))


def _detect_suite_mode(suite: dict) -> str:
    for m in _suite_categories(suite):
        for p in m.get("prompts") or []:
            if isinstance(p.get("prompts"), list):
                return "multi"
            if isinstance(p.get("prompt"), str):
                return "single"
    return "single"


def _category_id(cat: dict) -> str:
    return str(cat.get("id") or "").strip()


def _copy_bounty_meta(prompt: dict, row: dict) -> None:
    """Propagate invent/mutate attribution fields from suite prompts."""
    for key in (
        "bounty_slot",
        "mutate_of",
        "mechanism_family",
        "ask_pattern",
        "enhance_phase",
        "broadened_ask",
    ):
        val = prompt.get(key)
        if val is not None and str(val).strip():
            row[key] = val


def _build_single_index(suite: dict) -> list[dict]:
    out: list[dict] = []
    for m in _suite_categories(suite):
        cat_name = _category_name(m)
        cat_id = _category_id(m)
        for p in m.get("prompts") or []:
            row = {
                "id": p.get("id", ""),
                "category": cat_name,
                "category_id": cat_id,
                "description": p.get("description", ""),
                "prompt": p.get("prompt", ""),
            }
            if p.get("vector_type"):
                row["vector_type"] = p["vector_type"]
            if p.get("payload"):
                row["payload"] = p["payload"]
            if p.get("context_mode"):
                row["context_mode"] = p["context_mode"]
            if p.get("control_type"):
                row["control_type"] = p["control_type"]
            _copy_bounty_meta(p, row)
            out.append(row)
    return out


def _build_multi_index(suite: dict) -> list[dict]:
    out: list[dict] = []
    for m in _suite_categories(suite):
        cat_name = _category_name(m)
        cat_id = _category_id(m)
        for p in m.get("prompts") or []:
            row = {
                "id": p.get("id", ""),
                "category": cat_name,
                "category_id": cat_id,
                "description": p.get("description", ""),
                "prompts": p.get("prompts", []),
            }
            if p.get("vector_type"):
                row["vector_type"] = p["vector_type"]
            if p.get("payload"):
                row["payload"] = p["payload"]
            if p.get("context_mode"):
                row["context_mode"] = p["context_mode"]
            if p.get("control_type"):
                row["control_type"] = p["control_type"]
            _copy_bounty_meta(p, row)
            out.append(row)
    return out


@lru_cache(maxsize=1)
def _ui_prompt_wrapper_parts() -> tuple[str | None, str | None]:
    try:
        root = Path(__file__).resolve().parent.parent
        bb = root / "browser-bot"
        if bb.is_dir() and str(bb) not in sys.path:
            sys.path.insert(0, str(bb))
        from browser_bot.config import UI_PROMPT_PREFIX, UI_PROMPT_PREFIX_SEPARATOR

        p = UI_PROMPT_PREFIX or ""
        sep = UI_PROMPT_PREFIX_SEPARATOR or ""
        if not p:
            return (None, None)
        head = f"{p}{sep}"
        tail = f"{sep}{p}"
        return (head, tail)
    except Exception:
        return (None, None)


def _strip_ui_prefix(submitted: str) -> str:
    """Strip configured UI_PROMPT_PREFIX wrappers only - never attack frames like [SCENE]."""
    s = submitted.strip()
    head, tail = _ui_prompt_wrapper_parts()
    if tail and s.endswith(tail):
        s = s[: -len(tail)].rstrip()
    elif head and s.startswith(head):
        s = s[len(head) :].strip()
    return s.strip()


def normalize_submitted_prompt(submitted: str) -> str:
    """Strip UI wrappers and run-time suffixes before matching suite prompts."""
    s = _strip_ui_prefix(submitted)
    # Empty suffix must not match: str.endswith("") is always True and s[:-0] == "".
    if _RUN_PROMPT_SUFFIX and s.endswith(_RUN_PROMPT_SUFFIX):
        s = s[: -len(_RUN_PROMPT_SUFFIX)].rstrip()
    return s.strip()

def _prompt_matches(original: str, submitted_body: str) -> bool:
    orig = original.strip()
    sub = normalize_submitted_prompt(submitted_body)
    if not sub:
        return False
    if orig == sub:
        return True
    if sub.startswith(orig) and len(orig) >= min(40, len(sub)):
        return True
    if orig.startswith(sub) and len(sub) >= min(80, len(orig)):
        return True
    return False


def _is_stable_suite_id(tid: str) -> bool:
    t = str(tid or "").strip()
    return bool(t) and not t.startswith(("entry-", "batch-"))


def _entry_capture_id(entry: dict[str, Any]) -> str:
    cid = str(entry.get("capture_id") or "").strip()
    if cid:
        return cid
    evidence = entry.get("network_evidence")
    if isinstance(evidence, dict):
        return str(evidence.get("capture_id") or "").strip()
    return ""


def _lookup_suite_id(tid: str, index: list[dict]) -> dict | None:
    if not _is_stable_suite_id(tid):
        return None
    for row in index:
        if row.get("id") == tid:
            return row
    return None


def build_suite_prompt_index(suite: dict) -> list[dict]:
    """Flat list of suite prompts with category metadata (single or multi-turn)."""
    if _detect_suite_mode(suite) == "multi":
        return _build_multi_index(suite)
    return _build_single_index(suite)


def resolve_suite_match(
    item: dict,
    index: list[dict],
    *,
    position: int | None = None,
    allow_position: bool = True,
) -> dict | None:
    """Match a run/assessment row back to its suite prompt definition.

    Priority: stable ``id`` / ``test_id`` / ``capture_id``, then prompt text.
    Positional fallback is opt-in and only used when the prompt at that index
    also matches (never a blind index steal).
    """
    for key in ("id", "test_id", "capture_id"):
        hit = _lookup_suite_id(str(item.get(key) or ""), index)
        if hit is not None:
            return hit
    prompt = item.get("prompt", "")
    for row in index:
        if _prompt_matches(row.get("prompt", ""), prompt):
            return row
    if (
        allow_position
        and position is not None
        and 0 <= position < len(index)
        and _prompt_matches(index[position].get("prompt", ""), prompt)
    ):
        return index[position]
    return None


def _warn_pairing(msg: str) -> None:
    print(f"[!] convert_log pairing: {msg}", file=sys.stderr)


def _apply_matched_metadata(
    row: dict[str, Any],
    matched: dict[str, Any] | None,
    *,
    submitted: str,
    fallback_id: str,
) -> None:
    """Fill id/category/prompt fields from a suite match, or submitted input."""
    if matched:
        row["id"] = matched.get("id") or fallback_id
        row["category"] = matched.get("category") or ""
        row["description"] = matched.get("description") or ""
        row["prompt"] = matched.get("prompt") or submitted
        if matched.get("category_id"):
            row["category_id"] = matched["category_id"]
        else:
            row.pop("category_id", None)
        if matched.get("control_type"):
            row["control_type"] = matched["control_type"]
        if matched.get("payload"):
            row["payload"] = matched["payload"]
        for key in (
            "bounty_slot",
            "mutate_of",
            "mechanism_family",
            "ask_pattern",
            "enhance_phase",
            "broadened_ask",
        ):
            if matched.get(key) is not None and str(matched.get(key) or "").strip():
                row[key] = matched[key]
            else:
                row.pop(key, None)
    else:
        row["id"] = fallback_id
        row["category"] = ""
        row["description"] = ""
        row["prompt"] = submitted
        row.pop("category_id", None)
        row.pop("control_type", None)
        row.pop("payload", None)
        for key in (
            "bounty_slot",
            "mutate_of",
            "mechanism_family",
            "ask_pattern",
            "enhance_phase",
            "broadened_ask",
        ):
            row.pop(key, None)


def _reconcile_id_capture_mismatch(
    row: dict[str, Any],
    *,
    index: list[dict],
    submitted: str,
) -> None:
    """If id and capture_id disagree, prefer capture_id suite metadata."""
    row_id = str(row.get("id") or "").strip()
    cap = str(row.get("capture_id") or "").strip()
    if not _is_stable_suite_id(row_id) or not _is_stable_suite_id(cap):
        return
    if row_id == cap:
        return
    corrected = _lookup_suite_id(cap, index)
    _warn_pairing(
        f"id={row_id!r} != capture_id={cap!r}; "
        f"{'re-binding to capture_id suite row' if corrected else 'using submitted input'}"
    )
    _apply_matched_metadata(
        row,
        corrected,
        submitted=submitted,
        fallback_id=cap,
    )
    row["id"] = corrected["id"] if corrected and corrected.get("id") else cap


def _infer_playbook_id(suite: dict) -> str:
    pid = (suite.get("playbook_id") or "").strip()
    if pid:
        return pid
    playbook = (suite.get("playbook") or suite.get("framework") or "").strip()
    if not playbook:
        return ""
    lower = playbook.lower()
    keyword_map = (
        ("sandbox", "sandbox_breakout"),
        ("jailbreak", "jailbreak"),
    )
    for needle, stem in keyword_map:
        if needle in lower:
            return stem
    try:
        from playbooks.registry import list_playbook_stems
        for stem in list_playbook_stems():
            if stem.replace("_", " ") in lower or stem in lower:
                return stem
    except Exception:
        pass
    return ""


def _suite_meta(suite: dict, *, strategy: str = "", suite_path: str = "") -> dict:
    playbook_id = _infer_playbook_id(suite)
    meta = {
        "playbook": suite.get("playbook", suite.get("framework", "")),
        "playbook_id": playbook_id,
    }
    if suite.get("oracle_version") and suite.get("oracle_hash"):
        meta["oracle_version"] = suite["oracle_version"]
        meta["oracle_hash"] = suite["oracle_hash"]
        meta["oracle_configured"] = bool(suite.get("oracle_configured", False))
    else:
        try:
            from pipeline.oracles import oracle_contract_metadata
            from playbooks.registry import load_playbook

            meta.update(oracle_contract_metadata(load_playbook(playbook_id)))
        except Exception:
            pass
    if strategy:
        meta["strategy"] = strategy

    target_ctx = suite.get("target_context")
    if isinstance(target_ctx, dict) and target_ctx.get("source"):
        meta["target_context"] = target_ctx
    elif suite_path:
        from pipeline.recon_context import load_recon, recon_provenance, resolve_site_component_from_paths

        site, component = resolve_site_component_from_paths(suite_path)
        if site and component:
            recon = load_recon(site, component)
            if recon:
                meta["target_context"] = recon_provenance(recon)
    return meta


def _run_log_stop_meta(run_log: dict) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    if run_log.get("stopped_early"):
        meta["stopped_early"] = True
        matched = str(run_log.get("stop_word_matched") or "").strip()
        if matched:
            meta["stop_word_matched"] = matched
    return meta


def _resolve_log_strategy(run_log: dict, suite_path: str) -> str:
    strategy = (run_log.get("strategy") or "").strip()
    if strategy:
        return strategy
    return infer_strategy_from_suite_path(suite_path)


def _attach_capture_and_outcome_fields(row: dict[str, Any], entry: dict[str, Any]) -> None:
    """Attach capture_id (legacy network_evidence fallback) + submission outcome."""
    cid = _entry_capture_id(entry)
    if cid and "capture_id" not in row:
        row["capture_id"] = cid
    _attach_submission_outcome_fields(row, entry)


def _attach_submission_outcome_fields(row: dict[str, Any], entry: dict[str, Any]) -> None:
    evidence = entry.get("network_evidence") if isinstance(entry.get("network_evidence"), dict) else {}
    outcome = entry.get("submission_outcome") or evidence.get("submission_outcome")
    if outcome:
        row["submission_outcome"] = outcome
        if outcome == "client_rejected":
            row["client_rejected"] = True
    signals = entry.get("rejection_signals") or evidence.get("rejection_signals")
    if signals:
        row["rejection_signals"] = signals
    capture_incomplete = entry.get("capture_incomplete")
    if capture_incomplete is None:
        capture_incomplete = evidence.get("capture_incomplete")
    if capture_incomplete:
        row["capture_incomplete"] = True
    delivered = entry.get("artifact_delivered")
    if delivered is None:
        delivered = evidence.get("artifact_delivered")
    if delivered is not None:
        row["artifact_delivered"] = bool(delivered)
    # Provider structured refusals (Anthropic stop_reason=refusal, etc.)
    if entry.get("api_refusal") or evidence.get("api_refusal"):
        row["api_refusal"] = True
        for key in ("stop_reason", "refusal_category", "refusal_explanation", "provider_signal"):
            val = entry.get(key) if entry.get(key) is not None else evidence.get(key)
            if val is not None and str(val).strip():
                row[key] = val
    if entry.get("http_status") is not None:
        row["http_status"] = entry["http_status"]
    elif evidence.get("http_status") is not None:
        row["http_status"] = evidence["http_status"]
    api_error = entry.get("api_error") or evidence.get("api_error")
    if api_error:
        row["api_error"] = str(api_error)[:800]


def _convert_single(run_log: dict, suite: dict, suite_path: str) -> dict:
    entries = run_log.get("entries") or []
    index = _build_single_index(suite)
    strategy = _resolve_log_strategy(run_log, suite_path)
    meta = _suite_meta(suite, strategy=strategy, suite_path=suite_path)
    results: list[dict] = []

    for i, entry in enumerate(entries):
        submitted = entry.get("input", "")
        response = entry.get("response")
        capture_id = _entry_capture_id(entry)
        fallback_id = (
            str(entry.get("id") or "").strip()
            or capture_id
            or f"entry-{i + 1}"
        )
        match_item = {
            "id": entry.get("id"),
            "test_id": entry.get("test_id"),
            "capture_id": capture_id,
            "prompt": submitted,
        }
        # Never blind positional fallback - probe_class run order ≠ suite file order.
        matched = resolve_suite_match(match_item, index, allow_position=False)

        vector_type = (
            entry.get("vector_type")
            or (matched.get("vector_type") if matched else None)
            or "text_direct"
        )
        response_text, sanitize_blanked = _resolved_convert_response(response, submitted)
        row: dict[str, Any] = {
            "response": response_text,
            "ok": bool(response_text and str(response_text).strip()),
            "vector_type": vector_type,
        }
        if sanitize_blanked:
            # Model reply existed but sanitize treated it as echo/boilerplate.
            # Keep text for assessment; do not mark as capture failure.
            row["sanitize_blanked"] = True
            row["ok"] = True
        _apply_matched_metadata(
            row,
            matched,
            submitted=submitted,
            fallback_id=fallback_id,
        )
        if strategy:
            row["strategy"] = strategy
        if entry.get("artifact_path"):
            row["artifact_path"] = entry["artifact_path"]
        if "upload_ok" in entry:
            row["upload_ok"] = entry["upload_ok"]
        if entry.get("extracted_text_preview"):
            row["extracted_text_preview"] = entry["extracted_text_preview"]
        elif matched:
            from pipeline.artifact_preview import preview_from_suite_prompt

            preview = preview_from_suite_prompt(matched)
            if preview:
                row["extracted_text_preview"] = preview
        _attach_capture_and_outcome_fields(row, entry)
        _reconcile_id_capture_mismatch(row, index=index, submitted=submitted)
        results.append(row)

    return {**meta, **_run_log_stop_meta(run_log), "source_file": suite_path, "results": results}


def _convert_multi(run_log: dict, suite: dict, suite_path: str) -> dict:
    """One attack_log row per multi-turn case - final turn only (for risk assessment)."""
    batches = run_log.get("batches") or []
    is_adaptive = run_log.get("mode") == "adaptive"
    index = _build_single_index(suite) if is_adaptive else _build_multi_index(suite)
    strategy = _resolve_log_strategy(run_log, suite_path)
    meta = _suite_meta(suite, strategy=strategy, suite_path=suite_path)
    results: list[dict] = []

    for batch_i, batch in enumerate(batches):
        turns = batch.get("turns") or []
        if not turns:
            continue
        first_input = turns[0].get("input", "") if turns else ""
        match_item = {
            "id": batch.get("id"),
            "test_id": batch.get("test_id"),
            "capture_id": batch.get("capture_id") or _entry_capture_id(turns[-1]),
            "prompt": first_input,
        }
        matched = resolve_suite_match(match_item, index, allow_position=False)
        if matched is None and turns:
            # Prompt-only: adaptive seeds use single prompt; multi uses prompts[0].
            for idx_entry in index:
                if is_adaptive:
                    seed = idx_entry.get("prompt", "")
                    if seed and _prompt_matches(seed, first_input):
                        matched = idx_entry
                        break
                elif idx_entry.get("prompts") and _prompt_matches(
                    idx_entry["prompts"][0], first_input
                ):
                    matched = idx_entry
                    break

        prior_turns: list[dict] = []
        all_turns: list[dict] = []
        for turn_i, turn in enumerate(turns[:-1]):
            if matched and not is_adaptive and turn_i < len(matched.get("prompts", [])):
                original_prompt = matched["prompts"][turn_i]
            elif matched and is_adaptive and turn_i == 0:
                original_prompt = matched.get("prompt", "")
            else:
                original_prompt = turn.get("input", "")
            turn_row = {
                "turn": turn_i,
                "prompt": original_prompt,
                "response": _resolved_convert_response(
                    turn.get("response"), turn.get("input", "")
                )[0],
            }
            prior_turns.append(turn_row)
            all_turns.append(turn_row)

        final_turn = turns[-1]
        final_i = len(turns) - 1
        if matched and not is_adaptive and final_i < len(matched.get("prompts", [])):
            final_prompt = matched["prompts"][final_i]
        else:
            final_prompt = final_turn.get("input", "")

        response_text, sanitize_blanked = _resolved_convert_response(
            final_turn.get("response"), final_turn.get("input", "")
        )
        final_row = {
            "turn": final_i,
            "prompt": final_prompt,
            "response": response_text,
        }
        all_turns.append(final_row)

        fallback_id = (
            str(batch.get("id") or "").strip()
            or str(match_item.get("capture_id") or "").strip()
            or f"batch-{batch_i + 1}"
        )
        row: dict[str, Any] = {
            "response": response_text,
            "ok": bool(response_text and str(response_text).strip()),
            "prior_turns": prior_turns,
            "turns": all_turns,
        }
        if sanitize_blanked and response_text.strip():
            row["sanitize_blanked"] = True
            row["ok"] = True
        if matched:
            _apply_matched_metadata(
                row,
                matched,
                submitted=final_prompt,
                fallback_id=fallback_id,
            )
            # Multi-turn final prompt may differ from seed; keep resolved final_prompt.
            row["prompt"] = final_prompt
            if batch.get("category"):
                row["category"] = batch["category"]
            if batch.get("description"):
                row["description"] = batch["description"]
            if batch.get("id"):
                row["id"] = batch["id"]
            for key in (
                "bounty_slot",
                "mutate_of",
                "mechanism_family",
                "ask_pattern",
                "enhance_phase",
                "broadened_ask",
            ):
                if batch.get(key) is not None and str(batch.get(key) or "").strip():
                    row[key] = batch[key]
        else:
            row["id"] = fallback_id
            row["category"] = batch.get("category") or ""
            row["description"] = batch.get("description") or ""
            row["prompt"] = final_prompt
            for key in (
                "bounty_slot",
                "mutate_of",
                "mechanism_family",
                "ask_pattern",
                "enhance_phase",
                "broadened_ask",
            ):
                if batch.get(key) is not None and str(batch.get(key) or "").strip():
                    row[key] = batch[key]
        category_id = batch.get("category_id") or (matched.get("category_id") if matched else "")
        if category_id:
            row["category_id"] = category_id
        if strategy:
            row["strategy"] = strategy
        if matched:
            vector_type = matched.get("vector_type") or "text_direct"
            row["vector_type"] = vector_type
            if matched.get("payload"):
                from pipeline.artifact_preview import preview_from_suite_prompt

                preview = preview_from_suite_prompt(matched)
                if preview:
                    row["extracted_text_preview"] = preview
        _attach_capture_and_outcome_fields(row, final_turn)
        _reconcile_id_capture_mismatch(row, index=index, submitted=final_prompt)
        # Keep multi-turn final prompt after any id/capture reconcile of seed metadata.
        if not is_adaptive and matched and final_i < len(matched.get("prompts", [])):
            # If reconcile rebound to a different suite row, refresh final prompt from it.
            rebound = _lookup_suite_id(str(row.get("id") or ""), index)
            if rebound and final_i < len(rebound.get("prompts") or []):
                row["prompt"] = rebound["prompts"][final_i]
                row["turns"][-1]["prompt"] = row["prompt"]
        results.append(row)

    return {**meta, **_run_log_stop_meta(run_log), "source_file": suite_path, "results": results}


def convert_run_log(
    run_log_path: Path,
    suite_path: Path,
    output_path: Path | None = None,
) -> Path:
    """Convert run log + suite into attack_log.json for security-assess."""
    run_log = _load_json(run_log_path)
    suite = _load_json(suite_path)
    suite_rel = str(suite_path)

    mode = run_log.get("mode", "single")
    if mode in ("multi", "adaptive"):
        attack_log = _convert_multi(run_log, suite, suite_rel)
    else:
        attack_log = _convert_single(run_log, suite, suite_rel)

    if output_path is None:
        output_path = run_log_path.parent / "attack_log.json"

    output_path.write_text(json.dumps(attack_log, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path
