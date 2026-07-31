"""Deterministic post-judge grounding filters for recon.json."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

# Platform-marketing / hedged self-reports must not become confirmed API tools.
_PLATFORM_HEDGE_RE = re.compile(
    r"(?:"
    r"\bsome\s+interfaces?\b|"
    r"\bin\s+many\s+(?:chat\s+)?interfaces?\b|"
    r"\bwhen\s+(?:this\s+feature\s+is\s+)?enabled\b|"
    r"\bdepending\s+on\b|"
    r"\bcan\s+often\b|"
    r"\bi\s+can\s+frequently\b|"
    r"\bfrequently\s+read\b|"
    r"\bmay\s+(?:vary|change|be\s+available)\b|"
    r"\bon\s+some\s+(?:platforms?|products?|surfaces?)\b|"
    r"\bvar(?:y|ies)\s+by\s+(?:platform|client|product|surface)\b|"
    r"\bgeneral\s+guide\b|"
    r"\bnot\s+a\s+guaranteed\b|"
    r"\bplatform\s+support\b|"
    r"\bother\s+(?:interfaces?|products?|surfaces?)\b"
    r")",
    re.IGNORECASE,
)

_API_SURFACE_CAPABILITY_RE = re.compile(
    r"(?:"
    r"code[\s_-]*exec|"
    r"file[\s_-]*upload|"
    r"file[\s_-]*analy|"
    r"web[\s_-]*browse|"
    r"web[\s_-]*search|"
    r"browsing|"
    r"\btool(?:s| use|_use)?\b|"
    r"function[\s_-]*call|"
    r"interpreter|"
    r"sandbox|"
    r"multipart|"
    r"attachment"
    r")",
    re.IGNORECASE,
)

_API_TRANSPORTS = frozenset({"api", "api_document", "api_multipart"})


def _norm_url(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    if not u:
        return ""
    try:
        p = urlparse(u)
        if p.scheme and p.netloc:
            return f"{p.scheme}://{p.netloc}{p.path}".rstrip("/").lower()
    except Exception:
        pass
    return u.lower().rstrip("/")


def _collect_network_urls(signals: dict[str, Any]) -> set[str]:
    urls: set[str] = set()
    for key in ("browser", "browser_confirmation"):
        probe = signals.get(key) or {}
        for raw in probe.get("network_urls") or []:
            n = _norm_url(str(raw))
            if n:
                urls.add(n)
        for entry in probe.get("network_log") or []:
            n = _norm_url(str(entry.get("url") or ""))
            if n:
                urls.add(n)
    for probe in (signals.get("api") or {}).get("probes") or []:
        resp = str(probe.get("response") or "")
        for m in re.finditer(r"https?://[^\s\"'<>]+", resp):
            n = _norm_url(m.group(0))
            if n:
                urls.add(n)
    return urls


def _build_evidence_corpus(signals: dict[str, Any]) -> str:
    parts: list[str] = []
    sub = (signals.get("config_summary") or {}).get("submission") or {}
    parts.append(str(sub))

    for key in ("browser", "browser_confirmation"):
        probe = signals.get(key) or {}
        parts.append(str(probe.get("html_excerpt") or ""))
        parts.append(str(probe.get("ui_hints") or ""))
        cap = probe.get("capability_probe") or {}
        parts.append(str(cap.get("response_text") or ""))
        parts.append(str(cap.get("full_content") or ""))
        for entry in probe.get("network_log") or []:
            parts.append(str(entry.get("url") or ""))

    for probe in (signals.get("api") or {}).get("probes") or []:
        parts.append(str(probe.get("response") or ""))

    return "\n".join(parts).lower()


def _endpoint_grounded(endpoint: str, network_urls: set[str]) -> bool:
    ep = _norm_url(endpoint)
    if not ep:
        return False
    if ep in network_urls:
        return True
    ep_path = urlparse(ep).path if "://" in ep else ep
    for nu in network_urls:
        if ep in nu or nu in ep:
            return True
        nu_path = urlparse(nu).path if "://" in nu else nu
        if ep_path and nu_path and ep_path == nu_path:
            return True
        if ep_path and ep_path in nu:
            return True
    return False


def _hint_grounded(hint: str, corpus: str, network_urls: set[str]) -> bool:
    h = (hint or "").strip().lower()
    if not h or len(h) < 2:
        return False
    if h in corpus:
        return True
    for nu in network_urls:
        if h in nu:
            return True
    tokens = [t for t in re.split(r"[\s/._-]+", h) if len(t) >= 4]
    return any(t in corpus for t in tokens)


def _tool_evidence_grounded(tool: dict, corpus: str, network_urls: set[str]) -> bool:
    evidence = str(tool.get("evidence") or "").lower()
    if not evidence or len(evidence) < 8:
        return False
    if evidence in corpus or any(evidence in c for c in (corpus[:50000],)):
        return True
    if any(frag in corpus for frag in evidence.split() if len(frag) >= 6):
        return True
    name = str(tool.get("name") or "").lower()
    if name and name in corpus:
        return True
    for nu in network_urls:
        if name and name.replace(" ", "") in nu.replace("-", ""):
            return True
    config_markers = ("selector", "config", "#", "data-testid", "submission")
    if any(m in evidence for m in config_markers) and any(m in corpus for m in config_markers):
        return True
    return False


def _tool_blob(tool: dict[str, Any]) -> str:
    return " ".join(
        str(tool.get(k) or "")
        for k in ("name", "type", "description", "evidence")
    ).lower()


def _is_platform_hedge_text(text: str) -> bool:
    return bool(_PLATFORM_HEDGE_RE.search(text or ""))


def _is_api_surface_claim(text: str) -> bool:
    return bool(_API_SURFACE_CAPABILITY_RE.search(text or ""))


def _config_supports_file_upload(signals: dict[str, Any]) -> bool:
    sub = (signals.get("config_summary") or {}).get("submission") or {}
    transport = str(sub.get("transport") or signals.get("transport") or "").lower()
    if transport in ("api_document", "api_multipart"):
        return True
    inputs = sub.get("inputs")
    if isinstance(inputs, list):
        for inp in inputs:
            if not isinstance(inp, dict):
                continue
            if inp.get("type") == "file" or inp.get("path_from") == "payload":
                return True
    return False


def _verify_tools_probe_text(signals: dict[str, Any]) -> str:
    for probe in (signals.get("api") or {}).get("probes") or []:
        if str(probe.get("label") or "").lower() == "verify_tools":
            return str(probe.get("response") or "")
    return ""


def _verify_tools_affirms_surface(verify_text: str, surface: str) -> bool:
    """True when verify_tools gives an unhedged YES for a surface question."""
    text = (verify_text or "").strip()
    if not text or _is_platform_hedge_text(text.lower()):
        return False
    low = text.lower()
    # Map surfaces to question numbers in _API_TOOL_VERIFY_PROBE.
    idx = {
        "code_execution": 1,
        "file_upload": 2,
        "web_browse": 3,
        "tool_use": 4,
    }.get(surface)
    if not idx:
        return False
    # Match "1) YES", "1. Yes", "1: yes", etc.
    pattern = re.compile(
        rf"(?:^|\n)\s*{idx}\s*[\)\]\.:\-]\s*(yes)\b",
        re.IGNORECASE,
    )
    if pattern.search(text):
        return True
    # Compact answers like "1) NO 2) NO 3) NO 4) NO" already handled; also
    # accept a lone YES only when the whole reply is short and clearly yes.
    if surface == "tool_use" and re.fullmatch(r"\s*yes[.!]?\s*", low):
        return True
    return False


def _surface_for_claim(text: str) -> str | None:
    low = (text or "").lower()
    if re.search(r"code[\s_-]*exec|interpreter|sandbox", low):
        return "code_execution"
    if re.search(r"file[\s_-]*upload|file[\s_-]*analy|multipart|attachment", low):
        return "file_upload"
    if re.search(r"web[\s_-]*browse|web[\s_-]*search|\bbrowsing\b", low):
        return "web_browse"
    if re.search(r"\btool|function[\s_-]*call", low):
        return "tool_use"
    return None


def _strip_api_platform_capability_claims(
    out: dict[str, Any],
    signals: dict[str, Any],
    issues: list[str],
) -> None:
    """Drop hedged / unverified surface tools+capabilities on API transport."""
    transport = str(out.get("transport") or signals.get("transport") or "").lower()
    if transport not in _API_TRANSPORTS:
        return

    verify_text = _verify_tools_probe_text(signals)
    upload_ok = _config_supports_file_upload(signals)

    kept_tools: list[Any] = []
    for tool in out.get("tools") or []:
        if not isinstance(tool, dict):
            issues.append(f"Removed non-object tool on API recon: {tool}")
            continue
        blob = _tool_blob(tool)
        surface = _surface_for_claim(blob)
        if surface is None and not _is_api_surface_claim(blob):
            kept_tools.append(tool)
            continue
        surface = surface or "tool_use"
        if surface == "file_upload" and upload_ok:
            kept_tools.append(tool)
            continue
        if _is_platform_hedge_text(blob):
            issues.append(
                f"Removed hedged API platform tool claim: {tool.get('name') or surface}"
            )
            continue
        if _verify_tools_affirms_surface(verify_text, surface):
            kept_tools.append(tool)
            continue
        # Unhedged but unverified API self-report - still not enough for plain API.
        issues.append(
            f"Removed unverified API tool claim (need verify_tools YES or config): "
            f"{tool.get('name') or surface}"
        )
    out["tools"] = kept_tools

    kept_caps: list[str] = []
    for cap in out.get("capabilities") or []:
        cap_s = str(cap).strip()
        surface = _surface_for_claim(cap_s)
        if surface is None:
            kept_caps.append(cap_s)
            continue
        if surface == "file_upload" and upload_ok:
            kept_caps.append(cap_s)
            continue
        # Capability list entries rarely carry hedge text; require verify YES
        # or a tool that survived the API surface filter above.
        if _verify_tools_affirms_surface(verify_text, surface):
            kept_caps.append(cap_s)
            continue
        if any(
            _surface_for_claim(_tool_blob(t)) == surface
            for t in kept_tools
            if isinstance(t, dict)
        ):
            kept_caps.append(cap_s)
            continue
        issues.append(f"Removed unverified API capability claim: {cap_s}")

    # Generic hint-grounding may have dropped synonym labels (e.g. "code execution"
    # vs probe text "execute Python"). Re-sync labels from tools / verify_tools YES.
    surface_labels = {
        "code_execution": "code execution",
        "file_upload": "file upload",
        "web_browse": "web browse",
        "tool_use": "tool use",
    }
    have = {
        str(c).strip().lower().replace("-", "_").replace(" ", "_")
        for c in kept_caps
        if str(c).strip()
    }

    def _ensure_surface(surface: str) -> None:
        key = surface.replace(" ", "_")
        if key in have:
            return
        kept_caps.append(surface_labels.get(surface, surface.replace("_", " ")))
        have.add(key)

    for tool in kept_tools:
        if isinstance(tool, dict):
            surface = _surface_for_claim(_tool_blob(tool))
            if surface:
                _ensure_surface(surface)
    for surface in surface_labels:
        if surface == "file_upload" and upload_ok:
            _ensure_surface(surface)
            continue
        if _verify_tools_affirms_surface(verify_text, surface):
            _ensure_surface(surface)

    out["capabilities"] = kept_caps

    # Avoid leaving API self-report text in the UI-only field.
    ui_cap = str(out.get("ui_capability_response") or "")
    if ui_cap and _is_platform_hedge_text(ui_cap.lower()):
        out["ui_capability_response"] = ""
        issues.append("Cleared hedged API self-report from ui_capability_response")


def apply_deterministic_grounding(
    final_recon: dict[str, Any],
    signals: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Strip fields not supported by probe evidence. Returns (recon, filter_issues)."""
    if not isinstance(final_recon, dict):
        return {}, ["invalid final_recon"]

    out = dict(final_recon)
    issues: list[str] = []
    network_urls = _collect_network_urls(signals)
    corpus = _build_evidence_corpus(signals)

    kept_eps: list[str] = []
    for ep in out.get("api_endpoints") or []:
        ep_s = str(ep).strip()
        if _endpoint_grounded(ep_s, network_urls):
            kept_eps.append(ep_s)
        else:
            issues.append(f"Removed ungrounded api_endpoint: {ep_s}")
    out["api_endpoints"] = kept_eps

    kept_hints: list[str] = []
    for hint in out.get("model_hints") or []:
        hint_s = str(hint).strip()
        if _hint_grounded(hint_s, corpus, network_urls):
            kept_hints.append(hint_s)
        else:
            issues.append(f"Removed ungrounded model_hint: {hint_s}")
    out["model_hints"] = kept_hints

    kept_tools: list[dict] = []
    for tool in out.get("tools") or []:
        if isinstance(tool, dict) and _tool_evidence_grounded(tool, corpus, network_urls):
            kept_tools.append(tool)
        else:
            name = tool.get("name") if isinstance(tool, dict) else str(tool)
            issues.append(f"Removed ungrounded tool: {name}")
    out["tools"] = kept_tools

    kept_caps: list[str] = []
    for cap in out.get("capabilities") or []:
        cap_s = str(cap).strip()
        if _hint_grounded(cap_s, corpus, network_urls):
            kept_caps.append(cap_s)
        else:
            issues.append(f"Removed ungrounded capability: {cap_s}")
    out["capabilities"] = kept_caps

    integrations = out.get("integrations") or []
    cleaned_integrations = []
    for item in integrations:
        s = str(item).strip()
        low = s.lower()
        if low in ("cloudflare", "cloudflare turnstile", "turnstile"):
            issues.append(f"Removed infrastructure label from integrations: {s}")
            continue
        if low in corpus or any(low in nu for nu in network_urls):
            cleaned_integrations.append(s)
        else:
            issues.append(f"Removed ungrounded integration: {s}")
    out["integrations"] = cleaned_integrations

    _strip_api_platform_capability_claims(out, signals, issues)

    if issues:
        existing = [str(x) for x in (out.get("grounding_issues") or []) if x]
        out["grounding_issues"] = existing + issues
        out["grounding_passed"] = False

    return out, issues
