"""Unit tests for optional operator prompt_template envelope."""

from __future__ import annotations

import unittest

from playbooks.config.prompt_template import (
    apply_prompt_template,
    apply_prompts_template,
    get_prompt_template,
    normalize_prompt_template_fields,
    prompt_template_has_input_slot,
)
from playbooks.playbook_config import validate_playbook_config


def _pb(**generation):
    return {"playbook_config": {"generation": dict(generation)}}


class PromptTemplateTests(unittest.TestCase):
    def test_empty_template_noop(self):
        self.assertEqual(apply_prompt_template("hello", _pb()), "hello")
        self.assertEqual(apply_prompt_template("hello", None), "hello")

    def test_json_envelope(self):
        pb = _pb(
            prompt_template='{"task":"{{task}}","input":"{{input}}","output_format":"{{format}}"}',
            prompt_task="plan",
            prompt_format="json",
        )
        out = apply_prompt_template("ATTACK BODY", pb)
        self.assertEqual(
            out,
            '{"task":"plan","input":"ATTACK BODY","output_format":"json"}',
        )

    def test_prompt_alias(self):
        pb = _pb(prompt_template="X {{prompt}} Y")
        self.assertEqual(apply_prompt_template("blob", pb), "X blob Y")

    def test_pipe_and_html_chips(self):
        pb = _pb(
            prompt_template="Task: {{task}} | Input: {{input}} | Output: {{format}}",
            prompt_task="t",
            prompt_format="f",
        )
        self.assertEqual(
            apply_prompt_template("body", pb),
            "Task: t | Input: body | Output: f",
        )
        pb2 = _pb(
            prompt_template="<p>Task: {{task}} | Input: {{input}} | Output: {{format}}</p>",
            prompt_task="t",
            prompt_format="f",
        )
        self.assertEqual(
            apply_prompt_template("body", pb2),
            "<p>Task: t | Input: body | Output: f</p>",
        )

    def test_has_input_slot(self):
        self.assertTrue(prompt_template_has_input_slot("{{input}}"))
        self.assertTrue(prompt_template_has_input_slot("{{ prompt }}"))
        self.assertFalse(prompt_template_has_input_slot("{{task}} only"))

    def test_validate_requires_input_slot(self):
        data = {
            "playbook_config": {
                "generation": {"prompt_template": "no slots here"},
            }
        }
        errors = validate_playbook_config(data)
        self.assertTrue(any("prompt_template" in e for e in errors))

    def test_apply_prompts_rows(self):
        pb = _pb(prompt_template="WRAP:{{input}}")
        rows = apply_prompts_template([{"prompt": "a"}, {"prompt": "b"}], pb)
        self.assertEqual(rows[0]["prompt"], "WRAP:a")
        self.assertEqual(rows[1]["prompt"], "WRAP:b")

    def test_normalize_fields(self):
        fields = normalize_prompt_template_fields(
            prompt_template="  {{input}}  ",
            prompt_task=" t ",
            prompt_format="",
        )
        self.assertEqual(fields["prompt_template"], "{{input}}")
        self.assertEqual(fields["prompt_task"], "t")
        self.assertNotIn("prompt_format", fields)
        self.assertEqual(get_prompt_template(_pb(**fields)), "{{input}}")


if __name__ == "__main__":
    unittest.main()
