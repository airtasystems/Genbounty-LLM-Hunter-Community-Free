# Genbounty LLM Hunter

![Genbounty LLM Hunter War Room](web/llm-hunter/llm-hunter-war-room.png)

**Genbounty LLM Hunter** is an open-source toolkit for **AI bug bounty hunting**, **LLM security testing**, and **authorized whitehat assessments** of chatbots, AI agents, and LLM-backed APIs. It turns manual prompt trials into a repeatable pipeline: generate adversarial probes, run them at scale (Playwright or HTTP API), triage severity, and export findings as JSON or to [Genbounty](https://genbounty.com).

Use it to hunt **prompt injection**, **jailbreaks**, **system prompt exfiltration**, **sensitive data disclosure**, **indirect injection via file uploads**, and **agentic/tool abuse**.

> **Authorized testing only.** Use on targets and programs you are permitted to assess. You are responsible for scope, rate limits, and program rules.

**Full documentation:** [documentation/](documentation/README.md).

This is the **Community** edition. Premium options (Start Battle, Adaptive, Intel, Open Hunt,
standalone Multimodal builder) are marked in the UI — details in
[Community vs Premium](documentation/01-overview.md#community-vs-premium) and at
[genbounty.com/llm-hunter](https://genbounty.com/llm-hunter).

## AI Red Team Toolkit

We also provide this tool as an internal **[AI Red Team Toolkit](https://genbounty.com/adversarial-testing-platform)** for enterprise security teams — continuous in-house adversarial testing for LLMs and AI agents.

The Genbounty AI Red Team Toolkit is powered by Genbounty LLM Hunter. Equip your security team with a repeatable pipeline to probe chatbots, agents, and LLM APIs the way attackers do: multi-turn campaigns, multimodal inputs, and tool abuse simulations, not one-off jailbreak demos and screenshots.

## Screenshots

![Attack — Deploy Probes, hunt mode, and Enhance Auto-run](web/llm-hunter/attack-llms-agents.png)

![Forge — Prompt Transforms and strategy controls](web/llm-hunter/llm-hunter-prompt-transforms.png)

![Armory — edit probe suites and prompts](web/llm-hunter/llm-hunter-armory-zoomed-in.png)

![Multimodal — file and audio payload builder](web/llm-hunter/llm-hunter-multimodal-testing.png)

## Pipeline

| Step | UI tab | Output |
|------|--------|--------|
| Connect target | Connect Target | Target connection (+ optional auth) |
| Recon | Recon | Target baseline recon |
| Forge | Forge | Probe suites for the selected play/strategy |
| Build artifacts | Multimodal strategy | File/media probes when that strategy is used |
| Edit / run | Armory → Attack | Run evidence and attack logs |
| Assess | Analysis | Severity-scored report |
| Submit | Report | JSON download or Genbounty import |

```
connect → recon → generate → (multimodal) → Attack → Analysis → export & report
```

## Quick start

```bash
cp .env.example .env   # add your LLM provider key (see .env.example)
python start.py        # or python3 start.py
```

Open **http://localhost:8000**, then: **Connect Target** → **Recon** → **Forge** (shipped play: `data_system_prompt_leak`) → **Attack** → **Analysis** → **Report**.

Step-by-step: [03 - Quick start](documentation/03-quickstart.md). Install / Playwright notes: [02 - Installation](documentation/02-installation.md).

### Secrets vs settings

| Where | What |
|-------|------|
| `.env` | API keys only (never commit). See `.env.example` for names. |
| `llm.yaml` | Role → provider/model (Settings → Configure LLMs) |
| `pipeline_settings.yaml` | Batch sizes, assess concurrency, cache toggles, export batching |

## CLI (automation / CI)

Web UI is primary. For scripting:

```bash
python main.py generate --strategy zero_shot --playbook data_system_prompt_leak \
  --site example.com --component chat
python main.py run browser-bot/sites/example.com/chat/tests/zero-shot/data-system-prompt-leak.json \
  --site example.com --component chat --assess
python main.py security-assess path/to/attack_log.json
python main.py export path/to/pipeline_report.json
```

`--playbook` is required unless you use `--all` / `--all-playbooks`. Full flags: [06 - CLI reference](documentation/06-cli-reference.md).

## Plays & strategies

Hypothesis rubrics live in `playbooks/*.json` (schema v3). This repo ships **`data_system_prompt_leak`** plus `_template.json` (UI-excluded). Author more plays in the **Missions** tab; the category catalog covers the full L1/L2 taxonomy.

Strategies include `zero_shot`, `multimodal`, `jailbreak`, multi-turn packs (`multi_shot`, `few_shot`, `iterative`, …), and shaping strategies (`chain_of_thought`, `tree_of_thoughts`, …). The **Adaptive** strategy is Premium. Details: [07 - Playbooks](documentation/07-playbooks.md), [08 - Multimodal](documentation/08-payloads-multimodal.md).

## Project layout

| Path | Role |
|------|------|
| `start.py` / `main.py` | Bootstrap UI / scripting CLI |
| `web/` | FastAPI + Ops SPA |
| `generate-tests/` | Probe generation |
| `browser-bot/` | Playwright / API runner |
| `pipeline/` | Convert, assess, export |
| `playbooks/` / `payloads/` | Plays and multimodal generators |
| `documentation/` | Full docs index |

## License

MIT - see [LICENSE](LICENSE).
