# 02 — Installation

Get the UI running locally. Next step: [Quick start](03-quickstart.md).

## Requirements

- **Python 3.10+** (`python3 --version`)
- **Chromium** via Playwright (installed automatically by `start.py`)
- **At least one LLM provider key** for generation and Analysis (see `.env.example`)

Optional: Genbounty credentials for Report submit; per-target API keys for HTTP targets.

## 1. Add your API keys

```bash
cp .env.example .env
```

Edit `.env`, or launch the UI and save keys under **Settings → Configure LLMs**.
Secrets never leave `.env` (never commit that file).

Provider/model per role live in `llm.yaml` (or the same Settings screen). Non-secret knobs
(cache, batch sizes) live in `pipeline_settings.yaml` / Settings. See
[Settings, LLMs & data](07-settings-llms-and-data.md).

## 2. Launch

```bash
python start.py
# or: python3 start.py
```

On first run, `start.py` creates a virtualenv, installs dependencies, installs Chromium,
and starts the web UI. Later runs reuse the venv.

Open **http://localhost:8000**.

Optional:

```bash
PORT=8001 python3 start.py          # different port
GENBOUNTY_DEV_RELOAD=1 python3 start.py   # auto-reload while developing
```

## 3. Verify

- UI loads at `http://localhost:8000`
- Interactive API docs (optional) at `http://localhost:8000/api/docs`

If the page hangs, see [Troubleshooting](09-troubleshooting.md).

## Platform notes

### `python` vs `python3` (Debian / Ubuntu / WSL)

| Symptom | Fix |
|---------|-----|
| `python: command not found` | Use `python3 start.py` |
| Want `python` in your shell | `alias python=python3` in `~/.bash_aliases` |
| Scripts/CI need `python` | `sudo apt install python-is-python3` |

### Playwright on Ubuntu 26.04+

`start.py` sets a platform override automatically. If Chromium install still fails, see
[Troubleshooting](09-troubleshooting.md).

## Multimodal (file uploads)

PDF / image / audio generators install with `requirements.txt`. For text-to-speech WAV
output, install **ffmpeg** on your PATH (otherwise MP3 is used). Multimodal strategy notes:
[Missions & strategies](05-missions-and-strategies.md#multimodal-strategy).
