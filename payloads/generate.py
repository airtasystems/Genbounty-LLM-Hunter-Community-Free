#!/usr/bin/env python3
"""CLI: python -m payloads.generate --type pdf_hidden --out payloads/generate/run1"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from payloads.generators import GENERATORS, generate_payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate multimodal attack payloads")
    parser.add_argument(
        "--type",
        "-t",
        required=True,
        choices=sorted(GENERATORS.keys()),
        help="Generator type",
    )
    parser.add_argument("--out", "-o", type=Path, help="Output directory")
    parser.add_argument("--args", type=str, default="{}", help="JSON object of generator args")
    args = parser.parse_args(argv)

    gen_args = json.loads(args.args) if args.args.strip() else {}
    out_dir = args.out or Path(__file__).resolve().parent / "generate" / "cli"
    path = generate_payload(args.type, gen_args, out_dir=out_dir)
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
