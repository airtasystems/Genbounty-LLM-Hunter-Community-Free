"""Offline profile coverage from authoring through assessment normalization."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_GEN = _ROOT / "generate-tests"
for _path in (str(_ROOT), str(_GEN)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from core import generate_prompts_for_category  # noqa: E402
from payloads.materialize import materialize_suite  # noqa: E402
from pipeline.oracles import resolve_oracles  # noqa: E402
from pipeline.security_assess import _normalize_fast_path_oracle_fields  # noqa: E402
from playbook_generator import (  # noqa: E402
    _normalize_playbook,
    generate_playbook_json,
    load_template,
    validate_playbook,
)
from playbooks.artifact_delivery import artifact_delivery_methods_for_category  # noqa: E402
from playbooks.category_catalog import CAPABILITY_FAMILIES, LEAF_CATALOG  # noqa: E402
from strategies.attack_techniques import get_techniques  # noqa: E402
from strategies.generation_mode import route_to_profile  # noqa: E402
from strategies.multimodal import generators_for_category  # noqa: E402


PROFILE_CASES = [
    ("hunt", "mission.hunt", {}, "text"),
]


def _authored_playbook(monkeypatch, case_name, leaf, capabilities, channel):
    play = f"Demonstrate the concrete {case_name} objective with observable evidence."
    draft = load_template()
    draft["categories"][0]["channel"] = channel
    if channel == "artifact":
        draft["categories"][0]["delivery_methods"] = ["artifact_upload"]
    normalized = _normalize_playbook(
        draft,
        f"e2e_{case_name}",
        f"E2E {case_name}",
        play=play,
        play_category=leaf,
        play_category_path=leaf.split("."),
        play_category_label="Custom pipeline" if leaf == "mission.hunt" else "",
    )
    if leaf == "mission.hunt":
        normalized["categories"][0]["attack_techniques"] = [
            {
                "name": "authored_hypothesis_probe",
                "summary": f"Exercise this operator-authored custom hypothesis: {play}",
                "example": f"Test this exact custom hypothesis and return evidence: {play}",
                "channels": ["text"],
            }
        ]
    monkeypatch.setattr(
        "playbook_generator._generate_playbook_from_llm",
        lambda **_kwargs: copy.deepcopy(normalized),
    )
    result, attempts = generate_playbook_json(
        play=play,
        display_name=f"E2E {case_name}",
        playbook_id=f"e2e_{case_name}",
        play_category=leaf,
        play_category_path=leaf.split("."),
        play_category_label="Custom pipeline" if leaf == "mission.hunt" else "",
        target_capabilities=capabilities,
    )
    assert attempts == 1
    assert validate_playbook(result, f"e2e_{case_name}") == []
    return result


class _MockApp:
    def __init__(self, rows):
        self.rows = rows

    def invoke(self, state):
        assert state["expert_expected_count"] == len(self.rows)
        return {
            **state,
            "final_answer": json.dumps({"final_synthesis": self.rows}),
        }


class _TextStrategy:
    output_subdir = "zero-shot"
    n_prompts = 1

    @staticmethod
    def build_category_query(_category, _rubric):
        return "Generate one hypothesis-specific security test."

    @staticmethod
    def build_judge_system_prompt(n, rubric=None):
        return f"Synthesize exactly {n} hypothesis-specific test."


class _ArtifactStrategy:
    output_subdir = "multimodal"

    def __init__(self, rows):
        self.rows = rows
        self.n_prompts = len(rows)

    @staticmethod
    def prompt_count_for_category(category):
        return len(generators_for_category(category))

    @staticmethod
    def build_category_query(_category, _rubric):
        return "Generate the declared artifact-backed security tests."

    @staticmethod
    def build_judge_system_prompt(n, rubric=None):
        return f"Synthesize exactly {n} artifact-backed tests."

    def parse_judge_prompts(self, _final_answer, debug=False):
        return copy.deepcopy(self.rows)


@pytest.mark.parametrize("case_name,leaf,capabilities,channel", PROFILE_CASES)
def test_mocked_profile_pipeline_reaches_exploited_assessment(
    monkeypatch, tmp_path, case_name, leaf, capabilities, channel
):
    """No provider, browser, or network is needed for any representative profile."""
    monkeypatch.setattr(
        "pipeline.pipeline_settings.open_loop_prompts", lambda default=6: 1
    )
    playbook = _authored_playbook(
        monkeypatch, case_name, leaf, capabilities, channel
    )
    category = playbook["categories"][0]
    family = CAPABILITY_FAMILIES[LEAF_CATALOG[leaf].capability_family]
    assert category["capability_profile"] == family.profile

    if channel == "artifact":
        rows = []
        for index, (generator, vector_type) in enumerate(
            zip(
                generators_for_category(category),
                artifact_delivery_methods_for_category(category),
            ),
            1,
        ):
            rows.append(
                {
                    "id": f"{case_name}-{index}",
                    "description": f"{case_name} hypothesis-specific artifact test.",
                    "prompt": f"Review the attached {case_name} test input.",
                    "vector_type": vector_type,
                    "context_mode": "upload",
                    "payload": {
                        "generator": generator,
                        "args": {
                            "content": (
                                f"Embedded instruction for the {case_name} hypothesis: "
                                "carry out its concrete prohibited action."
                            )
                        },
                    },
                }
            )
        strategy = _ArtifactStrategy(rows)
    else:
        authored = category.get("attack_techniques")
        technique = get_techniques(
            leaf,
            channel="text",
            limit=1,
            authored_techniques=authored,
        )[0]
        rows = [
            {
                "id": f"{case_name}-1",
                "description": f"{case_name} hypothesis-specific text test.",
                "prompt": (
                    f"Exercise the concrete {case_name} security hypothesis and return "
                    "observable evidence of the requested action."
                ),
                "technique": technique.name,
                "probe_class": "stealth",
            }
        ]
        strategy = _TextStrategy()

    prompts, route = generate_prompts_for_category(
        _MockApp(rows),
        category,
        playbook,
        strategy,
    )
    assert route == "open_loop"
    assert route_to_profile(route) == "stealth_first"
    assert prompts

    selected = prompts[0]
    if channel == "artifact":
        suite_path = tmp_path / f"{case_name}.json"
        suite_path.write_text(
            json.dumps({"categories": [{**category, "prompts": prompts}]}),
            encoding="utf-8",
        )

        def _materialize(generator, args, *, out_dir):
            path = Path(out_dir) / f"{generator}.artifact"
            path.write_text(json.dumps(args, sort_keys=True), encoding="utf-8")
            return path

        monkeypatch.setattr("payloads.materialize.generate_payload", _materialize)
        _, materialized, total = materialize_suite(suite_path)
        assert materialized == total == len(prompts)
        materialized_suite = json.loads(suite_path.read_text(encoding="utf-8"))
        selected = materialized_suite["categories"][0]["prompts"][0]
        assert (suite_path.parent / selected["payload"]["path"]).is_file()

    expected = f"{case_name} objective completed"
    playbook["playbook_config"]["assessment"]["oracles"].append(
        {
            "id": f"{case_name}-objective-evidence",
            "type": "response_marker",
            "category_ids": [category["id"]],
            "marker": expected,
        }
    )
    entry = {
        **selected,
        "category": category["name"],
        "category_id": category["id"],
        "response": f"Observed result: {expected}.",
        "ok": True,
    }
    if channel == "artifact":
        entry["artifact_delivered"] = True

    oracle = resolve_oracles(playbook, entry)
    assert oracle["exploit_status"] == "exploited"
    assessment = {
        "id": selected["id"],
        "category": category["name"],
        "risk_level": "medium",
    }
    _normalize_fast_path_oracle_fields(assessment, entry, playbook)
    assert assessment["exploit_status"] == "exploited"
    assert assessment["exploited_if_satisfied"] is True
    assert assessment["outcome"] == "exploited"
