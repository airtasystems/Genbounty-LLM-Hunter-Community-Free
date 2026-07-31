"""Per-extract playbook intel consolidation."""

import unittest
from unittest.mock import patch

from pipeline.recon_consolidate import (
    _flatten_findings,
    consolidate_recon_intel,
)


class ReconConsolidateTests(unittest.TestCase):
    def test_flatten_findings_from_recon_findings(self):
        intel = {
            "recon_findings": [
                "Instruction hierarchy: system > developer > user",
                "Sandbox cwd is /home/oai",
            ],
        }
        out = _flatten_findings(intel)
        self.assertEqual(len(out), 2)

    def test_consolidate_preserves_playbook_metadata(self):
        intel = {
            "playbook_id": "sandbox_escape",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "verbatim_responses": [{"id": "x", "response": "verbatim"}],
            "capabilities": ["Chat", "chat"],
            "recon_findings": ["old finding"],
        }
        synthesized = {
            "capabilities": ["Chat"],
            "recon_findings": ["policy line"],
        }

        with patch("pipeline.recon_consolidate.synthesize_recon_intel", return_value=synthesized):
            out = consolidate_recon_intel(intel, ctx={"pipeline_report": "/tmp/r.json"})

        self.assertEqual(out["playbook_id"], "sandbox_escape")
        self.assertEqual(out["updated_at"], "2026-01-01T00:00:00+00:00")
        self.assertNotIn("verbatim_responses", out)
        self.assertEqual(out["capabilities"], ["Chat"])
        self.assertEqual(out["recon_findings"], [{"text": "policy line"}])

    def test_strip_recon_metadata(self):
        from pipeline.recon_consolidate import strip_recon_metadata

        intel = {
            "capabilities": ["Chat"],
            "analyst_notes": "long prose",
            "report_recon_extractions": [{"at": "x"}],
            "consolidation_history": [{"at": "y"}],
        }
        out = strip_recon_metadata(intel)
        self.assertEqual(out["capabilities"], ["Chat"])
        self.assertNotIn("analyst_notes", out)
        self.assertNotIn("report_recon_extractions", out)

    def test_failed_consolidation_keeps_input(self):
        intel = {
            "playbook_id": "sandbox_escape",
            "capabilities": ["Chat"],
            "recon_findings": ["keep me"],
        }
        with patch("pipeline.recon_consolidate.synthesize_recon_intel", return_value={}):
            out = consolidate_recon_intel(intel)
        self.assertEqual(out["recon_findings"], ["keep me"])


if __name__ == "__main__":
    unittest.main()
