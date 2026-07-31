"""Subprocess wrapper for login - opens a browser, user logs in, auth state is saved."""
import asyncio
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "browser-bot"))

from browser_bot.auth import capture_login  # noqa: E402
from browser_bot.config import apply_component_settings, use_cdp_browser  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python login_worker.py <site> <component> <url> [--use-cdp]", file=sys.stderr)
        print("   or: python login_worker.py <url> [--use-cdp]", file=sys.stderr)
        sys.exit(1)
    args = [a for a in sys.argv[1:] if a != "--use-cdp"]
    explicit_cdp = "--use-cdp" in sys.argv[1:]
    if len(args) >= 3:
        site = args[0].strip()
        component = args[1].strip()
        url = args[2].strip()
    else:
        site = ""
        component = ""
        url = args[0].strip()
    if not url or url.startswith("{"):
        print("[!] Invalid login URL", file=sys.stderr)
        sys.exit(1)
    if site and component:
        applied = apply_component_settings(site, component)
        if applied:
            print(f"[login] Applied component browser settings ({len(applied)} keys)")
    use_cdp = use_cdp_browser(explicit_cdp)
    target = asyncio.run(
        capture_login(
            url,
            site=site or None,
            component=component or None,
            use_cdp=use_cdp,
        )
    )
    if target:
        scope = f"{site}/{component}" if site and component else site or target
        print(f"[+] Auth saved for {scope}")
        sys.exit(0)
    print("[!] Login failed or cancelled")
    sys.exit(1)
