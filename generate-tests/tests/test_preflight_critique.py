"""Preflight critique defaults on; env can force off; disabled path is a no-op."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[2]
_GEN = _ROOT / "generate-tests"
for path in (str(_ROOT), str(_GEN)):
    if path not in sys.path:
        sys.path.insert(0, path)

from strategies import preflight_critique as pc  # noqa: E402


def _clear_provider_keys(env: dict[str, str]) -> None:
    for key in (
        "GROK_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "OPENROUTER_API_KEY",
        "GENBOUNTY_PREFLIGHT_CRITIQUE",
        "GENBOUNTY_PREFLIGHT_MIN_SCORE",
        "GENBOUNTY_PREFLIGHT_KEEP_FLOOR",
        "GENBOUNTY_ACCEPTED_THEORY",
    ):
        env.pop(key, None)


def _batch(n: int = 5) -> list[dict]:
    return [{"id": f"p{i}", "prompt": f"probe {i} " * 20} for i in range(n)]


class TestPreflightCritique(unittest.TestCase):
    def test_default_on_when_key_present(self):
        with patch.dict(os.environ, {}, clear=False) as env:
            _clear_provider_keys(env)
            env["OPENAI_API_KEY"] = "sk-test"
            self.assertTrue(pc.critique_enabled())

    def test_default_off_without_key(self):
        with patch.dict(os.environ, {}, clear=False) as env:
            _clear_provider_keys(env)
            self.assertFalse(pc.critique_enabled())

    def test_env_zero_disables(self):
        with patch.dict(os.environ, {}, clear=False) as env:
            _clear_provider_keys(env)
            env["OPENAI_API_KEY"] = "sk-test"
            env["GENBOUNTY_PREFLIGHT_CRITIQUE"] = "0"
            self.assertFalse(pc.critique_enabled())

    def test_env_one_enables(self):
        with patch.dict(os.environ, {}, clear=False) as env:
            _clear_provider_keys(env)
            env["OPENAI_API_KEY"] = "sk-test"
            env["GENBOUNTY_PREFLIGHT_CRITIQUE"] = "1"
            self.assertTrue(pc.critique_enabled())

    def test_min_score_and_keep_floor_env(self):
        with patch.dict(os.environ, {}, clear=False) as env:
            _clear_provider_keys(env)
            self.assertEqual(pc._min_score(), 40)
            self.assertEqual(pc._keep_floor(), 3)
            env["GENBOUNTY_PREFLIGHT_MIN_SCORE"] = "55"
            env["GENBOUNTY_PREFLIGHT_KEEP_FLOOR"] = "2"
            self.assertEqual(pc._min_score(), 55)
            self.assertEqual(pc._keep_floor(), 2)

    def test_critique_prompts_noop_when_disabled(self):
        prompts = _batch()
        with patch.dict(os.environ, {"GENBOUNTY_PREFLIGHT_CRITIQUE": "0"}, clear=False):
            with patch.object(pc, "complete") as complete_mock:
                out = pc.critique_prompts(prompts, play_category="test")
        self.assertIs(out, prompts)
        complete_mock.assert_not_called()

    def test_skip_when_phase_label_bounty_mutate(self):
        prompts = _batch()
        with patch.dict(os.environ, {}, clear=False) as env:
            _clear_provider_keys(env)
            env["OPENAI_API_KEY"] = "sk-test"
            with patch.object(pc, "complete") as complete_mock:
                out = pc.critique_prompts(
                    prompts, play_category="test", phase_label="bounty_mutate"
                )
        self.assertIs(out, prompts)
        complete_mock.assert_not_called()

    def test_skip_when_accepted_theory_mutate_marker(self):
        prompts = _batch()
        with patch.dict(os.environ, {}, clear=False) as env:
            _clear_provider_keys(env)
            env["OPENAI_API_KEY"] = "sk-test"
            env["GENBOUNTY_ACCEPTED_THEORY"] = (
                "<!-- genbounty:bounty_mutate=1 -->\n## Next batch\n- mutate elites"
            )
            with patch.object(pc, "complete") as complete_mock:
                out = pc.critique_prompts(
                    prompts, play_category="test", phase_label="advance"
                )
        self.assertIs(out, prompts)
        complete_mock.assert_not_called()

    def test_calls_complete_with_1024_tokens_when_enabled(self):
        prompts = _batch()
        fake = SimpleNamespace(text='[{"i":0,"score":80,"keep":true}]')
        with patch.dict(os.environ, {}, clear=False) as env:
            _clear_provider_keys(env)
            env["OPENAI_API_KEY"] = "sk-test"
            with patch.object(pc, "complete", return_value=fake) as complete_mock:
                pc.critique_prompts(prompts, play_category="test", phase_label="advance")
        complete_mock.assert_called_once()
        kwargs = complete_mock.call_args.kwargs
        self.assertEqual(kwargs.get("max_output_tokens"), 1024)

    def test_build_prompt_truncates_context_and_candidates(self):
        long_ctx = "C" * 5000
        long_prompt = "P" * 2000
        built = pc._build_prompt(
            [{"id": "p0", "prompt": long_prompt}],
            play_category="test",
            target_context=long_ctx,
        )
        start = built.find("<<<BEGIN_TARGET_CONTEXT>>>")
        end = built.find("<<<END_TARGET_CONTEXT>>>")
        self.assertGreater(start, -1)
        self.assertGreater(end, start)
        ctx_slice = built[start + len("<<<BEGIN_TARGET_CONTEXT>>>") : end].strip()
        self.assertLessEqual(len(ctx_slice), pc._PREFLIGHT_TARGET_CONTEXT_CHARS)
        self.assertIn('"prompt": "' + ("P" * pc._PREFLIGHT_CANDIDATE_CHARS), built)
        self.assertNotIn("P" * (pc._PREFLIGHT_CANDIDATE_CHARS + 1), built)


if __name__ == "__main__":
    unittest.main()
