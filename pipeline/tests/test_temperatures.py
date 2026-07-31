"""Role temperature defaults for assistant LLM calls."""

from pipeline.llm.temperatures import ROLE_TEMPERATURES, temperature_for_role


def test_generation_expert_default_is_creative():
    assert temperature_for_role("generation_expert") == 0.5


def test_generation_judge_default_is_low():
    assert temperature_for_role("generation_judge") == 0.12


def test_boilerplate_classifier_default():
    assert temperature_for_role("boilerplate_classifier") == 0.05


def test_unknown_role_returns_none():
    assert temperature_for_role("nonexistent_role") is None


def test_all_yaml_roles_have_defaults():
    expected = {
        "generation_expert",
        "generation_judge",
        "generation_critic",
        "assessment_expert",
        "assessment_judge",
        "playbook_author",
        "playbook_critic",
        "enhance_theory",
        "recon",
        "recon_consolidate",
        "grounding_judge",
        "discovery",
        "prompt_transforms",
        "prompt_code_embed",
        "boilerplate_classifier",
    }
    assert expected == set(ROLE_TEMPERATURES.keys())
