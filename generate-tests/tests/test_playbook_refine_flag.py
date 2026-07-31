"""Playbook critic refine is opt-in via env / skipped on rebuild by default."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[2]
_GEN = _ROOT / "generate-tests"
for path in (str(_ROOT), str(_GEN)):
    if path not in sys.path:
        sys.path.insert(0, path)

from playbook_generator import (  # noqa: E402
    PLAYBOOK_GENERATION_MAX_OUTPUT_TOKENS,
    _refine_enabled,
)


class TestPlaybookRefineFlag(unittest.TestCase):
    def test_output_token_budget_is_bounded(self):
        self.assertEqual(PLAYBOOK_GENERATION_MAX_OUTPUT_TOKENS, 8192)

    def test_default_create_runs_critic(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GENBOUNTY_PLAYBOOK_REFINE", None)
            self.assertTrue(_refine_enabled(rebuild_from_objective=False))

    def test_default_rebuild_skips_critic(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GENBOUNTY_PLAYBOOK_REFINE", None)
            self.assertFalse(_refine_enabled(rebuild_from_objective=True))

    def test_env_zero_skips_even_on_create(self):
        with patch.dict(os.environ, {"GENBOUNTY_PLAYBOOK_REFINE": "0"}):
            self.assertFalse(_refine_enabled(rebuild_from_objective=False))
            self.assertFalse(_refine_enabled(rebuild_from_objective=True))

    def test_env_one_forces_critic_on_rebuild(self):
        with patch.dict(os.environ, {"GENBOUNTY_PLAYBOOK_REFINE": "1"}):
            self.assertTrue(_refine_enabled(rebuild_from_objective=True))
            self.assertTrue(_refine_enabled(rebuild_from_objective=False))


if __name__ == "__main__":
    unittest.main()
