"""Subprocess wrapper for discovery - gives run_training its own event loop."""
import os
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))
sys.path.insert(0, str(_root / "browser-bot"))

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python discover_worker.py <site> <component>", file=sys.stderr)
        sys.exit(1)
    site, component = sys.argv[1], sys.argv[2]
    os.environ["GENBOUNTY_SITE"] = site
    os.environ["GENBOUNTY_COMPONENT"] = component
    from browser_bot.config import apply_component_settings

    apply_component_settings(site, component)
    from browser_bot.record_submission import run_training  # noqa: E402

    ok = run_training(site, component)
    sys.exit(0 if ok else 1)
