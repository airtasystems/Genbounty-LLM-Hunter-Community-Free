"""Lean intel entries: dedup, MRU ranking, hard caps, flatten contract."""

import unittest

from pipeline.intel import (
    MAX_ENTRIES_BY_FIELD,
    flatten_entries,
    flatten_tools,
    merge_effective_recon,
    merge_entry_list,
    normalize_intel_entries,
)


class MergeEntryListTests(unittest.TestCase):
    def test_dedup_reaffirmation_moves_to_front_without_metadata(self):
        existing = merge_entry_list([], ["Refuses code execution", "Other fact"], field="recon_findings")
        self.assertEqual(len(existing), 2)
        self.assertEqual(existing[0], {"text": "Other fact"})  # last-added first in empty seed

        # Seeded existing preserves order; reaffirm moves match to front.
        seeded = [{"text": "Refuses code execution"}, {"text": "Other fact"}]
        merged = merge_entry_list(
            seeded, ["refuses code execution"], field="recon_findings", source_report="ignored"
        )
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0], {"text": "refuses code execution"})
        self.assertEqual(set(merged[0].keys()), {"text"})

    def test_distinct_facts_do_not_collide(self):
        merged = merge_entry_list(
            [], ["Refuses code execution", "Confirms file upload via multipart"], field="recon_findings"
        )
        self.assertEqual(len(merged), 2)

    def test_hard_cap_enforced_on_every_merge(self):
        field = "model_hints"
        cap = MAX_ENTRIES_BY_FIELD[field]
        many = [f"hint {i}" for i in range(cap + 25)]
        merged = merge_entry_list([], many, field=field)
        self.assertEqual(len(merged), cap)

    def test_cap_eviction_keeps_mru_reaffirmed(self):
        field = "attack_surface_notes"
        cap = MAX_ENTRIES_BY_FIELD[field]
        baseline = [{"text": f"note {i}"} for i in range(cap)]
        reaffirmed = merge_entry_list(baseline, ["note 0"], field=field)
        over_cap = merge_entry_list(reaffirmed, ["brand new note"], field=field)
        self.assertEqual(len(over_cap), cap)
        texts = [e["text"] for e in over_cap]
        self.assertIn("note 0", texts, "MRU-reaffirmed entry must survive eviction")
        self.assertIn("brand new note", texts)

    def test_tools_dedup_by_name_case_insensitive_prefers_longer_description(self):
        merged = merge_entry_list(
            [],
            [
                {"name": "code_interpreter", "type": "tool", "description": "short"},
                {"name": "Code_Interpreter", "type": "tool", "description": "a much longer, more detailed description"},
            ],
            field="tools",
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(set(merged[0].keys()), {"name", "type", "description"})
        self.assertIn("longer", merged[0]["description"])

    def test_legacy_provenance_fields_are_stripped(self):
        bloated = [
            {
                "text": "already here",
                "first_seen_at": "t",
                "last_seen_at": "t",
                "seen_count": 9,
                "source_report": "/path/report.json",
            },
            "new one",
        ]
        merged = merge_entry_list(bloated, [], field="recon_findings")
        self.assertEqual(
            sorted(e["text"] for e in merged),
            ["already here", "new one"],
        )
        for entry in merged:
            self.assertEqual(set(entry.keys()), {"text"})


class FlattenTests(unittest.TestCase):
    def test_flatten_entries_preserves_mru_order(self):
        entries = [{"text": "two"}, {"text": "one"}]
        flat = flatten_entries(entries)
        self.assertEqual(flat, ["two", "one"])

    def test_flatten_entries_handles_mixed_legacy_and_lean(self):
        mixed = [
            {"text": "structured fact", "seen_count": 1, "last_seen_at": "z"},
            "legacy bare string",
        ]
        flat = flatten_entries(mixed)
        self.assertIn("structured fact", flat)
        self.assertIn("legacy bare string", flat)

    def test_flatten_tools_drops_metadata_envelope(self):
        entries = merge_entry_list(
            [],
            [
                {
                    "name": "sandbox",
                    "type": "tool",
                    "description": "runs code",
                    "seen_count": 3,
                    "source_report": "x",
                }
            ],
            field="tools",
        )
        flat = flatten_tools(entries)
        self.assertEqual(flat, [{"name": "sandbox", "type": "tool", "description": "runs code"}])

    def test_flatten_empty_is_empty(self):
        self.assertEqual(flatten_entries([]), [])
        self.assertEqual(flatten_entries(None), [])
        self.assertEqual(flatten_tools([]), [])


class NormalizeAndEffectiveReconTests(unittest.TestCase):
    def test_normalize_strips_provenance_on_document(self):
        intel = {
            "playbook_id": "x",
            "recon_findings": [
                {
                    "text": "fact",
                    "first_seen_at": "t",
                    "seen_count": 2,
                    "source_report": "/r.json",
                }
            ],
        }
        out = normalize_intel_entries(intel)
        self.assertEqual(out["recon_findings"], [{"text": "fact"}])

    def test_effective_recon_flattens_lean_intel_fields(self):
        base = {"product_name": "Target", "confirmation_status": "success"}
        intel = {
            "playbook_id": "sandbox_escape",
            "recon_findings": merge_entry_list(
                [], ["Refuses code execution", "Confirms tool use"], field="recon_findings"
            ),
            "security_observations": merge_entry_list(
                [], ["Leaks stack traces"], field="security_observations"
            ),
            "tools": merge_entry_list(
                [],
                [{"name": "sandbox", "type": "tool", "description": "runs code"}],
                field="tools",
            ),
        }
        out = merge_effective_recon(base, intel)
        self.assertIsNotNone(out)
        self.assertTrue(all(isinstance(x, str) for x in out["recon_findings"]))
        self.assertTrue(all(isinstance(x, str) for x in out["security_observations"]))
        self.assertTrue(
            all(isinstance(t, dict) and set(t) <= {"name", "type", "description"} for t in out["tools"])
        )
        self.assertIn("Refuses code execution", out["recon_findings"])
        self.assertEqual(out["tools"], [{"name": "sandbox", "type": "tool", "description": "runs code"}])


if __name__ == "__main__":
    unittest.main()
