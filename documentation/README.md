# Genbounty LLM Hunter - Documentation

**Genbounty LLM Hunter** is an open-source toolkit for **AI bug bounty hunting**, **LLM
security testing**, and **authorized whitehat assessments** of chatbots, AI agents, and
LLM-backed APIs. It turns manual prompt trials into a repeatable pipeline: generate
adversarial probes, execute them at scale, triage severity, and export structured findings
as JSON or to the [Genbounty](https://genbounty.com) platform.

> **Authorized testing only.** Use on targets and programs you are permitted to assess.
> This tool automates offensive prompts; you are responsible for scope, rate limits, and
> program rules.

## The pipeline

```
connect target -> recon -> generate probes -> (multimodal) -> Attack -> Analysis -> export & report
```

Plays are hypothesis rubrics with clear win/lose rules. Generation and assessment share
those rules so you measure whether the target failed a defined security bar—not just
whether a reply looked interesting.

## Documentation index

| Doc | What it covers |
|-----|----------------|
| [01 - Overview](01-overview.md) | What the tool does, who it is for, scope, and ethics |
| [02 - Installation](02-installation.md) | Prerequisites, `start.py` bootstrap, Playwright/WSL/Ubuntu notes |
| [03 - Quick start](03-quickstart.md) | First end-to-end run through the web UI |
| [04 - Architecture](04-architecture.md) | Components, data flow, and directory map |
| [05 - Web UI guide](05-web-ui-guide.md) | Every tab, from Connect Target to Report |
| [06 - CLI reference](06-cli-reference.md) | `main.py` subcommands for automation and CI |
| [07 - Playbooks & strategies](07-playbooks.md) | Play schema v3, categories, and attack strategies |
| [08 - Payloads & multimodal](08-payloads-multimodal.md) | File-upload artifact generators |
| [09 - Configuration](09-configuration.md) | `.env` secrets, `pipeline_settings.yaml`, `llm.yaml`, `config.yaml` precedence |
| [10 - API reference](10-api-reference.md) | FastAPI endpoints and the async job system |
| [11 - Artifacts & schemas](11-artifacts-and-schemas.md) | `recon.json`, run/attack logs, `pipeline_report.json` |
| [12 - Export & reporting](12-export-and-reporting.md) | JSON download and Genbounty import |
| [13 - Troubleshooting](13-troubleshooting.md) | Python, Playwright, and common runtime errors |
| [14 - Taxonomy & leaf catalog](14-taxonomy-and-leaves.md) | L1/L2 browse guide, capability families (authoring catalog) |
| [15 - Authoring a play](15-authoring-a-play.md) | Operator recipe for creating a custom play |
| [16 - Closed-loop Enhance](16-closed-loop-enhance.md) | Enhance / Auto-Run phase gates and outcomes |
| [17 - Genbounty import contract](17-genbounty-import-contract.md) | Security-assessment import fields and batching |
| [18 - LLM roles](18-llm-roles.md) | `llm.yaml` profiles and pipeline roles |
| [19 - Auth & Connect Target](19-auth-and-connect-target.md) | Discovery modes, login, API keys, Cloudflare |
| [20 - Scripts](20-scripts.md) | Offline helpers under `scripts/` |
| [21 - Where your data lives](21-storage-and-saas-path.md) | Local file layout, secrets, and backups |

## Community vs Premium

This is the **Community** edition. Core hunting (Recon, Forge, Attack, Enhance Auto-run,
Bug Bounty / Compliance) is included. Start Battle, Adaptive strategy, Intel, Open Hunt,
and the standalone Multimodal builder are **Premium** — see
[01 - Overview](01-overview.md#community-vs-premium) or
[genbounty.com/llm-hunter](https://genbounty.com/llm-hunter).

## Fastest path to a first run

1. Copy `.env.example` → `.env` and add your LLM provider key (or use
   **Settings → Configure LLMs** in the UI).
2. Install and launch: `python start.py` (see [Installation](02-installation.md)).
3. Open `http://localhost:8000`.
4. Follow the [Quick start](03-quickstart.md) to connect a target, run recon, create a
   mission via Plan Mission, generate a suite, run it, assess findings, and export a report.

## Requirements at a glance

- Python 3.10+
- Chromium via Playwright (installed automatically on first run by `start.py`)
- **API keys in `.env` only** (never commit this file):
  - A generation/assessment provider key (for example Gemini, OpenAI, Anthropic, Grok, or OpenRouter — see `.env.example`)
  - Optional Genbounty platform credentials for Report submit
  - Optional per-target API keys for Connect Target HTTP auth
- Non-secret knobs (cache, export batching, pipeline batch sizes) →
  `pipeline_settings.yaml` / Settings - not `.env`

## Blog

- [Introducing Genbounty LLM Hunter](../blog/introducing-genbounty-llm-hunter.md) - overview post for hunters and AppSec teams
- [Style brief](../blog/style-brief.md) - UI palette, type, layout, and component conventions

## License

MIT - see [LICENSE](../LICENSE).
