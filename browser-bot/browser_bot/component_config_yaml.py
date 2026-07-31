"""Format component config.yaml with documented inline comments."""

from __future__ import annotations

from pathlib import Path
from typing import Any

COMPONENT_CONFIG_INTRO = """# =============================================================================
# Component config - browser-bot/sites/<site>/<component>/config.yaml
# =============================================================================
#
# Tells browser-bot how to drive this AI product's UI: where to log in, which page
# to open, what to fill in, how to submit, and where to read the model response.
#
# Precedence for settings: overrides here beat site config, config.py/.env, then
# config.defaults.yaml. See repo-root config.defaults.yaml for all settings keys.
#
# Prefer stable CSS selectors: #id, [name="..."], [data-testid="..."], tag.class
# Playwright also supports: button:has-text("Send") scoped under a landmark.
#
# Web UI: Settings → Component Config (or run Discovery to auto-fill submission).
"""

SETTINGS_OVERRIDES_EXAMPLE = """
# --- Settings overrides (optional) ---------------------------------------------
# Same keys as Settings → Browser Config and Cache Control. Omit keys to inherit.
# Full list and allowed values: see config.defaults.yaml at repo root.
#
# settings:
#   gemini_use_cache: false          # true | false
#   intel_credentials_and_paths: true  # auto-extract credentials/paths after risk assessment
#   FETCH_METHOD: human              # auto | pool | cluster | human
#   HEADLESS: false                  # true | false
#   HUMAN_COUNTRY: UK                # US | UK | DE | FR | JP | CA | AU | NL | ES | IT
#   CHROME_CHANNEL: chromium         # chromium | chrome | chrome-beta | msedge
#   BLOCKED_TYPES: [font, media]     # image | font | media | stylesheet
#   POOL_SIZE: 1
#   POOL_CLUSTER_HUMAN_LIKE: true
#   API_CONCURRENCY: 2
#   EVASION_REQUEST_DELAY_S: 0.5
#   RUN_SCREENSHOT_INTERVAL_S: 0.0  # 0 = disabled; 1–120 = interval seconds
"""

_INPUT_TYPE_COMMENT = """      # Input type - affects how Playwright fills the field:
      #   text | textarea | contenteditable | password | email | search
      #   select | combobox | checkbox | radio | click | file (path_from: payload)"""

_KNOWN_TOP_LEVEL_KEYS = frozenset({
    "urls", "posts", "login_url", "endpoint_url", "refresh_url", "refresh_mode",
    "refresh_cookies", "submission", "settings",
})


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        if not value:
            return "''"
        import yaml

        return yaml.dump(value, default_style='"', allow_unicode=True).strip()
    import yaml

    return yaml.dump(value, default_flow_style=True, allow_unicode=True).strip().removesuffix("...")


def _format_inputs(inputs: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    if not inputs:
        lines.append("  inputs: []")
        return lines

    lines.append("  # Fields to fill in order before submit. One object per input.")
    lines.append(
        "  # Leading type: click + surface_prep: true rows are surface pre-steps "
        "(notices/tabs/levels/Start) replayed after every reload before the prompt."
    )
    lines.append("  inputs:")
    for inp in inputs:
        if not isinstance(inp, dict):
            continue
        selector = inp.get("selector", "")
        lines.append(f"    - selector: {_yaml_scalar(selector)}")
        lines.append(_INPUT_TYPE_COMMENT)
        lines.append(f"      type: {inp.get('type', 'text')}")
        if inp.get("upload_prep"):
            lines.append("      upload_prep: true")
        if inp.get("surface_prep"):
            lines.append("      surface_prep: true")
        if inp.get("name") not in (None, ""):
            lines.append(f"      name: {_yaml_scalar(inp['name'])}")
        if inp.get("role") not in (None, ""):
            lines.append(f"      role: {_yaml_scalar(inp['role'])}")
        if inp.get("type") == "file" or inp.get("path_from"):
            lines.append(f"      path_from: {_yaml_scalar(inp.get('path_from', 'payload'))}")
        if inp.get("value") not in (None, ""):
            lines.append(f"      value: {_yaml_scalar(inp['value'])}")
        else:
            lines.append("      # value: optional fixed string (usually leave unset; tests supply the prompt)")
    return lines


def _format_api_submission(submission: dict[str, Any]) -> list[str]:
    import yaml

    lines = [
        "# --- API submission (direct HTTP - no browser selectors required) -------------",
        "submission:",
        "  # Transport: ui (browser automation) | api (HTTP endpoint)",
        "  transport: api",
        "",
        "  # Full URL of the chat/completion endpoint. Use {{model}} in URL/body when needed.",
        f"  api_url: {_yaml_scalar(submission.get('api_url', ''))}",
        "",
    ]
    api_model = submission.get("api_model")
    if api_model:
        lines.append(f"  api_model: {_yaml_scalar(api_model)}")
        lines.append("")
    lines.extend([
        "  # HTTP method. Options: POST | GET | PUT | PATCH",
        f"  api_method: {(submission.get('api_method') or 'POST')}",
        "",
    ])
    headers = submission.get("api_headers") or {}
    if headers:
        lines.append("  # Optional request headers (merged with saved auth headers).")
        lines.append("  api_headers:")
        for k, v in headers.items():
            lines.append(f"    {k}: {_yaml_scalar(v)}")
        lines.append("")
    else:
        lines.extend([
            "  # Optional request headers (merged with saved auth headers).",
            "  # api_headers:",
            "  #   Authorization: Bearer <token>",
            "",
        ])

    api_body = submission.get("api_body") or submission.get("api_body_template") or {"prompt": "{{prompt}}"}
    lines.extend([
        "  # JSON request body. Use {{prompt}} where the test prompt should be inserted.",
        "  api_body:",
    ])
    body_yaml = yaml.dump(api_body, default_flow_style=False, sort_keys=False, allow_unicode=True)
    for line in body_yaml.splitlines():
        lines.append(f"    {line}" if line.strip() else "")
    lines.extend([
        "",
        "  # Dot path into JSON response for assistant text (e.g. response or data.message).",
        f"  api_response_path: {_yaml_scalar(submission.get('api_response_path') or 'response')}",
    ])
    context_mode = submission.get("api_context_mode")
    prefix = submission.get("api_messages_prefix")
    if context_mode or prefix:
        lines.append("")
        lines.append("  # Multi-turn API: accumulate prior user/assistant turns into messages (see {{messages}}).")
        if context_mode:
            lines.append(f"  api_context_mode: {_yaml_scalar(context_mode)}")
        if isinstance(prefix, list) and prefix:
            lines.append("  api_messages_prefix:")
            prefix_yaml = yaml.dump(prefix, default_flow_style=False, sort_keys=False, allow_unicode=True)
            for line in prefix_yaml.splitlines():
                lines.append(f"    {line}" if line.strip() else "")
    return lines


def _format_submission(submission: dict[str, Any]) -> list[str]:
    transport = (submission.get("transport") or "ui").strip().lower()
    if transport == "api_document":
        import yaml

        lines = [
            "# --- API document upload + chat (multimodal) -------------------------------",
            "submission:",
            "  transport: api_document",
            f"  upload_url: {_yaml_scalar(submission.get('upload_url', ''))}",
            f"  upload_file_field: {_yaml_scalar(submission.get('upload_file_field', 'file'))}",
            f"  upload_response_path: {_yaml_scalar(submission.get('upload_response_path', 'document_id'))}",
            f"  api_url: {_yaml_scalar(submission.get('api_url', ''))}",
            f"  api_method: {(submission.get('api_method') or 'POST')}",
            "  api_body:",
        ]
        api_body = submission.get("api_body") or {
            "prompt": "{{prompt}}",
            "document_id": "{{document_id}}",
            "context_from": "upload",
        }
        body_yaml = yaml.dump(api_body, default_flow_style=False, sort_keys=False, allow_unicode=True)
        for line in body_yaml.splitlines():
            lines.append(f"    {line}" if line.strip() else "")
        lines.append(f"  api_response_path: {_yaml_scalar(submission.get('api_response_path') or 'response')}")
        return lines
    if transport == "api_multipart":
        return [
            "# --- API multipart upload (file + prompt in one POST) -----------------------",
            "submission:",
            "  transport: api_multipart",
            f"  api_url: {_yaml_scalar(submission.get('api_url', ''))}",
            f"  multipart_prompt_field: {_yaml_scalar(submission.get('multipart_prompt_field', 'prompt'))}",
            f"  multipart_file_field: {_yaml_scalar(submission.get('multipart_file_field', 'file'))}",
            f"  api_response_path: {_yaml_scalar(submission.get('api_response_path') or 'response')}",
        ]
    if transport == "api":
        return _format_api_submission(submission)
    lines = [
        "# --- UI submission (browser automation - Run Tests / Sample Request) ----------",
        "submission:",
        "  # Transport: ui (browser automation) | api (HTTP endpoint)",
        "  transport: ui",
        "",
        "  # Page URL where the chat / prompt UI lives (loaded before each test).",
        f"  start_url: {_yaml_scalar(submission.get('start_url', ''))}",
        "",
    ]
    lines.extend(_format_inputs(submission.get("inputs") or []))
    lines.extend([
        "",
        "  # Element that sends the prompt (button, etc.).",
        f"  submit_selector: {_yaml_scalar(submission.get('submit_selector', ''))}",
        "",
        "  # Container(s) for assistant output - roots the response capture.",
        "  # Often a message list, bubble, or [data-testid=\"assistant-message\"].",
        f"  response_selector: {_yaml_scalar(submission.get('response_selector', ''))}",
        "",
    ])

    within = submission.get("response_within_selector")
    if within:
        lines.extend([
            "  # Descendant under response_selector - last visible match wins.",
            f"  response_within_selector: {_yaml_scalar(within)}",
            "",
        ])
    else:
        lines.extend([
            "  # Optional: descendant under response_selector - last visible match wins.",
            "  # Use when the root holds multiple messages and you want the latest bubble.",
            "  # response_within_selector: div.message-body",
            "",
        ])

    text_within = submission.get("response_text_within_selector")
    if text_within:
        lines.extend([
            "  # Narrower node for inner_text only (e.g. \"> p\" inside the bubble).",
            f"  response_text_within_selector: {_yaml_scalar(text_within)}",
            "",
        ])
    else:
        lines.extend([
            "  # Optional: narrower node for inner_text only (e.g. \"> p\" inside the bubble).",
            "  # response_text_within_selector: \"> p\"",
            "",
        ])

    capture_mode = submission.get("response_capture_mode")
    list_sel = submission.get("response_list_selector")
    role_sel = submission.get("response_role_selector")
    if capture_mode or list_sel or role_sel:
        lines.extend([
            "  # Response capture strategy (auto-detected in Discovery for message lists).",
            "  # last = newest match; role = assistant-only roots;",
            "  # parity_odd / parity_even = alternating user/assistant threads.",
        ])
        if capture_mode:
            lines.append(f"  response_capture_mode: {_yaml_scalar(capture_mode)}")
        if list_sel:
            lines.append(f"  response_list_selector: {_yaml_scalar(list_sel)}")
        if role_sel:
            lines.append(f"  response_role_selector: {_yaml_scalar(role_sel)}")
        lines.append("")

    submit_via = submission.get("submit_via", "click")
    response_wait_ms = submission.get("response_wait_ms", 5000)
    lines.extend([
        "  # How to submit after filling inputs.",
        "  # Options: click | enter",
        f"  submit_via: {submit_via}",
        "",
        "  # Max time to wait for a new response after submit, in milliseconds (min ~500).",
        f"  response_wait_ms: {int(response_wait_ms)}",
    ])

    ignore_subs = submission.get("response_ignore_substrings")
    if ignore_subs:
        lines.extend([
            "",
            "  # Substrings to reject as non-actionable response text (case-insensitive,",
            "  # per-line when capture is longer). Recorded during Configure (welcome/intro",
            "  # click step) and may also be auto-appended from pre-submit chrome.",
            f"  response_ignore_substrings: {_yaml_scalar(ignore_subs)}",
        ])
    else:
        lines.extend([
            "",
            "  # Optional: substrings to reject as non-actionable response text",
            "  # (case-insensitive; line-level for long captures). Prefer Configure's",
            "  # welcome/intro click step; also auto-learned from pre-submit chrome.",
            "  # response_ignore_substrings:",
            "  #   - welcome to our chat",
            "  #   - [beta notice]",
        ])

    mode = submission.get("mode")
    batch_size = submission.get("batch_size")
    if mode or batch_size is not None:
        lines.append("")
        if mode:
            lines.append(f"  mode: {_yaml_scalar(mode)}")
        if batch_size is not None:
            lines.append(f"  batch_size: {int(batch_size)}")

    lines.extend([
        "",
        "  # Optional multi-turn UI mode (for tree-of-thoughts / batched suites):",
        "  # mode: single | multi     - single = one prompt per case (default)",
        "  # batch_size: 3           - if >1 without mode, implies multi",
    ])
    return lines


def _format_settings(settings: dict[str, Any]) -> list[str]:
    import yaml

    lines = [
        "# --- Settings overrides (optional) ---------------------------------------------",
        "# Same keys as Settings → Browser Config and Cache Control. Omit keys to inherit.",
        "# Full list and allowed values: see config.defaults.yaml at repo root.",
        "settings:",
    ]
    block = yaml.dump(settings, default_flow_style=False, sort_keys=False, allow_unicode=True)
    for line in block.splitlines():
        if line.strip():
            lines.append(f"  {line}")
        else:
            lines.append("")
    return lines


def _format_submission_skeleton() -> list[str]:
    return [
        "# --- Submission (choose one transport) -----------------------------------------",
        "# transport: ui   - browser automation (Discovery records selectors)",
        "# transport: api  - direct HTTP endpoint (Connect via API below)",
        "#",
        "# UI example:",
        "# submission:",
        "#   transport: ui",
        "#   start_url: https://example.com/chat",
        "#   inputs:",
        "#     - selector: '#prompt'",
        "#       type: textarea",
        "#   submit_selector: button[type='submit']",
        "#   response_selector: .assistant-message",
        "#   submit_via: click",
        "#   response_wait_ms: 8000",
        "#",
        "# API example:",
        "# submission:",
        "#   transport: api",
        "#   api_url: http://localhost:3000/api/chat",
        "#   api_method: POST",
        "#   api_body:",
        "#     prompt: \"{{prompt}}\"",
        "#   # Multi-turn API (multi_shot / iterative suites): set api_context_mode and use {{messages}}:",
        "#   api_context_mode: messages",
        "#   api_messages_prefix:",
        "#     - role: system",
        "#       content: \"You are a helpful assistant.\"",
        "#   api_body:",
        "#     model: \"{{model}}\"",
        "#     messages: \"{{messages}}\"",
        "#   api_response_path: response",
    ]


def format_component_config_yaml(config: dict[str, Any]) -> str:
    """Render component config dict as documented YAML text."""
    import yaml

    lines: list[str] = [COMPONENT_CONFIG_INTRO.rstrip(), ""]

    lines.extend([
        "# --- Legacy / API fetch (optional) -------------------------------------------",
        "# urls: HTTP GET targets for non-UI fetch modes",
        "# posts: POST targets [{url, data?, json?, headers?}]",
    ])
    lines.append(yaml.dump({"urls": config.get("urls") or []}, default_flow_style=False, sort_keys=False).strip())
    lines.append(yaml.dump({"posts": config.get("posts") or []}, default_flow_style=False, sort_keys=False).strip())
    lines.append("")

    lines.extend([
        "# --- Auth --------------------------------------------------------------------",
        "# Page opened for \"Add Login\" / manual sign-in. Usually the site root or /login.",
        "# http:// for localhost; https:// for production hosts.",
    ])
    login_url = config.get("login_url")
    lines.append(f"login_url: {_yaml_scalar(login_url if login_url not in (None, '') else '')}")

    optional_auth: list[tuple[str, str]] = [
        ("endpoint_url", "# Optional: API endpoint URL for legacy fetch modes."),
        ("refresh_url", "# Optional: token refresh URL (often set at site level)."),
        ("refresh_mode", "# Optional: cookie | both - how refresh requests are sent."),
        ("refresh_cookies", "# Optional: cookie names to send on refresh."),
    ]
    has_optional_auth = False
    for key, comment in optional_auth:
        if key in config and config[key] not in (None, ""):
            has_optional_auth = True
            lines.append(comment)
            val = config[key]
            if isinstance(val, list):
                lines.append(f"{key}:")
                for item in val:
                    lines.append(f"  - {_yaml_scalar(item)}")
            else:
                lines.append(f"{key}: {_yaml_scalar(val)}")

    if not has_optional_auth:
        lines.append("")
        lines.append("# Optional (usually site-level): refresh_url, refresh_mode (cookie | both), endpoint_url")

    lines.append("")

    submission = config.get("submission")
    if isinstance(submission, dict) and submission:
        lines.extend(_format_submission(submission))
    else:
        lines.extend(_format_submission_skeleton())

    settings = config.get("settings")
    lines.append("")
    if isinstance(settings, dict) and settings:
        lines.extend(_format_settings(settings))
    else:
        lines.append(SETTINGS_OVERRIDES_EXAMPLE.rstrip())

    extras = {k: v for k, v in config.items() if k not in _KNOWN_TOP_LEVEL_KEYS}
    if extras:
        lines.extend(["", "# --- Additional config ---------------------------------------------------------"])
        lines.append(yaml.dump(extras, default_flow_style=False, sort_keys=False, allow_unicode=True).rstrip())

    return "\n".join(lines).rstrip() + "\n"


def write_component_config_documented(path: Path, config: dict) -> None:
    """Write component config.yaml with full inline documentation."""
    path.write_text(format_component_config_yaml(config), encoding="utf-8")
