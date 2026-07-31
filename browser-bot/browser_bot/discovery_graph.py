"""LangGraph agents for manual discovery v2: step experts → wide-context experts → judge."""

from __future__ import annotations

import json
import logging
import operator
import re
import sys
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

logger = logging.getLogger(__name__)


# Discovery judge context caps. The wide composer HTML dominates the payload sent
# to the judge on every attempt (× retries), so keep it bounded. Cleaned composer
# HTML is normally well under these ceilings; lowering them mainly trims the
# worst-case cost/latency on very large pages.
_JUDGE_WIDE_HTML_CHARS = 60000
_JUDGE_CONTEXT_CHARS = 72000

_EXPERT_OUTPUT_SCHEMA = """{
  "expert_id": "<prompt_input|submit|response|file_input|dropdown|upload_prep|surface_prep>",
  "confidence": "<high|medium|low>",
  "selector": "css-selector",
  "type": "text|textarea|contenteditable|select|combobox|click|file|optional",
  "reasoning": "<1-2 sentences citing HTML evidence>",
  "limitations": "<what could not be confirmed>"
}"""

_JUDGE_OUTPUT_SCHEMA = """{
  "grounding_passed": true,
  "grounding_issues": ["<issue if selector wrong type or not in HTML>"],
  "judge_reasoning": "<2-4 sentences on merge and fixes>",
  "final_submission": {
    "inputs": [
      {"selector": "css-selector", "type": "text|textarea|contenteditable|select|combobox|click|file", "upload_prep": true, "path_from": "payload when type is file"}
    ],
    "submit_selector": "css-selector",
    "response_selector": "css-selector",
    "response_capture_mode": "last|role|parity_odd|parity_even",
    "response_list_selector": "css-selector matching all message rows when needed",
    "response_role_selector": "css-selector for assistant-only rows when mode is role"
  }
}"""

_STEP_EXPERT_RULES: dict[str, str] = {
    "prompt_input": (
        "Identify the prompt/chat TEXT INPUT only: textarea or input[type=text|search|email|password]. "
        "Use contenteditable only if no textarea/text input exists. "
        "NEVER return button, submit, or file input selectors."
    ),
    "submit": (
        "Identify the SEND/SUBMIT control only: button, input[type=submit|button], or [role=button] "
        "that submits the prompt. NEVER return textarea, text input, or response containers."
    ),
    "response": (
        "Identify the ASSISTANT RESPONSE container: div/article/section/code/pre holding model reply text. "
        "For syntax-highlighted JSON or code replies use stable selectors like code.language-json or "
        "code[class*='language-']. Prefer [data-message-author-role=assistant] only when that attribute "
        "exists in the HTML. NEVER return textarea, input, button, or form controls. "
        "When the chat shows multiple turns (user/assistant alternating), return a selector that "
        "matches EVERY message bubble of the same kind - never a unique nth-of-type path to one node."
    ),
    "file_input": (
        "Identify FILE UPLOAD: input[type=file] preferred, else upload/attach button or menuitem."
    ),
    "dropdown": (
        "Identify DROPDOWN/MODEL PICKER: select or [role=combobox] or button with aria-haspopup."
    ),
    "upload_prep": (
        "Identify MENU/ATTACHMENT trigger that reveals upload - button or menuitem, NOT the text prompt."
    ),
    "surface_prep": (
        "Identify the on-page element the operator clicked to prepare the surface: "
        "cookie/notice dismiss, tab, card/row, or Start/Begin CTA. Prefer stable "
        "role+text / :text-is selectors. NOT the chat textarea and NOT Send/Submit."
    ),
}


class DiscoveryJudgeState(TypedDict):
    page_url: str
    wide_context_html: str
    multiturn_html: bool
    step_expert_responses: List[Dict]
    expert_responses: Annotated[List[Dict], operator.add]
    draft_submission: dict
    judge_reasoning: str
    grounding_passed: bool
    grounding_issues: List[str]
    final_submission: dict
    retry_count: int


def _parse_json_response(text: str) -> dict:
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if m:
        return json.loads(m.group(1))
    m = re.search(r"\{[\s\S]*\}", text)
    return json.loads(m.group()) if m else json.loads(text)


def _invoke_llm(
    system_prompt: str,
    human_content: str,
    *,
    json_mode: bool = False,
    use_judge_model: bool = False,
) -> str:
    """Discovery step/wide experts and the grounding judge via the shared layer.

    use_judge_model selects the grounding_judge role; otherwise the discovery
    operator role is used for step and wide-context experts.
    """
    role = "grounding_judge" if use_judge_model else "discovery"
    return complete(
        role,
        system=system_prompt,
        user=human_content,
        json_mode=json_mode,
        max_output_tokens=8192,
    ).text


def _discovery_html_helpers():
    from browser_bot.record_submission import (
        _build_focused_context_for_llm,
        _clean_html_for_llm,
        _click_hint_block,
        _submission_for_llm_reconcile,
        sanitize_discovered_selector,
    )

    return (
        _build_focused_context_for_llm,
        _clean_html_for_llm,
        _click_hint_block,
        _submission_for_llm_reconcile,
        sanitize_discovered_selector,
    )


def _build_expert_human_content(
    *,
    target_kind: str,
    page_url: str,
    context_html: str,
    click_hint: dict | None,
    context_depth: int,
) -> str:
    (
        _build_focused_context_for_llm,
        _clean_html_for_llm,
        _click_hint_block,
        _,
        _,
    ) = _discovery_html_helpers()

    focused_html, candidates = _build_focused_context_for_llm(context_html, target_kind)
    candidate_block = ""
    if candidates:
        numbered = "\n".join(f"  {i + 1}. {line}" for i, line in enumerate(candidates))
        candidate_block = f"\nPre-filtered candidates:\n{numbered}\n"

    return (
        f"Page URL: {page_url}\n"
        f"Context depth: {context_depth} DOM levels up from user click\n"
        f"{_click_hint_block(click_hint or {})}\n"
        f"{candidate_block}\n"
        f"HTML fragment (filtered for {target_kind}):\n{focused_html[:80000]}"
    )


def _normalize_expert_payload(payload: dict, expert_id: str) -> dict:
    from browser_bot.record_submission import sanitize_discovered_selector

    out = dict(payload or {})
    out.setdefault("expert_id", expert_id)
    sel = sanitize_discovered_selector(str(out.get("selector") or "").strip())
    if sel:
        out["selector"] = sel
    out.setdefault("confidence", "medium")
    out.setdefault("reasoning", "")
    out.setdefault("limitations", "")
    return out


def _invoke_step_expert(
    target_kind: str,
    page_url: str,
    context_html: str,
    click_hint: dict | None,
    *,
    context_depth: int = 5,
) -> dict:
    rules = _STEP_EXPERT_RULES.get(target_kind, _STEP_EXPERT_RULES["prompt_input"])
    system_prompt = f"""You are a discovery expert ({target_kind}) for browser UI automation on AI chat apps.
{rules}

Return JSON matching:
{_EXPERT_OUTPUT_SCHEMA}

Set expert_id to "{target_kind}".
confidence=high only when HTML directly supports the selector.
If pre-filtered candidates are listed, your selector MUST be one of them.
You MUST return a non-empty selector when any candidate exists in the HTML.
Return ONLY valid JSON."""

    human_content = _build_expert_human_content(
        target_kind=target_kind,
        page_url=page_url,
        context_html=context_html,
        click_hint=click_hint,
        context_depth=context_depth,
    )
    try:
        raw = _invoke_llm(system_prompt, human_content, json_mode=True, use_judge_model=False)
        payload = _normalize_expert_payload(_parse_json_response(raw), target_kind)
    except Exception as exc:
        logger.warning("Discovery expert %s failed: %s", target_kind, exc)
        payload = {
            "expert_id": target_kind,
            "confidence": "low",
            "selector": "",
            "reasoning": "",
            "limitations": str(exc),
        }

    if not (payload.get("selector") or "").strip():
        from browser_bot.record_submission import deterministic_selector_from_context

        fallback = deterministic_selector_from_context(context_html, target_kind, click_hint)
        if fallback.get("selector"):
            print(f"    expert {target_kind}: LLM empty - deterministic fallback {fallback['selector']}")
            payload = {**payload, **fallback}
    return payload


def run_discovery_expert(
    target_kind: str,
    context_html: str,
    page_url: str,
    click_hint: dict | None = None,
) -> dict:
    """Run a single step expert (3-level click context) and return its proposal.

    This is a single LLM call, so it invokes the expert directly rather than
    wrapping it in a one-node LangGraph (the graph added no orchestration value).
    """
    print(f"  Discovery expert ({target_kind})…")
    expert = _invoke_step_expert(
        target_kind,
        page_url,
        context_html,
        click_hint or {},
    ) or {}
    sel = expert.get("selector") or ""
    if sel:
        print(f"    expert {target_kind}: {sel} (confidence={expert.get('confidence', '?')})")
    else:
        print(f"    expert {target_kind}: no selector ({expert.get('limitations') or 'unknown'})")
    return expert


def make_wide_expert_node(target_kind: str):
    """Factory: expert re-analyzes full composer HTML (8 levels up)."""

    def wide_expert_node(state: DiscoveryJudgeState) -> Dict:
        payload = _invoke_step_expert(
            target_kind,
            state["page_url"],
            state["wide_context_html"],
            {"pickKind": "wide_composer", "note": f"wide {target_kind} expert"},
            context_depth=8,
        )
        payload["source"] = "wide_context"
        payload["context_depth"] = 8
        return {"expert_responses": [payload]}

    wide_expert_node.__name__ = f"expert_wide_{target_kind}"
    return wide_expert_node


def judge_node(state: DiscoveryJudgeState) -> Dict:
    (
        _,
        _clean_html_for_llm,
        _,
        _submission_for_llm_reconcile,
        sanitize_discovered_selector,
    ) = _discovery_html_helpers()

    retry_count = int(state.get("retry_count") or 0)
    prior_issues = state.get("grounding_issues") or []
    draft = _submission_for_llm_reconcile(state.get("draft_submission") or {})
    wide_html = state.get("wide_context_html") or ""
    cleaned_wide = _clean_html_for_llm(wide_html)
    multiturn = bool(state.get("multiturn_html"))
    multiturn_note = (
        "The wide composer HTML was captured AFTER a second probe prompt - multiple user/assistant "
        "turns should be visible. Use repeating list selectors and response_capture_mode "
        "(role or parity_*) accordingly."
        if multiturn
        else "The wide composer HTML may contain only one turn - still avoid nth-of-type ladders for response."
    )

    system_prompt = f"""You are the discovery judge for an AI bug bounty browser automation tool.
Merge step-by-step expert proposals and wide-composer expert proposals into one final submission config.

Your response must match:
{_JUDGE_OUTPUT_SCHEMA}

Grounding rules (grounding_passed=false if violated):
- final_submission.inputs must have the SAME count and ORDER as draft_submission.inputs - only fix selectors/types.
- Text prompt field: textarea or text-like input (contenteditable only if no textarea/input in HTML).
- submit_selector: MUST be button or input[type=submit|button] - never textarea or response container.
- response_selector: MUST be assistant message container - never prompt input or submit button.
- When the UI shows multiple chat turns in one view, set response_list_selector to a repeating
  bubble/row selector (same class or [data-message-author-role]) and response_capture_mode to
  role (assistant-only), parity_odd, or parity_even - NEVER a unique nth-of-type path.
- Every selector MUST match an element in the wide composer HTML fragment below.
- Prefer step experts with confidence=high when wide experts agree; prefer wide experts when step selectors look wrong or fragile.
- NEVER use CSS-module hashed classes; use [class*='prefix'] or stable attributes.
- NEVER use data-gtm-form-interact-id or other session/ephemeral attributes - they are missing on fresh page loads.
- Prefer placeholder, name, data-testid, or aria-label for inputs.
- Keep selectors short (max 4 nesting levels).

{multiturn_note}

On retry, fix grounding_issues from the prior attempt."""

    step_experts = state.get("step_expert_responses") or []
    wide_experts = state.get("expert_responses") or []

    human_content = json.dumps(
        {
            "page_url": state.get("page_url"),
            "draft_submission": draft,
            "step_expert_responses": step_experts,
            "wide_composer_expert_responses": wide_experts,
            "prior_grounding_issues": prior_issues,
            "retry_count": retry_count,
            "multiturn_composer_html": multiturn,
            "wide_composer_html": cleaned_wide[:_JUDGE_WIDE_HTML_CHARS],
        },
        indent=2,
    )[:_JUDGE_CONTEXT_CHARS]

    try:
        raw = _invoke_llm(system_prompt, human_content, json_mode=True, use_judge_model=True)
        payload = _parse_json_response(raw)
    except Exception as exc:
        logger.warning("Discovery judge failed: %s", exc)
        return {
            "judge_reasoning": str(exc),
            "grounding_passed": False,
            "grounding_issues": [str(exc)],
            "final_submission": {},
            "retry_count": retry_count + 1,
        }

    final = payload.get("final_submission") if isinstance(payload.get("final_submission"), dict) else {}
    issues = [str(x) for x in (payload.get("grounding_issues") or []) if x]
    passed = bool(payload.get("grounding_passed"))
    reasoning = str(payload.get("judge_reasoning") or "")

    if isinstance(final, dict) and final:
        if final.get("submit_selector"):
            final["submit_selector"] = sanitize_discovered_selector(str(final["submit_selector"]))
        if final.get("response_selector"):
            final["response_selector"] = sanitize_discovered_selector(str(final["response_selector"]))
        for cap_key in ("response_list_selector", "response_role_selector"):
            if final.get(cap_key):
                final[cap_key] = sanitize_discovered_selector(str(final[cap_key]))
        if final.get("response_capture_mode"):
            final["response_capture_mode"] = str(final["response_capture_mode"]).strip().lower()
        inputs = final.get("inputs")
        if isinstance(inputs, list):
            for row in inputs:
                if isinstance(row, dict) and row.get("selector"):
                    row["selector"] = sanitize_discovered_selector(str(row["selector"]))

    return {
        "judge_reasoning": reasoning,
        "grounding_passed": passed,
        "grounding_issues": issues,
        "final_submission": final,
        "retry_count": retry_count + 1,
    }


def _route_after_judge(state: DiscoveryJudgeState) -> str:
    if state.get("grounding_passed"):
        return "done"
    if int(state.get("retry_count") or 0) >= 2:
        return "done"
    return "retry"


def build_discovery_judge_graph():
    """Wide-context parallel experts → judge (with optional retry)."""
    graph = StateGraph(DiscoveryJudgeState)
    graph.add_node("judge", judge_node)
    for kind in ("prompt_input", "submit", "response"):
        node_name = f"expert_wide_{kind}"
        graph.add_node(node_name, make_wide_expert_node(kind))
        graph.add_edge(START, node_name)
        graph.add_edge(node_name, "judge")
    graph.add_conditional_edges("judge", _route_after_judge, {"done": END, "retry": "judge"})
    return graph.compile()


def run_discovery_judge(
    wide_context_html: str,
    page_url: str,
    draft_submission: dict,
    step_expert_responses: List[Dict] | None = None,
    *,
    multiturn: bool = False,
) -> dict[str, Any]:
    """
    Run LangGraph judge pipeline: parallel wide experts + merge with step experts.
    Returns dict with final_submission, judge_reasoning, grounding_passed, etc.
    """
    if not (wide_context_html or "").strip():
        return {"final_submission": {}, "grounding_passed": False, "judge_reasoning": "No wide HTML."}

    print("  Running discovery judge (wide experts → merge judge)…")
    app = build_discovery_judge_graph()
    initial: DiscoveryJudgeState = {
        "page_url": page_url,
        "wide_context_html": wide_context_html,
        "multiturn_html": multiturn,
        "step_expert_responses": list(step_expert_responses or []),
        "expert_responses": [],
        "draft_submission": dict(draft_submission or {}),
        "judge_reasoning": "",
        "grounding_passed": False,
        "grounding_issues": [],
        "final_submission": {},
        "retry_count": 0,
    }
    result = app.invoke(initial)
    passed = result.get("grounding_passed")
    retries = result.get("retry_count") or 0
    print(f"  Judge: grounding_passed={passed}, retries={retries}")
    if result.get("judge_reasoning"):
        print(f"  Judge reasoning: {str(result['judge_reasoning'])[:300]}")
    for issue in (result.get("grounding_issues") or [])[:5]:
        print(f"    [!] {issue}")
    return result
