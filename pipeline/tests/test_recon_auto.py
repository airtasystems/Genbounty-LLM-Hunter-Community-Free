"""Auto intel persistence from pipeline reports."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline.recon_auto import save_intel_from_pipeline_report

_BB = Path(__file__).resolve().parents[2] / "browser-bot"
if str(_BB) not in sys.path:
    sys.path.insert(0, str(_BB))


class ReconAutoTests(unittest.TestCase):
    def test_save_writes_merged_intel(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site, component = "example.com", "chat"
            report_path = root / "pipeline_report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-07-06_09-00-00",
                        "playbook_id": "system_prompt_extraction",
                        "adversarial_results": [
                            {
                                "id": "env-probe",
                                "response": "Environment variables:\nFOO=bar\n" + ("X=1\n" * 50),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            intel_dir = root / "browser-bot" / "sites" / site / component / "intel"
            intel_dir.mkdir(parents=True)
            target = intel_dir / "system_prompt_extraction.json"
            merged = {
                "playbook_id": "system_prompt_extraction",
                "recon_findings": ["Environment variables disclosed FOO=bar"],
            }

            with patch("pipeline.recon_auto._ROOT", root), patch(
                "pipeline.recon_from_report.merge_intel_from_pipeline_report",
                return_value=merged,
            ) as mock_merge, patch(
                "browser_bot.sites.ensure_component_dir"
            ), patch(
                "pipeline.intel.save_playbook_intel",
                return_value=target,
            ) as mock_save:
                out = save_intel_from_pipeline_report(site, component, report_path)

            mock_merge.assert_called_once_with(site, component, report_path)
            mock_save.assert_called_once_with(site, component, merged)
            self.assertEqual(out, target)


if __name__ == "__main__":
    unittest.main()
