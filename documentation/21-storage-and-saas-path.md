# 21 - Where your data lives

Genbounty LLM Hunter keeps hunt state as **files in your checkout**. There is no
application database. Companion to [04 - Architecture](04-architecture.md) and
[11 - Artifacts & schemas](11-artifacts-and-schemas.md).

## What you should know

- **One checkout = one workspace.** Install locally, point at an authorized target, and
  everything for that hunt lives under the repo (mostly under `browser-bot/sites/`).
- **Secrets stay in `.env`.** Never commit that file. Session cookies and similar
  metadata live in gitignored `auth.json` files per component.
- **Evidence is folders.** Each Attack run creates a timestamped probe directory with
  logs, reports, and screenshots you can open, copy, or archive.
- **Jobs are in-memory.** Stopping the server clears in-progress UI jobs; finished
  artifacts on disk remain.

## Common paths

| What | Where |
|------|--------|
| Plays (hypotheses) | `playbooks/<id>.json` |
| Target connection | `browser-bot/sites/<host>/<component>/config.yaml` |
| Auth metadata | `…/auth.json` (gitignored); API secrets in `.env` |
| Recon baseline | `…/recon.json` |
| Hunt learning | `…/intel/{playbook_id}.json` (written by Recon / report extract) |
| Probe suites | `…/tests/<strategy>/<playbook>.json` |
| Run evidence | `…/logs/probes/<timestamp>/` |
| LLM & pipeline knobs | `llm.yaml`, `pipeline_settings.yaml` |

## Backups

To keep a hunt, copy or zip the relevant `browser-bot/sites/<host>/` tree (and any custom
plays under `playbooks/`). Exclude `.env` from shared archives; restore secrets separately.

## Related docs

- [04 - Architecture](04-architecture.md) — components and directory map
- [09 - Configuration](09-configuration.md) — `.env` and settings
- [11 - Artifacts & schemas](11-artifacts-and-schemas.md) — log and report shapes
- [19 - Auth & Connect Target](19-auth-and-connect-target.md) — login and API keys
