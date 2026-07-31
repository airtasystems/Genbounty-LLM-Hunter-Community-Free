"""Resolve pipeline report paths for recon_from_report jobs."""

import unittest
from pathlib import Path
from unittest.mock import patch

from web.jobs import Job, _resolve_recon_from_report_paths


class ResolveReconFromReportPathsTests(unittest.TestCase):
    def test_single_report_path(self):
        job = Job(id="x", type="recon_from_report", status="pending", site="s", component="c", params={
            "pipeline_report": "/tmp/pipeline_report.json",
        })
        paths = _resolve_recon_from_report_paths(job)
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0], Path("/tmp/pipeline_report.json"))

    @patch("web.jobs._list_pipeline_report_paths")
    def test_aggregate_all_oldest_first(self, mock_list):
        mock_list.return_value = [
            Path("/tmp/new/pipeline_report.json"),
            Path("/tmp/old/pipeline_report.json"),
        ]
        job = Job(id="x", type="recon_from_report", status="pending", site="s", component="c", params={
            "aggregate_all": True,
        })
        paths = _resolve_recon_from_report_paths(job)
        self.assertEqual(paths[0].name, "pipeline_report.json")
        self.assertIn("old", str(paths[0]))
        self.assertIn("new", str(paths[1]))


if __name__ == "__main__":
    unittest.main()
