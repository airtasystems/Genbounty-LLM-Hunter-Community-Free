"""Subprocess wrapper for assessment-driven recon round probes."""
import json
import os
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))
sys.path.insert(0, str(_root / "browser-bot"))
sys.path.insert(0, str(_root / "generate-tests"))

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python recon_round_worker.py <site> <component> [json_params]", file=sys.stderr)
        sys.exit(1)

    site, component = sys.argv[1], sys.argv[2]
    params = {}
    if len(sys.argv) > 3 and sys.argv[3].strip():
        params = json.loads(sys.argv[3])

    os.environ["GENBOUNTY_SITE"] = site
    os.environ["GENBOUNTY_COMPONENT"] = component

    playbook_id = str(params.get("playbook_id") or "").strip()
    strategy = str(params.get("strategy") or "").strip()
    if not playbook_id:
        print("[!] recon_round requires playbook_id", file=sys.stderr)
        sys.exit(1)

    from browser_bot.config import apply_component_settings

    apply_component_settings(site, component)

    from pipeline.intel import empty_intel, load_playbook_intel, save_playbook_intel
    from pipeline.recon_round import (
        apply_intel_merge,
        build_recon_round_context,
        generate_recon_probes,
        synthesize_recon_merge,
    )
    from browser_bot.recon_round import run_recon_round
    from playbooks.registry import normalize_playbook_id

    pid = normalize_playbook_id(playbook_id)
    print(f"[recon_round] Planning probes for {site}/{component} ({pid}/{strategy})", flush=True)
    ctx = build_recon_round_context(site, component, pid, strategy=strategy or None)
    probes = params.get("probes")
    if not isinstance(probes, list) or not probes:
        probes = generate_recon_probes(ctx)
    print(f"[recon_round] Generated {len(probes)} probe(s)", flush=True)
    for p in probes:
        if isinstance(p, dict):
            print(f"  - {p.get('id', '?')}: {str(p.get('topic') or '')[:40]}", flush=True)

    print("[recon_round] Executing probes against target…", flush=True)
    try:
        probe_results = run_recon_round(site, component, probes)
    except Exception as exc:
        print(f"[!] Recon round probe execution failed: {exc}", flush=True)
        sys.exit(1)

    existing = load_playbook_intel(site, component, pid) or empty_intel(
        pid,
        play_category=str(ctx.get("play_category") or ""),
    )
    print(f"[recon_round] Merging probe results into intel/{pid}.json…", flush=True)
    try:
        merged = synthesize_recon_merge(existing, probe_results, ctx)
    except Exception as exc:
        print(f"[!] Intel merge failed ({exc}); applying transcript-only merge", flush=True)
        merged = apply_intel_merge(existing, {}, probe_results, ctx)

    from pipeline.recon_consolidate import consolidate_recon_intel

    print("[recon_round] Consolidating probe intel…", flush=True)
    merged = consolidate_recon_intel(merged, ctx=ctx)

    target = save_playbook_intel(site, component, merged)
    print(f"[recon_round] Saved -> {target}", flush=True)
    print(
        "[genbounty_progress] "
        + json.dumps({"type": "run_done", "phase": "recon", "elapsed_sec": 0}, ensure_ascii=False),
        flush=True,
    )
    sys.exit(0)
