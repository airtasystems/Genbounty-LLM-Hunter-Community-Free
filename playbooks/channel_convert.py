"""Convert artifact-channel playbook categories to text for text-only CTF harnesses."""
from __future__ import annotations

import copy
import re
from typing import Any

from playbooks.registry import get_category_channel

_UPLOAD_RE = re.compile(
    r"\b(upload(?:ed)?|attach(?:ed|ment)?|file upload|OCR|image file|PDF file)\b",
    re.IGNORECASE,
)


def _rewrite_upload_phrases(text: str) -> str:
    if not text:
        return text
    out = _UPLOAD_RE.sub("submit inline in chat", text)
    out = out.replace("text_file", "text_direct")
    return out


def convert_category_to_text(category: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Return a copy of one category converted to text channel, plus change notes."""
    cat = copy.deepcopy(category)
    changes: list[str] = []
    cid = str(cat.get("id") or cat.get("name") or "?")

    if get_category_channel(cat) != "artifact":
        return cat, changes

    cat["channel"] = "text"
    changes.append(f"{cid}: channel artifact → text")

    old_methods = list(cat.get("delivery_methods") or [])
    cat["delivery_methods"] = ["text_direct"]
    if old_methods != ["text_direct"]:
        changes.append(f"{cid}: delivery_methods → text_direct")

    if cat.get("category_vectors") != []:
        cat["category_vectors"] = []
        changes.append(f"{cid}: category_vectors cleared")

    name = str(cat.get("name", ""))
    if "artifact" in name.lower():
        cat["name"] = re.sub(r"\bartifact\b", "Text Submission", name, flags=re.IGNORECASE)
        changes.append(f"{cid}: renamed category")

    for field in ("focus", "description"):
        val = str(cat.get(field, ""))
        if val and (_UPLOAD_RE.search(val) or "file upload" in val.lower()):
            cat[field] = _rewrite_upload_phrases(val)
            if "paste" not in cat[field].lower() and "inline" not in cat[field].lower():
                cat[field] = (cat[field].rstrip(".") + ". Paste content inline in chat - no file upload.").strip()
            changes.append(f"{cid}: updated {field}")

    forensic = str(cat.get("forensic_evidence_required", ""))
    if forensic and _UPLOAD_RE.search(forensic):
        cat["forensic_evidence_required"] = _rewrite_upload_phrases(forensic)
        changes.append(f"{cid}: updated forensic evidence note")

    return cat, changes


def convert_playbook_to_text_channel(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Convert artifact categories in a playbook copy for text-only harnesses."""
    out = copy.deepcopy(data)
    all_changes: list[str] = []

    categories = out.get("categories")
    if not isinstance(categories, list):
        return out, all_changes

    converted: list[dict[str, Any]] = []
    for cat in categories:
        if not isinstance(cat, dict):
            converted.append(cat)
            continue
        new_cat, changes = convert_category_to_text(cat)
        converted.append(new_cat)
        all_changes.extend(changes)

    out["categories"] = converted

    if all_changes:
        for field in ("evaluation_instructions",):
            val = str(out.get(field, ""))
            if val and _UPLOAD_RE.search(val):
                out[field] = _rewrite_upload_phrases(val)

        methodology = out.get("evaluation_methodology")
        if isinstance(methodology, list):
            out["evaluation_methodology"] = [
                _rewrite_upload_phrases(str(step)) for step in methodology
            ]

        play = str(out.get("play", ""))
        if play and "text-only" not in play.lower() and any(
            get_category_channel(c) == "artifact" for c in categories if isinstance(c, dict)
        ):
            out["play"] = play.rstrip() + (
                "\n\nNote: This CTF target uses a text-only chat harness - submit poisoned content "
                "inline in chat rather than uploading files."
            )
            all_changes.append("play: appended text-only harness note")

        assessment = str(out.get("assessment_type", ""))
        if assessment and "text-only" not in assessment.lower() and all_changes:
            out["assessment_type"] = assessment.rstrip(".") + " (text-only harness)"

    return out, all_changes


def playbook_has_artifact_categories(data: dict[str, Any]) -> bool:
    categories = data.get("categories")
    if not isinstance(categories, list):
        return False
    return any(
        isinstance(cat, dict) and get_category_channel(cat) == "artifact"
        for cat in categories
    )
