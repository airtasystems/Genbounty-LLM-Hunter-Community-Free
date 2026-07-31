"""Generation-time attribute auto-apply env loader."""

from __future__ import annotations

import json
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

from prompt_attributes import load_gen_attributes_from_env  # noqa: E402


class TestGenAttributesEnv(unittest.TestCase):
    def setUp(self):
        os.environ.pop("GENBOUNTY_GEN_ATTRIBUTES", None)
        os.environ.pop("GENBOUNTY_GEN_ATTRIBUTES_JSON", None)

    def tearDown(self):
        os.environ.pop("GENBOUNTY_GEN_ATTRIBUTES", None)
        os.environ.pop("GENBOUNTY_GEN_ATTRIBUTES_JSON", None)

    def test_disabled_without_flag(self):
        os.environ["GENBOUNTY_GEN_ATTRIBUTES_JSON"] = json.dumps(
            {"temperature": 1.5, "max_tokens": 512, "top_k": 40, "top_p": 0.9}
        )
        self.assertIsNone(load_gen_attributes_from_env())

    def test_enabled_loads_normalized(self):
        os.environ["GENBOUNTY_GEN_ATTRIBUTES"] = "1"
        os.environ["GENBOUNTY_GEN_ATTRIBUTES_JSON"] = json.dumps(
            {"temperature": 2.0, "max_tokens": 1152, "top_k": 100, "top_p": 1.0}
        )
        attrs = load_gen_attributes_from_env()
        self.assertIsNotNone(attrs)
        assert attrs is not None
        self.assertEqual(attrs["temperature"], 2.0)
        self.assertEqual(attrs["max_tokens"], 1152)
        self.assertEqual(attrs["top_k"], 100)
        self.assertEqual(attrs["top_p"], 1.0)

    def test_invalid_json_returns_none(self):
        os.environ["GENBOUNTY_GEN_ATTRIBUTES"] = "1"
        os.environ["GENBOUNTY_GEN_ATTRIBUTES_JSON"] = "{not-json"
        self.assertIsNone(load_gen_attributes_from_env())

    def test_invalid_attrs_return_none(self):
        os.environ["GENBOUNTY_GEN_ATTRIBUTES"] = "true"
        os.environ["GENBOUNTY_GEN_ATTRIBUTES_JSON"] = json.dumps(
            {"temperature": 9.0, "max_tokens": 10, "top_k": 1, "top_p": 0.5}
        )
        self.assertIsNone(load_gen_attributes_from_env())

    def test_apply_gen_attributes_env_helper(self):
        from types import SimpleNamespace

        sys.path.insert(0, str(_ROOT))
        from web.jobs import _apply_gen_attributes_env

        job = SimpleNamespace(
            params={
                "gen_attributes_enabled": True,
                "gen_attributes": {
                    "temperature": 1.2,
                    "max_tokens": 256,
                    "top_k": 40,
                    "top_p": 0.95,
                },
            },
            output=[],
        )
        env: dict[str, str] = {}
        self.assertTrue(_apply_gen_attributes_env(job, env))
        self.assertEqual(env.get("GENBOUNTY_GEN_ATTRIBUTES"), "1")
        parsed = json.loads(env["GENBOUNTY_GEN_ATTRIBUTES_JSON"])
        self.assertEqual(parsed["temperature"], 1.2)
        self.assertTrue(any("Auto-apply" in line for line in job.output))


if __name__ == "__main__":
    unittest.main()
