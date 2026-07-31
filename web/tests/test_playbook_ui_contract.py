"""Deterministic UI/API checks for strict playbook fields."""

from __future__ import annotations

import asyncio
from pathlib import Path

from web.routers.playbooks import api_play_category_presets


_ROOT = Path(__file__).resolve().parents[2]


def test_playbook_editor_exposes_only_category_vectors():
    playbooks_js = (
        _ROOT / "web" / "static" / "js" / "tabs" / "playbooks.js"
    ).read_text(encoding="utf-8")
    playbooks_html = (
        _ROOT / "web" / "static" / "partials" / "tabs" / "playbooks.html"
    ).read_text(encoding="utf-8")
    source = f"{playbooks_js}\n{playbooks_html}"

    assert "vectors_to_try" not in source
    assert "file_vectors_to_try" not in source
    assert "category_vectors: []" in playbooks_js
    assert "cat.category_vectors" in playbooks_html
    assert "Category vectors (one per line)" in playbooks_html


def test_regenerate_uses_create_ai_contract():
    """Regenerate must full-rewrite from play like Create AI (not rebuild-from-objective)."""
    js = (
        _ROOT / "web" / "static" / "js" / "tabs" / "playbooks.js"
    ).read_text(encoding="utf-8")
    assert "authoring_mode: 'ai'" in js
    assert "rebuild_from_objective: false" in js
    assert "Full AI rewrite from play hypothesis" in js
    assert "pbStripObjectiveCoupledFieldsForRebuild" not in js
    assert "pbPlaybookConfigForRegenerate" not in js
    assert "PB_DEFAULT_MANDATORY_DIRECTIVES" not in js
    # Must not set rebuild_from_objective: true on the UI regenerate path.
    assert "rebuild_from_objective: true" not in js


def test_plan_mission_exposes_keep_play_verbatim():
    js = (
        _ROOT / "web" / "static" / "js" / "tabs" / "playbooks.js"
    ).read_text(encoding="utf-8")
    modal = (
        _ROOT / "web" / "static" / "partials" / "modals" / "playbook.html"
    ).read_text(encoding="utf-8")
    assert "keep_play_verbatim: false" in js
    assert "keep_play_verbatim: authoringMode === 'ai' && !!pbForm.keep_play_verbatim" in js
    assert 'v-model="pbForm.keep_play_verbatim"' in modal
    assert "Use mission brief verbatim" in modal


def test_plan_mission_exposes_exact_canary():
    js = (
        _ROOT / "web" / "static" / "js" / "tabs" / "playbooks.js"
    ).read_text(encoding="utf-8")
    modal = (
        _ROOT / "web" / "static" / "partials" / "modals" / "playbook.html"
    ).read_text(encoding="utf-8")
    assert "exact_canary: ''" in js
    assert "exact_canary: String(pbForm.exact_canary || '').trim()" in js
    assert "pbWizardApplyExactCanary" in js
    assert 'v-model="pbForm.exact_canary"' in modal
    assert "Exact canary string" in modal
    assert "Response contains the exact string:" in js
    assert "Response does not contain the exact string:" in js


def test_regenerate_preserves_prompt_template_in_payload():
    """Regenerate must re-send existing prompt_template (not omit playbook_config)."""
    js = (
        _ROOT / "web" / "static" / "js" / "tabs" / "playbooks.js"
    ).read_text(encoding="utf-8")
    assert "preservedEnvelope" in js
    assert "prompt_template envelope and exact canary are kept" in js
    assert "const existingCfg = pbPlaybookConfigFromRecord(pbRecord.value)" in js
    # Must not leave playbookConfig null on the non-preset regenerate path.
    assert "let playbookConfig = pbPlaybookConfigApiPayload(preservedEnvelope)" in js
    assert "pbExactCanaryFromRecord" in js
    assert "if (preservedExactCanary) body.exact_canary = preservedExactCanary" in js


def test_plan_mission_exposes_prompt_template():
    js = (
        _ROOT / "web" / "static" / "js" / "tabs" / "playbooks.js"
    ).read_text(encoding="utf-8")
    modal = (
        _ROOT / "web" / "static" / "partials" / "modals" / "playbook.html"
    ).read_text(encoding="utf-8")
    editor = (
        _ROOT / "web" / "static" / "partials" / "tabs" / "playbooks.html"
    ).read_text(encoding="utf-8")
    assert "prompt_template: ''" in js
    assert "PB_PROMPT_TEMPLATE_CHIPS" in js
    assert "pbApplyPromptTemplateChip" in js
    assert 'v-model="pbForm.prompt_template"' in modal
    assert "Prompt template" in modal
    assert "pb-objective-lexicon" not in modal
    assert "Sensitive-word placeholders" not in modal
    assert 'v-model="pbConfigForm.prompt_template"' in editor
    assert "pb-record-objective-lexicon" not in editor
    assert '{"task":"{{task}}","input":"{{input}}","output_format":"{{format}}"}' in js


def test_preset_catalog_api_omits_misleading_compatibility_keys():
    payload = asyncio.run(api_play_category_presets())
    assert set(payload) == {
        "preset_families",
        "capability_families",
        "leaf_mappings",
        "leaf_presets",
        "leaf_count",
    }
    assert payload["preset_families"]
    assert payload["capability_families"]
    assert payload["leaf_presets"]
    assert payload["leaf_mappings"]
    assert payload["leaf_count"] == len(payload["leaf_presets"])
