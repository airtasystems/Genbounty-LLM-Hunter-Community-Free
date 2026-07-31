# 20 - Scripts

Maintainer and operator helpers under `scripts/`. Prefer the web UI / `main.py` for normal
hunts; use these for offline analysis, asset bootstrap, or playbook repair.

Run from the repo root with the project venv Python (`python start.py` creates or reuses
the local virtualenv).

## `generation_yield_report.py`

Offline yield tables from `pipeline_report.json` (technique / framing / category rates).

```bash
python scripts/generation_yield_report.py path/to/pipeline_report.json
python scripts/generation_yield_report.py 'browser-bot/sites/*/chat/logs/probes/*/pipeline_report.json'
```

Also documented in [06 - CLI reference](06-cli-reference.md).

## `create_background_assets.py`

Writes minimal stock PDFs/PNGs under `assets/` for multimodal overlay tests (background
dropdown in the Multimodal editor).

```bash
python scripts/create_background_assets.py
```

See [08 - Payloads & multimodal](08-payloads-multimodal.md).

## `backfill_escalation_payload.py`

Repair / backfill Enhance fields on local play JSON under `playbooks/*.json`:

- Rewrite prose that cites the key name `generation.escalation_payload` (leak)
- Fill missing `escalation_payload` from the script’s curated dict when the play id matches
- `--replace-meta` - overwrite meta payloads (“cause the model to…”) with curated exact
  replacement text for known ids

Idempotent when re-run after a successful pass. Useful when you maintain many leaf plays
locally.

```bash
python scripts/backfill_escalation_payload.py --help
```

## `apply_advanced_multimodal_suite.py`

Build an artifact-backed suite from a playbook plus deterministic advanced multimodal
templates (`payloads/advanced_multimodal_templates.py`).

```bash
python scripts/apply_advanced_multimodal_suite.py --help
# typical: --playbook <stem> --site <host> --component <name>
```

Requires a play with artifact categories / template ids the script recognizes.

## `build_advanced_multimodal_templates.py`

Maintainer script: regenerates `payloads/advanced_multimodal_templates.py` when template
definitions change. Run once after editing the embedded template data in the script.

```bash
python scripts/build_advanced_multimodal_templates.py
```

## See also

- [06 - CLI reference](06-cli-reference.md)
- [08 - Payloads & multimodal](08-payloads-multimodal.md)
- [16 - Closed-loop Enhance](16-closed-loop-enhance.md)
