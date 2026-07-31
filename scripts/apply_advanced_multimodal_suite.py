#!/usr/bin/env python3
"""Build artifact-backed test suite from a security playbook + deterministic templates."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from payloads.normalize import finalize_artifact_category  # noqa: E402
from playbooks.registry import get_categories  # noqa: E402


def _category_meta(playbook: dict, cat: dict) -> dict:
    return {
        "id": cat.get("id", ""),
        "name": cat.get("name", ""),
        "focus": cat.get("focus", ""),
        "prompts": [],
    }


def build_suite(playbook_path: Path) -> dict:
    playbook = json.loads(playbook_path.read_text(encoding="utf-8-sig"))
    playbook_id = playbook.get("playbook_id") or playbook_path.stem
    categories_out = []
    from payloads.advanced_multimodal_templates import ADVANCED_ATTACK_TEMPLATES_BY_CATEGORY

    for cat in get_categories(playbook):
        cid = cat.get("id", "")
        name = cat.get("name", "")
        vectors = cat.get("category_vectors") or []
        is_nc = cid in ("NC01", "MM06", "LLM01-NC")
        has_templates = cid in ADVANCED_ATTACK_TEMPLATES_BY_CATEGORY
        if not vectors and not has_templates and not is_nc:
            continue
        prompts = finalize_artifact_category(cid, name, [])
        if not prompts:
            continue
        row = _category_meta(playbook, cat)
        row["prompts"] = prompts
        categories_out.append(row)
    return {
        "playbook": playbook.get("playbook", ""),
        "playbook_id": playbook_id,
        "description": (
            f"Artifact-backed tests for {playbook_id} "
            "(file-upload vectors mapped to playbook categories)."
        ),
        "categories": categories_out,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build artifact test suite from playbook JSON.")
    parser.add_argument(
        "--playbook",
        default="data_system_prompt_leak",
        help="Play stem under playbooks/ (default: data_system_prompt_leak).",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output suite path (default: generate-tests/multimodal/<playbook>.json).",
    )
    parser.add_argument("--materialize", action="store_true", help="Run payload materialize after write.")
    args = parser.parse_args()

    stem = args.playbook.strip().replace("-", "_")
    playbook_path = _ROOT / "playbooks" / f"{stem}.json"
    if not playbook_path.is_file():
        raise SystemExit(f"Playbook not found: {playbook_path}")

    out = Path(args.output) if args.output else _ROOT / "generate-tests" / "multimodal" / f"{stem.replace('_', '-')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    suite = build_suite(playbook_path)
    out.write_text(json.dumps(suite, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    n_prompts = sum(len(c["prompts"]) for c in suite["categories"])
    print(f"Wrote {out} ({n_prompts} prompts, playbook_id={suite['playbook_id']})")

    if args.materialize:
        from payloads.materialize import materialize_suite

        _, n, t = materialize_suite(out)
        print(f"Materialized {n}/{t} under {out.parent / 'artifacts'}")


if __name__ == "__main__":
    main()
