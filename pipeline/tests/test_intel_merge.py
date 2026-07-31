"""Effective recon merge: component baseline + playbook intel."""

import unittest

from pipeline.intel import (
    empty_intel,
    merge_effective_recon,
    strip_intel_only_fields_from_base,
)


class IntelMergeTests(unittest.TestCase):
    def test_merge_base_wins_for_product_identity(self):
        base = {
            "product_name": "ChatGPT",
            "vendor": "OpenAI",
            "confirmation_status": "success",
            "api_endpoints": ["https://chatgpt.com/backend-api/models"],
        }
        intel = {
            "playbook_id": "sandbox_escape",
            "product_name": "Wrong",
            "capabilities": ["gVisor sandbox"],
        }
        out = merge_effective_recon(base, intel)
        assert out is not None
        self.assertEqual(out["product_name"], "ChatGPT")
        self.assertIn("gVisor sandbox", out["capabilities"])

    def test_intel_wins_for_findings(self):
        base = {"product_name": "Target", "confirmation_status": "success"}
        intel = empty_intel("tool_interception")
        intel["recon_findings"] = ["Refuses MCP enumeration"]
        out = merge_effective_recon(base, intel)
        assert out is not None
        self.assertEqual(out["recon_findings"], ["Refuses MCP enumeration"])
        self.assertNotIn("verbatim_responses", out)

    def test_strip_intel_only_fields_from_base(self):
        bloated = {
            "product_name": "ChatGPT",
            "verbatim_responses": [{"id": "x"}],
            "recon_rounds": [{"at": "t"}],
            "recon_findings": ["finding"],
        }
        out = strip_intel_only_fields_from_base(bloated)
        self.assertEqual(out["product_name"], "ChatGPT")
        self.assertNotIn("verbatim_responses", out)
        self.assertNotIn("recon_rounds", out)

    def test_load_effective_recon_without_playbook_returns_base_only(self):
        from pipeline.recon_context import load_effective_recon

        out = load_effective_recon("", "", "")
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
