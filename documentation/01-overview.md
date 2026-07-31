# 01 - Overview

## What it is

**Genbounty LLM Hunter** is a toolkit for **authorized** security testing of LLM-backed
products - chatbots, AI agents, and LLM APIs. Instead of running one-off prompts by hand in
a ChatGPT session, it provides a repeatable pipeline that:

- **generates** category-aligned adversarial probe suites from security rubrics ("plays"),
- **executes** them at scale through browser automation (Playwright) or direct HTTP APIs,
- **captures** prompt/response evidence per probe case,
- **assesses** each finding for severity with AI-assisted judging, and
- **delivers** structured reports as downloadable JSON or via Genbounty's import API.

## What it hunts

- Prompt injection (direct and indirect)
- Jailbreaks and safety-guardrail bypasses
- System prompt exfiltration
- Sensitive data disclosure
- Indirect injection via file uploads (PDF, CSV, images, audio)
- Agentic / tool abuse and sandbox / code-execution breakouts

## The pipeline

```
connect -> recon -> generate -> (multimodal) -> Attack -> Analysis -> export & report
```

| Step | UI tab | Primary output |
|------|--------|----------------|
| Connect target | Connect Target | Target connection settings |
| Recon | Recon | Target baseline recon |
| Forge | Forge | Probe suite for the selected play and strategy |
| Build artifacts | Multimodal | File/media probes when using the multimodal strategy |
| Edit suites | Armory | Edits to categories and prompts |
| Run probes | Attack | Run evidence and attack logs |
| Assess findings | Analysis | Severity-scored pipeline report |
| Submit | Report | Downloadable JSON, or submit to Genbounty |

## Who this is for

- **Bug bounty hunters** targeting AI chatbots, agents, and API-backed LLM apps.
- **Whitehats / pentesters** running structured hunts on customer staging with exportable
  evidence.
- **AppSec / MLSec teams** doing regression runs per release and comparing severity
  rollups across builds.

## Scope

Observable **black-box behavior only**: prompts, uploads, and responses. The tool does
not attempt to access target infrastructure beyond what a user of the product could.

## Community vs Premium

This package is the **Community** edition of Genbounty LLM Hunter.

**Included in Community**

- Connect Target, Recon, Missions, Forge, Armory, Attack, Analysis, Report
- Enhance and Auto-run on Attack
- Hunt modes **Bug Bounty** and **Compliance**
- Multimodal **strategy** (file/media probes generated with your suite)
- CLI generate / run / assess / export for supported strategies

**Premium** (upgrade at [genbounty.com/llm-hunter](https://genbounty.com/llm-hunter))

| Feature | What it adds |
|---------|----------------|
| **Start Battle** | One-click unattended hunt that chains generate → attack → enhance |
| **Adaptive** strategy | Multi-turn adaptive probing driven by live target replies |
| **Multimodal builder** | Standalone Artifacts tab for crafting upload payloads by hand |
| **Intel** | Dedicated intel workspace and credentials/paths inventory tools |
| **Open Hunt** | Hunt mode that can broaden the hypothesis when a leaf stagnates |

In Community, Premium controls show an upgrade prompt in the UI. Prefer Attack
**Enhance / Auto-run** instead of Start Battle.

## Authorization and ethics

This toolkit automates offensive prompts and exports findings. Use it **only** on targets
and programs you are explicitly permitted to test. You are responsible for:

- staying within the program's scope,
- respecting rate limits and terms of service,
- and following responsible-disclosure rules.

See [12 - Export & reporting](12-export-and-reporting.md) for how findings are packaged for
disclosure.
