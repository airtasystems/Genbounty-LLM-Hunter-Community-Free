# Porting LLM API Endpoint Support to a Matching Genbounty Clone

Assumes the clone has the same layout: `browser-bot/`, `web/` (FastAPI + `static/app.js` + `index.html`), Connect Target flow, and `api_discover` jobs.

---

## 1. New module: API presets

1. **Add** `browser-bot/browser_bot/api_presets.py`
   - Export `LLM_API_PRESETS` (custom, openai, openrouter, gemini, anthropic, azure_openai, test_target).
   - Each preset: `id`, `label`, `description`, `url`, `method`, `response_path`, `body`, `headers`, `auth_header`, `auth_query_param`, `default_model`.
   - Export `get_llm_api_presets()` and `get_preset(preset_id)`.

---

## 2. API request helpers

2. **Edit** `browser-bot/browser_bot/submit/api_helpers.py`:
   - **`apply_prompt_template`**: replace `{{prompt}}` and `{{model}}` in nested dicts/lists/strings.
   - **`extract_json_path`**: support numeric path segments for arrays (e.g. `choices.0.message.content`).
   - **Add** `_merge_url_query(url, extra)` to append auth query params without overwriting existing keys.
   - **Add** `_normalize_provider_auth(headers, url, query_params)`: for `generativelanguage.googleapis.com`, map `Authorization` / `AIza…` / `?key=` to `x-goog-api-key`.
   - **Change** `auth_headers_for_site(site, *, url="")` to call `_normalize_provider_auth` with loaded `query_params`.
   - **Add** `auth_query_params_for_site(site)` reading `auth.json` → `query_params`.
   - **Add** `resolve_api_url(sub, *, site)`: fail if URL contains `{{model}}` but `api_model` is empty; substitute `{{model}}`; merge query params.
   - **Change** `do_api_request`: use `resolve_api_url`; pass `url` into `auth_headers_for_site`; substitute model in body; preflight error if Gemini URL has no key header and no `key=` in URL.

---

## 3. Auth storage

3. **Edit** `browser-bot/browser_bot/auth_state.py`:
   - **Add** `_api_key_header_value(header_name, key, use_bearer=None)` - Bearer only for `Authorization` by default.
   - **Extend** `save_api_key_auth(domain, api_key, *, header_name, use_bearer, query_param_name)` to write `headers` and/or `query_params` in `auth.json`.
   - **Extend** `_normalize_auth_config` to ensure `query_params: {}` exists.

---

## 4. Submission config (runtime + YAML)

4. **Edit** `browser-bot/browser_bot/sites.py` - in `_normalize_api_submission`, include `api_model` on the returned dict when set.

5. **Edit** `browser-bot/browser_bot/component_config_yaml.py` - in `_format_api_submission`, emit optional `api_model` and comments for `{{model}}` in URL/body.

6. **Edit** `browser-bot/browser_bot/record_submission.py` - `run_api_discovery`:
   - Accept `api_model`.
   - Fail early if URL has `{{model}}` and model is empty.
   - Use `resolve_api_url` for the printed probe URL (not raw template URL).
   - On 403 for Gemini, print hint about `x-goog-api-key` / `?key=`.
   - Save `api_model` in `submission` block.

---

## 5. Web backend

7. **Edit** `web/jobs.py` - in `_start_api_discover`, add `"api_model": job.params.get("api_model", "")` to the JSON params passed to the worker (this was a bug if missing).

8. **Edit** `web/api_discover_worker.py` - pass `api_model=params.get("api_model", "")` into `run_api_discovery`.

9. **Edit** `web/app.py`:
   - **Extend** `ApiKeyAuthBody`: `header_name`, `use_bearer`, `query_param_name`.
   - **Add** `GET /api/llm-api-presets` → `get_llm_api_presets()`.
   - **Update** `POST /api/sites/{site}/auth/api-key` to call extended `save_api_key_auth`.
   - **Extend** `GET /api/sites/{site}/auth-status` with `auth_header`, `auth_query_param` (from saved config, not secret values).

---

## 6. Frontend - `web/static/app.js`

10. **Add constants**: `PROMPT_MODEL_HINT = '{{model}}'` (do **not** use nested `{{ '{{model}}' }}` in HTML).

11. **Extend** `compCfg.submission` with `api_model: ''`.

12. **Add** `llmApiPresets` ref; **`loadLlmApiPresets()`** from `GET /api/llm-api-presets`; call on mount and when switching to API transport.

13. **Add** `applyApiPreset(presetId, { authOnly })`: fills URL, method, body JSON, headers JSON, response path, default model; sets `authApiKeyHeader`, `authUseBearer`, `authApiKeyQueryParam` from preset.

14. **Add** `syncApiDiscoverFromCompCfg()`, `onDiscoverTransportChange()`, `onSettingsApiPreset(ev)`.

15. **Add** computed: `apiNeedsAuth`, `apiAuthReady` (preset requires auth and `auth_mode === 'api_key'`).

16. **Extend** `applySubmissionToCompCfg` / `buildSubmissionPayload` to read/write `api_model`.

17. **Extend** auth flow:
    - `authApiKeyHeader`, `authApiKeyQueryParam`, `authUseBearer` refs.
    - `saveAuthApiKey()` POST body includes header/query/bearer flags.
    - `loadAuthStatus()` restores header/query hints from API response.

18. **Extend** `startApiDiscover()`:
    - Validate JSON body/headers.
    - Block if `apiNeedsAuth && !apiAuthReady`.
    - Block if URL contains `{{model}}` and model field empty.
    - Pass `api_model` in job params.

19. **Add** `discoverTransport`, `apiDiscover` reactive object (`presetId`, `url`, `method`, `responsePath`, `model`, `bodyJson`, `headersJson`).

20. **Update** Connect Target / Attack copy (and any in-app help) for UI vs API paths.

21. **Export** new symbols from the Vue `return { … }` (presets, auth fields, helpers).

22. **Add** `watch(discoverTransport, onDiscoverTransportChange)`.

---

## 7. Frontend - `web/static/index.html`

23. **Step 1 (Target access)**:
    - Clarify three choices: Login to UI / API key / public.
    - API key sub-form: password field, auth header `<select>`, optional query param, Bearer checkbox for `Authorization`.

24. **Step 3 (Configure component)**:
    - Connection type: “Browser UI (chat app)” vs “API endpoint (LLM HTTP API)”.
    - API branch: preset dropdown, description, URL, model, method, response path, body textarea, extra headers textarea.
    - Banner when auth required but not saved; link to Step 1.
    - Use `{{ PROMPT_TEMPLATE_HINT }}` and `{{ PROMPT_MODEL_HINT }}` only (never nested mustaches).

25. **Settings → Component → Submission** (API transport block):
    - Same fields as above; “Apply preset…” dropdown calling `onSettingsApiPreset`.
    - Note that API keys live in Step 1, not YAML.

---

## 8. Verify in the clone

26. **Restart** the web server after backend changes.

27. **Hard refresh** the browser (`Ctrl+Shift+R`).

28. **Gemini smoke test** (if you have a key):
    - Step 1: API key, header `x-goog-api-key` (or query `key`).
    - Step 3: Gemini preset, model e.g. `gemini-3.1-flash-lite`, Connect via API → should probe resolved URL (no literal `{{model}}`).

29. **Attack / Send Sample Request** with `transport: api` in `sites/<site>/<component>/config.yaml` - should use same helpers as discovery.

30. **Optional structural test** in the clone:

    ```bash
    PYTHONPATH=browser-bot python -c "
    from browser_bot.api_presets import get_llm_api_presets
    from browser_bot.submit.api_helpers import extract_json_path
    assert extract_json_path({'choices':[{'message':{'content':'x'}}]}, 'choices.0.message.content')=='x'
    print(len(get_llm_api_presets()), 'presets OK')
    "
    ```

---

## 9. Files touched (checklist)

| # | File | Action |
|---|------|--------|
| 1 | `browser-bot/browser_bot/api_presets.py` | **Create** |
| 2 | `browser-bot/browser_bot/submit/api_helpers.py` | **Edit** |
| 3 | `browser-bot/browser_bot/auth_state.py` | **Edit** |
| 4 | `browser-bot/browser_bot/sites.py` | **Edit** |
| 5 | `browser-bot/browser_bot/component_config_yaml.py` | **Edit** |
| 6 | `browser-bot/browser_bot/record_submission.py` | **Edit** |
| 7 | `web/jobs.py` | **Edit** |
| 8 | `web/api_discover_worker.py` | **Edit** |
| 9 | `web/app.py` | **Edit** |
| 10 | `web/static/app.js` | **Edit** |
| 11 | `web/static/index.html` | **Edit** |

---

## 10. Easiest port strategy

31. If the clone is a git fork of the same repo: **cherry-pick or diff-copy** these 11 files from the branch where this work landed, then run steps 26–30.

32. If trees diverged: implement in order **1 → 3 → 4–6 → 7–9 → 10–11** so backend works before UI.

---

## 11. Common pitfalls

33. **`api_model` dropped in `web/jobs.py`** → probe hits `…/models/{{model}}:generateContent` and fails.

34. **Gemini + `Authorization` header only** → 403 until `_normalize_provider_auth` exists or user uses `x-goog-api-key`.

35. **Vue template `{{ '{{model}}' }}`** → `SyntaxError: missing ) after argument list`; use `PROMPT_MODEL_HINT` in JS instead.

36. **Azure preset** - user must manually replace `{resource}` in URL; only `{{model}}` and `{{prompt}}` are auto-substituted.

37. **Genbounty assistant LLM keys** (`.env` / Settings → Configure LLMs) and role models
   (`llm.yaml`) are for test generation/Analysis, **not** the target API key in
   Connect Target Step 1.

---

## Preset reference (verified May 2026)

| Preset | Endpoint | Auth (Step 1) | Response path |
|--------|----------|---------------|---------------|
| OpenAI | `POST /v1/chat/completions` | `Authorization` (Bearer) | `choices.0.message.content` |
| Gemini | `POST …/models/{model}:generateContent` | `x-goog-api-key` or `?key=` | `candidates.0.content.parts.0.text` |
| Anthropic | `POST /v1/messages` | `x-api-key` | `content.0.text` |
| Test target | `POST /api/chat` | None (public) | `response` |
| Azure | `POST …/deployments/{model}/chat/completions?api-version=2024-10-21` | `api-key` | `choices.0.message.content` |

**Not covered by presets:** Vertex AI Gemini (OAuth), Azure v1 API (`/openai/v1/chat/completions`), OpenAI Responses API, streaming.
