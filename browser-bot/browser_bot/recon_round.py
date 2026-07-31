"""Execute assessment-driven recon probes against the target UI and return responses."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from browser_bot.page_blockers import ensure_page_ready_for_submit
from browser_bot.submit.common import (
    _do_one_submit_step,
    inputs_for_submission,
    response_capture_kwargs,
)
from browser_bot.submit.api_helpers import do_api_request


def _submission_ready_for_ui_probe(submission: dict | None) -> bool:
    if not submission or (submission.get("transport") or "ui").lower() != "ui":
        return False
    if not submission.get("start_url") or not submission.get("submit_selector"):
        return False
    inputs = submission.get("inputs") or []
    if submission.get("input_selector"):
        return True
    return bool(inputs)


async def _send_ui_probe(
    page,
    site: str,
    component: str,
    submission: dict,
    prompt: str,
    *,
    human_behavior: bool = True,
) -> dict[str, Any]:
    """Send one recon probe through configured UI selectors."""
    result: dict[str, Any] = {
        "prompt": prompt,
        "response_text": None,
        "full_content": None,
        "error": None,
        "skipped": False,
    }
    if not _submission_ready_for_ui_probe(submission):
        result["skipped"] = True
        result["error"] = "submission config incomplete for UI probe"
        return result

    inputs = inputs_for_submission(submission.get("inputs") or [])
    if not inputs:
        result["skipped"] = True
        result["error"] = "no text inputs for recon probe"
        return result

    try:
        if human_behavior:
            from browser_bot.browser.human_behavior import human_mouse_wander, human_scroll
            from browser_bot.config import HUMAN_READ_DELAY_MS

            await asyncio.sleep(HUMAN_READ_DELAY_MS / 1000.0)
            await human_mouse_wander(page, count=2)
            await ensure_page_ready_for_submit(
                page,
                site=site,
                component=component,
                inputs=inputs,
                submit_selector=submission["submit_selector"],
                start_url=submission.get("start_url") or "",
                blockers=submission.get("blockers"),
            )
            await human_mouse_wander(page, count=1)
            await human_scroll(page)

        _prompt, response_text, full_content, *_ = await _do_one_submit_step(
            page,
            inputs,
            submission["submit_selector"],
            prompt,
            response_selector=submission.get("response_selector") or "",
            response_within_selector=submission.get("response_within_selector") or "",
            response_text_within_selector=submission.get("response_text_within_selector") or "",
            **response_capture_kwargs(submission),
            submit_via=submission.get("submit_via") or "click",
            response_wait_ms=min(int(submission.get("response_wait_ms") or 30000), 90000),
            human_behavior=human_behavior,
            submission=submission,
        )
        result["response_text"] = (response_text or "")[:8000] or None
        result["full_content"] = (full_content or "")[:8000] or None
        if not result["response_text"] and not result["full_content"]:
            result["error"] = "empty response from recon probe"
    except Exception as exc:
        result["error"] = str(exc)
    return result


async def _execute_ui_probes(
    site: str,
    component: str,
    probes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    import importlib.util
    import sys
    import time
    from pathlib import Path

    from browser_bot.sites import (
        browser_ui_session_ready,
        get_browser_storage_state_path,
        get_submission_config,
    )

    sub = get_submission_config(site, component)
    if not sub:
        raise RuntimeError(f"No submission config for {site}/{component}")

    if not browser_ui_session_ready(site, component):
        raise RuntimeError(
            f"No browser login/session for {site}/{component}. "
            "Run Add Login first (sibling API keys are not a UI session)."
        )
    storage_path = get_browser_storage_state_path(site, component)
    start_url = str(sub.get("start_url") or "").strip()

    bb_dir = Path(__file__).resolve().parent.parent
    bb_main_path = bb_dir / "main.py"
    spec = importlib.util.spec_from_file_location("browser_bot_main", bb_main_path)
    if not spec or not spec.loader:
        raise RuntimeError("Could not load browser-bot main.py")
    bb_main = importlib.util.module_from_spec(spec)
    sys.modules["browser_bot_main"] = bb_main
    spec.loader.exec_module(bb_main)

    from browser_bot.page_blockers import submission_needs_headed_human
    from pipeline.component_settings import playwright_headless_kwarg

    human_only = submission_needs_headed_human(site, component)
    headless_override = playwright_headless_kwarg(site, component)
    results: list[dict[str, Any]] = []
    total = len(probes)

    async def _run(page):
        inputs = inputs_for_submission(sub.get("inputs") or [])
        await page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(0.15)
        await ensure_page_ready_for_submit(
            page,
            site=site,
            component=component,
            inputs=inputs,
            submit_selector=sub["submit_selector"],
            start_url=start_url,
            blockers=sub.get("blockers"),
        )

        for i, probe in enumerate(probes, start=1):
            if not isinstance(probe, dict):
                continue
            probe_id = str(probe.get("id") or f"recon-probe-{i}")
            topic = str(probe.get("topic") or "intelligence")
            prompt = str(probe.get("prompt") or "").strip()
            print(
                f"[recon_round] Probe {i}/{total}: {probe_id} ({topic})",
                flush=True,
            )
            print(
                "[genbounty_progress] "
                + json.dumps(
                    {
                        "type": "progress",
                        "phase": "recon",
                        "current": i,
                        "total": total,
                        "mode": "recon_round",
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if not prompt:
                results.append(
                    {
                        "id": probe_id,
                        "topic": topic,
                        "prompt": "",
                        "response_text": None,
                        "error": "empty probe prompt",
                    }
                )
                continue

            started = time.perf_counter()
            sent = await _send_ui_probe(
                page,
                site,
                component,
                sub,
                prompt,
                human_behavior=True,
            )
            elapsed = time.perf_counter() - started
            row = {
                "id": probe_id,
                "topic": topic,
                "prompt": prompt,
                "response_text": sent.get("response_text"),
                "full_content": sent.get("full_content"),
                "error": sent.get("error"),
                "elapsed_sec": round(elapsed, 2),
            }
            results.append(row)
            excerpt = (row.get("response_text") or row.get("error") or "")[:200]
            print(f"[recon_round]   -> {excerpt}", flush=True)
            await asyncio.sleep(1.0)
        return results

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        out = await bb_main.run_with_page_from_fetchers(
            p,
            site,
            _run,
            storage_path=str(storage_path) if storage_path else None,
            interactive=False,
            human_only=human_only,
            headless=headless_override,
            component=component,
            start_url=start_url or None,
        )
    return out or results


def _execute_api_probes(
    site: str,
    component: str,
    probes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    import time

    from browser_bot.sites import get_submission_config

    sub = get_submission_config(site, component)
    if not sub:
        raise RuntimeError(f"No submission config for {site}/{component}")

    results: list[dict[str, Any]] = []
    total = len(probes)
    for i, probe in enumerate(probes, start=1):
        if not isinstance(probe, dict):
            continue
        probe_id = str(probe.get("id") or f"recon-probe-{i}")
        topic = str(probe.get("topic") or "intelligence")
        prompt = str(probe.get("prompt") or "").strip()
        print(f"[recon_round] Probe {i}/{total}: {probe_id} ({topic})", flush=True)
        if not prompt:
            results.append(
                {
                    "id": probe_id,
                    "topic": topic,
                    "prompt": "",
                    "response_text": None,
                    "error": "empty probe prompt",
                }
            )
            continue
        started = time.perf_counter()
        status, response_text, err, *_ = do_api_request(sub, prompt, site=site, component=component)
        elapsed = time.perf_counter() - started
        results.append(
            {
                "id": probe_id,
                "topic": topic,
                "prompt": prompt,
                "response_text": (response_text or "")[:8000] or None,
                "error": err if not response_text else None,
                "http_status": status,
                "elapsed_sec": round(elapsed, 2),
            }
        )
    return results


def run_recon_round(
    site: str,
    component: str,
    probes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Execute recon probes and return structured results."""
    from browser_bot.sites import get_submission_config

    sub = get_submission_config(site, component)
    if not sub:
        raise RuntimeError(f"No submission config for {site}/{component}")

    if (sub.get("transport") or "ui").lower() == "api":
        return _execute_api_probes(site, component, probes)
    return asyncio.run(_execute_ui_probes(site, component, probes))
