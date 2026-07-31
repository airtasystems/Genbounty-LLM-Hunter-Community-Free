"""Shared filesystem roots and sys.path bootstrap for the web package."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BB_DIR = ROOT / "browser-bot"
WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"
IMG_DIR = WEB_DIR / "IMG"

if str(BB_DIR) not in sys.path:
    sys.path.insert(0, str(BB_DIR))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def ensure_generate_tests_path() -> None:
    gen_dir = ROOT / "generate-tests"
    if str(gen_dir) not in sys.path:
        sys.path.insert(0, str(gen_dir))
