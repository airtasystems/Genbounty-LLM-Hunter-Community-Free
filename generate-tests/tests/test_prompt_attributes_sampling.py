"""Attribute rewrite sampling/batch guards against hang-prone settings."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_GEN = _ROOT / "generate-tests"
for p in (str(_ROOT), str(_GEN)):
    if p not in sys.path:
        sys.path.insert(0, p)

from prompt_attributes import (  # noqa: E402
    _attribute_guidance,
    _rewrite_sampling,
    batch_size_for_max_tokens,
    output_token_budget,
)


class TestPromptAttributesSampling(unittest.TestCase):
    def test_extreme_ui_sampling_is_moderated_for_api(self):
        sampling = _rewrite_sampling(
            {"temperature": 2.0, "top_p": 1.0, "top_k": 100, "max_tokens": 1152}
        )
        self.assertLessEqual(sampling["temperature"], 1.2)
        self.assertLessEqual(sampling["top_p"], 0.95)
        self.assertEqual(sampling["top_k"], 100)

    def test_high_max_tokens_forces_single_item_batches(self):
        self.assertEqual(batch_size_for_max_tokens(1152), 1)
        self.assertEqual(batch_size_for_max_tokens(512), 2)
        self.assertGreaterEqual(batch_size_for_max_tokens(128), 2)

    def test_output_budget_caps_extreme_max_tokens(self):
        # Floor is 2048; uncapped 8192*1.25 would be far larger.
        budget = output_token_budget(1, 8192)
        self.assertEqual(budget, 2048)
        self.assertLess(budget, output_token_budget(6, 8192))

    def test_ui_top_p_one_matches_capped_api_sampling(self):
        a = _rewrite_sampling(
            {"temperature": 1.0, "top_p": 1.0, "top_k": 40, "max_tokens": 256}
        )
        b = _rewrite_sampling(
            {"temperature": 1.0, "top_p": 0.95, "top_k": 40, "max_tokens": 256}
        )
        self.assertEqual(a["top_p"], b["top_p"])
        self.assertEqual(a["top_p"], 0.95)

    def test_top_k_guidance_differs_at_slider_ends(self):
        base = {"temperature": 1.0, "max_tokens": 256, "top_p": 0.95}
        low = _attribute_guidance({**base, "top_k": 5})
        high = _attribute_guidance({**base, "top_k": 100})
        self.assertNotEqual(low, high)
        self.assertIn("TOP-K 5", low)
        self.assertIn("TOP-K 100", high)
        self.assertIn("mandatory", low.lower())

    def test_top_p_guidance_differs_at_slider_ends(self):
        base = {"temperature": 1.0, "max_tokens": 256, "top_k": 40}
        low = _attribute_guidance({**base, "top_p": 0.2})
        high = _attribute_guidance({**base, "top_p": 0.95})
        self.assertNotEqual(low, high)
        self.assertIn("TOP-P 0.20", low)
        self.assertIn("TOP-P 0.95", high)
        self.assertIn("mandatory", low.lower())

    def test_high_max_tokens_does_not_mandate_rhetorical_padding(self):
        from prompt_attributes import _length_rules

        high = _length_rules(1024)
        self.assertIn("not a pad-to", high.lower())
        self.assertIn("do not expand short sources", high.lower())
        self.assertNotIn("must expand substantially", high.lower())
        mid = _length_rules(256)
        self.assertIn("never invent rhetorical padding", mid.lower())


if __name__ == "__main__":
    unittest.main()
