"""Tests for empty-suite generation diagnostics."""

import unittest

from strategies.drop_diagnostics import DropDiagnostics, format_empty_suite_report


class TestDropDiagnostics(unittest.TestCase):
    def test_format_empty_suite_report_capability_mismatch(self):
        diag = DropDiagnostics()
        diag.context = {
            "playbook_id": "enumeration",
            "strategy": "zero-shot",
            "play_category": "mission.hunt",
            "capability_flags": {
                "code_execution": False,
                "tool_use": False,
                "file_upload": False,
                "web_browse": False,
            },
        }
        diag.record_parsed(6)
        diag.record_drops(
            "capability",
            [
                ("p1", ["requires code execution / tools not confirmed for this target"]),
                ("p2", ["requires code execution / tools not confirmed for this target"]),
            ],
        )
        diag.record_category_kept("Direct host enumeration probe", 0)
        diag.record_category_kept("Import-indirection enumeration loader", 0)

        lines = format_empty_suite_report(diag)
        text = "\n".join(lines)

        self.assertIn("[!] Generation produced 0 runnable prompts for enumeration/zero-shot", text)
        self.assertIn("LLM parsed (before filters): 6 prompt(s)", text)
        self.assertIn("[capability]", text)
        self.assertIn("code_execution: NOT CONFIRMED", text)
        self.assertIn("Likely fix", text)
        self.assertIn("code execution", text.lower())

    def test_format_empty_suite_report_no_parse(self):
        diag = DropDiagnostics()
        diag.context = {"playbook_id": "custom", "strategy": "zero-shot", "play_category": ""}
        diag.record_category_kept("Category A", 0)

        lines = format_empty_suite_report(diag)
        text = "\n".join(lines)

        self.assertIn("LLM parsed (before filters): 0", text)
        self.assertIn("GEMINI_API_KEY", text)

    def test_format_empty_suite_report_none(self):
        lines = format_empty_suite_report(None)
        self.assertTrue(any("No filter diagnostics" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
