"""API-based submission (direct HTTP, no browser automation)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from browser_bot.config import (
    API_CONCURRENCY,
    EVASION_REQUEST_DELAY_S,
    get_posts_batches,
    get_posts_strings,
    get_suite_multi_test_cases,
    get_suite_test_cases,
)
from browser_bot.sites import get_submission_config

from browser_bot.submit.api_helpers import do_api_request, uses_messages_context
from browser_bot.submit.common import (
    SubmissionProgressTracker,
    _write_run_log,
    append_test_prompt_delimiter,
    load_run_stop_words,
    log_evasion,
    log_resilience,
    response_stop_word_match,
)
from browser_bot.run_control import (
    SkipCurrentPromptError,
    await_with_skip,
    clear_skip_request,
    log_skip_current_applied,
    sleep_or_skip,
)
from browser_bot.submit.rejection_detection import (
    OUTCOME_SKIPPED,
    OUTCOME_SUBMIT_FAILED,
    apply_submission_outcome,
)


async def _api_request_one(
    sub: dict,
    text: str,
    *,
    site: str | None,
    component: str | None = None,
    test_case: dict | None = None,
    suite_path=None,
    conversation_history: list[tuple[str, str | None]] | None = None,
) -> tuple[str, str, str | None, dict]:
    """Returns ``(raw_text, submitted_text, response_text, submission_meta)``."""
    submitted = append_test_prompt_delimiter(text)
    try:
        status, response_text, err, submission_meta = await await_with_skip(
            asyncio.to_thread(
                do_api_request,
                sub,
                submitted,
                site=site,
                component=component,
                test_case=test_case,
                suite_path=suite_path,
                conversation_history=conversation_history,
            )
        )
    except SkipCurrentPromptError:
        clear_skip_request()
        log_skip_current_applied()
        return text, submitted, None, apply_submission_outcome({}, OUTCOME_SKIPPED)
    meta = submission_meta or {}
    if response_text and meta.get("api_refusal"):
        cat = meta.get("refusal_category") or meta.get("stop_reason") or "refusal"
        print(f"  [api] model refusal ({cat})", flush=True)
    elif err and not response_text:
        print(f"  [api] prompt failed ({status}): {err}")
        if not meta.get("submission_outcome"):
            meta = apply_submission_outcome(meta, OUTCOME_SUBMIT_FAILED)
        if err and not meta.get("api_error"):
            meta = {**meta, "api_error": str(err)[:800]}
        if status is not None and meta.get("http_status") is None:
            meta = {**meta, "http_status": int(status)}
    return text, submitted, response_text, meta


async def _api_request_batch(
    sub: dict,
    batch: list[str],
    *,
    site: str | None,
    component: str | None = None,
    tracker: SubmissionProgressTracker,
    stop_words: list[str] | None = None,
) -> list[tuple[str, str | None, dict]]:
    results: list[tuple[str, str | None, dict]] = []
    history: list[tuple[str, str | None]] = []
    accumulate = uses_messages_context(sub)
    for text in batch:
        raw, submitted, response, net = await _api_request_one(
            sub,
            text,
            site=site,
            component=component,
            conversation_history=list(history) if accumulate else None,
        )
        results.append((raw, response, net))
        if accumulate:
            history.append((submitted, response or ""))
        tracker.record_completed(
            1,
            input_text=raw,
            response=response,
            submission_outcome=str((net or {}).get("submission_outcome") or ""),
            rejection_signals=list((net or {}).get("rejection_signals") or []),
        )
        if response_stop_word_match(response, stop_words or []):
            break
    return results


def _api_concurrency() -> int:
    return max(1, int(API_CONCURRENCY or 1))


async def run_api_submission_single(
    site: str,
    component: str,
    *,
    suite_path=None,
) -> tuple[list[tuple[str, str | None]], Path | None]:
    sub = get_submission_config(site, component)
    transport = (sub or {}).get("transport", "")
    if not sub or transport not in ("api", "api_document", "api_multipart"):
        return [], None

    test_cases = get_suite_test_cases(suite_path) if suite_path else []
    posts = [tc["prompt"] for tc in test_cases] if test_cases else get_posts_strings(suite_path=suite_path)
    if not posts:
        return [], None
    case_list = test_cases if test_cases else [None] * len(posts)

    tracker = SubmissionProgressTracker("single", len(posts))
    tracker.emit_run_start()

    stop_words = load_run_stop_words(suite_path)
    stop_word_matched = ""
    stopped_early = False
    concurrency = _api_concurrency()
    results: list[tuple[str, str | None]] = []
    submission_metas: list[dict] = []

    if concurrency > 1 and len(posts) > 1:
        print(
            f"  [api] running {len(posts)} prompt(s) with concurrency={concurrency}",
            flush=True,
        )
        sem = asyncio.Semaphore(concurrency)

        async def _one(text: str, tc: dict | None) -> tuple[str, str | None, dict]:
            async with sem:
                # Stagger concurrent workers so burst traffic is less likely to 429.
                if EVASION_REQUEST_DELAY_S:
                    await sleep_or_skip(EVASION_REQUEST_DELAY_S)
                raw, _submitted, response, meta = await _api_request_one(
                    sub, text, site=site, component=component, test_case=tc, suite_path=suite_path
                )
                try:
                    from browser_bot.submit.bounty_adaptive import (
                        bounty_hybrid_should_attempt,
                        run_bounty_hybrid_followups_api,
                    )

                    if bounty_hybrid_should_attempt(suite_path, tc):
                        raw, response, meta = await run_bounty_hybrid_followups_api(
                            sub=sub,
                            site=site,
                            component=component,
                            seed_prompt=text,
                            first_response=response,
                            first_meta=meta,
                            test_case=tc or {},
                            suite_path=suite_path,
                            stop_words=stop_words,
                        )
                except Exception as exc:
                    try:
                        from browser_bot.submit.common import log_resilience

                        log_resilience(
                            "bounty_adaptive",
                            f"API hybrid wrapper skipped: {exc}",
                        )
                    except Exception:
                        pass
                tracker.record_completed(
                    1,
                    input_text=raw,
                    response=response,
                    submission_outcome=str((meta or {}).get("submission_outcome") or ""),
                    rejection_signals=list((meta or {}).get("rejection_signals") or []),
                )
                return raw, response, meta

        gathered = await asyncio.gather(*[_one(text, tc) for text, tc in zip(posts, case_list)])
        for raw, response, meta in gathered:
            results.append((raw, response))
            submission_metas.append(meta)
    else:
        for i, (text, tc) in enumerate(zip(posts, case_list)):
            clear_skip_request()
            if i > 0:
                log_evasion(
                    "sequential_burst_pause",
                    sleep_s=EVASION_REQUEST_DELAY_S,
                    detail="Pause between sequential API prompts",
                )
                await sleep_or_skip(EVASION_REQUEST_DELAY_S)
            try:
                raw, _submitted, response, meta = await _api_request_one(
                    sub, text, site=site, component=component, test_case=tc, suite_path=suite_path
                )
            except SkipCurrentPromptError:
                clear_skip_request()
                log_skip_current_applied()
                results.append((text, None))
                submission_metas.append(apply_submission_outcome({}, OUTCOME_SKIPPED))
                tracker.record_completed(
                    1,
                    input_text=text,
                    response=None,
                    submission_outcome=OUTCOME_SKIPPED,
                )
                continue
            try:
                from browser_bot.submit.bounty_adaptive import (
                    bounty_hybrid_should_attempt,
                    run_bounty_hybrid_followups_api,
                )

                if bounty_hybrid_should_attempt(suite_path, tc):
                    raw, response, meta = await run_bounty_hybrid_followups_api(
                        sub=sub,
                        site=site,
                        component=component,
                        seed_prompt=text,
                        first_response=response,
                        first_meta=meta,
                        test_case=tc or {},
                        suite_path=suite_path,
                        stop_words=stop_words,
                    )
            except Exception as exc:
                try:
                    from browser_bot.submit.common import log_resilience

                    log_resilience(
                        "bounty_adaptive",
                        f"API hybrid wrapper skipped: {exc}",
                    )
                except Exception:
                    pass
            results.append((raw, response))
            submission_metas.append(meta)
            tracker.record_completed(
                1,
                input_text=raw,
                response=response,
                submission_outcome=str((meta or {}).get("submission_outcome") or ""),
                rejection_signals=list((meta or {}).get("rejection_signals") or []),
            )
            matched = response_stop_word_match(response, stop_words)
            if matched:
                stop_word_matched = matched
                stopped_early = True
                log_resilience(
                    "success_markers",
                    f"Success marker '{matched}' found in response - ending run early "
                    f"({i + 1}/{len(posts)} prompts completed)",
                )
                break

    tracker.emit_run_done()
    log_path = (
        _write_run_log(
            site,
            component,
            results,
            test_cases=test_cases or None,
            suite_path=suite_path,
            stopped_early=stopped_early,
            stop_word_matched=stop_word_matched,
            submission_metas=submission_metas or None,
        )
        if results
        else None
    )
    return results, log_path


async def run_api_submission_multi(
    site: str,
    component: str,
    *,
    suite_path=None,
) -> tuple[list[tuple[str, str | None]], Path | None]:
    sub = get_submission_config(site, component)
    if not sub or sub.get("transport") not in ("api", "api_document", "api_multipart"):
        return [], None

    batches = get_posts_batches(suite_path=suite_path)
    if not batches:
        return [], None

    total_turns = sum(len(b) for b in batches)
    tracker = SubmissionProgressTracker("multi", total_turns)
    tracker.emit_run_start()

    stop_words = load_run_stop_words(suite_path)
    stop_word_matched = ""
    stopped_early = False
    concurrency = _api_concurrency()
    all_results: list[tuple[str, str | None]] = []
    all_submission_metas: list[dict] = []

    if concurrency > 1 and len(batches) > 1:
        print(
            f"  [api] running {len(batches)} batch(es) ({total_turns} turn(s)) "
            f"with concurrency={concurrency}",
            flush=True,
        )
        sem = asyncio.Semaphore(concurrency)

        async def _one_batch(batch: list[str]) -> list[tuple[str, str | None, dict]]:
            async with sem:
                return await _api_request_batch(sub, batch, site=site, component=component, tracker=tracker)

        batch_results = await asyncio.gather(*[_one_batch(batch) for batch in batches])
        for batch in batch_results:
            for raw, resp, meta in batch:
                all_results.append((raw, resp))
                all_submission_metas.append(meta)
    else:
        for i, batch in enumerate(batches):
            if i > 0:
                log_evasion(
                    "sequential_burst_pause",
                    sleep_s=EVASION_REQUEST_DELAY_S,
                    detail="Pause between sequential API batches",
                )
                await asyncio.sleep(EVASION_REQUEST_DELAY_S)
            batch_results = await _api_request_batch(
                sub,
                batch,
                site=site,
                component=component,
                tracker=tracker,
                stop_words=stop_words,
            )
            for raw, resp, meta in batch_results:
                all_results.append((raw, resp))
                all_submission_metas.append(meta)
            for _, resp, _ in batch_results:
                matched = response_stop_word_match(resp, stop_words)
                if matched:
                    stop_word_matched = matched
                    stopped_early = True
                    log_resilience(
                        "success_markers",
                        f"Success marker '{matched}' found in response - ending run early",
                    )
                    break
            if stopped_early:
                break

    tracker.emit_run_done()
    multi_test_cases = get_suite_multi_test_cases(suite_path) if suite_path else []
    log_batches = batches
    if stopped_early and all_results:
        effective_batches: list[list[str]] = []
        offset = 0
        for batch in batches:
            if offset >= len(all_results):
                break
            take = min(len(batch), len(all_results) - offset)
            effective_batches.append(batch[:take])
            offset += take
            if offset >= len(all_results):
                break
        log_batches = effective_batches
        if stop_word_matched and multi_test_cases:
            multi_test_cases = multi_test_cases[: len(effective_batches)]
    log_path = (
        _write_run_log(
            site,
            component,
            all_results,
            multi_batches=log_batches,
            multi_test_cases=multi_test_cases or None,
            suite_path=suite_path,
            stopped_early=stopped_early,
            stop_word_matched=stop_word_matched,
            submission_metas=all_submission_metas or None,
        )
        if all_results
        else None
    )
    return all_results, log_path
