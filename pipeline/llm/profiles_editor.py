"""Read/write assistant LLM profiles in ``llm.yaml`` for the Settings UI."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pipeline.llm.config import PROVIDER_KEY_ENV, _LLM_YAML, _ROOT, load_llm_yaml, reset_caches

LLM_PROVIDERS: tuple[str, ...] = tuple(PROVIDER_KEY_ENV.keys())

# Order and metadata for editable profiles (matches shipped llm.yaml).
PROFILE_META: dict[str, dict[str, str]] = {
    "offensive_generator": {
        "label": "Offensive generator",
        "description": (
            "Offensive prompt generation - most permissive model (best for unsafe "
            "behaviour / lowest refusal rate on adversarial content)."
        ),
    },
    "offensive_fast": {
        "label": "Offensive fast",
        "description": (
            "High-volume offensive rewriting/synthesis - cheaper, fast "
            "permissive model (e.g. OpenRouter Dolphin)."
        ),
    },
    "offensive_editor": {
        "label": "Offensive editor",
        "description": "Attack judge / editor - rigorous evaluation and refinement.",
    },
    "triager": {
        "label": "Triager",
        "description": "Harm / risk assessment (triage) - nuanced judgement, high volume.",
    },
    "methodologist": {
        "label": "Methodologist",
        "description": "Methodology (playbooks, enhancement theory) - deepest strategic reasoning.",
    },
    "grounder": {
        "label": "Grounder",
        "description": "Evidence grounding for recon/discovery judges.",
    },
    "operator": {
        "label": "Operator",
        "description": "Browser operators - fast, cheap, high-throughput.",
    },
}

_PROFILE_ORDER: tuple[str, ...] = tuple(PROFILE_META.keys())


def _ensure_llm_yaml() -> None:
    if _LLM_YAML.is_file():
        return
    example = _ROOT / "llm.yaml.example"
    if example.is_file():
        _LLM_YAML.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        return
    raise FileNotFoundError(f"LLM config not found: {_LLM_YAML}")


def _coerce_provider(value: Any) -> str:
    provider = str(value or "gemini").strip().lower()
    return provider if provider in LLM_PROVIDERS else "gemini"


def _normalize_provider(value: Any) -> str:
    provider = str(value or "gemini").strip().lower()
    if provider not in LLM_PROVIDERS:
        raise ValueError(
            f"Unknown provider '{provider}'. Choose one of: {', '.join(LLM_PROVIDERS)}."
        )
    return provider


def _normalize_model(value: Any) -> str:
    return str(value or "").strip()


def llm_config_payload() -> dict[str, Any]:
    """Schema + current values for the Settings → LLM Profiles tab."""
    _ensure_llm_yaml()
    cfg = load_llm_yaml(force=True)
    raw_profiles = cfg.get("profiles") if isinstance(cfg.get("profiles"), dict) else {}
    profiles: dict[str, dict[str, str]] = {}
    for name, meta in PROFILE_META.items():
        prof = raw_profiles.get(name)
        prof_dict = prof if isinstance(prof, dict) else {}
        profiles[name] = {
            "provider": _coerce_provider(prof_dict.get("provider")),
            "model": _normalize_model(prof_dict.get("model")),
            "label": meta["label"],
            "description": meta.get("description", ""),
        }
    from pipeline.llm.openrouter_models import validate_openrouter_assignments

    # Validate every OpenRouter profile in llm.yaml (including ones not in the UI).
    or_validation = validate_openrouter_assignments(
        raw_profiles if isinstance(raw_profiles, dict) else {},
        require_catalog=False,
    )
    return {
        "path": "llm.yaml",
        "providers": list(LLM_PROVIDERS),
        "profiles": profiles,
        "openrouter_validation": or_validation.as_dict(),
    }


def _profile_sort_key(name: str) -> tuple[int, str]:
    try:
        return (_PROFILE_ORDER.index(name), name)
    except ValueError:
        return (len(_PROFILE_ORDER), name)


def _render_profiles_section(profiles: dict[str, dict[str, str]]) -> str:
    lines = ["  profiles:"]
    for name in sorted(profiles, key=_profile_sort_key):
        meta = PROFILE_META.get(name, {})
        desc = meta.get("description")
        if desc:
            lines.append(f"    # {desc}")
        prof = profiles[name]
        provider = prof["provider"]
        model = prof["model"]
        lines.append(f"    {name}: {{ provider: {provider}, model: {model} }}")
    return "\n".join(lines) + "\n"


def _splice_profiles_section(text: str, profiles: dict[str, dict[str, str]]) -> str:
    profiles_match = re.search(r"^\s{2}profiles:\s*$", text, re.MULTILINE)
    roles_match = re.search(r"^\s{2}roles:\s*$", text, re.MULTILINE)
    if profiles_match and roles_match and roles_match.start() > profiles_match.start():
        before = text[: profiles_match.start()]
        after = text[roles_match.start() :]
        return before + _render_profiles_section(profiles) + after

    import yaml

    data = yaml.safe_load(text) or {}
    llm_block = data.get("llm", data)
    if not isinstance(llm_block, dict):
        llm_block = {}
    llm_block["profiles"] = {
        name: {"provider": prof["provider"], "model": prof["model"]}
        for name, prof in profiles.items()
    }
    data["llm"] = llm_block
    header_match = re.search(r"^llm:\s*$", text, re.MULTILINE)
    header = text[: header_match.start()] if header_match else ""
    body = yaml.dump({"llm": llm_block}, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return header + body


def save_llm_profiles(changes: dict[str, Any]) -> list[str]:
    """Update profile provider/model entries in ``llm.yaml``. Preserves header comments."""
    _ensure_llm_yaml()
    cfg = load_llm_yaml(force=True)
    raw_profiles = dict(cfg.get("profiles") or {}) if isinstance(cfg.get("profiles"), dict) else {}

    updated: list[str] = []
    for name, raw in (changes or {}).items():
        if name not in PROFILE_META or not isinstance(raw, dict):
            continue
        provider = _normalize_provider(raw.get("provider"))
        model = _normalize_model(raw.get("model"))
        raw_profiles[name] = {"provider": provider, "model": model}
        updated.append(name)

    if not updated:
        return []

    normalized: dict[str, dict[str, str]] = {}
    for name, prof in raw_profiles.items():
        if not isinstance(prof, dict):
            continue
        normalized[name] = {
            "provider": _normalize_provider(prof.get("provider")),
            "model": _normalize_model(prof.get("model")),
        }

    from pipeline.llm.openrouter_models import validate_openrouter_assignments

    # Fail closed on unknown/deprecated OpenRouter slugs when the catalog is reachable.
    # Catalog fetch failures are warnings only (do not block save).
    or_result = validate_openrouter_assignments(normalized, require_catalog=False)
    if or_result.errors:
        raise ValueError("; ".join(or_result.errors))
    for warning in or_result.warnings:
        print(f"[llm] {warning}", flush=True)

    text = _LLM_YAML.read_text(encoding="utf-8")
    _LLM_YAML.write_text(_splice_profiles_section(text, normalized), encoding="utf-8")
    reset_caches()
    return updated
