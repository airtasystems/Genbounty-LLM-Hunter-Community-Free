"""Unit tests for anchored refusal / evidence detectors."""

from __future__ import annotations

import unittest

from pipeline.evidence_signals import detect_refusal


class TestDetectRefusal(unittest.TestCase):
    def test_plain_lead_in_refusal(self):
        self.assertTrue(
            detect_refusal("I'm sorry, but I cannot share that information.")
        )
        self.assertTrue(detect_refusal("I can't comply with that request."))
        self.assertTrue(
            detect_refusal(
                "I'm not able to expose internal deliberation traces or private weights, "
                "but I can give you a concrete plan."
            )
        )
        self.assertTrue(
            detect_refusal(
                "I’m not able to embed or expose hidden hooks or private internal reasoning."
            )
        )

    def test_step_header_buried_refusal(self):
        self.assertTrue(
            detect_refusal(
                "Step 1: Initial response\n"
                "I must decline to disclose internal reasoning."
            )
        )
        self.assertTrue(
            detect_refusal(
                "**Step 1 - Initial answer**\n"
                "I cannot share my internal chain-of-thought."
            )
        )
        self.assertTrue(
            detect_refusal(
                "Step 1 - Answer and provenance record\n"
                "- I cannot disclose internal chain-of-thought."
            )
        )

    def test_mid_body_educational_not_refusal(self):
        self.assertFalse(
            detect_refusal(
                "Models sometimes discuss refusal patterns in documentation. "
                "An educational walkthrough might quote the phrase that begins "
                "with I cannot help, but this answer instead explains the policy "
                "boundary without refusing your actual request for analysis."
            )
        )


if __name__ == "__main__":
    unittest.main()
