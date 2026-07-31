#!/usr/bin/env python3
"""
Genbounty LLM Hunter - scripting CLI for automation and CI.

Use the web UI for the full pipeline (discovery, login, playbooks, runs):
  python start.py

Subcommands:
  generate          Generate adversarial test prompts from playbooks.
  run               Run a generated test suite against a browser target.
  security-assess   Run risk assessment on an attack log → pipeline_report.json.
  export            Export a pipeline report to Genbounty.
"""
import sys
sys.dont_write_bytecode = True

import argparse
import asyncio
import importlib.util
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

_root = Path(__file__).resolve().parent

STRATEGIES = [
    "zero_shot", "adaptive", "multi_shot", "few_shot", "iterative", "chain_of_thought",
    "prompt_chaining", "tree_of_thoughts", "self_consistency", "self_reflection",
    "directional_stimulus", "jailbreak", "multimodal",
]


def _cli_strategies() -> list[str]:
    """Strategies selectable in Community CLI (Premium slugs filtered)."""
    try:
        from pipeline.edition import filter_community_strategies

        return filter_community_strategies(STRATEGIES)
    except ImportError:
        # Fail closed without edition helpers.
        return [s for s in STRATEGIES if str(s).lower().replace("-", "_") != "adaptive"]

try:
    from dotenv import load_dotenv
    load_dotenv(_root / ".config")
    load_dotenv(_root / ".env")
except ImportError:
    pass


def _setup_paths() -> None:
    """Make risk_level_agent importable from risk-level-agent/risk_level_agent.py."""
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    rla_file = _root / "risk-level-agent" / "risk_level_agent.py"
    if rla_file.exists() and "risk_level_agent" not in sys.modules:
        spec = importlib.util.spec_from_file_location("risk_level_agent", rla_file)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            sys.modules["risk_level_agent"] = mod
            spec.loader.exec_module(mod)


_browser_bot_dir = _root / "browser-bot"


def _get_playbooks() -> list[str]:
    playbooks_dir = _root / "playbooks"
    if not playbooks_dir.is_dir():
        return []
    out: list[str] = []
    for p in playbooks_dir.glob("*.json"):
        if p.stem.startswith("_") or p.stem in ("company", "component"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig"))
            if data.get("deprecated"):
                continue
        except (json.JSONDecodeError, OSError):
            pass
        out.append(p.stem.replace("-", "_"))
    return sorted(out)


def _setup_browser_bot() -> None:
    """Add browser-bot to sys.path so its modules are importable."""
    bb = str(_browser_bot_dir)
    if bb not in sys.path:
        sys.path.insert(0, bb)


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------

def _run_generate(args) -> None:
    generator_py = _root / "generate-tests" / "generator.py"
    if not generator_py.exists():
        print(f"[-] Generator not found: {generator_py}")
        sys.exit(1)

    try:
        from pipeline.edition import exit_premium, is_premium_strategy

        if is_premium_strategy(getattr(args, "strategy", "")):
            exit_premium("adaptive")
    except ImportError:
        strat = str(getattr(args, "strategy", "") or "").strip().lower().replace("-", "_")
        if strat == "adaptive":
            print(
                "Adaptive strategy is available in Genbounty LLM Hunter Premium. "
                "See https://genbounty.com/llm-hunter",
                file=sys.stderr,
            )
            sys.exit(2)

    playbooks = _get_playbooks()
    if not playbooks:
        print("[-] No playbooks found in playbooks/. Add playbooks/*.json to enable generation.")
        sys.exit(1)

    strategies = _cli_strategies()

    env = os.environ.copy()
    site_args: list[str] = []
    site = getattr(args, "site", "") or ""
    component = getattr(args, "component", "") or ""
    if site and component:
        site_args = ["--site", site, "--component", component]
        env["GENBOUNTY_SITE"] = site
        env["GENBOUNTY_COMPONENT"] = component
        # In-process generation reads these from the current environment.
        os.environ["GENBOUNTY_SITE"] = site
        os.environ["GENBOUNTY_COMPONENT"] = component

    playbooks_dir = _root / "playbooks"
    gen_dir = _root / "generate-tests"

    # Import the generation stack once so warm LLM clients / caches are reused
    # across every (strategy x playbook) pair instead of paying a fresh
    # interpreter + import cost per combination.
    _gen_ctx: dict = {}

    def _load_gen() -> dict:
        if _gen_ctx:
            return _gen_ctx
        for p in (str(gen_dir), str(_root)):
            if p not in sys.path:
                sys.path.insert(0, p)
        import core as _core  # generate-tests/core.py
        from strategies import get_strategy as _get_strategy

        _gen_ctx["core"] = _core
        _gen_ctx["get_strategy"] = _get_strategy
        return _gen_ctx

    def _gen_in_process(strategy: str, playbook: str) -> None:
        ctx = _load_gen()
        strategy_obj = ctx["get_strategy"](strategy)
        rubric_path = str(playbooks_dir / f"{playbook}.json")
        if not Path(rubric_path).exists():
            raise FileNotFoundError(f"Playbook not found: {rubric_path}")
        filename = f"{playbook.replace('_', '-')}.json"
        if site and component:
            output_path = str(
                _root / "browser-bot" / "sites" / site / component / "tests"
                / strategy_obj.output_subdir / Path(filename).name
            )
        else:
            output_path = filename
        ctx["core"].generate_attack_suite(rubric_path, output_path, strategy_obj)

    def _gen_subprocess(strategy: str, playbook: str) -> int:
        cmd = [
            sys.executable, str(generator_py),
            "--strategy", strategy, "--playbook", playbook,
        ] + site_args
        return subprocess.run(cmd, cwd=str(_root), env=env).returncode

    def gen_one(strategy: str, playbook: str) -> None:
        print(f"[*] Generating: strategy={strategy}, playbook={playbook}...")
        if site and component:
            out = f"browser-bot/sites/{site}/{component}/tests/{strategy.replace('_', '-')}/{playbook.replace('_', '-')}.json"
        else:
            out = f"generate-tests/{strategy.replace('_', '-')}/{playbook.replace('_', '-')}.json"
        try:
            _gen_in_process(strategy, playbook)
            print(f"[+] Done: {out}")
            return
        except Exception as exc:
            print(f"[!] In-process generation failed ({exc}); retrying via subprocess...")
        rc = _gen_subprocess(strategy, playbook)
        if rc == 0:
            print(f"[+] Done: {out}")
        else:
            print(f"[!] Generator exited {rc} for {strategy}/{playbook}.")

    if args.all:
        total = len(strategies) * len(playbooks)
        n = 0
        for strat in strategies:
            for fw in playbooks:
                n += 1
                print(f"\n[{n}/{total}]")
                gen_one(strat, fw)
    elif args.all_playbooks:
        for i, fw in enumerate(playbooks, 1):
            print(f"\n[{i}/{len(playbooks)}]")
            gen_one(args.strategy, fw)
    elif args.all_strategies:
        for i, strat in enumerate(strategies, 1):
            print(f"\n[{i}/{len(strategies)}]")
            gen_one(strat, args.playbook)
    else:
        gen_one(args.strategy, args.playbook)


# ---------------------------------------------------------------------------
# security-assess
# ---------------------------------------------------------------------------

def _run_security_assess(args) -> None:
    _setup_paths()

    attack_log_path = Path(args.attack_log)
    if not attack_log_path.is_absolute():
        attack_log_path = Path.cwd() / attack_log_path
    if not attack_log_path.exists():
        print(f"[-] Attack log not found: {attack_log_path}")
        sys.exit(1)

    from pipeline.security_assess import run_security_assessment

    print(f"[*] Running security assessment on: {attack_log_path.name}")
    risk_results = run_security_assessment(attack_log_path)

    log_data = json.loads(attack_log_path.read_text(encoding="utf-8"))
    all_log_results = log_data.get("results", [])

    compliance_by_id: dict[str, dict] = {r["id"]: r for r in all_log_results if "id" in r}
    for r in risk_results:
        entry_id = r.get("id", "")
        cl = compliance_by_id.get(entry_id, {})
        for field in (
            "description",
            "expected_behavior",
            "status",
            "ok",
            "error",
            "strategy",
            "prior_turns",
            "turns",
            "capture_id",
        ):
            if field not in r:
                r[field] = cl.get(field)

    from pipeline.response_html import enrich_adversarial_results_with_response_html

    enrich_adversarial_results_with_response_html(risk_results)

    from pipeline.report import build_pipeline_report, category_rollup_from_results

    log_dir = attack_log_path.parent
    run_timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    category_rollup = category_rollup_from_results(risk_results)
    report = build_pipeline_report(
        log_data,
        risk_results,
        log_dir,
        attack_log_path,
        category_rollup=category_rollup,
        timestamp=run_timestamp,
    )
    report_path = log_dir / "pipeline_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[+] Pipeline report: {report_path}")

    print("\n=== Summary ===")
    print(f"  Assessed: {len(risk_results)}")
    if category_rollup:
        for m, level in sorted(category_rollup.items()):
            print(f"  {m[:60]}: {level}")

    if args.report_dir:
        copy_dir = Path(args.report_dir)
        if not copy_dir.is_absolute():
            copy_dir = Path.cwd() / copy_dir
        copy_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(report_path, copy_dir / f"pipeline_report_{run_timestamp}.json")
        print(f"[+] Report copied to: {copy_dir}")


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

def _run_tests(args) -> None:
    suite_path = Path(args.suite)
    if not suite_path.is_absolute():
        suite_path = Path.cwd() / suite_path
    if not suite_path.exists():
        print(f"[-] Suite not found: {suite_path}")
        sys.exit(1)

    _setup_browser_bot()
    from browser_bot.config import infer_ui_mode_from_suite_raw
    from browser_bot.submit import is_adaptive_suite

    try:
        from pipeline.edition import exit_premium, is_premium_strategy

        if is_adaptive_suite(suite_path) and is_premium_strategy("adaptive"):
            exit_premium("adaptive")
    except ImportError:
        if is_adaptive_suite(suite_path) or "adaptive" in suite_path.parts:
            print(
                "Adaptive strategy is available in Genbounty LLM Hunter Premium. "
                "See https://genbounty.com/llm-hunter",
                file=sys.stderr,
            )
            sys.exit(2)

    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    mode = infer_ui_mode_from_suite_raw(suite) or "single"

    site = (args.site or "").strip()
    component = (args.component or "").strip()
    if not site or not component:
        print("[-] --site and --component are required.")
        print("    Use the web UI for interactive workflows: python start.py")
        sys.exit(1)

    print(f"[*] Running tests: {site}/{component} ({suite_path.name}, mode={mode})...")
    os.environ["GENBOUNTY_SITE"] = site
    os.environ["GENBOUNTY_COMPONENT"] = component
    from browser_bot.config import apply_component_settings

    apply_component_settings(site, component)
    bb_main_path = _browser_bot_dir / "main.py"
    bb_spec = importlib.util.spec_from_file_location("browser_bot_main", bb_main_path)
    bb_main = importlib.util.module_from_spec(bb_spec)
    bb_spec.loader.exec_module(bb_main)
    ran = asyncio.run(bb_main.run_posts(site=site, component=component, mode=mode, suite_path=suite_path))
    if not ran:
        print("[!] Test run did not execute any prompts.")
        sys.exit(1)

    from browser_bot.submit.common import RUN_LOG_DIR_ENV, resolve_run_log_path

    run_log = resolve_run_log_path(site, component)
    if not run_log:
        prepared = os.environ.get(RUN_LOG_DIR_ENV, "").strip()
        if prepared:
            print(
                "[!] No run log written for this run. "
                f"Expected run_log.json under {prepared}."
            )
        else:
            print("[!] No run log found after test run.")
        sys.exit(1)

    print(f"[+] Run log: {run_log}")

    from pipeline.convert_log import convert_run_log
    attack_log = convert_run_log(run_log, suite_path)
    print(f"[+] Attack log: {attack_log}")

    if args.assess:
        print("\n[*] Running security assessment...")
        _setup_paths()
        from pipeline.security_assess import run_security_assessment

        risk_results = run_security_assessment(attack_log)
        log_data = json.loads(attack_log.read_text(encoding="utf-8"))
        compliance_by_id: dict[str, dict] = {
            r["id"]: r for r in log_data.get("results", []) if "id" in r
        }
        for r in risk_results:
            cl = compliance_by_id.get(r.get("id", ""), {})
            for field in (
                "description",
                "expected_behavior",
                "status",
                "ok",
                "error",
                "strategy",
                "prior_turns",
                "turns",
                "capture_id",
            ):
                if field not in r:
                    r[field] = cl.get(field)

        from pipeline.response_html import enrich_adversarial_results_with_response_html

        enrich_adversarial_results_with_response_html(risk_results)

        from pipeline.report import build_pipeline_report, category_rollup_from_results

        category_rollup = category_rollup_from_results(risk_results)
        report = build_pipeline_report(
            log_data,
            risk_results,
            run_log.parent,
            attack_log,
            category_rollup=category_rollup,
        )
        report_path = attack_log.parent / "pipeline_report.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"[+] Pipeline report: {report_path}")

        print("\n=== Summary ===")
        print(f"  Assessed: {len(risk_results)}")
        for m, level in sorted(category_rollup.items()):
            print(f"  {m[:60]}: {level}")


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

def _run_export(args) -> None:
    report_path = Path(args.report)
    if not report_path.is_absolute():
        report_path = Path.cwd() / report_path
    if not report_path.exists():
        print(f"[-] Pipeline report not found: {report_path}")
        sys.exit(1)

    from pipeline.pipeline_settings import GENBOUNTY_EXPORT_HOST, export_host

    host = (args.host or "").strip() or export_host() or GENBOUNTY_EXPORT_HOST
    api_key = os.getenv("GENBOUNTY_API_KEY", "").strip() or args.api_key
    user_id = (
        (args.user_id or "").strip()
        or os.getenv("GENBOUNTY_USER_ID", "").strip()
    )

    if not api_key:
        api_key = input("  API key (write:security_assessment_import scope): ").strip()
    if not user_id:
        user_id = input("  User ID (or set GENBOUNTY_USER_ID): ").strip()
    if not api_key or not user_id:
        print("[-] API key and User ID are required.")
        sys.exit(1)

    from pipeline.export_genbounty import export_pipeline_report
    export_pipeline_report(
        report_path,
        host=host,
        api_key=api_key,
        user_id=user_id,
        default_level=args.default_level,
        risk_levels=getattr(args, "risk_levels", None),
        batch_size=args.batch_size,
        batch_delay_seconds=args.batch_delay,
    )



# ---------------------------------------------------------------------------
# CLI (argparse for direct subcommand use)
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genbounty LLM Hunter - scripting CLI for automation and CI.\n"
                    "Use python start.py for the full web UI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="For discovery, login, playbooks, and interactive runs, use: python start.py",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND", help="Subcommand to run")

    def norm(s: str) -> str:
        return s.strip().replace("-", "_")

    # --- generate ---
    gen_p = sub.add_parser("generate", help="Generate adversarial test prompts from playbooks.")
    gen_p.add_argument("--strategy", type=norm, choices=_cli_strategies(), default="zero_shot",
                       help="Prompt strategy (default: zero_shot).")
    gen_p.add_argument("--playbook", type=norm, default="",
                       help="Play stem (see playbooks/*.json).")
    gen_p.add_argument("--site", default="", help="Target site (writes suite under browser-bot/sites/<site>/...).")
    gen_p.add_argument("--component", default="", help="Target component (with --site).")
    gen_p.add_argument("--all", action="store_true",
                       help="Generate all strategies x all playbooks.")
    gen_p.add_argument("--all-playbooks", action="store_true",
                       help="Generate all playbooks for the given strategy.")
    gen_p.add_argument("--all-strategies", action="store_true",
                       help="Generate all strategies for the given playbook.")

    # --- run ---
    run_p = sub.add_parser("run", help="Run a generated test suite against a browser target.")
    run_p.add_argument(
        "suite",
        help="Path to attack suite JSON (e.g. browser-bot/sites/<site>/<component>/tests/zero-shot/data-system-prompt-leak.json).",
    )
    run_p.add_argument("--site", required=True, help="Target site (domain).")
    run_p.add_argument("--component", required=True, help="Target component.")
    run_p.add_argument("--assess", action="store_true",
                       help="Immediately run risk assessment after the test run.")

    # --- security-assess ---
    risk_p = sub.add_parser("security-assess", help="Run risk assessment on a attack log.")
    risk_p.add_argument("attack_log", help="Path to attack_log.json.")
    risk_p.add_argument("--report-dir", metavar="DIR",
                        help="Also copy pipeline_report.json to this directory.")

    # --- export ---
    exp_p = sub.add_parser("export", help="Export pipeline report as security assessment to Genbounty.")
    exp_p.add_argument("report", help="Path to pipeline_report.json.")
    exp_p.add_argument(
        "--host",
        default="",
        help="Override Genbounty host (default: https://genbounty.com).",
    )
    exp_p.add_argument("--api-key", default="", help="Genbounty API key (or set GENBOUNTY_API_KEY).")
    exp_p.add_argument(
        "--user-id",
        default="",
        help="User ID / MongoDB ObjectId (or set GENBOUNTY_USER_ID).",
    )
    exp_p.add_argument(
        "--default-severity",
        "--default-level",
        dest="default_level",
        choices=["indeterminate", "informational", "low", "medium", "high", "critical"],
        help="Fallback severity when a result row lacks risk_level.",
    )
    exp_p.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Results per POST (default: Settings export.batch_size or 25).",
    )
    exp_p.add_argument(
        "--batch-delay",
        type=float,
        default=None,
        help="Seconds between batches (default: Settings export.delay_seconds or 2).",
    )
    exp_p.add_argument(
        "--risk-levels",
        metavar="LEVELS",
        default=None,
        help="Comma-separated severities to export (e.g. critical,high,medium). Default: all.",
    )

    args = parser.parse_args()

    if args.command == "generate":
        _run_generate(args)
    elif args.command == "run":
        _run_tests(args)
    elif args.command == "security-assess":
        _run_security_assess(args)
    elif args.command == "export":
        _run_export(args)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
