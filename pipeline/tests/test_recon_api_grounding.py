"""API recon must strip hedged platform capability claims."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_BB = _ROOT / "browser-bot"
if str(_BB) not in sys.path:
    sys.path.insert(0, str(_BB))

from browser_bot.recon_filter import apply_deterministic_grounding


def test_api_filter_strips_hedged_code_exec_and_upload():
    final = {
        "transport": "api",
        "capabilities": [
            "text-generation",
            "code execution",
            "file upload",
            "web-browse",
        ],
        "tools": [
            {
                "name": "Code execution",
                "type": "unknown",
                "description": "Some interfaces let me run code.",
                "evidence": "API probe [capabilities] response: Some interfaces let me run code",
            },
            {
                "name": "File upload/analysis",
                "type": "unknown",
                "description": "I can frequently read uploaded documents.",
                "evidence": "API probe [capabilities] response: I can frequently read documents",
            },
        ],
        "model_hints": ["claude-sonnet-5"],
        "api_endpoints": [],
        "integrations": [],
        "ui_capability_response": (
            "Likely available in many chat interfaces: code execution and file upload."
        ),
    }
    signals = {
        "transport": "api",
        "config_summary": {
            "submission": {
                "transport": "api",
                "api_url": "https://api.anthropic.com/v1/messages",
            }
        },
        "api": {
            "probes": [
                {
                    "label": "hello",
                    "response": "I'm a text-generation assistant (Claude).",
                },
                {
                    "label": "capabilities",
                    "response": (
                        "Some interfaces let me run code. "
                        "I can frequently read uploaded documents."
                    ),
                },
                {
                    "label": "verify_tools",
                    "response": "1) NO\n2) NO\n3) NO\n4) NO",
                },
            ]
        },
    }
    out, issues = apply_deterministic_grounding(final, signals)
    assert out["tools"] == []
    assert "code execution" not in [c.lower() for c in out["capabilities"]]
    assert "file upload" not in [c.lower() for c in out["capabilities"]]
    assert "text-generation" in out["capabilities"]
    assert out.get("ui_capability_response") == ""
    assert any("hedged" in i.lower() or "unverified" in i.lower() for i in issues)


def test_api_filter_keeps_file_upload_when_multipart_config():
    final = {
        "transport": "api_multipart",
        "capabilities": ["file upload", "text-generation"],
        "tools": [
            {
                "name": "File upload",
                "type": "builtin",
                "description": "Multipart file field in submission config.",
                "evidence": "submission config transport=api_multipart",
            }
        ],
        "model_hints": [],
        "api_endpoints": [],
        "integrations": [],
    }
    signals = {
        "transport": "api_multipart",
        "config_summary": {"submission": {"transport": "api_multipart"}},
        "api": {
            "probes": [
                {
                    "label": "capabilities",
                    "response": "submission config transport=api_multipart file upload",
                }
            ]
        },
    }
    out, _issues = apply_deterministic_grounding(final, signals)
    assert any("file" in str(c).lower() for c in out["capabilities"])
    assert out["tools"]


def test_api_filter_keeps_tool_when_verify_yes():
    final = {
        "transport": "api",
        "capabilities": ["code execution", "text-generation"],
        "tools": [
            {
                "name": "code_execution",
                "type": "builtin",
                "description": "I can execute Python in this conversation.",
                "evidence": "I can execute Python in this conversation.",
            }
        ],
        "model_hints": [],
        "api_endpoints": [],
        "integrations": [],
    }
    signals = {
        "transport": "api",
        "config_summary": {"submission": {"transport": "api"}},
        "api": {
            "probes": [
                {
                    "label": "hello",
                    "response": "Hello - text-generation ready.",
                },
                {
                    "label": "capabilities",
                    "response": "I can execute Python in this conversation.",
                },
                {
                    "label": "verify_tools",
                    "response": "1) YES\n2) NO\n3) NO\n4) YES",
                },
            ]
        },
    }
    out, _issues = apply_deterministic_grounding(final, signals)
    assert out["tools"]
    assert any("code" in str(c).lower() for c in out["capabilities"])
