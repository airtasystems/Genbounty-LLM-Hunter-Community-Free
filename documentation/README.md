# Genbounty LLM Hunter — Documentation

**Genbounty LLM Hunter** helps you run **authorized** AI security tests against chatbots,
agents, and LLM APIs. Generate adversarial probes, run them in the browser or over HTTP,
triage severity, and export findings as JSON or to [Genbounty](https://genbounty.com).

> **Authorized testing only.** Use only on targets and programs you are allowed to assess.
> You own scope, rate limits, and disclosure rules.

This is the **Community** edition. Core hunting is included; a few features are Premium —
see [Overview](01-overview.md#community-vs-premium).

## Start here

1. [Install](02-installation.md) — keys, `start.py`, verify the UI
2. [Quick start](03-quickstart.md) — first end-to-end hunt
3. Come back to the guides below as you need them

```
connect → recon → Plan Mission → Forge → Attack → Analysis → export
```

## Guides

| Guide | When to read it |
|-------|-----------------|
| [01 — Overview](01-overview.md) | What the tool does, ethics, Community vs Premium |
| [02 — Installation](02-installation.md) | First launch and environment setup |
| [03 — Quick start](03-quickstart.md) | Your first successful hunt |
| [04 — Using the UI](04-using-the-ui.md) | What each sidebar tab is for |
| [05 — Missions & strategies](05-missions-and-strategies.md) | Create plays and choose how probes are shaped |
| [06 — Enhance & Auto-run](06-enhance-and-auto-run.md) | Sharpen probes after an assessed run |
| [07 — Settings, LLMs & data](07-settings-llms-and-data.md) | Keys, roles, and where files live |
| [08 — Export & reporting](08-export-and-reporting.md) | Download JSON or submit to Genbounty |
| [09 — Troubleshooting](09-troubleshooting.md) | Common problems and fixes |
| [10 — CLI](10-cli.md) | Optional automation / CI commands |

## Advanced

Internals for contributors and integrators (not required for hunting):
[documentation/advanced/](advanced/README.md).

## Blog

- [Introducing Genbounty LLM Hunter](../blog/introducing-genbounty-llm-hunter.md)

## License

MIT — see [LICENSE](../LICENSE).
