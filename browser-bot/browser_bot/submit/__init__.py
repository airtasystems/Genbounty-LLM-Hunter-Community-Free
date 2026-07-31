"""UI- and API-based submission dispatch."""

import json
from pathlib import Path

from browser_bot.config import infer_ui_mode_from_suite_raw
from browser_bot.sites import get_submission_config

from browser_bot.submit.adaptive import run_adaptive_submission
from browser_bot.submit.api import run_api_submission_multi, run_api_submission_single
from browser_bot.submit.multi import run_ui_submission_multi
from browser_bot.submit.single import run_ui_submission_single


def is_adaptive_suite(suite_path: Path | str | None) -> bool:
    if not suite_path:
        return False
    path = Path(suite_path)
    if not path.is_file():
        return False
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        raw = None
    if isinstance(raw, dict) and str(raw.get("strategy") or "").replace("-", "_") == "adaptive":
        return True
    parts = path.parts
    if "tests" in parts:
        idx = parts.index("tests")
        if idx + 1 < len(parts) and parts[idx + 1].replace("-", "_") == "adaptive":
            return True
    return False


def resolve_ui_submission_use_multi(
    sub: dict,
    suite_path: Path | str | None,
    mode_override: str | None,
) -> bool:
    """Choose single vs multi: explicit override, then suite file shape, then config.yaml."""
    if mode_override is not None:
        return mode_override == "multi"
    if suite_path:
        path = Path(suite_path)
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8-sig"))
            except (json.JSONDecodeError, OSError):
                raw = None
            if raw is not None:
                inferred = infer_ui_mode_from_suite_raw(raw)
                if inferred == "multi":
                    return True
                if inferred == "single":
                    return False
    return bool(sub.get("mode") == "multi" or sub.get("batch_size", 1) > 1)


def run_ui_submission(
    site: str,
    component: str,
    *,
    fetcher_bundle=None,
    pool_fetcher=None,
    cluster_fetcher=None,
    human_fetcher=None,
    mode_override: str | None = None,
    suite_path=None,
) -> tuple[list[tuple[str, str | None]], Path | None]:
    """Run browser UI submission."""
    sub = get_submission_config(site, component)
    if not sub or sub.get("transport") != "ui":
        return [], None

    use_multi = resolve_ui_submission_use_multi(sub, suite_path, mode_override)

    if use_multi:
        return run_ui_submission_multi(
            site,
            component,
            fetcher_bundle=fetcher_bundle,
            pool_fetcher=pool_fetcher,
            cluster_fetcher=cluster_fetcher,
            human_fetcher=human_fetcher,
            suite_path=suite_path,
        )
    return run_ui_submission_single(
        site,
        component,
        fetcher_bundle=fetcher_bundle,
        pool_fetcher=pool_fetcher,
        cluster_fetcher=cluster_fetcher,
        human_fetcher=human_fetcher,
        suite_path=suite_path,
    )


async def run_api_submission(
    site: str,
    component: str,
    *,
    mode_override: str | None = None,
    suite_path=None,
) -> tuple[list[tuple[str, str | None]], Path | None]:
    """Run direct HTTP API submission."""
    sub = get_submission_config(site, component)
    if not sub or sub.get("transport") not in ("api", "api_document", "api_multipart"):
        return [], None

    use_multi = resolve_ui_submission_use_multi(sub, suite_path, mode_override)
    if use_multi:
        return await run_api_submission_multi(site, component, suite_path=suite_path)
    return await run_api_submission_single(site, component, suite_path=suite_path)


async def run_submission(
    site: str,
    component: str,
    *,
    fetcher_bundle=None,
    pool_fetcher=None,
    cluster_fetcher=None,
    human_fetcher=None,
    mode_override: str | None = None,
    suite_path=None,
) -> tuple[list[tuple[str, str | None]], Path | None]:
    """Dispatch to UI or API submission based on component config."""
    from browser_bot.run_control import arm_run_control, disarm_run_control

    if is_adaptive_suite(suite_path):
        try:
            import sys as _sys
            from pathlib import Path as _Path

            _root = _Path(__file__).resolve().parents[3]
            if str(_root) not in _sys.path:
                _sys.path.insert(0, str(_root))
            from pipeline.edition import is_premium_strategy, premium_error_message

            if is_premium_strategy("adaptive"):
                raise RuntimeError(premium_error_message("adaptive"))
        except ImportError as exc:
            raise RuntimeError(
                "Adaptive strategy is available in Genbounty LLM Hunter Premium. "
                "See https://genbounty.com/llm-hunter"
            ) from exc

    sub = get_submission_config(site, component)
    if not sub:
        return [], None

    await arm_run_control()
    try:
        return await _run_submission_inner(
            site,
            component,
            fetcher_bundle=fetcher_bundle,
            pool_fetcher=pool_fetcher,
            cluster_fetcher=cluster_fetcher,
            human_fetcher=human_fetcher,
            mode_override=mode_override,
            suite_path=suite_path,
        )
    finally:
        disarm_run_control()


async def _run_submission_inner(
    site: str,
    component: str,
    *,
    fetcher_bundle=None,
    pool_fetcher=None,
    cluster_fetcher=None,
    human_fetcher=None,
    mode_override: str | None = None,
    suite_path=None,
) -> tuple[list[tuple[str, str | None]], Path | None]:
    sub = get_submission_config(site, component)
    if not sub:
        return [], None

    transport = str(sub.get("transport") or "ui").strip().lower()
    is_api = transport in ("api", "api_document", "api_multipart")

    def _api_lacks_conversation_history() -> bool:
        if not is_api:
            return False
        if "multi_turn" in sub and not bool(sub.get("multi_turn")):
            return True
        if "single_turn" in sub and bool(sub.get("single_turn")):
            return True
        from browser_bot.submit.api_helpers import uses_messages_context

        return not uses_messages_context(sub)

    if is_adaptive_suite(suite_path):
        # Premium adaptive gate is enforced in run_submission() before this inner path.
        if _api_lacks_conversation_history():
            print(
                "[!] Adaptive suite requires conversation history, but this API "
                "target is stateless (no {{messages}} / multi_turn). "
                "Use zero_shot, few_shot, or Enhance instead.",
                flush=True,
            )
            return [], None
        batches, log_path = await run_adaptive_submission(
            site,
            component,
            fetcher_bundle=fetcher_bundle,
            pool_fetcher=pool_fetcher,
            cluster_fetcher=cluster_fetcher,
            human_fetcher=human_fetcher,
            suite_path=suite_path,
        )
        return [], log_path

    if is_api:
        use_multi = resolve_ui_submission_use_multi(sub, suite_path, mode_override)
        if use_multi and _api_lacks_conversation_history():
            print(
                "[!] Multi-turn suite requires conversation history, but this API "
                "target is stateless (no {{messages}} / multi_turn). "
                "Use zero_shot or few_shot instead.",
                flush=True,
            )
            return [], None
        return await run_api_submission(
            site,
            component,
            mode_override=mode_override,
            suite_path=suite_path,
        )
    return await run_ui_submission(
        site,
        component,
        fetcher_bundle=fetcher_bundle,
        pool_fetcher=pool_fetcher,
        cluster_fetcher=cluster_fetcher,
        human_fetcher=human_fetcher,
        mode_override=mode_override,
        suite_path=suite_path,
    )
