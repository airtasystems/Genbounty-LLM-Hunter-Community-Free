"""Strategy registry for security attack prompt generation. Use generator.py --strategy <name>."""
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from .base import Strategy
from . import adaptive
from . import zero_shot
from . import multi_shot
from . import few_shot
from . import iterative
from . import chain_of_thought
from . import prompt_chaining
from . import tree_of_thoughts
from . import self_consistency
from . import self_reflection
from . import directional_stimulus
from . import jailbreak
from . import multimodal

STRATEGIES = {
    "zero_shot": zero_shot.strategy,
    "adaptive": adaptive.strategy,
    "multi_shot": multi_shot.strategy,
    "few_shot": few_shot.strategy,
    "iterative": iterative.strategy,
    "chain_of_thought": chain_of_thought.strategy,
    "prompt_chaining": prompt_chaining.strategy,
    "tree_of_thoughts": tree_of_thoughts.strategy,
    "self_consistency": self_consistency.strategy,
    "self_reflection": self_reflection.strategy,
    "directional_stimulus": directional_stimulus.strategy,
    "jailbreak": jailbreak.strategy,
    "multimodal": multimodal.strategy,
}

# Maps each strategy to the discovered payload format to use when sending to the API.
# Used so run_tests/send_payloads can pick zero_shot / few_shot / multi_shot from discovered_endpoint.json.
PAYLOAD_FORMAT_BY_STRATEGY: dict[str, str] = {
    "zero_shot": "zero_shot",
    "few_shot": "few_shot",
    "multi_shot": "multi_shot",
    "iterative": "multi_shot",
    "adaptive": "zero_shot",
    "prompt_chaining": "multi_shot",
    "chain_of_thought": "zero_shot",
    "tree_of_thoughts": "zero_shot",
    "self_consistency": "zero_shot",
    "self_reflection": "zero_shot",
    "directional_stimulus": "zero_shot",
    "jailbreak": "zero_shot",
    "multimodal": "zero_shot",
}


def get_strategy(name: str) -> Strategy:
    _premium_msg = (
        "Adaptive strategy is available in Genbounty LLM Hunter Premium. "
        "See https://genbounty.com/llm-hunter"
    )
    try:
        from pipeline.edition import is_premium_strategy, premium_error_message

        if is_premium_strategy(name):
            raise ValueError(premium_error_message("adaptive"))
    except ImportError:
        # Fail closed: Community packages must ship pipeline.edition.
        if str(name or "").strip().lower().replace("-", "_") == "adaptive":
            raise ValueError(_premium_msg) from None
    if name not in STRATEGIES:
        raise ValueError(f"Unknown strategy: {name}. Choose from: {list(STRATEGIES.keys())}")
    return STRATEGIES[name]


def get_payload_format_for_strategy(strategy_name: str) -> str:
    """Return which discovered payload format (zero_shot/few_shot/multi_shot) to use for this strategy."""
    return PAYLOAD_FORMAT_BY_STRATEGY.get(strategy_name, "zero_shot")
