# 07 — Settings, LLMs & data

Where secrets, models, and hunt files live.

## Secrets vs settings

| Where | What belongs there |
|-------|--------------------|
| `.env` | API keys only (never commit) |
| `llm.yaml` | Which provider/model each pipeline **role** uses |
| `pipeline_settings.yaml` | Batch sizes, cache toggles, export batching |
| Component `config.yaml` | How to drive this target (selectors or API) |

Edit keys and roles in the UI under **Settings → Configure LLMs**, or edit the files
directly. Copy `.env.example` → `.env` and `llm.yaml.example` → `llm.yaml` on first setup.

## LLM roles (what needs a key)

Only providers used by a role need keys (`GEMINI_API_KEY`, `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, `GROK_API_KEY`, `OPENROUTER_API_KEY`, …).

| Role | Used for |
|------|----------|
| `generation_expert` / `generation_judge` | Writing and refining attack prompts |
| `assessment_expert` / `assessment_judge` | Scoring responses in Analysis |
| `playbook_author` | Plan Mission / Regenerate |
| `enhance_theory` | Enhance / Auto-run theories |
| `recon` | Recon probes |
| `discovery` | Connect Target UI discovery |

You do not need every key — configure the roles you actually use. Target API keys
(`TARGET_API_KEY_*`) are separate: they authenticate the **product under test**, not the
assistant LLMs.

## Where your data lives

There is **no application database**. One checkout = one workspace. Hunt state is files
under the repo (mostly `browser-bot/sites/`).

| What | Where |
|------|--------|
| Plays | `playbooks/<id>.json` |
| Target connection | `browser-bot/sites/<host>/<component>/config.yaml` |
| Auth metadata | `…/auth.json` (gitignored); API secrets in `.env` |
| Login session | `…/.login_profile/` |
| Recon baseline | `…/recon.json` |
| Probe suites | `…/tests/<strategy>/<playbook>.json` |
| Run evidence | `…/logs/probes/<timestamp>/` (`run_log`, `attack_log`, `pipeline_report`, screenshots) |

**Jobs are in-memory.** Stopping the server clears in-progress UI jobs; finished artifacts
on disk remain.

### Backups

Zip or copy `browser-bot/sites/<host>/` (and custom plays under `playbooks/`). Exclude
`.env` from shared archives; restore secrets separately.

## Related

- [Installation](02-installation.md)
- [Export & reporting](08-export-and-reporting.md)
- [Advanced schemas](advanced/schemas.md) — field-level log/report shapes
