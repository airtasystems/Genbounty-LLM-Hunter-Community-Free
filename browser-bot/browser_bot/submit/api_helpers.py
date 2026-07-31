"""HTTP helpers for API-based component submission."""

from __future__ import annotations

import json
import mimetypes
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import urllib.error
import urllib.request

_TRANSIENT_HTTP_STATUS = frozenset({429, 502, 503, 529})
_API_RETRY_WAIT_S = 1.5


_MESSAGES_CONTEXT_MODES = frozenset({"messages", "multi_turn", "accumulating"})


def uses_messages_context(sub: dict[str, Any]) -> bool:
    """True when API requests should carry prior turn user/assistant pairs in ``messages``."""
    mode = str(sub.get("api_context_mode") or "").strip().lower()
    if mode in _MESSAGES_CONTEXT_MODES:
        return True
    if mode in ("off", "none", "single"):
        return False
    body = sub.get("api_body") or {}
    return _contains_messages_placeholder(body)


def _contains_messages_placeholder(obj: Any) -> bool:
    if isinstance(obj, str):
        return "{{messages}}" in obj
    if isinstance(obj, dict):
        return any(_contains_messages_placeholder(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_contains_messages_placeholder(v) for v in obj)
    return False


def build_conversation_messages(
    sub: dict[str, Any],
    prompt: str,
    history: list[tuple[str, str | None]] | None = None,
) -> list[dict[str, str]]:
    """Build chat ``messages`` array: optional prefix, prior turns, current user prompt."""
    prefix = sub.get("api_messages_prefix") or []
    user_role = str(sub.get("api_user_role") or "user").strip() or "user"
    assistant_role = str(sub.get("api_assistant_role") or "assistant").strip() or "assistant"

    messages: list[dict[str, str]] = []
    for item in prefix:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if content is None:
            continue
        role = str(item.get("role") or "system").strip() or "system"
        messages.append({"role": role, "content": str(content)})

    for user_text, assistant_text in history or []:
        messages.append({"role": user_role, "content": user_text})
        if assistant_text:
            messages.append({"role": assistant_role, "content": assistant_text})

    messages.append({"role": user_role, "content": prompt})
    return messages


def _substitute_messages_placeholder(obj: Any, messages: list[dict[str, str]]) -> Any:
    if isinstance(obj, str) and obj.strip() == "{{messages}}":
        return messages
    if isinstance(obj, dict):
        return {k: _substitute_messages_placeholder(v, messages) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_substitute_messages_placeholder(v, messages) for v in obj]
    return obj


def build_api_request_body(
    sub: dict[str, Any],
    prompt: str,
    *,
    conversation_history: list[tuple[str, str | None]] | None = None,
) -> dict[str, Any] | list[Any] | Any:
    """Render ``api_body`` with prompt/model placeholders and optional multi-turn messages."""
    model = str(sub.get("api_model") or "").strip()
    extras = {"model": model} if model else {}
    body_template = sub.get("api_body") or {"prompt": "{{prompt}}"}

    if uses_messages_context(sub):
        messages = build_conversation_messages(sub, prompt, conversation_history)
        with_messages = _substitute_messages_placeholder(body_template, messages)
        return apply_prompt_template(with_messages, prompt, extra=extras)

    return apply_prompt_template(body_template, prompt, extra=extras)


def apply_prompt_template(obj: Any, prompt: str, *, extra: dict[str, str] | None = None) -> Any:
    """Replace ``{{prompt}}`` and optional ``{{key}}`` placeholders in nested structures."""
    extras = extra or {}

    def _sub(s: str) -> str:
        out = s.replace("{{prompt}}", prompt)
        for k, v in extras.items():
            out = out.replace(f"{{{{{k}}}}}", v)
        return out

    if isinstance(obj, str):
        return _sub(obj)
    if isinstance(obj, dict):
        return {k: apply_prompt_template(v, prompt, extra=extras) for k, v in obj.items()}
    if isinstance(obj, list):
        return [apply_prompt_template(v, prompt, extra=extras) for v in obj]
    return obj


def extract_json_path(data: Any, path: str) -> Any:
    """Extract a dotted path from parsed JSON (e.g. ``choices.0.message.content``)."""
    path = (path or "").strip()
    if not path:
        return data
    cur = data
    for part in path.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError, TypeError):
                return None
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _merge_url_query(url: str, extra: dict[str, str]) -> str:
    if not extra:
        return url
    parsed = urlparse(url)
    existing = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for k, v in extra.items():
        if k and k not in existing:
            existing[k] = v
    return urlunparse(parsed._replace(query=urlencode(existing)))


def _normalize_provider_auth(
    headers: dict[str, str],
    url: str,
    query_params: dict[str, str],
) -> dict[str, str]:
    """Map auth to provider-specific headers (e.g. Gemini x-goog-api-key)."""
    out = dict(headers)
    host = (urlparse(url).netloc or "").lower()
    if "generativelanguage.googleapis.com" not in host:
        return out

    key_val = None
    auth = out.pop("Authorization", None) or out.pop("authorization", None)
    if auth:
        auth = auth.strip()
        if auth.lower().startswith("bearer "):
            key_val = auth[7:].strip()
        elif auth.lower().startswith("aiza"):
            key_val = auth
        else:
            key_val = auth
    if not key_val and query_params.get("key"):
        key_val = query_params["key"]
    if key_val and "x-goog-api-key" not in {k.lower() for k in out}:
        out["x-goog-api-key"] = key_val
    return out


def auth_query_params_for_site(site: str | None, component: str | None = None) -> dict[str, str]:
    if not site:
        return {}
    from browser_bot.auth_state import load_auth_config

    cfg = load_auth_config(site, component) or {}
    raw = cfg.get("query_params") or {}
    return {str(k): str(v) for k, v in raw.items()}


def auth_headers_for_site(
    site: str | None,
    *,
    component: str | None = None,
    url: str = "",
) -> dict[str, str]:
    """Merge saved auth headers and cookies for API requests."""
    if not site:
        return {}
    from browser_bot.auth_state import load_auth_config

    cfg = load_auth_config(site, component) or {}
    headers = {str(k): str(v) for k, v in (cfg.get("headers") or {}).items()}
    cookies = cfg.get("cookies") or []
    if cookies:
        parts = []
        for cookie in cookies:
            if isinstance(cookie, dict) and cookie.get("name") is not None:
                parts.append(f"{cookie['name']}={cookie.get('value', '')}")
        if parts:
            headers.setdefault("Cookie", "; ".join(parts))
    query_params = {str(k): str(v) for k, v in (cfg.get("query_params") or {}).items()}
    return _normalize_provider_auth(headers, url, query_params)


def resolve_api_url(sub: dict[str, Any], *, site: str | None = None, component: str | None = None) -> str:
    """Substitute {{model}} and merge auth query params into the request URL."""
    url = str(sub.get("api_url") or "").strip()
    model = str(sub.get("api_model") or "").strip()
    if "{{model}}" in url and not model:
        raise ValueError("api_model is required when api_url contains {{model}}")
    if model:
        url = url.replace("{{model}}", model)
    extra = auth_query_params_for_site(site, component)
    return _merge_url_query(url, extra)


def _http_request(
    url: str,
    *,
    method: str = "POST",
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: float = 120.0,
) -> tuple[int, str]:
    req = urllib.request.Request(url, data=data, method=method.upper(), headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return getattr(resp, "status", 200) or 200, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = str(exc)
        return exc.code, body
    except Exception as exc:
        # URLError / TimeoutError / OSError - surface as status 0 with a JSON error body.
        payload = {"error": type(exc).__name__, "message": str(exc) or type(exc).__name__}
        return 0, json.dumps(payload)


def extract_api_refusal_signal(raw: str) -> dict[str, Any] | None:
    """Detect structured provider refusals (empty content + stop_reason/finish_reason).

    Anthropic Messages often returns HTTP 200 with ``content: []`` and
    ``stop_reason: "refusal"`` / ``stop_details.category`` (e.g. ``bio``). That is a
    model hard-block, not a harness capture failure - enhance needs the category.
    """
    raw_s = (raw or "").strip()
    if not raw_s or raw_s[0] not in "{[":
        return None
    try:
        parsed = json.loads(raw_s)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None

    stop_reason = str(parsed.get("stop_reason") or "").strip().lower()
    details = parsed.get("stop_details") if isinstance(parsed.get("stop_details"), dict) else {}
    detail_type = str(details.get("type") or "").strip().lower()
    if stop_reason == "refusal" or detail_type == "refusal":
        return {
            "api_refusal": True,
            "stop_reason": stop_reason or detail_type or "refusal",
            "refusal_category": str(details.get("category") or "").strip(),
            "refusal_explanation": str(details.get("explanation") or "").strip()[:600],
            "provider_signal": "anthropic_stop_reason",
        }

    choices = parsed.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        ch0 = choices[0]
        finish = str(ch0.get("finish_reason") or "").strip().lower()
        msg = ch0.get("message") if isinstance(ch0.get("message"), dict) else {}
        refusal_field = str(msg.get("refusal") or "").strip()
        if finish in ("content_filter", "refusal") or refusal_field:
            return {
                "api_refusal": True,
                "stop_reason": finish or "refusal",
                "refusal_category": "content_filter" if finish == "content_filter" else "",
                "refusal_explanation": refusal_field[:600],
                "provider_signal": "openai_finish_reason",
            }
    return None


def format_api_refusal_response(signal: dict[str, Any]) -> str:
    """Human-readable refusal body for run_log / assess / enhance samples."""
    reason = str(signal.get("stop_reason") or "refusal").strip() or "refusal"
    category = str(signal.get("refusal_category") or "unspecified").strip() or "unspecified"
    expl = str(signal.get("refusal_explanation") or "").strip()
    lines = [
        f"[API refusal] stop_reason={reason} category={category}",
        "The provider returned a structured hard refusal with empty assistant content.",
    ]
    if expl:
        lines.append(expl)
    return "\n".join(lines)


def _stamp_api_meta(
    meta: dict[str, Any] | None,
    *,
    status: int,
    err: str | None = None,
    refusal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach compact API diagnostics for run_log (status / parse / transport errors)."""
    out = dict(meta or {})
    out["http_status"] = int(status)
    if refusal and refusal.get("api_refusal"):
        for key in (
            "api_refusal",
            "stop_reason",
            "refusal_category",
            "refusal_explanation",
            "provider_signal",
        ):
            val = refusal.get(key)
            if val is not None and val != "":
                out[key] = val
        # HTTP succeeded; model refused - do not mark submit_failed.
        out.pop("api_error", None)
        if not out.get("submission_outcome"):
            try:
                from browser_bot.submit.rejection_detection import (
                    OUTCOME_EXECUTED,
                    apply_submission_outcome,
                )

                out = apply_submission_outcome(out, OUTCOME_EXECUTED)
            except Exception:
                out["submission_outcome"] = "executed"
        return out
    if err:
        out["api_error"] = str(err)[:800]
        if not out.get("submission_outcome"):
            try:
                from browser_bot.submit.rejection_detection import (
                    OUTCOME_SUBMIT_FAILED,
                    apply_submission_outcome,
                )

                out = apply_submission_outcome(out, OUTCOME_SUBMIT_FAILED)
            except Exception:
                out["submission_outcome"] = "submit_failed"
    return out


def _finalize_api_parse(
    status: int,
    raw: str,
    response_path: str,
    meta: dict[str, Any] | None,
) -> tuple[str | None, str | None, dict[str, Any]]:
    """Parse assistant text; promote structured provider refusals into response text."""
    text, err = _resolve_api_text(status, raw, response_path)
    refusal = extract_api_refusal_signal(raw)
    if refusal and not text:
        text = format_api_refusal_response(refusal)
        err = None
    return text, err, _stamp_api_meta(meta, status=status, err=err, refusal=refusal)


def _resolve_api_text(
    status: int,
    raw: str,
    response_path: str,
) -> tuple[str | None, str | None]:
    """Return ``(text, error)``. Error is set whenever text cannot be extracted."""
    parsed = _parse_response_text(raw, response_path)
    if parsed:
        return parsed, None
    # Prefer structured refusal over a generic "no text at path" error.
    if extract_api_refusal_signal(raw):
        return None, None
    raw_s = (raw or "").strip()
    if status >= 400:
        return None, f"HTTP {status}: {raw_s[:500] or '(empty body)'}"
    if status == 0:
        return None, raw_s[:500] or "API request failed (network/timeout)"
    if not raw_s:
        return None, f"HTTP {status}: empty response body"
    return None, (
        f"HTTP {status}: no text at api_response_path={response_path!r} "
        f"(body[:300]={raw_s[:300]!r})"
    )


def _http_request_with_retry(
    url: str,
    *,
    method: str = "POST",
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: float = 120.0,
    retries: int = 1,
) -> tuple[int, str]:
    """HTTP request with a short retry on transient overload / rate-limit statuses."""
    attempt = 0
    while True:
        status, raw = _http_request(
            url, method=method, headers=headers, data=data, timeout=timeout
        )
        if status not in _TRANSIENT_HTTP_STATUS or attempt >= max(0, retries):
            return status, raw
        attempt += 1
        time.sleep(_API_RETRY_WAIT_S * attempt)


def _encode_multipart(
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]],
) -> tuple[bytes, str]:
    boundary = f"----genbounty{uuid.uuid4().hex}"
    lines: list[bytes] = []
    for name, value in fields.items():
        lines.append(f"--{boundary}\r\n".encode())
        lines.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        lines.append(value.encode("utf-8"))
        lines.append(b"\r\n")
    for name, (filename, content, mime) in files.items():
        lines.append(f"--{boundary}\r\n".encode())
        lines.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        )
        lines.append(f"Content-Type: {mime}\r\n\r\n".encode())
        lines.append(content)
        lines.append(b"\r\n")
    lines.append(f"--{boundary}--\r\n".encode())
    body = b"".join(lines)
    return body, f"multipart/form-data; boundary={boundary}"


def _upload_document(
    sub: dict[str, Any],
    artifact_path: Path,
    *,
    site: str | None = None,
    component: str | None = None,
    timeout: float = 120.0,
) -> tuple[str | None, str | None]:
    upload_url = sub.get("upload_url") or sub.get("api_upload_url")
    if not upload_url:
        return None, "upload_url not configured"
    file_field = sub.get("upload_file_field", "file")
    headers = dict(sub.get("api_headers") or {})
    headers.update(auth_headers_for_site(site, component=component))
    content = artifact_path.read_bytes()
    mime, _ = mimetypes.guess_type(artifact_path.name)
    mime = mime or "application/octet-stream"
    body, ctype = _encode_multipart({}, {file_field: (artifact_path.name, content, mime)})
    headers["Content-Type"] = ctype
    status, raw = _http_request(upload_url, method="POST", headers=headers, data=body, timeout=timeout)
    if status >= 400:
        return None, f"upload HTTP {status}: {raw[:500]}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None, "upload response not JSON"
    doc_path = sub.get("upload_response_path", "document_id")
    doc_id = extract_json_path(parsed, doc_path)
    if doc_id is None and isinstance(parsed, dict):
        doc_id = parsed.get("id") or parsed.get("document_id")
    if doc_id is None:
        return None, f"document id not found at {doc_path}"
    return str(doc_id), None


def _api_submission_meta(test_case: dict | None) -> dict:
    """Compact per-request meta (capture_id only; outcome stamped in ``_finalize_api_parse``)."""
    capture_id = str((test_case or {}).get("id") or "api").strip()
    return {"capture_id": capture_id} if capture_id else {}


def do_api_request(
    sub: dict[str, Any],
    prompt: str,
    *,
    site: str | None = None,
    component: str | None = None,
    timeout: float = 120.0,
    test_case: dict | None = None,
    suite_path: Path | str | None = None,
    conversation_history: list[tuple[str, str | None]] | None = None,
) -> tuple[int, str | None, str | None, dict]:
    """Send one API submission. Returns ``(status_code, response_text, error, submission_meta)``."""
    transport = (sub.get("transport") or "api").lower()
    if transport == "api_document":
        return do_api_document_request(
            sub,
            prompt,
            site=site,
            component=component,
            timeout=timeout,
            test_case=test_case,
            suite_path=suite_path,
        )
    if transport == "api_multipart":
        return do_api_multipart_request(
            sub,
            prompt,
            site=site,
            component=component,
            timeout=timeout,
            test_case=test_case,
            suite_path=suite_path,
        )

    try:
        url = resolve_api_url(sub, site=site, component=component)
    except ValueError as exc:
        return 0, None, str(exc), {}

    method = (sub.get("api_method") or "POST").upper()
    headers = {"Accept": "application/json", **dict(sub.get("api_headers") or {})}
    headers.update(auth_headers_for_site(site, component=component, url=url))

    body_obj = build_api_request_body(
        sub,
        prompt,
        conversation_history=conversation_history,
    )
    data: bytes | None = None
    if method in {"POST", "PUT", "PATCH"}:
        if "Content-Type" not in headers and "content-type" not in headers:
            headers["Content-Type"] = "application/json"
        data = json.dumps(body_obj).encode("utf-8")

    status, raw = _http_request_with_retry(
        url, method=method, headers=headers, data=data, timeout=timeout
    )
    base_meta = _api_submission_meta(test_case)
    path = sub.get("api_response_path") or "response"
    text, err, meta = _finalize_api_parse(status, raw, path, base_meta)
    return status, text, err, meta


def do_api_document_request(
    sub: dict[str, Any],
    prompt: str,
    *,
    site: str | None = None,
    component: str | None = None,
    timeout: float = 120.0,
    test_case: dict | None = None,
    suite_path: Path | str | None = None,
) -> tuple[int, str | None, str | None, dict]:
    """Upload artifact then chat with document_id (DVAIA pattern)."""
    if not test_case:
        return 0, None, "api_document requires multimodal test case with payload", {}
    try:
        from browser_bot.artifacts import resolve_test_artifact

        artifact_path, _, upload_ok = resolve_test_artifact(test_case, suite_path=suite_path)
    except Exception as exc:
        return 0, None, str(exc), {}
    if not upload_ok or not artifact_path or not artifact_path.is_file():
        return 0, None, "failed to resolve upload artifact", {}

    doc_id, err = _upload_document(sub, artifact_path, site=site, component=component, timeout=timeout)
    if err or not doc_id:
        return 0, None, err or "upload failed", {}

    url = sub["api_url"]
    method = (sub.get("api_method") or "POST").upper()
    headers = {"Accept": "application/json", **dict(sub.get("api_headers") or {})}
    headers.update(auth_headers_for_site(site, component=component))
    body_obj = apply_prompt_template(
        sub.get("api_body") or {"prompt": "{{prompt}}", "document_id": "{{document_id}}"},
        prompt,
        extra={"document_id": doc_id},
    )
    data = json.dumps(body_obj).encode("utf-8")
    if "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"
    status, raw = _http_request_with_retry(
        url, method=method, headers=headers, data=data, timeout=timeout
    )
    base_meta = _api_submission_meta(test_case)
    path = sub.get("api_response_path") or "response"
    text, err, meta = _finalize_api_parse(status, raw, path, base_meta)
    return status, text, err, meta


def do_api_multipart_request(
    sub: dict[str, Any],
    prompt: str,
    *,
    site: str | None = None,
    component: str | None = None,
    timeout: float = 120.0,
    test_case: dict | None = None,
    suite_path: Path | str | None = None,
) -> tuple[int, str | None, str | None, dict]:
    """Single multipart POST with file + prompt fields."""
    url = sub.get("api_url") or sub.get("upload_url")
    if not url:
        return 0, None, "api_url not configured", {}
    prompt_field = sub.get("multipart_prompt_field", "prompt")
    file_field = sub.get("multipart_file_field", "file")
    fields = {prompt_field: prompt}
    extra_fields = sub.get("multipart_fields") or {}
    if isinstance(extra_fields, dict):
        for k, v in extra_fields.items():
            fields[str(k)] = apply_prompt_template(str(v), prompt) if isinstance(v, str) else str(v)

    files: dict[str, tuple[str, bytes, str]] = {}
    if test_case:
        try:
            from browser_bot.artifacts import resolve_test_artifact

            artifact_path, _, upload_ok = resolve_test_artifact(test_case, suite_path=suite_path)
            if upload_ok and artifact_path and artifact_path.is_file():
                content = artifact_path.read_bytes()
                mime, _ = mimetypes.guess_type(artifact_path.name)
                files[file_field] = (artifact_path.name, content, mime or "application/octet-stream")
        except Exception:
            pass

    body, ctype = _encode_multipart(fields, files)
    headers = dict(sub.get("api_headers") or {})
    headers.update(auth_headers_for_site(site, component=component))
    headers["Content-Type"] = ctype
    status, raw = _http_request_with_retry(
        url, method="POST", headers=headers, data=body, timeout=timeout
    )
    base_meta = _api_submission_meta(test_case)
    path = sub.get("api_response_path") or "response"
    text, err, meta = _finalize_api_parse(status, raw, path, base_meta)
    return status, text, err, meta


def _parse_response_text(raw: str, response_path: str) -> str | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    extracted = extract_json_path(parsed, response_path)
    if extracted is None:
        return None
    if isinstance(extracted, str):
        return extracted.strip() or None
    return json.dumps(extracted, ensure_ascii=False)
