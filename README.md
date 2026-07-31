# Genbounty LLM Hunter

![Genbounty LLM Hunter War Room](web/llm-hunter/llm-hunter-war-room.png)

**Genbounty LLM Hunter** is an open-source toolkit for **AI bug bounty hunting**, **LLM security testing**, and **authorized whitehat assessments** of chatbots, AI agents, and LLM-backed APIs. It turns manual prompt trials into a repeatable pipeline: generate adversarial probes, run them at scale (Playwright or HTTP API), triage severity, and export findings as JSON or to [Genbounty](https://genbounty.com).

Use it to hunt **prompt injection**, **jailbreaks**, **system prompt exfiltration**, **sensitive data disclosure**, **indirect injection via file uploads**, and **agentic/tool abuse**.

> **Authorized testing only.** Use on targets and programs you are permitted to assess. You are responsible for scope, rate limits, and program rules.

**Documentation:** [documentation/](documentation/README.md) — start with [Install](documentation/02-installation.md) and [Quick start](documentation/03-quickstart.md).

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

```
connect → recon → Plan Mission → Forge → Attack → Analysis → export
```

| Step | UI tab | Output |
|------|--------|--------|
| Connect target | Connect Target | Target connection (+ optional auth) |
| Recon | Recon | Target baseline recon |
| Plan a mission | Missions | Play with win/lose rules |
| Generate | Forge | Probe suite |
| Run / assess | Attack → Analysis | Evidence + severity report |
| Export | Report | JSON download or Genbounty import |

## Quick start

```bash
cp .env.example .env   # add your LLM provider key (see .env.example)
python start.py        # or python3 start.py
```

Open **http://localhost:8000**, then: **Connect Target** → **Recon** → **Forge** (shipped play: `data_system_prompt_leak`) → **Attack** → **Analysis** → **Report**.

Step-by-step: [Quick start](documentation/03-quickstart.md). Install notes: [Installation](documentation/02-installation.md).

### Secrets vs settings

| Where | What |
|-------|------|
| `.env` | API keys only (never commit). See `.env.example` for names. |
| `llm.yaml` | Role → provider/model (Settings → Configure LLMs) |
| `pipeline_settings.yaml` | Batch sizes, assess concurrency, cache toggles, export batching |

More: [Settings, LLMs & data](documentation/07-settings-llms-and-data.md).

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

`--playbook` is required unless you use `--all` / `--all-playbooks`. Full flags: [CLI](documentation/10-cli.md).

## Plays & strategies

Hypothesis rubrics live in `playbooks/*.json`. This repo ships **`data_system_prompt_leak`**
plus `_template.json` (UI-excluded). Author more plays in **Missions**.

Strategies include `zero_shot`, `multimodal`, `jailbreak`, multi-turn packs, and shaping
strategies. **Adaptive** is Premium. Details:
[Missions & strategies](documentation/05-missions-and-strategies.md).

## Project layout

| Path | Role |
|------|------|
| `start.py` / `main.py` | Bootstrap UI / scripting CLI |
| `web/` | FastAPI + Ops SPA |
| `generate-tests/` | Probe generation |
| `browser-bot/` | Playwright / API runner |
| `pipeline/` | Convert, assess, export |
| `playbooks/` / `payloads/` | Plays and multimodal generators |
| `documentation/` | Operator docs (+ `advanced/` for internals) |

## License

MIT - see [LICENSE](LICENSE).
