from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re as _re
import sys
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from web.paths import BB_DIR, ROOT, ensure_generate_tests_path
from web.services.suite_io import (
    apply_suite_transform,
    load_test_suite,
    save_test_suite,
    test_suite_path,
)

router = APIRouter()

from browser_bot.sites import ensure_component_dir, get_component_path
from web.jobs import start_job

def _pretty(slug: str) -> str:
    short = {"eu", "ai", "uk", "us"}
    long_ = {"oecd", "gdpr", "iso"}
    parts = slug.replace("_", "-").split("-")
    words = []
    for p in parts:
        if not p:
            continue
        pl = p.lower()
        if pl in short or pl in long_:
            words.append(p.upper())
        else:
            words.append(p.capitalize())
    return " ".join(words)


@router.get("/api/sites/{site}/{component}/strategies")
async def api_component_strategies(site: str, component: str):
    tests = BB_DIR / "sites" / site / component / "tests"
    if not tests.is_dir():
        return []
    return [
        {"slug": p.name, "label": _pretty(p.name)}
        for p in sorted(tests.iterdir())
        if p.is_dir() and any(p.glob("*.json"))
    ]


@router.get("/api/sites/{site}/{component}/all-playbooks")
async def api_all_playbooks(site: str, component: str):
    """Return unique playbook stems available across all strategy test dirs."""
    tests = BB_DIR / "sites" / site / component / "tests"
    if not tests.is_dir():
        return []
    stems: set[str] = set()
    for strat_dir in tests.iterdir():
        if strat_dir.is_dir():
            for f in strat_dir.glob("*.json"):
                stems.add(f.stem)
    return [{"slug": s, "label": _pretty(s)} for s in sorted(stems)]


@router.get("/api/sites/{site}/{component}/test-files")
def api_test_files(site: str, component: str):
    """Test files (playbook stems) with strategies that contain each file, newest first."""
    tests = BB_DIR / "sites" / site / component / "tests"
    if not tests.is_dir():
        return []
    by_stem: dict[str, dict] = {}
    for strat_dir in tests.iterdir():
        if not strat_dir.is_dir():
            continue
        strat = strat_dir.name
        for f in strat_dir.glob("*.json"):
            stem = f.stem
            if stem not in by_stem:
                by_stem[stem] = {
                    "slug": stem,
                    "label": _pretty(stem),
                    "strategies": [],
                    "mtime": 0.0,
                    "generation_profile": "",
                    "generation_notes": "",
                }
            entry = by_stem[stem]
            if strat not in entry["strategies"]:
                entry["strategies"].append(
                    {"slug": strat, "label": _pretty(strat)}
                )
            mtime = f.stat().st_mtime
            if mtime > entry["mtime"]:
                entry["mtime"] = mtime
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    entry["generation_profile"] = data.get("generation_profile") or ""
                    entry["generation_notes"] = data.get("generation_notes") or ""
                except (OSError, json.JSONDecodeError):
                    entry["generation_profile"] = ""
                    entry["generation_notes"] = ""
    items = list(by_stem.values())
    items.sort(key=lambda x: x["mtime"], reverse=True)
    for item in items:
        item["strategies"].sort(key=lambda s: s["slug"], reverse=True)
        del item["mtime"]
    return items


@router.get("/api/sites/{site}/{component}/strategies/{strategy}/playbooks")
def api_strategy_playbooks(site: str, component: str, strategy: str):
    d = BB_DIR / "sites" / site / component / "tests" / strategy
    if not d.is_dir():
        return []
    return [
        {"slug": p.stem, "label": _pretty(p.stem), "path": str(p)}
        for p in sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
    ]


@router.get("/api/sites/{site}/{component}/tests/{strategy}/{playbook}")
async def api_get_test_file(site: str, component: str, strategy: str, playbook: str):
    return load_test_suite(site, component, strategy, playbook)


class TestFileBody(BaseModel):
    data: dict


class ImportZeroShotTestsBody(BaseModel):
    filename: str
    data: dict | list


def _slugify_test_filename(name: str) -> str:
    stem = Path(name).stem
    slug = _re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_").lower()
    return slug or "imported_prompts"


def _normalize_prompt(raw, idx: int) -> dict:
    if isinstance(raw, str):
        prompt = raw.strip()
        description = "Imported zero-shot prompt"
        prompt_id = f"imported-zs-{idx:03d}"
    elif isinstance(raw, dict):
        description = str(raw.get("description") or "Imported zero-shot prompt").strip()
        prompt_id = str(raw.get("id") or f"imported-zs-{idx:03d}").strip()
        turns_raw = raw.get("prompts")
        if isinstance(turns_raw, list) and turns_raw:
            turns = [str(t).strip() for t in turns_raw if str(t).strip()]
            if not turns:
                raise HTTPException(400, f"Prompt {idx} has an empty prompts array")
            if not prompt_id:
                prompt_id = f"imported-zs-{idx:03d}"
            return {"id": prompt_id, "description": description, "prompts": turns}
        prompt = str(raw.get("prompt") or raw.get("text") or raw.get("content") or "").strip()
    else:
        raise HTTPException(400, f"Prompt {idx} must be a string or object")
    if not prompt:
        raise HTTPException(400, f"Prompt {idx} is empty")
    if not prompt_id:
        prompt_id = f"imported-zs-{idx:03d}"
    return {"id": prompt_id, "description": description, "prompt": prompt}


def _normalize_zero_shot_suite(data, filename: str) -> dict:
    if isinstance(data, dict) and isinstance(data.get("categories"), list):
        categories = data["categories"]
        for category_idx, category in enumerate(categories, start=1):
            if not isinstance(category, dict) or not isinstance(category.get("prompts"), list):
                raise HTTPException(400, f"Category {category_idx} must include a prompts list")
            category["prompts"] = [
                _normalize_prompt(prompt, prompt_idx)
                for prompt_idx, prompt in enumerate(category["prompts"], start=1)
            ]
        return {
            "playbook": data.get("playbook") or Path(filename).stem,
            "description": data.get("description") or "Imported zero-shot prompts",
            "categories": categories,
        }

    prompts = data.get("prompts") if isinstance(data, dict) else data
    if not isinstance(prompts, list) or not prompts:
        raise HTTPException(400, "JSON must be a prompt array, an object with prompts, or a full probe suite")

    playbook = (data.get("playbook") or Path(filename).stem) if isinstance(data, dict) else Path(filename).stem
    description = (data.get("description") or "Imported zero-shot prompts") if isinstance(data, dict) else "Imported zero-shot prompts"
    return {
        "playbook": playbook,
        "description": description,
        "categories": [
            {
                "category": data.get("category", "Imported zero-shot prompts") if isinstance(data, dict) else "Imported zero-shot prompts",
                "focus": data.get("focus", "Imported") if isinstance(data, dict) else "Imported",
                "prompts": [
                    _normalize_prompt(prompt, idx)
                    for idx, prompt in enumerate(prompts, start=1)
                ],
            }
        ],
    }


@router.put("/api/sites/{site}/{component}/tests/{strategy}/{playbook}")
async def api_put_test_file(site: str, component: str, strategy: str, playbook: str, body: TestFileBody):
    p = test_suite_path(site, component, strategy, playbook)
    if not p.exists():
        raise HTTPException(404, "Test file not found")
    save_test_suite(p, body.data)
    return {"ok": True}


@router.delete("/api/sites/{site}/{component}/tests/{strategy}/{playbook}")
async def api_delete_test_file(site: str, component: str, strategy: str, playbook: str):
    """Delete an entire probe suite JSON for this strategy/playbook."""
    p = test_suite_path(site, component, strategy, playbook)
    try:
        resolved = p.resolve()
        resolved.relative_to((BB_DIR / "sites").resolve())
    except (OSError, ValueError) as exc:
        raise HTTPException(400, "Invalid test path") from exc
    if not resolved.is_file():
        raise HTTPException(404, "Test file not found")
    resolved.unlink()
    return {
        "ok": True,
        "strategy": strategy,
        "playbook": playbook,
        "path": str(resolved),
    }


class FlagPromptBody(BaseModel):
    report_path: str
    prompt_id: str = ""
    position: int | None = None


class DeleteReportEntryBody(BaseModel):
    report_path: str
    prompt_id: str = ""
    position: int | None = None


def _resolve_pipeline_report_path(report_path: str) -> Path:
    """Resolve a pipeline report path and ensure it stays under the workspace."""
    path = Path(report_path.strip())
    if not path.is_absolute():
        path = ROOT / path
    try:
        resolved = path.resolve()
        resolved.relative_to(ROOT.resolve())
    except (OSError, ValueError):
        raise HTTPException(403, "Access denied") from None
    if not resolved.is_file():
        raise HTTPException(404, "Pipeline report not found")
    return resolved


@router.post("/api/sites/{site}/{component}/flag-prompt")
async def api_flag_prompt(site: str, component: str, body: FlagPromptBody):
    """Flag an assessed prompt into a custom {parent}-flagged.json probe suite."""
    from pipeline.flagged_suite import (
        add_prompt_to_flagged_suite,
        list_flagged_prompt_ids,
        resolve_parent_suite_path,
    )

    report_path = Path(body.report_path.strip())
    if not report_path.is_absolute():
        report_path = ROOT / report_path
    if not report_path.is_file():
        raise HTTPException(404, "Pipeline report not found")
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(400, f"Invalid report JSON: {exc}") from exc

    results = report.get("adversarial_results") or []
    if not isinstance(results, list) or not results:
        raise HTTPException(400, "Report has no adversarial_results to flag")

    target: dict | None = None
    prompt_id = body.prompt_id.strip()
    if prompt_id:
        for row in results:
            if isinstance(row, dict) and str(row.get("id") or "").strip() == prompt_id:
                target = row
                break
    elif body.position is not None and 0 <= body.position < len(results):
        row = results[body.position]
        target = row if isinstance(row, dict) else None

    if not target:
        raise HTTPException(404, "Assessment row not found in report")

    parent_path = resolve_parent_suite_path(report, site=site, component=component, bb_root=BB_DIR)
    if parent_path is None:
        raise HTTPException(
            404,
            "Parent probe suite not found (check report source_file or playbook_id/strategy).",
        )

    try:
        out = add_prompt_to_flagged_suite(
            site=site,
            component=component,
            parent_suite_path=parent_path,
            result=target,
            position=body.position,
            report_path=str(report_path),
            bb_root=BB_DIR,
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    flagged_path = Path(out["path"])
    out["flagged_ids"] = list_flagged_prompt_ids(flagged_path)
    out["flagged_count"] = len(out["flagged_ids"])
    return out


@router.delete("/api/sites/{site}/{component}/report-entry")
async def api_delete_report_entry(site: str, component: str, body: DeleteReportEntryBody):
    """Delete one adversarial_results entry from a pipeline_report.json and refresh category_rollup."""
    import importlib.util

    from pipeline.report import delete_adversarial_result

    rla_file = ROOT / "risk-level-agent" / "risk_level_agent.py"
    if rla_file.exists() and "risk_level_agent" not in sys.modules:
        spec = importlib.util.spec_from_file_location("risk_level_agent", rla_file)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            sys.modules["risk_level_agent"] = mod
            spec.loader.exec_module(mod)

    report_path = _resolve_pipeline_report_path(body.report_path)
    logs_root = (BB_DIR / "sites" / site / component / "logs").resolve()
    try:
        report_path.relative_to(logs_root)
    except ValueError:
        raise HTTPException(403, "Report is not under this site/component") from None

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(400, f"Invalid report JSON: {exc}") from exc

    try:
        removed, updated = delete_adversarial_result(
            report,
            prompt_id=body.prompt_id,
            position=body.position,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc

    try:
        report_path.write_text(
            json.dumps(updated, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise HTTPException(500, f"Failed to write report: {exc}") from exc

    remaining = updated.get("adversarial_results") or []
    return {
        "ok": True,
        "report_path": str(report_path),
        "removed_id": str(removed.get("id") or ""),
        "remaining_count": len(remaining) if isinstance(remaining, list) else 0,
        "category_rollup": updated.get("category_rollup") or {},
    }


@router.get("/api/sites/{site}/{component}/flagged-prompts")
async def api_flagged_prompts(site: str, component: str, strategy: str, parent: str):
    """Return prompt ids already present in the parent's -flagged.json suite."""
    from pipeline.flagged_suite import flagged_suite_stem, list_flagged_prompt_ids

    parent_stem = Path(parent).stem
    flagged_path = (
        BB_DIR / "sites" / site / component / "tests" / strategy
        / f"{flagged_suite_stem(parent_stem)}.json"
    )
    ids = list_flagged_prompt_ids(flagged_path)
    return {
        "parent": parent_stem,
        "strategy": strategy,
        "path": str(flagged_path) if flagged_path.is_file() else "",
        "prompt_ids": ids,
        "count": len(ids),
    }


class ObfuscateTestsBody(BaseModel):
    technique: str


def _prompt_transform_catalog() -> dict:
    """All Generate/Armory transform dropdown options in one payload."""
    ensure_generate_tests_path()
    from prompt_cipher import list_ciphers
    from prompt_code_embed import list_code_languages
    from prompt_control_code import list_control_codes
    from prompt_frame import list_frame_techniques
    from prompt_native import list_native_languages
    from prompt_obfuscation import list_techniques
    from prompt_translation import list_languages

    return {
        "techniques": list_techniques(),
        "languages": list_languages(),
        "native_languages": list_native_languages(),
        "frames": list_frame_techniques(),
        "code_languages": list_code_languages(),
        "ciphers": list_ciphers(),
        "control_codes": list_control_codes(),
    }


@router.get("/api/transform-options")
async def api_transform_options():
    """Single catalog for Prompt Transforms dropdowns (avoids blocked per-list URLs)."""
    return _prompt_transform_catalog()


@router.get("/api/obfuscation-techniques")
async def api_obfuscation_techniques():
    return _prompt_transform_catalog()["techniques"]


@router.get("/api/translation-languages")
async def api_translation_languages():
    return _prompt_transform_catalog()["languages"]


@router.get("/api/native-languages")
async def api_native_languages():
    return _prompt_transform_catalog()["native_languages"]


@router.get("/api/frame-techniques")
async def api_frame_techniques():
    return _prompt_transform_catalog()["frames"]


@router.post("/api/sites/{site}/{component}/tests/{strategy}/{playbook}/obfuscate")
async def api_obfuscate_test_file(
    site: str, component: str, strategy: str, playbook: str, body: ObfuscateTestsBody,
):
    ensure_generate_tests_path()
    from prompt_obfuscation import obfuscate_suite

    _, count = apply_suite_transform(
        site,
        component,
        strategy,
        playbook,
        lambda data: obfuscate_suite(data, body.technique),
        empty_message="No text prompts found to obfuscate in this suite",
    )
    technique = body.technique.strip().lower()
    return {"ok": True, "technique": technique, "fields_obfuscated": count, "has_backup": True}


@router.get("/api/sites/{site}/{component}/tests/{strategy}/{playbook}/obfuscation-status")
async def api_obfuscation_status(site: str, component: str, strategy: str, playbook: str):
    ensure_generate_tests_path()
    from prompt_obfuscation import suite_has_plain_backup, suite_transform_meta

    data = load_test_suite(site, component, strategy, playbook)
    meta = suite_transform_meta(data)
    return {
        "has_backup": suite_has_plain_backup(data),
        "technique": meta.get("technique"),
        "language": meta.get("language"),
        "native_language": meta.get("native_language"),
        "frame_technique": meta.get("frame_technique"),
        "code_language": meta.get("code_language"),
        "cipher": meta.get("cipher"),
        "control_code": meta.get("control_code"),
        "iq": meta.get("iq"),
        "emotion": meta.get("emotion"),
        "attributes": meta.get("attributes"),
    }


class PromptAttributesBody(BaseModel):
    temperature: float = 1.0
    max_tokens: int = 256
    top_k: int = 40
    top_p: float = 0.95


@router.post("/api/sites/{site}/{component}/tests/{strategy}/{playbook}/prompt-attributes")
async def api_prompt_attributes_test_file(
    site: str, component: str, strategy: str, playbook: str, body: PromptAttributesBody,
):
    """Start an async attributes-rewrite job (progress streams to Experiment Output)."""
    ensure_generate_tests_path()
    from prompt_attributes import normalize_attributes

    if not test_suite_path(site, component, strategy, playbook).exists():
        raise HTTPException(404, "Test file not found")
    try:
        attrs = normalize_attributes(body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    job = await start_job(
        "prompt_attributes",
        site,
        component,
        {
            "strategy": strategy,
            "playbook": playbook,
            "attributes": attrs,
        },
    )
    return {
        "ok": True,
        "job_id": job.id,
        "attributes": attrs,
        "async": True,
    }


class IqRewriteTestsBody(BaseModel):
    iq: int


@router.post("/api/sites/{site}/{component}/tests/{strategy}/{playbook}/iq-rewrite")
async def api_iq_rewrite_test_file(
    site: str, component: str, strategy: str, playbook: str, body: IqRewriteTestsBody,
):
    ensure_generate_tests_path()
    from prompt_iq import iq_rewrite_suite

    _, count = apply_suite_transform(
        site,
        component,
        strategy,
        playbook,
        lambda data: iq_rewrite_suite(data, body.iq),
        empty_message="No text prompts found to rewrite in this suite",
    )
    return {"ok": True, "iq": int(body.iq), "fields_rewritten": count, "has_backup": True}


class EmotionRewriteTestsBody(BaseModel):
    emotion: int


@router.post("/api/sites/{site}/{component}/tests/{strategy}/{playbook}/emotion-rewrite")
async def api_emotion_rewrite_test_file(
    site: str, component: str, strategy: str, playbook: str, body: EmotionRewriteTestsBody,
):
    ensure_generate_tests_path()
    from prompt_emotion import emotion_rewrite_suite

    _, count = apply_suite_transform(
        site,
        component,
        strategy,
        playbook,
        lambda data: emotion_rewrite_suite(data, body.emotion),
        empty_message="No text prompts found to rewrite in this suite",
    )
    return {"ok": True, "emotion": int(body.emotion), "fields_rewritten": count, "has_backup": True}


class CipherTestsBody(BaseModel):
    cipher: str


@router.get("/api/ciphers")
async def api_ciphers():
    return _prompt_transform_catalog()["ciphers"]


@router.post("/api/sites/{site}/{component}/tests/{strategy}/{playbook}/cipher")
async def api_cipher_test_file(
    site: str, component: str, strategy: str, playbook: str, body: CipherTestsBody,
):
    ensure_generate_tests_path()
    from prompt_cipher import cipher_suite

    _, count = apply_suite_transform(
        site,
        component,
        strategy,
        playbook,
        lambda data: cipher_suite(data, body.cipher),
        empty_message="No text prompts found to cipher in this suite",
    )
    cipher = body.cipher.strip().lower()
    return {"ok": True, "cipher": cipher, "fields_ciphered": count, "has_backup": True}


class TranslateTestsBody(BaseModel):
    language: str


class NativeRewriteTestsBody(BaseModel):
    language: str


class CodeEmbedTestsBody(BaseModel):
    language: str


class ControlCodeTestsBody(BaseModel):
    technique: str


@router.get("/api/code-languages")
async def api_code_languages():
    return _prompt_transform_catalog()["code_languages"]


@router.get("/api/control-codes")
async def api_control_codes():
    return _prompt_transform_catalog()["control_codes"]


@router.post("/api/sites/{site}/{component}/tests/{strategy}/{playbook}/code-embed")
async def api_code_embed_test_file(
    site: str, component: str, strategy: str, playbook: str, body: CodeEmbedTestsBody,
):
    ensure_generate_tests_path()
    from prompt_code_embed import code_embed_suite

    _, count = apply_suite_transform(
        site,
        component,
        strategy,
        playbook,
        lambda data: code_embed_suite(data, body.language),
        empty_message="No text prompts found to embed in this suite",
    )
    language = body.language.strip().lower()
    return {"ok": True, "language": language, "fields_embedded": count, "has_backup": True}


@router.post("/api/sites/{site}/{component}/tests/{strategy}/{playbook}/control-code")
async def api_control_code_test_file(
    site: str, component: str, strategy: str, playbook: str, body: ControlCodeTestsBody,
):
    ensure_generate_tests_path()
    from prompt_control_code import control_code_suite

    _, count = apply_suite_transform(
        site,
        component,
        strategy,
        playbook,
        lambda data: control_code_suite(data, body.technique),
        empty_message="No text prompts found to wrap in this suite",
    )
    technique = body.technique.strip().lower()
    return {"ok": True, "technique": technique, "fields_wrapped": count, "has_backup": True}


@router.post("/api/sites/{site}/{component}/tests/{strategy}/{playbook}/translate")
async def api_translate_test_file(
    site: str, component: str, strategy: str, playbook: str, body: TranslateTestsBody,
):
    ensure_generate_tests_path()
    from prompt_translation import translate_suite

    _, count = apply_suite_transform(
        site,
        component,
        strategy,
        playbook,
        lambda data: translate_suite(data, body.language),
        empty_message="No text prompts found to translate in this suite",
    )
    language = body.language.strip().lower()
    return {"ok": True, "language": language, "fields_translated": count, "has_backup": True}


@router.post("/api/sites/{site}/{component}/tests/{strategy}/{playbook}/native")
async def api_native_rewrite_test_file(
    site: str, component: str, strategy: str, playbook: str, body: NativeRewriteTestsBody,
):
    ensure_generate_tests_path()
    from prompt_native import rewrite_suite

    _, count = apply_suite_transform(
        site,
        component,
        strategy,
        playbook,
        lambda data: rewrite_suite(data, body.language),
        empty_message="No text prompts found to rewrite in this suite",
    )
    language = body.language.strip().lower()
    return {"ok": True, "language": language, "fields_rewritten": count, "has_backup": True}


class PromptNativeRewriteBody(BaseModel):
    prompt: str
    language: str = "llm_native"


@router.post("/api/sites/{site}/{component}/prompt-native-rewrite")
async def api_prompt_native_rewrite(
    site: str, component: str, body: PromptNativeRewriteBody,
):
    """Rewrite a single Firing Range prompt into a Native dialect (in-place UI)."""
    result = await api_prompt_transform(
        site,
        component,
        PromptTransformBody(prompt=body.prompt, kind="native", name=body.language),
    )
    return {"prompt": result["prompt"], "language": result["name"]}


class PromptTransformBody(BaseModel):
    prompt: str
    kind: str
    name: str = ""
    attributes: dict | None = None


@router.post("/api/sites/{site}/{component}/prompt-transform")
async def api_prompt_transform(
    site: str, component: str, body: PromptTransformBody,
):
    """Rewrite a single Firing Range prompt with one Prompt Transforms step."""
    _ = site, component
    prompt = (body.prompt or "").strip()
    if not prompt:
        raise HTTPException(400, "prompt is required")
    kind = (body.kind or "").strip().lower()
    if not kind:
        raise HTTPException(400, "kind is required")

    ensure_generate_tests_path()

    if kind == "attributes":
        from prompt_attributes import rewrite_texts_for_attributes

        attrs = body.attributes if isinstance(body.attributes, dict) else {}
        try:
            rewritten = await asyncio.to_thread(
                rewrite_texts_for_attributes, [prompt], attrs
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(503, f"Attribute rewrite failed: {exc}") from exc
        if not rewritten or not isinstance(rewritten[0], str) or not rewritten[0].strip():
            raise HTTPException(503, "Attribute rewrite returned empty result")
        return {"prompt": rewritten[0].strip(), "kind": kind, "name": "attributes"}

    from prompt_gen_pipeline import _text_transformer

    name = str(body.name or "").strip()
    if kind in {"iq", "emotion"}:
        if not name:
            name = "100" if kind == "iq" else "150"
    elif not name:
        raise HTTPException(400, "name is required")

    transform = _text_transformer(kind, name)
    if transform is None:
        raise HTTPException(400, f"Unknown transform: {kind}/{name}")

    try:
        out = await asyncio.to_thread(transform, prompt)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503, f"Transform failed: {exc}") from exc

    rewritten = str(out or "").strip()
    if not rewritten:
        raise HTTPException(503, "Transform returned empty result")
    return {"prompt": rewritten, "kind": kind, "name": name}


class FrameRewriteTestsBody(BaseModel):
    technique: str


@router.post("/api/sites/{site}/{component}/tests/{strategy}/{playbook}/frame")
async def api_frame_rewrite_test_file(
    site: str, component: str, strategy: str, playbook: str, body: FrameRewriteTestsBody,
):
    ensure_generate_tests_path()
    from prompt_frame import rewrite_suite

    _, count = apply_suite_transform(
        site,
        component,
        strategy,
        playbook,
        lambda data: rewrite_suite(data, body.technique),
        empty_message="No text prompts found to rewrite in this suite",
    )
    technique = body.technique.strip().lower()
    return {"ok": True, "technique": technique, "fields_rewritten": count, "has_backup": True}


@router.post("/api/sites/{site}/{component}/tests/{strategy}/{playbook}/restore-plain")
async def api_restore_plain_test_file(site: str, component: str, strategy: str, playbook: str):
    ensure_generate_tests_path()
    from prompt_obfuscation import restore_suite

    _, count = apply_suite_transform(
        site,
        component,
        strategy,
        playbook,
        restore_suite,
        empty_message="No obfuscation backup found - prompts are already plain English",
    )
    return {"ok": True, "fields_restored": count}


@router.post("/api/sites/{site}/{component}/tests/import-zero-shot")
async def api_import_zero_shot_tests(site: str, component: str, body: ImportZeroShotTestsBody):
    ensure_component_dir(site, component)
    filename = _slugify_test_filename(body.filename)
    suite = _normalize_zero_shot_suite(body.data, body.filename)
    tests_dir = BB_DIR / "sites" / site / component / "tests" / "zero-shot"
    tests_dir.mkdir(parents=True, exist_ok=True)
    p = tests_dir / f"{filename}.json"
    save_test_suite(p, suite)
    return {"ok": True, "strategy": "zero-shot", "playbook": filename, "path": str(p), "data": suite}

