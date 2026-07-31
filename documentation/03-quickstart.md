# 03 — Quick start

Your first full hunt in the web UI. Complete [Installation](02-installation.md) first
(at least one LLM provider key).

> **Authorized testing only.** Only run against targets you are permitted to assess.

## 1. Launch

```bash
python start.py
```

Open **http://localhost:8000**. If keys are missing, open **Settings → Configure LLMs**
and save a provider key. Work down the sidebar top to bottom.

## 2. Connect Target

Register the product under test (a host + component, for example `chatgpt.com` / `chat`).

- **Browser discovery** — opens the UI and records the prompt box, Send, response area,
  and (if present) file upload. Follow the on-screen **Do this now** steps.
- **API probe** — point at a chat HTTP endpoint instead of a browser UI.

Save login or an API key if the target needs auth. Details:
[Using the UI — Connect Target](04-using-the-ui.md#connect-target).

## 3. Recon

Run Recon so the tool learns what the target supports (file upload, tools, and so on).
You want a healthy baseline before generating probes.

## 4. Plan a mission (optional but recommended)

Under **Missions**, create a play: a short hypothesis with clear success/fail rules.
You can also use a shipped play such as `data_system_prompt_leak`.

See [Missions & strategies](05-missions-and-strategies.md).

## 5. Forge

Pick your **play** and a **strategy** (start with `zero_shot`). Generate a probe suite.

Output lands under
`browser-bot/sites/<host>/<component>/tests/<strategy>/<playbook>.json`.

If the target supports file upload and you want file-based probes, enable multimodal
on Forge (or choose strategy `multimodal`). See
[Multimodal strategy](05-missions-and-strategies.md#multimodal-strategy).

## 6. Attack

Select the same play/strategy and run. Watch live screenshots and the results table.
This captures prompt/response evidence for each probe.

## 7. Analysis

Assess the run. You get severities from indeterminate through critical and a
`pipeline_report.json` with per-probe reasoning.

## 8. Report

- **Export as JSON** — download findings (no Genbounty account needed)
- **Submit to Genbounty** — when `GENBOUNTY_API_KEY` and a program user id are set

See [Export & reporting](08-export-and-reporting.md).

## Next steps

- Sharpen after a report: [Enhance & Auto-run](06-enhance-and-auto-run.md)
- Automate later: [CLI](10-cli.md)
- Stuck? [Troubleshooting](09-troubleshooting.md)
