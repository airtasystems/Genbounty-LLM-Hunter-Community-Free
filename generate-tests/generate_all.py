#!/usr/bin/env python3
"""
Generate security attack prompts for all (strategy, playbook) pairs if the
output file does not exist. Uses generator.py under the hood.

Example:
  python generate-tests/generate_all.py
  python generate-tests/generate_all.py --force   # regenerate all

Strategies are discovered from generate-tests/strategies/ (registry).
Playbooks are discovered from playbooks/*.json (filename stem).
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

# Run from generate-tests so generator and strategies resolve
_gen_dir = Path(__file__).resolve().parent
if str(_gen_dir) not in sys.path:
    sys.path.insert(0, str(_gen_dir))

project_root = _gen_dir.parent
playbooks_dir = project_root / "playbooks"
generator_py = _gen_dir / "generator.py"


def get_playbooks() -> list[str]:
    """Return playbook stems (underscore form) from playbooks/*.json."""
    if not playbooks_dir.exists():
        return []
    names = []
    for p in sorted(playbooks_dir.glob("*.json")):
        if p.stem in ("company", "component") or p.stem.startswith("_"):
            continue  # context rubrics / reference templates, not attack playbooks
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig"))
            if data.get("deprecated"):
                continue
        except (json.JSONDecodeError, OSError):
            pass
        names.append(p.stem.replace("-", "_"))
    return names


def get_strategies() -> list[str]:
    """Return strategy names from the strategies registry."""
    from strategies import STRATEGIES
    return sorted(STRATEGIES.keys())


def output_path_for(strategy_name: str, playbook: str) -> Path | None:
    """Return the output file path for (strategy, playbook), or None if strategy unknown."""
    from strategies import get_strategy
    try:
        strategy = get_strategy(strategy_name)
    except ValueError:
        return None
    out_subdir = strategy.output_subdir
    filename = f"{playbook.replace('_', '-')}.json"
    return _gen_dir / out_subdir / filename


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate attack prompts for all strategy×playbook pairs if output missing."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even if output file already exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print what would be run.",
    )
    args = parser.parse_args()

    strategies = get_strategies()
    playbooks = get_playbooks()

    if not strategies:
        print("No strategies found.", file=sys.stderr)
        sys.exit(1)
    if not playbooks:
        print(f"No playbooks found in {playbooks_dir}.", file=sys.stderr)
        sys.exit(1)

    print(f"[*] Strategies: {len(strategies)} - {strategies}")
    print(f"[*] Playbooks: {len(playbooks)} - {playbooks}")
    print()

    to_run: list[tuple[str, str]] = []
    for strategy in strategies:
        for playbook in playbooks:
            out = output_path_for(strategy, playbook)
            if out is None:
                continue
            if args.force or not out.exists():
                to_run.append((strategy, playbook))

    if not to_run:
        print("[*] All output files exist. Use --force to regenerate.")
        return

    print(f"[*] Will generate {len(to_run)} file(s).")
    for strategy, playbook in to_run:
        cmd = [sys.executable, str(generator_py), "--strategy", strategy, "--playbook", playbook]
        if args.dry_run:
            print(f"  [dry-run] {' '.join(cmd)}")
            continue
        print(f"  → {strategy} / {playbook}")
        result = subprocess.run(cmd, cwd=str(project_root))
        if result.returncode != 0:
            print(f"  [!] Failed: {' '.join(cmd)}", file=sys.stderr)
            sys.exit(result.returncode)
    print("[+] Done.")


if __name__ == "__main__":
    main()
