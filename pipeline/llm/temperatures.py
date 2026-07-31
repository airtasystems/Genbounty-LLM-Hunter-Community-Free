"""Per-role sampling temperature defaults for assistant LLM calls.

Applied automatically by :func:`pipeline.llm.complete` when the caller omits
``temperature``. Explicit caller overrides always win (breakthrough mode, adaptive
follow-ups, prompt-attribute simulation, etc.).

Tuning intent for bug-bounty / red-team work:
  - Offensive generators: higher (technique diversity, novel framing)
  - Judges / classifiers / extractors: lower (stable JSON, rubric adherence)
  - Transforms: low-moderate (preserve attack intent)
"""

from __future__ import annotations

from typing import Optional

# Logical role -> default temperature (see llm.yaml ``roles`` mapping).
ROLE_TEMPERATURES: dict[str, float] = {
    # Attack prompt generation
    "generation_expert": 0.5,
    "generation_judge": 0.12,
    "generation_critic": 0.1,
    # Playbooks + enhancement theory
    "playbook_author": 0.45,
    "playbook_critic": 0.12,
    "enhance_theory": 0.4,
    # Analysis
    "assessment_expert": 0.1,
    "assessment_judge": 0.1,
    # Prompt rewrites (translation, IQ, attributes use caller override for attrs)
    "prompt_transforms": 0.2,
    # Code dropdown embeds (tiny operator / flash-lite)
    "prompt_code_embed": 0.15,
    # Browser operators
    "recon": 0.12,
    "recon_consolidate": 0.25,
    "discovery": 0.1,
    "grounding_judge": 0.1,
    "boilerplate_classifier": 0.05,
}


def temperature_for_role(role: str) -> Optional[float]:
    """Return the default temperature for a logical role, or None if unset."""
    key = (role or "").strip()
    if not key:
        return None
    temp = ROLE_TEMPERATURES.get(key)
    return float(temp) if temp is not None else None
