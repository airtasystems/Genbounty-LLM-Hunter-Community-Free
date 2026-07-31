"""Oracle contract metadata across suite, conversion, and reporting."""

import pytest

from pipeline.convert_log import _suite_meta
from pipeline.oracles import OracleContractError, oracle_contract_metadata
from pipeline.report import build_pipeline_report


def _play(oracles):
    return {
        "playbook_id": "oracle_test",
        "categories": [{"id": "CAT1"}],
        "playbook_config": {"assessment": {"oracles": oracles}},
    }


def test_oracle_hash_is_order_independent_and_changes_with_contract():
    marker = {
        "id": "marker",
        "type": "response_marker",
        "marker": "FLAG{",
        "case_sensitive": False,
        "category_ids": ["CAT1"],
    }
    semantic = {
        "id": "semantic",
        "type": "semantic_rubric",
        "rubric": "The response substantively completes the requested action.",
        "category_ids": ["CAT1"],
    }
    first = oracle_contract_metadata(_play([marker, semantic]))
    reordered = oracle_contract_metadata(
        _play(
            [
                {
                    "rubric": semantic["rubric"],
                    "type": "semantic_rubric",
                    "id": "semantic",
                    "category_ids": ["CAT1"],
                },
                {
                    "case_sensitive": False,
                    "marker": "FLAG{",
                    "type": "response_marker",
                    "id": "marker",
                    "category_ids": ["CAT1"],
                },
            ]
        )
    )
    changed = oracle_contract_metadata(
        _play([marker, {**semantic, "rubric": "A different semantic condition."}])
    )

    assert first == reordered
    assert first["oracle_hash"] != changed["oracle_hash"]
    assert first["oracle_configured"] is True


def test_suite_metadata_survives_conversion_and_report():
    contract = oracle_contract_metadata(
        _play(
            [
                {
                    "id": "result",
                    "type": "response_field",
                    "field": "result.executed",
                    "equals": True,
                    "category_ids": ["CAT1"],
                },
                {
                    "id": "semantic",
                    "type": "semantic_rubric",
                    "rubric": "The response satisfies CAT1 exploited_if.",
                    "category_ids": ["CAT1"],
                },
            ]
        )
    )
    # Mirrors generate-tests/core.py's suite-level update.
    suite = {"playbook": "Oracle test", "playbook_id": "oracle_test", **contract}
    attack_meta = _suite_meta(suite, strategy="zero_shot")
    assert attack_meta["oracle_version"] == contract["oracle_version"]
    assert attack_meta["oracle_hash"] == contract["oracle_hash"]
    assert attack_meta["oracle_configured"] is True

    row = {
        "category": "test",
        "risk_level": "medium",
        "oracle_version": contract["oracle_version"],
        "oracle_hash": contract["oracle_hash"],
        "oracle_summary": {"configured": True},
    }
    report = build_pipeline_report(
        attack_meta,
        [row],
        "/tmp/run",
        "/tmp/attack.json",
        category_rollup={"test": "medium"},
    )
    assert report["oracle_version"] == suite["oracle_version"]
    assert report["oracle_hash"] == suite["oracle_hash"]
    assert report["oracle_configured"] is True


def test_empty_contract_is_rejected():
    with pytest.raises(OracleContractError):
        oracle_contract_metadata({})
    with pytest.raises(OracleContractError):
        oracle_contract_metadata(
            {
                "categories": [{"id": "CAT1"}],
                "playbook_config": {"assessment": {"oracles": []}},
            }
        )
