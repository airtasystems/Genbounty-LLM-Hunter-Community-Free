# 02 - Installation

## Requirements

- **Python 3.10+** (`python3 --version` to check)
- **Chromium** via Playwright - installed automatically on first run by `start.py`
- **API keys** (secrets in `.env` only — never commit this file):
  - At least one LLM provider key for generation and Analysis (see `.env.example`)
  - Optional Genbounty platform credentials for Report submit
  - Optional per-target API keys for Connect Target HTTP auth

## 1. Configure environment (API keys)

Copy the example env file. `.env` is for **secrets only**:

```bash
cp .env.example .env
```

Then either edit `.env` and fill in the keys listed in `.env.example`, or launch the UI
and save keys under **Settings → Configure LLMs** (same file; secrets are never echoed
back to the browser).

Provider and model per assistant role are configured in `llm.yaml` (or
**Settings → Configure LLMs**). Non-secret knobs (cache, export batching, pipeline
batch sizes) live in `pipeline_settings.yaml` / Settings. Target API keys from Connect
Target are written as `TARGET_API_KEY_*` in `.env`. See
[09 - Configuration](09-configuration.md).

## 2. Bootstrap and launch

```bash
python start.py
```

`start.py` is the bootstrapper. On first run it:

1. creates a project virtual environment (or reuses an existing compatible one),
2. upgrades `pip` and installs `requirements.txt`,
3. installs Playwright's Chromium browser (with an Ubuntu platform override where needed),
4. launches the web UI (`web/app.py`).

On later runs it reuses the venv and skips browser install if Chromium is already present.

Once running, open **http://localhost:8000**.

Auto-reload is **off** by default (avoids a hung worker keeping `:8000` open but
unresponsive after Cancel). On each start, the UI **reclaims** `:8000` from a prior
Genbounty `web/app.py` for this checkout (including stopped/orphaned processes), so a
Cancel + restart should not leave the port blocked. For local UI/code reload while
developing:

```bash
GENBOUNTY_DEV_RELOAD=1 python3 start.py
```

Optional: `PORT=8001 python3 start.py` to bind a different port.

## 3. Verify

- The web UI loads at `http://localhost:8000`.
- The interactive API docs are available at `http://localhost:8000/api/docs`.
- If the browser hangs on `:8000`, see [13 - Troubleshooting](13-troubleshooting.md)
  (kill leftover uvicorn, then restart).

## Platform notes

### Debian / Ubuntu / WSL: `python` vs `python3`

On these systems the `python` command is often missing; only `python3` exists.

| Symptom | Fix |
|---------|-----|
| `python: command not found` | Use `python3` (e.g. `python3 start.py`) |
| Want `python` in your shell | Add `alias python=python3` to `~/.bash_aliases`, then reopen the shell |
| Still missing in scripts/CI | `sudo apt install python-is-python3` for a system-wide shim |
| Wrong/old Python | `python3 --version` (need 3.10+); use `python3 -m venv` for manual envs |

After the first run, `start.py` uses the venv's own Python; the `python` vs `python3` issue
only affects the host interpreter you use to bootstrap.

### Playwright on Ubuntu 26.04

Playwright does not ship an `ubuntu26.04-x64` browser build. `start.py` detects Ubuntu 26+
and sets `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE` to the Ubuntu 24.04 build automatically,
retrying the install if needed.

| Symptom | Fix |
|---------|-----|
| `Playwright does not support chromium on ubuntu26.04-x64` | Re-run `python3 start.py` |
| Manual browser install | `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64 python3 -m playwright install chromium` |
| Launch fails (missing libs) | `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64 python3 -m playwright install-deps` |

See [13 - Troubleshooting](13-troubleshooting.md) for more.

## Multimodal payload dependencies

File-upload payload generators ship with the root `requirements.txt` (installed by
`start.py`). No extra pip install is required for PDF/image/audio artifacts beyond that.

Install **ffmpeg** on your PATH for WAV output from text-to-speech (otherwise MP3 fallback).
See [08 - Payloads & multimodal](08-payloads-multimodal.md).
