"""Subprocess: aggregate recon from a selected pipeline_report.json."""
import json
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))
sys.path.insert(0, str(_root / "browser-bot"))

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python recon_from_report_worker.py <site> <component> [json_params]", file=sys.stderr)
        sys.exit(1)

    site, component = sys.argv[1], sys.argv[2]
    params: dict = {}
    if len(sys.argv) > 3 and sys.argv[3].strip():
        params = json.loads(sys.argv[3])

    report_path = str(params.get("pipeline_report") or params.get("report_path") or "").strip()
    if not report_path:
        print("[!] recon_from_report requires pipeline_report path", file=sys.stderr)
        sys.exit(1)

    from pipeline.recon_auto import save_recon_from_pipeline_report

    print(
        f"[recon_from_report] Extracting recon from {report_path} "
        f"for {site}/{component}",
        flush=True,
    )
    try:
        target = save_recon_from_pipeline_report(site, component, report_path)
    except Exception as exc:
        print(f"[!] Report recon failed: {exc}", flush=True)
        sys.exit(1)

    print("[recon_from_report] Consolidated revealing intel into recon profile", flush=True)
    print(f"[recon_from_report] Saved -> {target}", flush=True)
    print(
        "[genbounty_progress] "
        + json.dumps({"type": "run_done", "phase": "recon", "elapsed_sec": 0}, ensure_ascii=False),
        flush=True,
    )
    sys.exit(0)
