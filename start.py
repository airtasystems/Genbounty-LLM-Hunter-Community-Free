#!/usr/bin/env python3
"""Bootstrap venv, install dependencies, and launch the Genbounty LLM Hunter web UI."""

from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_VENV_DIR = ROOT / "genbounty-venv"
LEGACY_VENV_DIR = ROOT / "airta-venv"
REQUIREMENTS = ROOT / "requirements.txt"
WEB_APP = ROOT / "web" / "app.py"


def venv_dir() -> Path:
    """Prefer genbounty-venv; fall back to legacy airta-venv if present."""
    if DEFAULT_VENV_DIR.exists():
        return DEFAULT_VENV_DIR
    if LEGACY_VENV_DIR.exists():
        return LEGACY_VENV_DIR
    return DEFAULT_VENV_DIR


def venv_python() -> Path:
    vdir = venv_dir()
    if sys.platform == "win32":
        return vdir / "Scripts" / "python.exe"
    return vdir / "bin" / "python"


def ensure_venv() -> bool:
    """Create the virtual environment if missing. Returns True when newly created."""
    vdir = venv_dir()
    if vdir.exists():
        return False
    print(f"Creating virtual environment at {vdir} ...")
    subprocess.check_call([sys.executable, "-m", "venv", str(vdir)])
    return True


def install_requirements(python: Path) -> None:
    if not REQUIREMENTS.is_file():
        raise SystemExit(f"Missing requirements file: {REQUIREMENTS}")
    print("Installing requirements ...")
    subprocess.check_call([str(python), "-m", "pip", "install", "-U", "pip"])
    subprocess.check_call([str(python), "-m", "pip", "install", "-r", str(REQUIREMENTS)])


def playwright_platform_override() -> str | None:
    """Ubuntu 26+ is not in Playwright's manifest yet; use 24.04 binaries."""
    if sys.platform != "linux":
        return None
    try:
        content = Path("/etc/os-release").read_text(encoding="utf-8")
    except OSError:
        return None
    if not re.search(r"^ID=ubuntu$", content, re.MULTILINE):
        return None
    match = re.search(r'^VERSION_ID="?(\d+)', content, re.MULTILINE)
    if not match or int(match.group(1)) < 26:
        return None
    arch = platform.machine().lower()
    if arch in {"aarch64", "arm64"}:
        return "ubuntu24.04-arm64"
    return "ubuntu24.04-x64"


def apply_playwright_platform_env() -> None:
    override = playwright_platform_override()
    if override:
        os.environ["PLAYWRIGHT_HOST_PLATFORM_OVERRIDE"] = override


def playwright_chromium_installed() -> bool:
    cache = Path.home() / ".cache" / "ms-playwright"
    if not cache.is_dir():
        return False
    return any(cache.glob("chromium*")) or any(cache.glob("chromium_headless_shell*"))


def install_playwright_browsers(python: Path) -> None:
    print("Installing Playwright Chromium browser ...")
    apply_playwright_platform_env()
    override = os.environ.get("PLAYWRIGHT_HOST_PLATFORM_OVERRIDE")
    if override:
        print(f"Using Playwright platform override: {override}")
    cmd = [str(python), "-m", "playwright", "install", "chromium"]
    try:
        subprocess.check_call(cmd, env=os.environ.copy())
    except subprocess.CalledProcessError:
        if override:
            raise
        print("Retrying with PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64 ...")
        env = os.environ.copy()
        env["PLAYWRIGHT_HOST_PLATFORM_OVERRIDE"] = "ubuntu24.04-x64"
        subprocess.check_call(cmd, env=env)
        os.environ["PLAYWRIGHT_HOST_PLATFORM_OVERRIDE"] = "ubuntu24.04-x64"


def launch_ui(python: Path) -> None:
    apply_playwright_platform_env()
    os.chdir(ROOT)
    os.execv(str(python), [str(python), str(WEB_APP)])


def main() -> None:
    created = ensure_venv()
    python = venv_python()
    if not python.is_file():
        raise SystemExit(f"Virtual environment python not found: {python}")

    install_requirements(python)
    if created or not playwright_chromium_installed():
        install_playwright_browsers(python)

    print("Starting Genbounty LLM Hunter ...")
    launch_ui(python)


if __name__ == "__main__":
    main()
