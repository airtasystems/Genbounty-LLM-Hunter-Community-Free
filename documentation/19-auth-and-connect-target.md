# 19 - Auth & Connect Target

How targets are registered and authenticated. UI details:
[05 - Connect Target](05-web-ui-guide.md). Secrets vs settings:
[09 - Configuration](09-configuration.md). Frontend helpers live in
`web/static/js/tabs/connect-target.js` (`useConnectTarget`, wired before `useJobs`
so `loginRunning` is available to panel output).

## Sites and components

A **site** is a host folder under `browser-bot/sites/<host>/` (e.g. `chatgpt.com`).
A **component** is a sub-target (e.g. `chat`) with its own `config.yaml`, auth, recon,
tests, and logs.

## Discovery modes

| Mode | What it does |
|------|----------------|
| **Browser discovery** | Opens the UI with a step helper (Step N of M + one **Do this now** line); records optional initial popup + surface pre-steps (notices/tabs/levels/Start — one click at a time; wait for Already saved (N) before the next), then prompt/submit, optional welcome/intro ignores, response container, file upload |
| **Manual discovery** | You supply selectors when auto-probe is insufficient (same pre-step / intro recording available) |
| **API probe** | HTTP chat endpoint: plain JSON, `api_document`, or `api_multipart` for files. Configure Component presets include OpenAI, **OpenRouter** (OpenAI-compatible `/api/v1/chat/completions`, Bearer key, slug models), Gemini, Anthropic, Azure, custom, and local test target |

Result: per-component `config.yaml` (selectors or API transport). Surface pre-steps are stored as leading `submission.inputs` rows with `type: click` and `surface_prep: true` (also `upload_prep: true`), and are replayed after every reload before the prompt field is filled. Welcome/intro clicks are stored as `submission.response_ignore_substrings`.

## Access modes

| Mode | Storage | Notes |
|------|---------|-------|
| **Public** | Auth marked public | No credentials |
| **Login** | `.login_profile/` and/or cookies in `auth.json` | Real browser login; Login/Start URLs normalize (`https://`, `.com` when TLD missing). Configure Component prefers `submission.start_url` over `login_url` / site name when opening the browser. |
| **API key** | Secret in `.env` as `TARGET_API_KEY_<SITE>_<COMPONENT>`; metadata in `auth.json` | Header / query / bearer names only in `auth.json` - never plaintext keys there |
| **Reuse auth** | Copy from sibling component | Site fallback can also apply without copying |

Clearing auth removes the matching `TARGET_API_KEY_*` from `.env` when applicable.

Legacy plaintext keys still in `auth.json` migrate into `.env` on first load.

## Cloudflare / headed browser

If Turnstile / Cloudflare blocks runs: turn **Headless** off; complete the challenge once
when prompted. Components marked `cloudflare_headed` prefer real Chrome via CDP when
available and may merge `cf_clearance` into `auth.json`. See
[13 - Troubleshooting](13-troubleshooting.md).

## API routes (summary)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/sites/{site}/auth-status`, `.../{component}/auth-status` | Auth state |
| POST | `.../auth/reuse` | Copy auth from another component |
| POST | `.../auth/public` | Mark public |
| POST | `.../auth/api-key` | Save target API key to `.env` |
| DELETE | `.../auth` | Clear auth |

Full table: [10 - API reference](10-api-reference.md).

## See also

- [05 - Web UI guide](05-web-ui-guide.md)
- [03 - Quick start](03-quickstart.md)
- [13 - Troubleshooting](13-troubleshooting.md)
