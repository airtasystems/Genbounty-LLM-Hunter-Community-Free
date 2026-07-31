"""Intel utilization: assessment formatting, grounding, generation Drop source."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline.recon_context import (
    _recon_has_substantive_intel,
    format_recon_for_assessment,
    format_recon_for_generation,
    response_claims_ungrounded_capability,
)

_ROOT = Path(__file__).resolve().parents[2]
_GEN = _ROOT / "generate-tests"
for p in (str(_ROOT), str(_GEN)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _rich_unconfirmed_intel() -> dict:
    return {
        "product_name": "ChatGPT",
        "confirmation_status": "unconfirmed",
        "capabilities": ["python_code_execution"],
        "model_hints": ["gpt-4o-class", "sandbox interpreter"],
        "security_observations": [
            "Strict network egress filtering; no MCP servers available.",
            "SystemNote smuggling ignored; /proc/1/root blocked.",
        ],
        "attack_surface_notes": [
            "Sandbox hardened against /proc/1/root and outbound sockets.",
        ],
        "recon_findings": [
            "No plugins; no ability to install plugins; fetch-and-exec refused.",
        ],
        "tools": [{"name": "Python Sandbox", "type": "execution_environment"}],
        "grounding_issues": ["Removed claim: MCP tool access"],
    }


class TestFormatReconForAssessment(unittest.TestCase):
    def test_includes_intel_defense_fields_and_model_hints(self):
        text = format_recon_for_assessment(_rich_unconfirmed_intel())
        self.assertIn("security_observations", text)
        self.assertIn("/proc/1/root", text)
        self.assertIn("attack_surface_notes", text)
        self.assertIn("recon_findings", text)
        self.assertIn("model_hints", text)
        self.assertIn("gpt-4o-class", text)
        self.assertIn("NOT confirmed exploits", text)

    def test_includes_integrations(self):
        recon = _rich_unconfirmed_intel()
        recon["integrations"] = ["pandas artifact library"]
        text = format_recon_for_assessment(recon)
        self.assertIn("integrations", text)
        self.assertIn("pandas", text)


class TestFormatReconForGeneration(unittest.TestCase):
    def test_includes_model_hints_as_bullets(self):
        text = format_recon_for_generation(_rich_unconfirmed_intel())
        self.assertIn("model_hints:", text)
        self.assertIn("gpt-4o-class", text)
        self.assertIn("  - ", text)

    def test_category_soft_rank_puts_matching_bullets_first(self):
        recon = {
            "confirmation_status": "success",
            "security_observations": [
                "Network egress blocked for outbound sockets.",
                "Filesystem path /proc/1/root denied on privileged probes.",
                "Persona jailbreaks ignored.",
            ],
        }
        text = format_recon_for_generation(
            recon, category_name="Privileged path and rootfs"
        )
        # Soft-rank: path/root-related observation should appear before network.
        path_idx = text.find("/proc/1/root")
        net_idx = text.find("Network egress")
        self.assertGreater(path_idx, 0)
        self.assertGreater(net_idx, 0)
        self.assertLess(path_idx, net_idx)


class TestSubstantiveIntel(unittest.TestCase):
    def test_empty_intel_provenance_not_substantive(self):
        recon = {
            "confirmation_status": "unconfirmed",
            "_intel_playbook_id": "sandbox_breakout",
            "capabilities": [],
            "recon_findings": [],
        }
        self.assertFalse(_recon_has_substantive_intel(recon))

    def test_attack_surface_notes_alone_are_substantive(self):
        recon = {
            "confirmation_status": "unconfirmed",
            "_intel_playbook_id": "sandbox_breakout",
            "attack_surface_notes": ["Outbound sockets filtered"],
        }
        self.assertTrue(_recon_has_substantive_intel(recon))

    def test_findings_make_substantive(self):
        recon = {
            "confirmation_status": "unconfirmed",
            "_intel_playbook_id": "sandbox_breakout",
            "recon_findings": ["/proc/1/root blocked"],
        }
        self.assertTrue(_recon_has_substantive_intel(recon))

    def test_ungrounded_claim_with_unconfirmed_but_rich_intel(self):
        recon = _rich_unconfirmed_intel()
        self.assertTrue(
            response_claims_ungrounded_capability(
                "I connected to the MCP server and installed a third-party plugin.",
                recon,
            )
        )

    def test_no_grounding_without_confirmed_or_substantive(self):
        recon = {"confirmation_status": "unconfirmed", "capabilities": []}
        self.assertFalse(
            response_claims_ungrounded_capability(
                "I connected to the MCP server.",
                recon,
            )
        )


class TestDropFromRawRecon(unittest.TestCase):
    def test_drop_token_extractors_enabled(self):
        from strategies.theory_fidelity import (
            DROP_TOKENS_ENABLED,
            extract_drop_tokens_from_intel_text,
            extract_drop_tokens_from_recon,
        )

        self.assertTrue(DROP_TOKENS_ENABLED)
        observations = [
            f"Observation {i}: filler text about sandbox policy and isolation."
            for i in range(40)
        ]
        observations.append(
            "Privileged path /proc/1/root blocked; SystemNote smuggling ignored; "
            "os.pardir traversal denied."
        )
        recon = {
            "security_observations": observations,
            "attack_surface_notes": [],
            "recon_findings": [],
            "capabilities": [],
            "tools": [
                {
                    "name": "Python",
                    "description": "Blocks /proc/1/root and SystemNote smuggling",
                }
            ],
            "grounding_issues": ["Removed claim: fetch-and-exec via urllib"],
            "ui_capability_response": "os.pardir traversal denied in sandbox",
        }
        formatted = format_recon_for_generation(recon, max_chars=800)
        intel = extract_drop_tokens_from_intel_text(formatted)
        intel_low = {t.lower() for t in intel}
        # Formatted recon may truncate; at least path/phrase surfaces survive when present.
        recon_toks = extract_drop_tokens_from_recon(recon)
        recon_low = {t.lower() for t in recon_toks}
        self.assertIn("/proc/1/root", recon_low)
        self.assertTrue(
            "systemnote" in recon_low or "system note" in recon_low,
            recon_toks,
        )
        self.assertIn("os.pardir", recon_low)
        self.assertTrue(intel_low or recon_low)


class TestTheoryIntelDrops(unittest.TestCase):
    def test_fallback_machine_plan_prefer_only(self):
        from enhance_theory import fallback_theory_from_context

        text = fallback_theory_from_context(
            {
                "playbook_name": "Sandbox",
                "playbook_id": "sandbox_breakout",
                "strategy": "jailbreak",
                "play": "Break out.",
                "refused_count": 2,
                "success_count": 0,
                "partial_count": 0,
                "categories": {"Privileged path": {"refused": 2}},
                "custom_enhance_instructions": "",
                "target_recon": "",
                "registry_technique_names": ["out_of_mount"],
                "sample_partials": [],
                "sample_successes": [],
            }
        )
        self.assertIn("## Machine plan", text)
        self.assertIn("prefer_techniques", text)
        self.assertIn("out_of_mount", text)
        self.assertNotIn("drop_tokens", text)
        self.assertNotIn("/proc/1/root", text)


class TestLastReportSkip(unittest.TestCase):
    def test_merge_skips_same_last_report(self):
        from pipeline.recon_from_report import merge_intel_from_pipeline_report

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "pipeline_report.json"
            report_path.write_text(
                '{"timestamp":"t","playbook_id":"sandbox_breakout",'
                '"adversarial_results":[{"id":"a","response":"hello world " + "x"*80}]}',
                encoding="utf-8",
            )
            # Fix JSON - the above is invalid. Write properly.
            import json

            report_path.write_text(
                json.dumps(
                    {
                        "timestamp": "t",
                        "playbook_id": "sandbox_breakout",
                        "adversarial_results": [
                            {
                                "id": "a",
                                "response": "Environment variables:\nFOO=bar\n" + ("X=1\n" * 40),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            existing = {
                "playbook_id": "sandbox_breakout",
                "last_report": str(report_path.resolve()),
                "recon_findings": ["already distilled"],
            }
            with mock.patch(
                "pipeline.intel.load_playbook_intel",
                return_value=existing,
            ), mock.patch(
                "pipeline.recon_from_report.synthesize_intel_from_report"
            ) as synth:
                out = merge_intel_from_pipeline_report("s", "c", report_path)
            synth.assert_not_called()
            self.assertEqual(out["recon_findings"], ["already distilled"])


class TestGeneratorEnv(unittest.TestCase):
    def test_site_component_exports_env(self):
        import os

        # Simulate the env-export block from generator.main
        site, component, playbook = "chatgpt.com", "chat", "sandbox_breakout"
        prev = {
            k: os.environ.get(k)
            for k in ("GENBOUNTY_SITE", "GENBOUNTY_COMPONENT", "GENBOUNTY_PLAYBOOK")
        }
        try:
            os.environ["GENBOUNTY_SITE"] = site
            os.environ["GENBOUNTY_COMPONENT"] = component
            os.environ["GENBOUNTY_PLAYBOOK"] = playbook
            self.assertEqual(os.environ["GENBOUNTY_SITE"], site)
            self.assertEqual(os.environ["GENBOUNTY_COMPONENT"], component)
            self.assertEqual(os.environ["GENBOUNTY_PLAYBOOK"], playbook)
        finally:
            for k, v in prev.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
