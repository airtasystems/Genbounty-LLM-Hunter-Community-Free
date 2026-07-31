# 04 — Using the UI

The web UI is the primary interface. Open it with `python start.py` →
**http://localhost:8000**.

Pipeline overview: [Overview](01-overview.md#the-pipeline).

## Header

Use the header to pick the active **site**, **component**, and **play**. Most tabs act on
that selection.

**Clear Cache** / **Nuke** (gear menu) clear sticky UI state or wipe experiment artifacts
for the in-scope component while keeping `config.yaml`, `auth.json`, and `recon.json`.
Nuke writes a backup first.

## Connect Target

**Why:** Tell the tool how to talk to the product under test.

**When:** Before Recon, Forge, or Attack on a new target.

A **site** is a host folder (`browser-bot/sites/<host>/`). A **component** is a sub-target
(for example `chat`) with its own config, auth, recon, suites, and logs.

### Discovery modes

| Mode | Use when |
|------|----------|
| **Browser discovery** | The target is a chat UI you can open in a browser |
| **Manual discovery** | Auto-probe misses selectors — you click the controls yourself |
| **API probe** | The target is an HTTP chat/completion endpoint |

**Browser discovery tips**

1. Clear cookie/consent popups on the **first** step (do not use Continue to dismiss them).
2. Record **surface pre-steps** one click at a time (tabs, level cards, Start) — wait for
   **Already saved (N)** before the next click.
3. For ChatGPT-like upload: click **`+` / attach first**, then the file control if asked.
4. After Send, you can click welcome/intro bubbles to ignore them, then pick the real reply.

### Auth

| Mode | When |
|------|------|
| **Public** | No login required |
| **Login** | Browser session — use **Add Login**; session is reused for Configure / Fire / Attack |
| **API key** | HTTP targets — secret goes in `.env` as `TARGET_API_KEY_<SITE>_<COMPONENT>` |
| **Reuse auth** | Copy session/key metadata from a sibling component |

If Cloudflare / Turnstile blocks you: turn **Headless** off and complete the checkbox once.
See [Troubleshooting](09-troubleshooting.md).

## Recon

**Why:** Learn capabilities (upload, tools, streaming) so generation and assessment stay
grounded.

**When:** After Connect Target; again when the product UI changes.

Run a connected or manual-URL probe. Results land in `recon.json`. You can view Overview
or edit JSON on the tab.

## Missions

**Why:** Define the security hypothesis and win/lose rules for a hunt.

**When:** Before Forge, or when you want a new play for this target.

See [Missions & strategies](05-missions-and-strategies.md).

## Forge

**Why:** Generate the probe suite for a play + strategy.

**When:** After Recon (and usually after Plan Mission).

Pick play and strategy, then Generate. Optional multimodal checkbox builds file/image/audio
probes when the target supports upload.

## Armory

**Why:** Inspect or edit an existing suite before Attack.

**When:** You want to tweak prompts, drop weak cases, or review categories.

## Attack

**Why:** Execute the suite against the live target and capture evidence.

**When:** A suite exists for the selected play/strategy.

Use **Headless** off for Cloudflare-heavy targets. After Assessment exists, use
**Retarget and keep attacking** for closed-loop Enhance — see
[Enhance & Auto-run](06-enhance-and-auto-run.md).

**Firing Range** is a quick single-prompt sandbox for the connected UI (same auth as Attack).

## Analysis

**Why:** Score each probe for severity with AI-assisted judging.

**When:** After an Attack run produced logs.

Produces `pipeline_report.json` used by Report and Enhance.

## Report

**Why:** Package findings for disclosure or Genbounty.

**When:** After Analysis.

See [Export & reporting](08-export-and-reporting.md).

## Settings

**Why:** Provider keys, models per role, and non-secret pipeline knobs.

See [Settings, LLMs & data](07-settings-llms-and-data.md).

## Notes

Free-form operator notes for the component. Useful for program rules, out-of-scope reminders,
and scratch observations.
