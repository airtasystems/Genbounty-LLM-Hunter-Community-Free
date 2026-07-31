"""Subprocess wrapper for API endpoint discovery."""
import json
import os
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))
sys.path.insert(0, str(_root / "browser-bot"))

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python api_discover_worker.py <site> <component> [json_params]", file=sys.stderr)
        sys.exit(1)
    site, component = sys.argv[1], sys.argv[2]
    params = {}
    if len(sys.argv) > 3 and sys.argv[3].strip():
        params = json.loads(sys.argv[3])
    os.environ["GENBOUNTY_SITE"] = site
    os.environ["GENBOUNTY_COMPONENT"] = component
    from browser_bot.config import apply_component_settings

    apply_component_settings(site, component)
    from browser_bot.record_submission import run_api_discovery  # noqa: E402

    ok = run_api_discovery(
        site,
        component,
        api_url=params.get("api_url", ""),
        api_method=params.get("api_method", "POST"),
        api_headers=params.get("api_headers") or {},
        api_body=params.get("api_body"),
        api_response_path=params.get("api_response_path", "response"),
        api_model=params.get("api_model", ""),
        probe_prompt=params.get("probe_prompt", "Hello from Genbounty Hunter"),
        transport=params.get("transport", "api"),
        upload_url=params.get("upload_url", ""),
        upload_file_field=params.get("upload_file_field", "file"),
        upload_response_path=params.get("upload_response_path", "document_id"),
        multipart_prompt_field=params.get("multipart_prompt_field", "prompt"),
        multipart_file_field=params.get("multipart_file_field", "file"),
    )
    sys.exit(0 if ok else 1)
