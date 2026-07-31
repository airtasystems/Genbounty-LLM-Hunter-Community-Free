# Introducing Genbounty LLM Hunter: Structured Security Testing for AI Chatbots and Agents

*From one-off prompt trials to a repeatable pipeline for authorized LLM bug bounty hunting.*

---

AI products ship fast. Chatbots, agents, and LLM-backed APIs are now in production everywhere-and so are the failure modes that come with them: prompt injection, jailbreaks, system-prompt leaks, sensitive data disclosure, and tool abuse.

Most researchers still hunt these issues the hard way: paste a clever prompt into a chat window, screenshot the reply, try again, lose the thread. That works for a single finding. It does not scale to a program, a release gate, or a serious assessment.

**Genbounty LLM Hunter** is an open-source toolkit built for that gap. It turns LLM security testing into a pipeline you can run, improve, and report-on targets you are authorized to assess.

## What it is

Genbounty LLM Hunter helps whitehats, bug bounty hunters, and AppSec / MLSec teams:

- **Generate** adversarial test suites from security playbooks (attack hypotheses with clear win/lose rules)
- **Execute** those tests at scale through a real browser (Playwright) or a direct HTTP API
- **Capture** prompt/response evidence
- **Assess** each result with AI-assisted judging (severity plus reasoning)
- **Export** structured findings as JSON, or submit them to the [Genbounty](https://genbounty.com) platform

In short: connect a target, recon what it can do, generate attacks, run them, triage severity, and ship a report.

```
connect → recon → generate → (payloads) → run → finding assessment → bug bounty report
```

## What it hunts

The toolkit focuses on observable black-box behavior-the same surface a normal user of the product would see:

- Prompt injection (direct and indirect)
- Jailbreaks and safety-guardrail bypasses
- System prompt exfiltration
- Sensitive data disclosure
- Indirect injection via file uploads (PDF, CSV, images, audio)
- Agentic / tool abuse and sandbox or code-execution breakouts

It does not try to break into infrastructure beyond what a product user could reach. Scope stays on prompts, uploads, responses, and (when captured) the target’s own network requests.

## Why playbooks beat random prompts

A “play” is a hypothesis-driven rubric: one attack idea, a category, and clear conditions for *exploited* vs *mitigated*. Strategies then shape how that hypothesis is probed-zero-shot, jailbreak-focused, multi-turn chaining, multimodal uploads, and more.

That means generation and assessment share the same success criteria. You are not just collecting interesting replies; you are measuring whether the target failed a defined security bar.

First runs default to **stealth-first** prompts (they read more like legitimate requests than blunt probes). After you run and assess a suite, closed-loop feedback can refine the next round-so the hunt gets sharper instead of repeating the same shots.

## Browser UI or API-same pipeline

Targets are not all chat widgets. Some are production UIs; others are backend chat endpoints.

Genbounty LLM Hunter supports both:

- **Browser discovery** - open the target, probe selectors (input, send, response, file upload), optionally log in and reuse session state
- **API probe** - point at an HTTP chat endpoint (including document / multipart modes for file delivery)

Either path feeds the same generate → run → assess → export flow.

## Multimodal is a delivery channel

Many real-world LLM apps accept files. Indirect injection often lives there.

With the `multimodal` strategy and the payloads toolkit, you can build and attach PDF, CSV, image, and audio artifacts as part of a hunt-when recon shows the target actually supports upload. Campaign planning skips multimodal when it does not.

## From run log to bounty-ready report

After a run, Finding Assessment judges each prompt from indeterminate through critical and writes a `pipeline_report.json` with per-prompt reasoning and optional category rollups.

From there you can:

- **Download filtered JSON** (single report or a recent time window)-no platform credentials required
- **Submit to Genbounty** (`https://genbounty.com`) when API key and program user ID are configured

That makes the same workflow useful for bug bounty submissions, pentest deliverables, and release-to-release regression comparisons.

## Who should use it

- **Bug bounty hunters** targeting AI chatbots, agents, and API-backed LLM apps
- **Whitehats / pentesters** running structured hunts on customer staging with exportable evidence
- **AppSec / MLSec teams** doing regression runs per release and comparing severity rollups across builds

## Get started

This is the **Community** edition. Core hunting (Recon, Forge, Attack, Enhance Auto-run,
Bug Bounty / Compliance) is included; some advanced options are Premium — see
[genbounty.com/llm-hunter](https://genbounty.com/llm-hunter).

Requirements are intentionally light: Python 3.10+, Chromium via Playwright (installed on
first launch), and an LLM provider key for generation and judging (see `.env.example`).

```bash
cp .env.example .env   # add your provider key
python start.py
```

Open **http://localhost:8000** and follow the sidebar: Connect Target → Recon → Forge →
Attack → Analysis → Report.

Full docs live in the project’s `documentation/` folder.

## Authorized testing only

This toolkit automates offensive prompts and packages findings. Use it **only** on targets and programs you are explicitly permitted to test. Stay in scope, respect rate limits and terms of service, and follow responsible disclosure.

---

**Genbounty LLM Hunter** is MIT-licensed and open source. If you are already hunting LLM apps by hand, this is the pipeline that turns those hunts into something repeatable, evidence-backed, and ready to report.
