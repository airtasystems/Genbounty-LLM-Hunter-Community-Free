"""Multi-string UI submission: N prompts per page/session in sequence."""

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from browser_bot.browser.human_behavior import human_mouse_wander
from browser_bot.config import EVASION_REQUEST_DELAY_S, get_posts_batches, get_suite_multi_test_cases
from browser_bot.live_preview import capture_preview_screenshot, live_preview_context
from browser_bot.page_blockers import (
    PageBlockedError,
    check_login_wall_before_submit,
    check_rate_limit_before_submit,
    ensure_page_ready_for_submit,
)
from browser_bot.sites import get_storage_state_path, get_submission_config

from browser_bot.submit.common import (
    NonSuccessResponseError,
    SubmissionProgressTracker,
    _do_one_submit_step,
    _write_run_log,
    append_test_prompt_delimiter,
    fetcher_with_page_kwargs,
    inputs_for_submission,
    load_run_stop_words,
    log_evasion,
    log_resilience,
    resolve_ui_parallel_concurrency,
    response_capture_kwargs,
    response_stop_word_match,
    run_ui_submit_with_strategy_fallback,
    run_with_evasion_retry,
    ui_fetchers_to_try,
)
from browser_bot.run_control import (
    SkipCurrentPromptError,
    clear_skip_request,
    log_skip_current_applied,
    sleep_or_skip,
)
from browser_bot.submit.rejection_detection import (
    OUTCOME_CLIENT_REJECTED,
    OUTCOME_SKIPPED,
    apply_submission_outcome,
)

if TYPE_CHECKING:
    from playwright.async_api import Page

    from browser_bot.fetchers.ui_bundle import UIFetcherBundle


async def do_ui_submit_sequence_with_page(
    page: "Page",
    start_url: str,
    inputs: list[dict],
    submit_selector: str,
    texts: list[str],
    *,
    site: str = "",
    component: str = "",
    blockers: list[dict] | None = None,
    response_selector: str = "",
    response_within_selector: str = "",
    response_text_within_selector: str = "",
    response_capture_mode: str = "last",
    response_list_selector: str = "",
    response_role_selector: str = "",
    submit_via: str = "click",
    response_wait_ms: int = 5000,
    human_behavior: bool = False,
    progress_tracker: "SubmissionProgressTracker | None" = None,
    stop_words: list[str] | None = None,
    submission: dict | None = None,
    test_case: dict | None = None,
    turn_cases: list[dict] | None = None,
    suite_path=None,
) -> list[tuple[str, str | None, dict]]:
    """Run a sequence of UI submissions on the same page. Returns list of (text, response_text, submission_meta)."""
    async with live_preview_context(page):
        await asyncio.sleep(0.1 + time.perf_counter() % 0.15)
        await page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
        # DCL is enough; waiting for "load" stalls SPAs that keep network activity.
        await asyncio.sleep(0.15)
        if human_behavior:
            await human_mouse_wander(page, count=1)
        await capture_preview_screenshot(page)

        active_inputs = inputs_for_submission(
            inputs, test_case=test_case, suite_path=suite_path
        )

        await ensure_page_ready_for_submit(
            page,
            site=site,
            component=component,
            inputs=active_inputs,
            submit_selector=submit_selector,
            start_url=start_url,
            blockers=blockers,
        )

        results: list[tuple[str, str | None, dict]] = []
        baseline = ""
        for idx, text in enumerate(texts):
            await check_login_wall_before_submit(
                page, site=site, component=component, start_url=start_url
            )
            await check_rate_limit_before_submit(
                page, site=site, component=component, blockers=blockers
            )
            prompt_text = append_test_prompt_delimiter(text)
            turn_case = (
                turn_cases[idx]
                if isinstance(turn_cases, list) and idx < len(turn_cases)
                else test_case
            )
            try:
                text_out, response_out, full_content, submission_meta = await _do_one_submit_step(
                    page,
                    active_inputs,
                    submit_selector,
                    prompt_text,
                    response_selector=response_selector,
                    response_within_selector=response_within_selector,
                    response_text_within_selector=response_text_within_selector,
                    response_capture_mode=response_capture_mode,
                    response_list_selector=response_list_selector,
                    response_role_selector=response_role_selector,
                    submit_via=submit_via,
                    response_wait_ms=response_wait_ms,
                    baseline_text=baseline,
                    test_case=turn_case,
                    suite_path=suite_path,
                    human_behavior=human_behavior,
                    submission=submission,
                    site=site,
                    component=component,
                    capture_id=str((turn_case or {}).get("id") or (test_case or {}).get("id") or f"turn-{idx + 1}"),
                )
            except SkipCurrentPromptError:
                clear_skip_request()
                log_skip_current_applied()
                results.append((text, None, apply_submission_outcome({}, OUTCOME_SKIPPED)))
                if progress_tracker is not None:
                    progress_tracker.record_completed(
                        1,
                        input_text=text,
                        response=None,
                        submission_outcome=OUTCOME_SKIPPED,
                    )
                break
            if not response_out and full_content and str(full_content).strip():
                response_out = str(full_content).strip()
            results.append((text_out, response_out, submission_meta or {}))
            baseline = full_content
            if progress_tracker is not None:
                meta = submission_meta or {}
                progress_tracker.record_completed(
                    1,
                    input_text=text_out,
                    response=response_out,
                    submission_outcome=str(meta.get("submission_outcome") or ""),
                    rejection_signals=list(meta.get("rejection_signals") or []),
                )
            if (submission_meta or {}).get("submission_outcome") == OUTCOME_CLIENT_REJECTED:
                break
            matched = response_stop_word_match(response_out, stop_words or [])
            if matched:
                return results
        return results


async def _submit_one_ui_multi_batch(
    *,
    index: int,
    batch: list[str],
    tc: dict | None,
    strategies: list,
    start_url: str,
    inputs: list[dict],
    submit_selector: str,
    page_kwargs: dict,
    storage_str: str,
    page_kw: dict,
    tracker: SubmissionProgressTracker,
    stop_words: list[str],
    suite_path,
) -> tuple[int, list[tuple[str, str | None, dict[str, Any]]] | None]:
    """Run one multi-turn batch on a dedicated page."""

    async def _run_once(fetcher, human_behavior, tier, *, b=batch, case=tc):
        async def _cb(page, batch_texts=b, hb=human_behavior, c=case):
            turn_cases = c.get("turns") if isinstance(c, dict) else None
            return await do_ui_submit_sequence_with_page(
                page,
                start_url,
                inputs,
                submit_selector,
                batch_texts,
                human_behavior=hb,
                progress_tracker=tracker,
                stop_words=stop_words,
                test_case=c,
                turn_cases=turn_cases if isinstance(turn_cases, list) else None,
                suite_path=suite_path,
                **page_kwargs,
            )

        try:
            return await run_with_evasion_retry(
                lambda f=_cb, fet=fetcher: fet.with_page(
                    f, storage_path=storage_str, **page_kw
                )
            )
        except PageBlockedError:
            raise
        except NonSuccessResponseError:
            return None
        except SkipCurrentPromptError:
            raise

    batch_results = await run_ui_submit_with_strategy_fallback(
        strategies,
        _run_once,
        is_success=lambda r: r is not None and all(resp for _, resp, *_ in r),
    )
    return index, batch_results


async def run_ui_submission_multi(
    site: str,
    component: str,
    *,
    fetcher_bundle: "UIFetcherBundle | None" = None,
    pool_fetcher=None,
    cluster_fetcher=None,
    human_fetcher=None,
    suite_path=None,
) -> tuple[list[tuple[str, str | None]], Path | None]:
    """
    Run UI submission for each batch in posts.json (array of arrays).
    Tries fetcher strategies fastest-first with fallthrough on recoverable blocks.
    """
    sub = get_submission_config(site, component)
    if not sub:
        return [], None

    multi_test_cases = get_suite_multi_test_cases(suite_path) if suite_path else []
    if multi_test_cases:
        batches_raw = [
            [str(t) for t in (tc.get("prompts") or [])]
            for tc in multi_test_cases
            if isinstance(tc, dict)
        ]
    else:
        batches_raw = get_posts_batches(suite_path=suite_path)
    if not batches_raw:
        return [], None
    batches = [[append_test_prompt_delimiter(t) for t in batch] for batch in batches_raw]

    storage_path = get_storage_state_path(site, component)
    if not storage_path:
        return [], None

    start_url = sub["start_url"]
    inputs: list[dict] = sub["inputs"]
    submit_selector = sub["submit_selector"]
    blockers = sub.get("blockers") if isinstance(sub.get("blockers"), list) else None
    response_selector = sub.get("response_selector") or ""
    response_within_selector = sub.get("response_within_selector") or ""
    response_text_within_selector = sub.get("response_text_within_selector") or ""
    capture = response_capture_kwargs(sub)
    submit_via = sub.get("submit_via", "click")
    response_wait_ms = int(sub.get("response_wait_ms", 5000) or 5000)

    if fetcher_bundle and fetcher_bundle.strategies:
        strategies = fetcher_bundle.strategies
    else:
        legacy = ui_fetchers_to_try(
            site,
            component,
            pool_fetcher=pool_fetcher,
            cluster_fetcher=cluster_fetcher,
            human_fetcher=human_fetcher,
        )
        tier_labels = iter(("pool", "cluster", "human"))
        strategies = [(f, hb, next(tier_labels, "fetcher")) for f, hb in legacy]

    if not strategies:
        return [], None

    all_results: list[tuple[str, str | None]] = []
    all_submission_metas: list[dict[str, Any]] = []
    storage_str = str(storage_path)
    page_kw = fetcher_with_page_kwargs(site, component, start_url=start_url)

    total_turns = sum(len(b) for b in batches)
    tracker = SubmissionProgressTracker("multi", total_turns)
    tracker.emit_run_start()

    page_kwargs = dict(
        site=site,
        component=component,
        blockers=blockers,
        response_selector=response_selector,
        response_within_selector=response_within_selector,
        response_text_within_selector=response_text_within_selector,
        response_capture_mode=capture["response_capture_mode"],
        response_list_selector=capture["response_list_selector"],
        response_role_selector=capture["response_role_selector"],
        submit_via=submit_via,
        response_wait_ms=response_wait_ms,
        submission=sub,
    )

    stop_words = load_run_stop_words(suite_path)
    stop_word_matched = ""
    stopped_early = False

    case_list: list[dict | None] = list(multi_test_cases[: len(batches)])
    if len(case_list) < len(batches):
        case_list.extend([None] * (len(batches) - len(case_list)))

    concurrency = resolve_ui_parallel_concurrency(
        site=site,
        component=component,
        strategies=strategies,
        work_count=len(batches),
        stop_words=stop_words,
        fetcher_bundle=fetcher_bundle,
    )

    if concurrency > 1:
        print(
            f"  [ui] running {len(batches)} batch(es) with concurrency={concurrency}",
            flush=True,
        )
        sem = asyncio.Semaphore(concurrency)

        async def _one_batch(i: int, batch: list[str], tc: dict | None):
            async with sem:
                return await _submit_one_ui_multi_batch(
                    index=i,
                    batch=batch,
                    tc=tc,
                    strategies=strategies,
                    start_url=start_url,
                    inputs=inputs,
                    submit_selector=submit_selector,
                    page_kwargs=page_kwargs,
                    storage_str=storage_str,
                    page_kw=page_kw,
                    tracker=tracker,
                    stop_words=stop_words,
                    suite_path=suite_path,
                )

        try:
            gathered = await asyncio.gather(
                *[_one_batch(i, batch, tc) for i, (batch, tc) in enumerate(zip(batches, case_list))]
            )
        except PageBlockedError:
            raise
        gathered.sort(key=lambda row: row[0])
        for _i, batch_results in gathered:
            if batch_results is not None:
                for row in batch_results:
                    if len(row) >= 3:
                        all_results.append((row[0], row[1]))
                        all_submission_metas.append(row[2] if isinstance(row[2], dict) else {})
                    else:
                        all_results.append((row[0], row[1]))
                        all_submission_metas.append({})
            else:
                batch = batches[_i]
                all_results.extend((t, None) for t in batch)
                all_submission_metas.extend({} for _ in batch)
    else:
        for i, (batch, tc) in enumerate(zip(batches, case_list)):
            clear_skip_request()
            if i > 0:
                log_evasion(
                    "sequential_burst_pause",
                    sleep_s=EVASION_REQUEST_DELAY_S,
                    detail="Pause between sequential batches to reduce burst-rate detection",
                )
                await sleep_or_skip(EVASION_REQUEST_DELAY_S)

            try:
                _i, batch_results = await _submit_one_ui_multi_batch(
                    index=i,
                    batch=batch,
                    tc=tc,
                    strategies=strategies,
                    start_url=start_url,
                    inputs=inputs,
                    submit_selector=submit_selector,
                    page_kwargs=page_kwargs,
                    storage_str=storage_str,
                    page_kw=page_kw,
                    tracker=tracker,
                    stop_words=stop_words,
                    suite_path=suite_path,
                )
            except PageBlockedError:
                raise
            except SkipCurrentPromptError:
                clear_skip_request()
                log_skip_current_applied()
                all_results.extend((t, None) for t in batch)
                all_submission_metas.extend(
                    apply_submission_outcome({}, OUTCOME_SKIPPED) for _ in batch
                )
                for skipped_text in batch:
                    tracker.record_completed(
                        1,
                        input_text=skipped_text,
                        response=None,
                        submission_outcome=OUTCOME_SKIPPED,
                    )
                continue
            if batch_results is not None:
                for row in batch_results:
                    if len(row) >= 3:
                        all_results.append((row[0], row[1]))
                        all_submission_metas.append(row[2] if isinstance(row[2], dict) else {})
                    else:
                        all_results.append((row[0], row[1]))
                        all_submission_metas.append({})
            else:
                all_results.extend((t, None) for t in batch)
                all_submission_metas.extend({} for _ in batch)

            for _, resp, *_ in (batch_results or []):
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
    log_batches = batches_raw
    if stopped_early and all_results:
        effective_batches: list[list[str]] = []
        offset = 0
        for batch in batches_raw:
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
