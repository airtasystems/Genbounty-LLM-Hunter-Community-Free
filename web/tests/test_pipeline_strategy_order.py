"""Contract: pipeline All-strategies uses in-scope registry order (no recommended_strategies)."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PIPELINE_JS = _ROOT / "web" / "static" / "js" / "tabs" / "pipeline.js"


def test_pipeline_all_mode_does_not_prioritize_recommended_strategies():
    src = _PIPELINE_JS.read_text(encoding="utf-8")
    assert "orderStrategiesForPipeline" not in src
    assert "recommended_strategies" not in src
    assert "pipelineStrategyOptions.value" in src
    assert "hardRefusalEarlyStop" in src
    assert "circularEnhanceEarlyStop" in src
    # Header Deploy Probes always enables soft early-stop (not All-mode only).
    assert "hardRefusalEarlyStop: 3" in src
    assert "circularEnhanceEarlyStop: 3" in src
    assert "pipelineAllMode.value ? 3 : 0" not in src
