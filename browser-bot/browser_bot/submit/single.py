"""Single-string UI submission: one prompt per page/session."""

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from browser_bot.browser.human_behavior import human_mouse_wander
from browser_bot.config import EVASION_REQUEST_DELAY_S, get_posts_strings, get_suite_test_cases
from browser_bot.live_preview import capture_preview_screenshot, live_preview_context
from browser_bot.page_blockers import (
    PageBlockedError,
    ensure_page_ready_for_submit,
)
from browser_bot.sites import (
    browser_ui_session_ready,
    get_browser_storage_state_path,
    get_submission_config,
)

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
    normalize_ui_submit_result,
    resolve_ui_parallel_concurrency,
    response_capture_kwargs,
    response_stop_word_match,
    run_ui_submit_with_strategy_fallback,
    run_with_evasion_retry,
    ui_fetchers_to_try,
)
from browser_bot.submit.response_filters import filter_context_from_submission
from browser_bot.run_control import (
    SkipCurrentPromptError,
    clear_skip_request,
    log_skip_current_applied,
    sleep_or_skip,
)
from browser_bot.submit.rejection_detection import OUTCOME_SKIPPED, apply_submission_outcome

if TYPE_CHECKING:
    from playwright.async_api import Page

    from browser_bot.fetchers.ui_bundle import UIFetcherBundle


async def do_ui_submit_with_page(
    page: "Page",
    start_url: str,
    inputs: list[dict],
    submit_selector: str,
    text: str,
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
    test_case: dict | None = None,
    suite_path=None,
    submission: dict | None = None,
) -> tuple[str, str | None, dict[str, Any]]:
    """Run a single UI submission with the given page. Returns (text, response_text, submission_meta)."""
    async with live_preview_context(page):
        await asyncio.sleep(0.1 + time.perf_counter() % 0.15)
        await page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
        # DCL is enough; waiting for "load" stalls SPAs that keep network activity.
        await asyncio.sleep(0.15)
        if human_behavior:
            await human_mouse_wander(page, count=1)
        await capture_preview_screenshot(page)

        # Cloudflare is handled inside ensure_page_ready_for_submit (avoid a second
        # pre-composer poll before surface_prep).

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

        prompt_text = append_test_prompt_delimiter(text)
        # Same capture upgrade Configure uses (role roots, drop nested list_selector).
        eff_response_selector = response_selector
        eff_within = response_within_selector
        eff_text_within = response_text_within_selector
        eff_mode = response_capture_mode
        eff_list = response_list_selector
        eff_role = response_role_selector
        try:
            from browser_bot.record_submission import upgrade_response_capture_kwargs

            tmp_sub = dict(submission or {})
            tmp_sub["response_selector"] = response_selector
            tmp_sub["response_within_selector"] = response_within_selector
            tmp_sub["response_text_within_selector"] = response_text_within_selector
            tmp_sub["response_capture_mode"] = response_capture_mode
            tmp_sub["response_list_selector"] = response_list_selector
            tmp_sub["response_role_selector"] = response_role_selector
            upgraded = await upgrade_response_capture_kwargs(page, tmp_sub)
            eff_response_selector = upgraded.get("response_selector") or response_selector
            eff_mode = upgraded.get("response_capture_mode") or response_capture_mode or "last"
            eff_list = upgraded.get("response_list_selector") or ""
            eff_role = upgraded.get("response_role_selector") or response_role_selector
            if str(eff_mode).strip().lower() == "role":
                eff_list = ""
                if not eff_role:
                    eff_role = eff_response_selector
            if isinstance(submission, dict):
                submission["response_selector"] = eff_response_selector
                if str(eff_mode).strip().lower() == "role":
                    submission["response_capture_mode"] = "role"
                    submission["response_role_selector"] = eff_role
                    submission.pop("response_list_selector", None)
                elif eff_mode and eff_mode != "last":
                    submission["response_capture_mode"] = eff_mode
                    if eff_list:
                        submission["response_list_selector"] = eff_list
        except Exception:
            if str(eff_mode).strip().lower() == "role":
                eff_list = ""

        filter_ctx = filter_context_from_submission(
            submission, prompt_text, site=site, component=component
        )
        text_out, response_out, full_content, submission_meta = await _do_one_submit_step(
            page,
            active_inputs,
            submit_selector,
            prompt_text,
            response_selector=eff_response_selector,
            response_within_selector=eff_within,
            response_text_within_selector=eff_text_within,
            response_capture_mode=eff_mode,
            response_list_selector=eff_list,
            response_role_selector=eff_role,
            submit_via=submit_via,
            response_wait_ms=response_wait_ms,
            test_case=test_case,
            suite_path=suite_path,
            human_behavior=human_behavior,
            submission=submission,
            filter_ctx=filter_ctx,
            site=site,
            component=component,
            capture_id=str((test_case or {}).get("id") or ""),
        )
        if not response_out and full_content and str(full_content).strip():
            response_out = str(full_content).strip()

        # Bug Bounty hybrid: DNA-locked follow-ups on same page after refuse/partial.
        try:
            from browser_bot.submit.bounty_adaptive import (
                bounty_hybrid_should_attempt,
                run_bounty_hybrid_followups_ui,
            )
            from browser_bot.submit.common import load_run_stop_words

            if bounty_hybrid_should_attempt(suite_path, test_case):
                page_kwargs = dict(
                    site=site,
                    component=component,
                    blockers=blockers,
                    response_selector=response_selector,
                    response_within_selector=response_within_selector,
                    response_text_within_selector=response_text_within_selector,
                    response_capture_mode=response_capture_mode,
                    response_list_selector=response_list_selector,
                    response_role_selector=response_role_selector,
                    submit_via=submit_via,
                    response_wait_ms=response_wait_ms,
                    suite_path=suite_path,
                    submission=submission,
                )
                text_out, response_out, submission_meta = await run_bounty_hybrid_followups_ui(
                    page=page,
                    site=site,
                    component=component,
                    start_url=start_url,
                    inputs=inputs,
                    submit_selector=submit_selector,
                    seed_prompt=text,
                    first_response=response_out,
                    first_full_content=full_content,
                    first_meta=submission_meta if isinstance(submission_meta, dict) else {},
                    test_case=test_case or {},
                    page_kwargs=page_kwargs,
                    human_behavior=human_behavior,
                    stop_words=load_run_stop_words(suite_path),
                )
        except Exception as exc:
            try:
                from browser_bot.submit.common import log_resilience

                log_resilience(
                    "bounty_adaptive",
                    f"UI hybrid wrapper skipped: {exc}",
                )
            except Exception:
                pass
        return (text_out, response_out, submission_meta)


async def _submit_one_ui_single_prompt(
    *,
    text: str,
    tc: dict | None,
    strategies: list,
    start_url: str,
    inputs: list[dict],
    submit_selector: str,
    page_kwargs: dict,
    storage_str: str,
    page_kw: dict,
) -> tuple[str, str | None, dict[str, Any]]:
    """Run one flat-list prompt through fetcher strategy fallback."""

    async def _run_once(fetcher, human_behavior, tier, *, t=text, case=tc):
        async def _cb(page, prompt=t, hb=human_behavior, c=case):
            return await do_ui_submit_with_page(
                page,
                start_url,
                inputs,
                submit_selector,
                prompt,
                human_behavior=hb,
                test_case=c,
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

    result = await run_ui_submit_with_strategy_fallback(strategies, _run_once)
    return normalize_ui_submit_result(result, text)


async def run_ui_submission_single(
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
    Run UI submission for each string in posts.json (flat list).
    Tries fetcher strategies fastest-first with fallthrough on cloudflare/captcha/rate-limit blocks.
    """
    sub = get_submission_config(site, component)
    if not sub:
        return [], None

    test_cases = get_suite_test_cases(suite_path) if suite_path else []
    if test_cases:
        posts = [append_test_prompt_delimiter(tc["prompt"]) for tc in test_cases]
    else:
        posts = [append_test_prompt_delimiter(p) for p in get_posts_strings(suite_path=suite_path)]
    if not posts:
        return [], None

    if not browser_ui_session_ready(site, component):
        return [], None
    storage_path = get_browser_storage_state_path(site, component)

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

    results: list[tuple[str, str | None]] = []
    submission_metas: list[dict[str, Any]] = []
    storage_str = str(storage_path) if storage_path else None
    page_kw = fetcher_with_page_kwargs(site, component, start_url=start_url)

    stop_words = load_run_stop_words(suite_path)
    stop_word_matched = ""
    stopped_early = False

    tracker = SubmissionProgressTracker("single", len(posts))
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
        suite_path=suite_path,
        submission=sub,
    )

    case_list = test_cases if test_cases else [None] * len(posts)
    concurrency = resolve_ui_parallel_concurrency(
        site=site,
        component=component,
        strategies=strategies,
        work_count=len(posts),
        stop_words=stop_words,
        fetcher_bundle=fetcher_bundle,
    )

    if concurrency > 1:
        print(
            f"  [ui] running {len(posts)} prompt(s) with concurrency={concurrency}",
            flush=True,
        )
        sem = asyncio.Semaphore(concurrency)

        async def _one(i: int, text: str, tc: dict | None) -> tuple[int, str, str | None, dict[str, Any]]:
            async with sem:
                row = await _submit_one_ui_single_prompt(
                    text=text,
                    tc=tc,
                    strategies=strategies,
                    start_url=start_url,
                    inputs=inputs,
                    submit_selector=submit_selector,
                    page_kwargs=page_kwargs,
                    storage_str=storage_str,
                    page_kw=page_kw,
                )
                meta = row[2] if isinstance(row[2], dict) else {}
                tracker.record_completed(
                    1,
                    input_text=row[0],
                    response=row[1],
                    submission_outcome=str(meta.get("submission_outcome") or ""),
                    rejection_signals=list(meta.get("rejection_signals") or []),
                )
                return i, row[0], row[1], row[2]

        try:
            gathered = await asyncio.gather(
                *[_one(i, text, tc) for i, (text, tc) in enumerate(zip(posts, case_list))]
            )
        except PageBlockedError:
            raise
        gathered.sort(key=lambda row: row[0])
        for _i, text, response, meta in gathered:
            results.append((text, response))
            submission_metas.append(meta)
    else:
        for i, (text, tc) in enumerate(zip(posts, case_list)):
            clear_skip_request()
            if i > 0:
                log_evasion(
                    "sequential_burst_pause",
                    sleep_s=EVASION_REQUEST_DELAY_S,
                    detail="Pause between sequential prompts to reduce burst-rate detection",
                )
                await sleep_or_skip(EVASION_REQUEST_DELAY_S)

            try:
                text_out, response, meta = await _submit_one_ui_single_prompt(
                    text=text,
                    tc=tc,
                    strategies=strategies,
                    start_url=start_url,
                    inputs=inputs,
                    submit_selector=submit_selector,
                    page_kwargs=page_kwargs,
                    storage_str=storage_str,
                    page_kw=page_kw,
                )
            except PageBlockedError:
                raise
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
            results.append((text_out, response))
            submission_metas.append(meta)
            tracker.record_completed(
                1,
                input_text=text_out,
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
