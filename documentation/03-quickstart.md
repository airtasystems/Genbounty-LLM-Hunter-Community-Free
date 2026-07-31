# 03 - Quick start

This walks through a full run using the web UI, which is the primary interface. It assumes
you have completed [02 - Installation](02-installation.md) and set at least
your LLM provider key from `.env.example` (edit `.env`, or **Settings → Configure LLMs**
after launch).

> **Authorized testing only.** Only run against targets you are permitted to assess.

## 1. Launch the UI

```bash
python start.py
```

Open **http://localhost:8000**. If you have not set keys yet, open **Settings → Configure
LLMs** and save a provider key before generating or assessing. The workflow follows the
sidebar top to bottom.

## 2. Connect Target

Register the target under `browser-bot/sites/<host>/<component>/`.

- **Browser discovery**: the tool opens the target UI and probes selectors (input box,
  send button, response area, file upload).
- **API probe**: point at a chat HTTP endpoint instead of a UI.

This writes a per-component `config.yaml` (selectors or API transport). Auth options:

- **UI login** / public access → session metadata in `auth.json` (gitignored)
- **API key** → secret in `.env` as `TARGET_API_KEY_<SITE>_<COMPONENT>`; `auth.json` keeps
  header/query metadata only

## 3. Recon

Run the browser or API probe to produce `recon.json` - a component baseline describing what
the target supports (e.g. file upload, streaming, tool use). On API endpoints, only tools
confirmed for **this** request count; hedged "available on other interfaces" answers are
discarded.

After assessed runs, you can also use **Recon Round** or **Extract from report** to update
per-play hunt learning in `intel/{playbook_id}.json`. When a playbook is selected,
generation and assessment merge the baseline plus playbook intel.

## 4. Forge

Pick a **playbook category**, then a **play** (attack hypothesis) within it, then a
**strategy** (e.g. `zero_shot`, `jailbreak`, `multimodal`).

- The first run uses **stealth-first** prompts (no mandatory direct probes).
- After a run and assessment exist, **Enhance and Run** uses closed-loop feedback; plain
  **Generate** auto-enables feedback when a prior `pipeline_report.json` is present.
- For max-critical compounding: after assessment, use **Enhance and Auto-Run** with Hunt
  mode **Bug Bounty**, Max rounds 8, Stop-at High/Critical - theory uses shipped
  `enhance_theory` → Grok (`offensive_fast`). Details: [16 - Closed-loop Enhance](16-closed-loop-enhance.md).

Output is a suite JSON under
`browser-bot/sites/<host>/<component>/tests/<strategy>/<playbook>.json`.

See [07 - Playbooks & strategies](07-playbooks.md).

## 5. (Optional) Multimodal

For file-upload hunts, build multimodal artifacts (PDF, CSV, images, audio) in the
**Multimodal** tab. With strategy `multimodal`, artifacts are materialized alongside the
suite. See [08 - Payloads & multimodal](08-payloads-multimodal.md).

## 6. Attack

Pick a **playbook category** (and a **play** + **strategy** for single-play scope), then
execute. You get live browser screenshots and a results table. This writes
`run_log.json`, which is normalized to `attack_log.json`.

## 7. Analysis

Judge each result's severity from `indeterminate` through `critical`. This writes
`pipeline_report.json` with per-prompt reasoning and an optional `category_rollup`.

See [11 - Artifacts & schemas](11-artifacts-and-schemas.md) for the report structure.

## 8. Report

- **Export as JSON**: download one report, or a batch (last 1h / 4h / 24h). No platform
  credentials required.
- **Submit to Genbounty**: POST to `https://genbounty.com` when `GENBOUNTY_API_KEY`
  and a program `user_id` are configured.

See [12 - Export & reporting](12-export-and-reporting.md).

## Doing the same from the CLI

The web UI covers discovery, login, and playbooks. For scripting/CI, the equivalent core
steps are:

```bash
python main.py generate --strategy zero_shot --playbook <your_mission_id> --site example.com --component chat
python main.py run browser-bot/sites/example.com/chat/tests/zero-shot/<your_mission_id>.json \
  --site example.com --component chat --assess
python main.py export browser-bot/sites/example.com/chat/logs/.../pipeline_report.json
```

See [06 - CLI reference](06-cli-reference.md).
