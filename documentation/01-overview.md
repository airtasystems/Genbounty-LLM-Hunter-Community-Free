# 01 — Overview

## What it is

**Genbounty LLM Hunter** turns one-off prompt trials into a repeatable security hunt.
You define a hypothesis (“play”), generate probes, run them against an authorized target,
judge severity, and export evidence.

It works through:

- **Browser automation** (Playwright) for chat UIs, or
- **HTTP APIs** for chat/completion endpoints

## What it hunts

- Prompt injection (direct and indirect)
- Jailbreaks and safety-guardrail bypasses
- System prompt exfiltration
- Sensitive data disclosure
- Indirect injection via file uploads (PDF, images, audio, and more)
- Agentic / tool abuse and sandbox breakouts

## The pipeline

```
connect → recon → Plan Mission → Forge → Attack → Analysis → export
```

| Step | Where in the UI | What you get |
|------|-----------------|--------------|
| Connect target | Connect Target | How to talk to the product (UI or API) |
| Recon | Recon | What the target can do (upload, tools, …) |
| Plan a mission | Missions | A play with clear win/lose rules |
| Generate probes | Forge | A suite of adversarial prompts |
| Run probes | Attack | Captured prompt/response evidence |
| Assess | Analysis | Severity-scored report |
| Export | Report | JSON download or Genbounty submit |

Details for each tab: [Using the UI](04-using-the-ui.md).

## Who this is for

- Bug bounty hunters testing AI chatbots, agents, and LLM APIs
- Whitehats / pentesters who need structured evidence on staging
- AppSec / MLSec teams running regression hunts across releases

## Scope

Black-box only: prompts, uploads, and responses a normal user of the product could produce.
It does not attack infrastructure beyond that.

## Community vs Premium

This package is the **Community** edition.

**Included**

- Connect Target, Recon, Missions, Forge, Armory, Attack, Analysis, Report
- Enhance and Auto-run on Attack
- Hunt modes **Bug Bounty** and **Compliance**
- Multimodal **strategy** (file/media probes with your suite)
- CLI generate / run / assess / export for supported strategies

**Premium** — [genbounty.com/llm-hunter](https://genbounty.com/llm-hunter)

| Feature | What it adds |
|---------|----------------|
| **Start Battle** | One-click unattended hunt loop |
| **Adaptive** strategy | Multi-turn probing driven by live replies |
| **Multimodal builder** | Standalone tab for hand-crafted upload payloads |
| **Intel** | Dedicated intel workspace |
| **Open Hunt** | Hunt mode that can broaden a stuck hypothesis |

In Community, Premium controls show an upgrade prompt. Use Attack **Enhance / Auto-run**
instead of Start Battle.

## Authorization and ethics

Use this toolkit **only** on targets and programs you are explicitly permitted to test.
You are responsible for scope, rate limits, terms of service, and responsible disclosure.

See [Export & reporting](08-export-and-reporting.md) for how findings are packaged.
