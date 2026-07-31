# 13 - Troubleshooting

## Python / `python3`

On Debian, Ubuntu, and WSL, the `python` command is often missing; only `python3` exists.

| Symptom | Fix |
|---------|-----|
| `python: command not found` | Use `python3` (e.g. `python3 start.py`) |
| Want `python` in your terminal | Add `alias python=python3` to `~/.bash_aliases`, then reopen the shell |
| Still missing in scripts / CI | Aliases only apply to interactive bash; use `python3`, or `sudo apt install python-is-python3` |
| Wrong or ancient Python | `python3 --version` (need 3.10+); use `python3 -m venv` for manual envs |

After the first run, `start.py` uses the venv's Python; the `python` vs `python3` issue only
affects the host interpreter you bootstrap with.

## Playwright / Chromium

`start.py` installs Playwright's Chromium on first run and re-installs if it is missing.

| Symptom | Fix |
|---------|-----|
| `Playwright does not support chromium on ubuntu26.04-x64` | Re-run `python3 start.py`; it sets an Ubuntu 24.04 platform override |
| Manual install | `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64 python3 -m playwright install chromium` |
| Browser launch fails (missing system libs) | `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64 python3 -m playwright install-deps` |
| Chromium not found after install | Delete `~/.cache/ms-playwright` and re-run `python3 start.py` |

Use the venv's Python for manual Playwright commands after the first bootstrap.

## Virtual environment

- `start.py` creates or reuses the project virtualenv in the repo root.
- If dependencies seem stale or broken, delete the venv directory and re-run `python3
  start.py` to rebuild it.
- "Virtual environment python not found" means venv creation failed - check that
  `python3 -m venv` works on the host.

## API keys and LLM providers

| Symptom | Likely cause |
|---------|--------------|
| Generation or assessment errors immediately | Provider API key missing/invalid - set in `.env` (see `.env.example`) or **Settings → Configure LLMs** |
| A role fails with an auth error | The provider assigned to that role in `llm.yaml` has no key in `.env` |
| Save profiles fails citing OpenRouter catalog | Model slug removed/renamed on OpenRouter - pick a live id (Settings banner) |
| App refuses to start: `OpenRouter model validation failed` | Same - fix every `provider: openrouter` model in `llm.yaml` / Settings, or restore network/`OPENROUTER_API_KEY` if the catalog fetch failed; then restart |
| Generate returns provider 404 for OpenRouter model | Same as above; restart after fixing `llm.yaml` |
| Target API calls return 401 / unauthorized | Missing `TARGET_API_KEY_<SITE>_<COMPONENT>` - set via **Connect Target → API key** (stored in `.env`, not `auth.json`) |
| Rate-limit / 429 during generation or assessment | Lower **Settings → Pipeline → Assessment concurrency**; providers also apply retry/backoff from `llm.yaml` |

Only providers actually referenced by a role in `llm.yaml` need their key set. `.env` is
secrets-only; cache and export-batch knobs are under Settings / `pipeline_settings.yaml`
(Genbounty host is hardcoded, not a Settings field).

## Runs

| Symptom | Fix |
|---------|-----|
| "Test run did not execute any prompts" | Check the suite path, and that `--site`/`--component` match a registered target with valid selectors/config |
| "No run log written" | The run failed before producing output; check target auth and selectors, and the job stream in the UI |
| Target refuses/blocks everything | Re-check auth (login may have expired), pacing (`EVASION_*`), and that recon selectors still match the live UI |
| Cloudflare / Turnstile blocks the run | Turn **Headless** off (pool/auto with a visible window is fine). Complete the checkbox once if prompted. Components marked `cloudflare_headed` (Run modal or after a successful clear) auto-use real Chrome via CDP when available and force pool/cluster stealth; clearance cookies are saved into `auth.json` so later runs reuse them |
| Selectors no longer match | Re-run Recon / discovery to refresh `recon.json` and `config.yaml` |
| Configure Component opens the marketing site / wrong host (e.g. `lakera.ai` instead of `play.lakera.ai/...`) | Discovery used to launch from `login_url` / the site folder name. Set **Start URL** on the component (`submission.start_url`) and re-run Configure - discovery prefers that path. Also set Login URL to the real host (not a brand folder like `https://Lakera`) |
| Configure opens but you are logged out after a successful Login | Login stores the session under the **component** `.login_profile` (e.g. `OpenAI/chatgpt/.login_profile`). Configure now uses that path (site profile as fallback). Also: sibling API-key auth no longer clears profile cookies on CDP launch. Re-run Login once if an older Configure wipe already cleared the profile, then Configure again. Delete any mistaken `surface_prep` **Log in** row from the component `config.yaml` (Configure now rejects those clicks). |
| Firing Range / Attack opens a browser but you are logged out | Headed UI used to treat a sibling **API key** as auth and launch an ephemeral Chromium, ignoring `.login_profile`. Fire / Attack / recon now reuse the component login profile (CDP) and pass `start_url`. Turn **Headless** off, ensure Login completed for that UI component, then Fire again. |
| Recon headed pass opens a browser but you are logged out | Headed recon used to launch without `site`/`component` and skipped `.login_profile` when recording HAR (blank Chromium). It now opens the component login profile with HAR, uses session-cookie auth only (not sibling API keys), and passes `site`/`component`/`start_url` into the launcher. Soft-reload, confirm Login for that UI component, then Recon again. |
| Final verification fills `2+2` but never sends (prompt sits in the composer) | Discovery saved attach / **More actions** / `+` as `submit_selector` instead of Send. Configure now rejects that chrome; submit also heals to `[data-testid="send-button"]` (or Enter) when the probe text is still in the composer. Re-run Configure (Send step: click the black Send arrow, not `+`), or soft-reload so `record_submission.py` / `submit/common.py` are picked up. |
| Reply visible on screen but capture hangs / returns none (ChatGPT) | Role mode nested `response_list_selector` under assistant roots (Playwright only searches descendants). Capture now reads `[data-message-author-role="assistant"]` directly; Fire heals/persists that selector if a brittle `.markdown` leaf fails. Configure fails closed when final verify never captures text. Soft-reload and Fire again, or re-run Configure. |
| Fire returns none after Configure left a short answer (e.g. `4`) on screen | Short replies used to lose to welcome-phrase / length heuristics. Capture now prefers short answers; welcome is ignored only via Configure `response_ignore_substrings` (exact match for short text), loaders, or redacted banners — not phrase guessing. Soft-reload and Fire again. |
| Attack log / report shows only a static phone/chat intro instead of the real reply | Capture treated welcome chrome as the model reply. Re-run Configure: after Submit, use the **welcome/intro** step (click the greeting once, then Done) so it is saved to `response_ignore_substrings`, then pick the real reply. Short replies are no longer blocked by welcome-length heuristics; longer greeting bubbles still use Configure ignores + phrase fallback. Raise `response_wait_ms` for slow research agents (often 30–60s). |
| Discovery sample request fails / `cannot unpack non-iterable NoneType` / “prompt input disabled” on gated UIs | Pages that hide the composer behind a start CTA, tab/card picker, or cookie banner need those clicks as surface pre-steps. Re-run Configure and record them (or add `type: click` + `upload_prep: true` inputs before the textarea). Use a specific enabled textarea selector and point `response_selector` at the preview reply. Submit also auto-clicks common Start/Begin labels when text inputs are missing. |
| Configure **Continue** closes a Congratulations / cookie popup but nothing is saved | Site dialogs treat the Genbounty helper as an outside click. Restart Configure: **step 1** is click the popup ✕ / Close (saved as `surface_prep`); **step 2** is Continue. Do not use Continue to clear the modal. Confirm `config.yaml` has a leading `type: click` + `surface_prep: true` row. |
| Pre-step click worked in Configure but not on Run | Common failures: (1) saved selector was `button[type=button]` — matches the first header icon; (2) `text=` / `has-text` matched a large **ancestor** that merely contains the label. Replay skips generic button selectors when `name` is set, prefers deepest text match, and clicks the nearest pointer host. Re-run Configure so rows use `button:has-text("…")` / `:text-is("…")`. Confirm `[surface_prep] clicked …` in the run log. |
| Surface pre-steps feel very slow (~8–12s) before the first click on Run | Main cause was Cloudflare resolve polling for the composer 10×0.4s (~4s) even when no challenge existed — and that ran twice before gates. Also: readiness waited for a gated textarea, and `wait_for_load_state("load")` stalled SPAs after DCL. Now: CF checks challenge visibility immediately, gates run before readiness, submit continues after `domcontentloaded`. Soft-reload so `page_blockers.py` / `submit/*.py` are picked up. |
| Configure pre-steps only saves the first gate (Saved (1) while clicking later steps) | Two causes: (1) UI mode resolved the click with `elementFromPoint` after the page advanced; (2) the in-page helper could steal a card click onto a nearby toolbar button via a “single button in parent” heuristic, then skip it as a duplicate. Both are fixed — restart Configure, click **one gate at a time**, wait for `Saved (N)` to increment. A ⚠ appears if a click is rejected or treated as a duplicate. |
| Tab / card / start selection does not stick across headless runs | Choosing a tab or card only during Configure does not persist unless recorded. Use the Configure **surface pre-steps** step: click **one** on-page element at a time, wait for the blue outline / save, then the next, then Done. Those clicks are saved as leading `surface_prep` inputs and replayed on every `start_url` load. Confirm `config.yaml` lists them with `type: click` and `surface_prep: true` before the textarea. Soft-reload the web UI so Component Config shows the **click** type (older UI dropped it). |
| Headless: `[!] Readiness: Input not visible: textarea…` on gated UIs (View all Levels → MASTER / Level N) | The composer stays hidden until surface pre-steps finish. Headless used to click the next gate after only ~0.2s, so MASTER often missed while the level list was still expanding. Replay now waits for the next gate (or the textarea) between prep clicks and retries misses. Confirm `[surface_prep] clicked …` (not `missed`) for each gate. If gates never appear, Cloudflare may be blocking headless Chromium — turn **Headless** off or clear Turnstile once headed so `cf_clearance` is saved. |
| Headless works for level pick but still no textarea (Info / Attack / Preview UIs) | Selecting MASTER only highlights the level on the **Info** tab; the prompt box is under **Attack**. Headed CDP often reuses a profile already on Attack; headless cold-starts on Info. Record **Attack** as a `surface_prep` click after the level (Configure), or rely on the auto composer-tab click. Confirm logs show `[surface_prep] clicked …Attack` / `composer tab 'Attack'`. Screenshots land under `logs/probes/*/screenshots/` and in War Room → **Live operations**. |
| Attack **Live operations** stays Idle / black while the run progresses | Frames were saving on disk but the preview URL builder referenced an out-of-scope `API` constant, so each screenshot SSE update threw and was ignored. Soft-reload the UI, ensure `RUN_SCREENSHOT_INTERVAL_S` > 0, and re-run. Previews now live on **War Room** (left column above COMMS; TRAFFIC keeps full height on the right). |
| Progress shows **Single · 1/N** but Experiment Output says concurrency=N, only Worker 1 busy | **Single** means single-turn strategy, not concurrency=1. If only one worker runs with `FETCH_METHOD=pool` + `POOL_SIZE`>1, confirm the job log has `[pool] launched N page(s)` (not `1`). Older builds collapsed the pool to one page when `POOL_CLUSTER_HUMAN_LIKE` was on; restart the web server after updating. Headed/CDP still caps pool to 1. |
| Browser Config values look saved but runs use different numbers | Check **Component Config → Settings overrides** - a component `API_CONCURRENCY` (and similar) overrides Browser Config at run time |
| Run log shows `response: null` / assessor says “Harness failed to capture a response” on **API** transport | Often rate-limit/overload or a missing `api_response_path`. Check the same entry for `http_status`, `api_error`, and `submission_outcome: submit_failed`. Lower component `API_CONCURRENCY` (default `2`; avoid large bursts), keep `EVASION_REQUEST_DELAY_S`, and confirm `api_response_path` (Anthropic Messages: `content.0.text`). Transient 429/502/503/529 are retried once |
| First UI prompt captures, later ones `submission_outcome: timeout` | `response_wait_ms` is too short for slow itinerary/research agents (8s is rarely enough). Raise Component Config `response_wait_ms` to 30–60s. Also confirm surface pre-steps still open the composer after each reload. |
| First headed CDP prompt works, then `TargetClosedError` / `human submit failed with no result` on later prompts | Per-prompt release was killing auto-launched Chrome while the run still held a stale CDP session. Bundle-owned CDP now stays open for the whole Run Tests session. Soft-reload so `fetchers/ui_bundle.py` is picked up, then re-run. |
| Judge says expert assessment failed / malformed JSON, but final risk still looks right | Expert triage JSON was truncated mid-object (`parse_ok` false). Salvage recovers `risk_level` / `exploit_status` when possible; judge may still re-score from the raw response. Soft-reload so the assessor code is current. |
| Advanced encoding / obfuscation prompts lose homoglyphs, zero-width, or bidi after Generate | Attributes rewrite styles **live** prompts, skips structural/encoded fields, and rolls back if encoding characters disappear. Re-Generate the suite |
| `Generation produced 0 runnable prompts` with Top filter reasons `theory_drop:*` | Drop metal detector rejected prompts that reintroduced burned tokens from theory/intel. Narrow Enhance Drop bullets or regenerate. A wipe-guard keeps the batch if *every* prompt would be dropped - if you still see 0, another filter emptied the suite |
| `Generation produced 0 runnable prompts` (any play/strategy) | Read the **`[!] Diagnosis`** block in experiment output: parsed vs filtered counts, top filter reasons (`[capability]`, `[filter]`, `[playbook]`), recon capability flags. Common causes: code-execution plays on text-only targets, URLs in text strategies, missing attack objective tokens, or LLM parse/API failure (0 parsed) |
| API recon lists code execution / file upload but sample chat denies tools | Re-run Recon. API probes ask about **this** request and verify with YES/NO; hedged platform answers are stripped. Plain `api` transport never gets `file_upload` from self-report (use `api_document` / `api_multipart` when uploads are real) |
| `:8000` accepts TCP but every request hangs / times out | A prior uvicorn worker is wedged (common after Cancel under auto-reload). Re-run `python3 start.py` - startup **reclaims** `:8000` from a prior Genbounty `web/app.py` for this checkout (SIGKILL, including Ctrl+Z-stopped orphans). Auto-reload is off unless `GENBOUNTY_DEV_RELOAD=1`. Manual: `ss -ltnp \| grep :8000` then `kill -9 <pid>` |
| Armory **Delete test** shows `Delete failed: {"detail":"Method Not Allowed"}` | Restart with `python3 start.py` (or re-run `web/app.py`), then hard-refresh. A healthy delete of a missing suite returns **404** `Test file not found`, not 405 |
| `Address already in use` / start.py jumps off port 8000 | Startup reclaims Genbounty holders and **retries bind** if another Genbounty UI races onto `:8000`. If it still moves to 8001+, something else owns the port - startup prints a holder hint; stop that process or set `PORT=…`. Do not run two `start.py` / `web/app.py` at once |
| Play invents **file upload / tool-escape** categories though recon says the target has none | Denial prose does not count as capability confirmation. Authoring emits `capability_absent` constraints and rejects the full generated play when any authored category requires an unconfirmed capability. Re-create the play with compatible categories |
| Enhance / Generate invents **Python script / code interpreter** prompts for text-only targets | Theory and generation check recon `capabilities`/`tools`, emit `capability_absent`, and post-filter script/tool/upload/browse prompts when those surfaces are not confirmed. Re-run Enhance / Forge after recon is accurate |
| Seeds use dossier framing but never name what to extract | Set **Attack objective** on the play (exact information/instruction). It is distinct from **Standard action** (an optional follow-up, not an exploit oracle). Re-Generate the suite after saving |
| After changing **Attack objective** + Regenerate, refusals still mention the *old* ask | Hard-refresh the UI, **Regenerate** (rebuilds from the new objective and clears cached suites), then **Forge** before Run |
| Playbook is clean but **Run** still uses old prompts (stale suite JSON) | Regenerate invalidates cached suites; then **Forge**. Closed-loop Generate does not reuse prior assessments from a different `attack_objective` |
| Attack log / report shows wrong persona or canary vs the logged prompt, or `id ≠ capture_id` | Trust `run_log.json`. Re-convert then re-assess: `python3 -c "from pathlib import Path; from pipeline.convert_log import convert_run_log; convert_run_log(Path('…/run_log.json'), Path('…/suite.json'))"` then Analysis / `security-assess` on the new `attack_log.json` |
| Judge / expert says the response was “truncated” but `pipeline_report.json` / `run_log.json` show a full reply | That was usually the old **2k head-only** assess clip, not a capture failure. Experts now receive up to **50k** chars (head+tail if still over); the judge preserves the `BEGIN_UNTRUSTED_RESPONSE` block (budget **64k**, enough for a full expert response plus metadata). Re-run Analysis if you need updated verdicts on older logs |

## Multimodal payloads

| Symptom | Fix |
|---------|-----|
| Payload generation fails | Confirm `start.py` / `requirements.txt` install completed; install **ffmpeg** on PATH for WAV TTS (otherwise MP3 fallback) |
| TTS produces MP3 instead of WAV | Install `ffmpeg` on PATH |
| Artifacts land in the wrong place | Set **Settings → Pipeline → Output directory** (`pipeline_settings.yaml`) |

## Export / Genbounty submit

| Symptom | Fix |
|---------|-----|
| Submit reports missing API key / user id | Set `GENBOUNTY_API_KEY` and `GENBOUNTY_USER_ID` in `.env` (or enter User ID on Export and Save export settings). Job output names the missing field. Host is hardcoded to `https://genbounty.com` |
| 403 / scope error | The API key needs the `write:security_assessment_import` scope |
| Repeated 429s | Raise export delay / lower batch size under Settings → Pipeline |
| Wrong import endpoint | Export always posts to `https://genbounty.com/api/v2/security-assessments/import`. Check API key scope (`write:security_assessment_import`) |
| `parent_id is required` on import | Empty report `parent_id` is filled from playbook/`category_id` on export. Re-export the report |

JSON export never needs platform credentials.

## Where to look

- Live job output and browser screenshots stream in the UI while a job runs.
- Server log: `GET /api/log` (or the terminal running `start.py`).
- Interactive API docs: `http://localhost:8000/api/docs`.
- Per-target artifacts: `browser-bot/sites/<host>/<component>/` (see
  [04 - Architecture](04-architecture.md)).
