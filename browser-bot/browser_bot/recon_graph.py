"""LangGraph agent for recon: parallel probe experts → grounding judge."""

from __future__ import annotations

import json
import logging
import operator
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Dict, List, TypedDict

_root = Path(__file__).resolve().parents[2]
try:
    from dotenv import load_dotenv

    load_dotenv(_root / ".config")
    load_dotenv(_root / ".env")
    load_dotenv()
except ImportError:
    pass

if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from langgraph.graph import END, START, StateGraph

from pipeline.llm import complete

from browser_bot.recon import (
    _RECON_SCHEMA,
    _append_browser_probe_context,
    _confirmation_status,
    _parse_json_response,
    _sanitize_submission_for_llm,
)

logger = logging.getLogger(__name__)

_EXPERT_PARTIAL_SCHEMA = """{
  "expert_id": "<headless|headed|api>",
  "confidence": "<high|medium|low>",
  "partial_recon": {
    "product_name": "...",
    "vendor": "...",
    "description": "...",
    "provider": "...",
    "model_hints": [],
    "inference_type": "...",
    "capabilities": [],
    "tools": [{"name": "...", "type": "...", "description": "...", "evidence": "..."}],
    "integrations": [],
    "api_endpoints": [],
    "auth_mechanisms": [],
    "tech_stack": [],
    "ui_features": [],
    "security_observations": [],
    "attack_surface_notes": [],
    "evidence": [{"kind": "...", "source": "...", "excerpt": "..."}]
  },
  "limitations": "<what this probe could NOT confirm>"
}"""

_JUDGE_OUTPUT_SCHEMA = """{
  "grounding_passed": true,
  "grounding_issues": ["<issue if any claim lacks probe evidence>"],
  "judge_reasoning": "<2-4 sentences on merge decisions>",
  "final_recon": <full recon.json object matching recon schema>
}"""


class ReconGraphState(TypedDict):
    signals: dict
    expert_responses: Annotated[List[Dict], operator.add]
    judge_reasoning: str
    grounding_passed: bool
    grounding_issues: List[str]
    final_recon: dict
    retry_count: int


def _invoke_llm(system_prompt: str, human_content: str, *, json_mode: bool = False) -> str:
    """Recon experts (free-text) and the grounding judge (JSON) via the shared layer.

    json_mode selects the grounding_judge role (JSON output); otherwise the recon
    operator role is used for probe experts.
    """
    if json_mode:
        return complete(
            "grounding_judge",
            system=system_prompt,
            user=human_content,
            json_mode=True,
            max_output_tokens=8192,
        ).text
    return complete(
        "recon",
        system=system_prompt,
        user=human_content,
        json_mode=True,
    ).text


def _probe_context_parts(signals: dict, probe_key: str, *, label: str) -> list[str]:
    parts = [f"=== {label} ==="]
    if probe_key == "api":
        for probe in (signals.get("api") or {}).get("probes") or []:
            parts.append(
                f"API probe [{probe.get('label')}]: status={probe.get('status')} "
                f"response={probe.get('response') or probe.get('error') or ''}"[:4000]
            )
        return parts
    probe = signals.get(probe_key) or {}
    _append_browser_probe_context(parts, probe, label=label)
    return parts


def _shared_signal_context(signals: dict) -> str:
    lines = [
        f"Site: {signals.get('site')}",
        f"Component: {signals.get('component')}",
        f"Source mode: {signals.get('mode')}",
        f"Target URL: {signals.get('target_url')}",
        f"Transport: {signals.get('transport')}",
        f"Config summary: {json.dumps(signals.get('config_summary') or {}, indent=2)[:6000]}",
        f"Auth summary: {json.dumps(signals.get('auth_summary') or {}, indent=2)}",
    ]
    return "\n".join(lines)


def make_expert_node(expert_id: str, probe_key: str, *, priority: str):
    """Factory: one expert interprets a single probe bundle into partial_recon."""

    def expert_node(state: ReconGraphState) -> Dict:
        signals = state["signals"]
        context = [_shared_signal_context(signals)]
        if probe_key == "api":
            context.extend(_probe_context_parts(signals, "api", label="API probes"))
            role = (
                "You analyze API probe responses (hello + capabilities + verify_tools). "
                "Infer provider, model, tools, and capabilities ONLY from response text and config. "
                "CRITICAL for API transport: do NOT record code execution, file upload, web browse, "
                "or tools from platform marketing or hedged language "
                "('some interfaces', 'when enabled', 'often', 'frequently', 'in many chat interfaces', "
                "'depending on platform'). Only list those surfaces when the model clearly affirms "
                "they work in THIS API conversation (unhedged YES on verify_tools, or an explicit "
                "this-request tool inventory) OR config transport is api_document/api_multipart "
                "(file upload only). Text chat alone is capabilities=['text-generation'] with tools=[]."
            )
        elif probe_key == "browser":
            context.extend(_probe_context_parts(signals, "browser", label="Phase 1 headless probe"))
            role = (
                "You analyze the headless browser probe. This pass may hit bot challenges (Cloudflare). "
                "Use low confidence when the page is a challenge interstitial. Do not invent models or API URLs."
            )
        else:
            context.extend(
                _probe_context_parts(
                    signals,
                    "browser_confirmation",
                    label="Phase 2 headed authenticated confirmation (PRIMARY when present)",
                )
            )
            role = (
                "You analyze the headed authenticated browser confirmation. "
                "This is the PRIMARY probe when it reached the real app UI. "
                "Only list api_endpoints present in network_urls from this probe. "
                "UI capability_probe response (model self-report) is high-value evidence for tools and capabilities."
            )

        system_prompt = f"""You are a recon expert ({expert_id}, priority={priority}) for AI bug bounty hunting.
{role}

Return JSON matching this schema:
{_EXPERT_PARTIAL_SCHEMA}

Rules:
- Set expert_id to "{expert_id}".
- confidence=high only when probe data directly supports claims.
- Every tool must include evidence citing probe data (html, ui_hint, network, api_response, config).
- Do not list Cloudflare as an integration.
- Return ONLY valid JSON."""

        human_content = "\n".join(context)
        try:
            raw = _invoke_llm(system_prompt, human_content, json_mode=False)
            payload = _parse_json_response(raw)
        except Exception as exc:
            logger.warning("Recon expert %s failed: %s", expert_id, exc)
            payload = {
                "expert_id": expert_id,
                "confidence": "low",
                "partial_recon": {},
                "limitations": str(exc),
            }

        payload.setdefault("expert_id", expert_id)
        payload.setdefault("priority", priority)
        return {"expert_responses": [payload]}

    return expert_node


def judge_node(state: ReconGraphState) -> Dict:
    signals = state["signals"]
    retry_count = int(state.get("retry_count") or 0)
    prior_issues = state.get("grounding_issues") or []

    network_urls: list[str] = []
    for key in ("browser_confirmation", "browser"):
        probe = signals.get(key) or {}
        network_urls.extend(probe.get("network_urls") or [])
    api_responses = [
        (p.get("response") or "")[:500]
        for p in (signals.get("api") or {}).get("probes") or []
    ]

    system_prompt = f"""You are the recon judge for an AI bug bounty tool.
Merge expert partial recon reports into one final recon.json and audit grounding against RAW probe data.

Final recon must match this schema:
{_RECON_SCHEMA}

Your response must match:
{_JUDGE_OUTPUT_SCHEMA}

Grounding rules (grounding_passed=false if violated):
- api_endpoints must appear in observed network_urls or API probe responses (provided below).
- model_hints, tools, capabilities from headed expert (priority=primary) beat headless when they conflict.
- Reject claims supported only by generic product knowledge when probes show Cloudflare/challenge pages.
- Cloudflare is security_observations, NOT integrations.
- Every tool in final_recon must have evidence traceable to probe excerpts.
- UI capability_probe response (when present) is authoritative for self-reported tools/capabilities on UI transport.
- API transport: reject hedged/platform capability claims. code execution / file upload / web browse / tools
  require unhedged THIS-API affirmation (verify_tools YES, or explicit this-request inventory).
  Plain `api` transport does not imply file upload; only api_document/api_multipart config does.
  Prefer capabilities=["text-generation"] and tools=[] when verify_tools answers NO or hedges.
- confirmation_status: success | partial | failed (UI: headed probe; API: endpoint answered).
- probed_at: current UTC ISO8601.
- source_mode: "{signals.get('mode', 'connected')}"
- target_url: "{signals.get('target_url', '')}"
- transport: "{signals.get('transport', 'unknown')}"

On retry, fix grounding_issues from the prior attempt."""

    human_content = json.dumps(
        {
            "shared_context": _shared_signal_context(signals),
            "observed_network_urls": sorted(set(network_urls))[:60],
            "api_response_excerpts": api_responses,
            "config_submission": signals.get("config_summary", {}).get("submission"),
            "expert_responses": state.get("expert_responses") or [],
            "prior_grounding_issues": prior_issues,
            "retry_count": retry_count,
        },
        indent=2,
    )[:120000]

    try:
        raw = _invoke_llm(system_prompt, human_content, json_mode=True)
        payload = _parse_json_response(raw)
    except Exception as exc:
        logger.warning("Recon judge failed: %s", exc)
        return {
            "judge_reasoning": str(exc),
            "grounding_passed": False,
            "grounding_issues": [str(exc)],
            "final_recon": {},
            "retry_count": retry_count + 1,
        }

    final_recon = payload.get("final_recon") if isinstance(payload.get("final_recon"), dict) else {}
    issues = [str(x) for x in (payload.get("grounding_issues") or []) if x]
    passed = bool(payload.get("grounding_passed"))
    reasoning = str(payload.get("judge_reasoning") or "")

    if isinstance(final_recon, dict) and final_recon:
        final_recon["probed_at"] = datetime.now(timezone.utc).isoformat()
        final_recon.setdefault("source_mode", signals.get("mode", "connected"))
        final_recon.setdefault("target_url", signals.get("target_url", ""))
        final_recon.setdefault("transport", signals.get("transport", "unknown"))
        final_recon["confirmation_status"] = _confirmation_status(signals)
        final_recon["grounding_passed"] = passed
        if reasoning:
            final_recon["judge_reasoning"] = reasoning
        if issues:
            final_recon["grounding_issues"] = issues

    out: Dict[str, Any] = {
        "judge_reasoning": reasoning,
        "grounding_passed": passed,
        "grounding_issues": issues,
        "final_recon": final_recon,
        "retry_count": retry_count + 1,
    }
    return out


def _route_after_judge(state: ReconGraphState) -> str:
    if state.get("grounding_passed"):
        return "done"
    if int(state.get("retry_count") or 0) >= 2:
        return "done"
    return "retry"


def build_recon_graph(signals: dict):
    """Build expert→judge graph based on probe mode (UI vs API)."""
    graph = StateGraph(ReconGraphState)
    graph.add_node("judge", judge_node)

    if signals.get("api"):
        graph.add_node("expert_api", make_expert_node("api", "api", priority="primary"))
        graph.add_edge(START, "expert_api")
        graph.add_edge("expert_api", "judge")
    else:
        graph.add_node(
            "expert_headless",
            make_expert_node("headless", "browser", priority="secondary"),
        )
        graph.add_node(
            "expert_headed",
            make_expert_node("headed", "browser_confirmation", priority="primary"),
        )
        graph.add_edge(START, "expert_headless")
        graph.add_edge(START, "expert_headed")
        graph.add_edge("expert_headless", "judge")
        graph.add_edge("expert_headed", "judge")

    graph.add_conditional_edges("judge", _route_after_judge, {"done": END, "retry": "judge"})
    return graph.compile()


def run_recon_agent(signals: dict[str, Any]) -> dict:
    """Run LangGraph recon pipeline; returns final recon dict or {}."""
    from browser_bot.recon_filter import apply_deterministic_grounding

    print("  Running recon agent (experts → grounding judge)...", flush=True)
    print("[recon] LLM experts starting: page, capability, and network evidence review...", flush=True)
    app = build_recon_graph(signals)
    initial: ReconGraphState = {
        "signals": signals,
        "expert_responses": [],
        "judge_reasoning": "",
        "grounding_passed": False,
        "grounding_issues": [],
        "final_recon": {},
        "retry_count": 0,
    }
    result = app.invoke(initial)
    print("[recon] LLM experts and grounding judge completed.", flush=True)
    final = result.get("final_recon") or {}
    if isinstance(final, dict) and final:
        final, filter_issues = apply_deterministic_grounding(final, signals)
        if filter_issues:
            print(f"  Deterministic filter removed {len(filter_issues)} ungrounded item(s)", flush=True)
            for issue in filter_issues[:5]:
                print(f"    [filter] {issue}", flush=True)
        conf = signals.get("browser_confirmation") or {}
        cap = conf.get("capability_probe") or {}
        if cap.get("response_text"):
            final["ui_capability_response"] = str(cap["response_text"])[:4000]
        if conf.get("har_path"):
            final["har_path"] = conf["har_path"]
        site = signals.get("site") or ""
        component = signals.get("component") or ""
        if site and component:
            from browser_bot.sites import get_recon_network_log_path

            net_path = get_recon_network_log_path(site, component)
            if net_path.is_file():
                final["network_log_path"] = str(net_path)
    passed = result.get("grounding_passed")
    if isinstance(final, dict):
        passed = final.get("grounding_passed", passed)
    retries = result.get("retry_count") or 0
    print(f"  Judge: grounding_passed={passed}, retries={retries}", flush=True)
    if isinstance(final, dict) and final.get("grounding_issues"):
        for issue in final["grounding_issues"][:5]:
            print(f"    [!] {issue}", flush=True)
    if result.get("judge_reasoning"):
        print(f"  Judge reasoning: {result['judge_reasoning'][:300]}", flush=True)
    har = (signals.get("browser_confirmation") or {}).get("har_path")
    if har:
        print(f"  HAR artifact: {har}", flush=True)
    return final if isinstance(final, dict) else {}
