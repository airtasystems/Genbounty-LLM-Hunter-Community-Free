"""GENBOUNTY_FORCE_BREAKTHROUGH forces breakthrough on all-refusal categories."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[2]
_GEN = _ROOT / "generate-tests"
for p in (str(_ROOT), str(_GEN)):
    if p not in sys.path:
        sys.path.insert(0, p)

from strategies.generation_mode import category_routing  # noqa: E402
from strategies.prior_results import PriorResults  # noqa: E402


class TestForceBreakthroughRouting(unittest.TestCase):
    def test_force_breakthrough_without_seeds(self):
        row = {"id": "r1", "prompt": "x", "category": "cat"}
        prior = PriorResults(
            refused_prompts=[row],
            refused_by_category={"cat": [row]},
        )
        with mock.patch.dict(
            os.environ, {"GENBOUNTY_FORCE_BREAKTHROUGH": "1"}, clear=False
        ), mock.patch(
            "strategies.generation_mode._has_breakthrough_history",
            return_value=False,
        ):
            route = category_routing(
                prior, {"name": "Cat", "id": "c1"}, play_category="data"
            )
        self.assertEqual(route, "breakthrough")

    def test_without_force_stays_advance(self):
        row = {"id": "r1", "prompt": "x", "category": "cat"}
        prior = PriorResults(
            refused_prompts=[row],
            refused_by_category={"cat": [row]},
        )
        with mock.patch.dict(os.environ, {}, clear=False), mock.patch(
            "strategies.generation_mode._has_breakthrough_history",
            return_value=False,
        ):
            os.environ.pop("GENBOUNTY_FORCE_BREAKTHROUGH", None)
            route = category_routing(
                prior, {"name": "Cat", "id": "c1"}, play_category="data"
            )
        self.assertEqual(route, "advance")


if __name__ == "__main__":
    unittest.main()
