"""Subprocess wrapper for manual browser-guided component discovery."""
import os
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))
sys.path.insert(0, str(_root / "browser-bot"))

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(
            "Usage: python manual_discover_worker.py <site> <component> [--guided] [--use-cdp]",
            file=sys.stderr,
        )
        sys.exit(1)
    site, component = sys.argv[1], sys.argv[2]
    flags = set(sys.argv[3:])
    guided = "--guided" in flags
    os.environ["GENBOUNTY_SITE"] = site
    os.environ["GENBOUNTY_COMPONENT"] = component
    from browser_bot.config import USE_CDP_BROWSER, apply_component_settings, use_cdp_browser

    apply_component_settings(site, component)
    from browser_bot.record_submission import run_manual_training  # noqa: E402

    use_cdp = use_cdp_browser("--use-cdp" in flags)
    ok = run_manual_training(site, component, guided=guided, use_cdp=use_cdp)
    sys.exit(0 if ok else 1)
