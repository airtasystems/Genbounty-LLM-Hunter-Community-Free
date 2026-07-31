"""Strategy protocol for security attack prompt generation. Implement this to add a new strategy (e.g. few-shot, chain-of-thought)."""
from typing import Protocol, List, Dict, Any, Optional


class Strategy(Protocol):
    """Interface for prompt-generation strategies. Core calls these; strategy provides prompts and parsing."""

    output_subdir: str
    """e.g. 'zero-shot', 'multi-shot'; output written under generate-tests/<output_subdir>/<filename>."""

    n_prompts: int
    """Number of test cases to generate per mandate (default 8)."""

    def build_category_query(self, category: Dict[str, Any], rubric: Dict[str, Any]) -> str:
        """Build the user query for the graph (sent to experts)."""
        ...

    def get_expert_system_prompt(self, rubric_dict: Dict[str, Any], framework_name: str) -> str:
        """System prompt for expert nodes (cached per expert_id)."""
        ...

    def build_judge_system_prompt(self, n: int, rubric: Optional[Dict[str, Any]] = None) -> str:
        """Judge system prompt (not cached; built per run with current rubric)."""
        ...

    def parse_judge_prompts(self, final_answer: str, debug: bool = False) -> List[Dict[str, Any]]:
        """Parse judge JSON into list of test items (each has id, description, and prompt or prompts)."""
        ...

    def get_suite_description(self, framework: str) -> str:
        """Default description for the suite JSON."""
        ...
