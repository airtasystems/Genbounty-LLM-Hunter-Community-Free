# 09 — Troubleshooting

Symptom → fix. For deeper internals see [Advanced](advanced/README.md).

## Install and launch

| Symptom | Fix |
|---------|-----|
| `python: command not found` | Use `python3 start.py` (Debian/Ubuntu/WSL). |
| UI won’t start / missing packages | Re-run `python3 start.py` so the venv and requirements install. |
| Playwright / Chromium install fails on Ubuntu 26+ | Re-run `python3 start.py` (platform override is automatic). Manual: `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64 python3 -m playwright install chromium`. |
| `:8000` accepts TCP but every request hangs | A prior worker is wedged. Re-run `python3 start.py` (startup reclaims the port). Or `ss -ltnp \| grep :8000` then kill the old PID. |

## Keys and LLMs

| Symptom | Fix |
|---------|-----|
| Generate / Analysis fails with auth errors | Set a provider key in `.env` or **Settings → Configure LLMs**. Only providers used by roles need keys. |
| OpenRouter model rejected on save | Use a slug from OpenRouter’s live catalog; fix `llm.yaml` and save again. |

## Connect Target / browser session

| Symptom | Fix |
|---------|-----|
| Configure opens the wrong host | Set **Start URL** on the component (`submission.start_url`) and re-run Configure. |
| Configure / Fire / Recon opens logged out | Complete **Login** for that UI component. Headed runs reuse `.login_profile`. Turn **Headless** off. Sibling API-key auth is not a browser session. |
| Cloudflare / Turnstile blocks runs | Turn **Headless** off; complete the checkbox once when prompted. |
| Final verify fills `2+2` but never sends | You clicked `+` / More actions instead of Send during Configure. Re-run Configure and click the real Send control. |
| Multimodal Attack sends text with no file | Re-run Configure: click `+` / attach first, then the file control. Config should include `upload_menu: true` before the file input. |
| Surface pre-steps don’t stick | Click **one** gate at a time; wait for **Already saved (N)** before the next. Confirm `surface_prep: true` rows in `config.yaml`. |

## Generate / Attack / capture

| Symptom | Fix |
|---------|-----|
| `Generation produced 0 runnable prompts` | Read the **Diagnosis** block in Experiment Output (capability/filter/playbook reasons). Narrow the play or fix Recon capabilities. |
| Forge multimodal fails with `channel_mismatch` | Confirm Recon shows file upload; soft-reload; Generate again. Regenerate the play to persist artifact siblings. |
| Reply visible but capture returns none (ChatGPT) | Re-run Configure so response selectors point at assistant messages; raise `response_wait_ms` for slow agents. |
| Fire returns none after a short answer like `4` | Soft-reload and Fire again; short answers are capturable. |
| First prompt works, later ones time out | Raise Component Config `response_wait_ms` (often 30–60s for research agents). |

## Export

| Symptom | Fix |
|---------|-----|
| Genbounty submit fails auth | Set `GENBOUNTY_API_KEY` and program `user_id`. See [Export](08-export-and-reporting.md). |

Still stuck? Check Experiment Output for the failing job, then the component folder under
`browser-bot/sites/<host>/<component>/`.
