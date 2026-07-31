"""Subprocess wrapper for LLM-powered target recon."""
import json
import os
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))
sys.path.insert(0, str(_root / "browser-bot"))

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python recon_worker.py <site> <component> [json_params]", file=sys.stderr)
        sys.exit(1)
    site, component = sys.argv[1], sys.argv[2]
    params = {}
    if len(sys.argv) > 3 and sys.argv[3].strip():
        params = json.loads(sys.argv[3])
    os.environ["GENBOUNTY_SITE"] = site
    os.environ["GENBOUNTY_COMPONENT"] = component
    print(f"[recon] Starting reconnaissance for {site}/{component}", flush=True)
    print(
        f"[recon] Mode: {params.get('mode', 'connected')} "
        f"{'(manual URL)' if params.get('mode') == 'manual_url' else '(configured target)'}",
        flush=True,
    )
    from browser_bot.config import apply_component_settings

    apply_component_settings(site, component)
    from browser_bot.recon import run_recon  # noqa: E402

    ok = run_recon(
        site,
        component,
        mode=params.get("mode", "connected"),
        manual_url=params.get("manual_url"),
        overwrite=bool(params.get("overwrite", True)),
    )
    sys.exit(0 if ok else 1)
