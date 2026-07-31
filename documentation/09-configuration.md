# 09 - Configuration

Configuration comes from several sources with a clear precedence, plus API keys in `.env`
and the multi-provider LLM mapping in `llm.yaml`.

## Config sources

| Source | Purpose |
|--------|---------|
| `.env` | API keys only (provider keys, `GENBOUNTY_API_KEY`, and per-target `TARGET_API_KEY_<SITE>_<COMPONENT>`) |
| Browser local storage | Last-selected site/component in the web UI (`genbounty_site`, `genbounty_component`) |
| `.config` | Optional local overrides loaded before `.env` (rarely needed) |
| `config.defaults.yaml` | Shipped baseline browser-bot settings |
| `llm.yaml` | Multi-provider role → provider/model mapping (including Gemini models) |
| `pipeline_settings.yaml` | Pipeline knobs, cache globals, export batching (Settings → Pipeline / Cache Control) |
| `browser-bot/sites/<site>/config.yaml` | Optional site-wide setting overrides |
| `browser-bot/sites/<site>/<component>/config.yaml` | Per-component selectors, API URL, setting overrides, export.user_id |

## Settings precedence

From lowest to highest priority (higher wins):

1. `config.defaults.yaml` (shipped baseline)
2. `browser-bot/browser_bot/config.py` + `pipeline_settings.yaml` cache block (Settings → Browser Config / Cache Control)
3. `browser-bot/sites/<site>/config.yaml` (site-wide overrides)
4. `browser-bot/sites/<site>/<component>/config.yaml` (per-component overrides)

In the UI, per-component setting overrides can be left as "inherit" to fall back to the
global value.

## Core `.env` keys (secrets only)

`.env` stores **API secrets only**. Non-secret knobs (cache, export batching, prompt
batch sizes, payloads dir) live in [`pipeline_settings.yaml`](../pipeline_settings.yaml)
and the Settings UI. See [`.env.example`](../.env.example).

```bash
# Provider keys - assign provider + model per role in llm.yaml
# (or Settings → Configure LLMs).
GEMINI_API_KEY=
# OPENAI_API_KEY=
# ANTHROPIC_API_KEY=
# GROK_API_KEY=
# OPENROUTER_API_KEY=

# Optional Genbounty platform submit (Export tab).
# GENBOUNTY_API_KEY=
# GENBOUNTY_USER_ID=

# Optional target LLM HTTP API keys (Connect Target → API key).
# Written automatically, e.g.:
# TARGET_API_KEY_ANTHROPIC_CLAUDE5=
```

| Key | Purpose | Set via |
|-----|---------|---------|
| `GEMINI_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GROK_API_KEY` / `OPENROUTER_API_KEY` | Hunter LLM providers used by `llm.yaml` roles | **Settings → Configure LLMs**, or edit `.env` |
| `GENBOUNTY_API_KEY` | Genbounty security-assessment import | **Export** tab, or edit `.env` |
| `GENBOUNTY_USER_ID` | Program user id for Genbounty submit (fallback) | **Export** tab (also saved to component `config.yaml`), or edit `.env` |
| `TARGET_API_KEY_<SITE>_<COMPONENT>` | Target chat/API auth for Connect Target | **Connect Target → API key**, or edit `.env` |

`GEMINI_MODEL` / `GEMINI_JUDGE` / `GEMINI_THEORY_MODEL` are obsolete; set models on the
profiles in `llm.yaml` instead.

Provider and Genbounty keys use the same secure UI pattern (password input, never echoed
back) and update the running process environment immediately. The web server only writes
allowlisted secret keys into `.env` (provider keys, `GENBOUNTY_API_KEY`,
`GENBOUNTY_USER_ID`, and `TARGET_API_KEY_*`).

### Target API keys (`TARGET_API_KEY_*`)

For API-transport targets, **Connect Target → Target access → API key** saves the secret
to `.env` as `TARGET_API_KEY_<SITE>_<COMPONENT>` (site/component names sanitized to
`A-Z0-9_`). Component `auth.json` keeps only non-secret metadata (`auth_mode`, header /
query param names, bearer flag, `api_key_env`). Clearing auth removes the `.env` entry.
Legacy plaintext keys still in `auth.json` are migrated into `.env` on first load.

UI / session login cookies stay in `auth.json` (gitignored); that file is not used for
target API secrets anymore.

### Prompt cache (per provider)

Global cache toggles live under the `cache:` block in `pipeline_settings.yaml`
(Settings → Cache Control). Per-component overrides use `config.yaml` `settings:`.

Defaults: Gemini off; OpenAI / Grok / Anthropic on (`openai_cache_retention=standard`,
`anthropic_cache_ttl=5m`).

### Web UI site / component selection

The top-bar **site** and **component** are chosen in the UI (Manage modal or the header
dropdowns). The last selection is stored in the browser’s local storage
(`genbounty_site`, `genbounty_component`) and restored on the next visit. It is not read
from `.env`.

### Genbounty submit (optional)

| Setting | Where |
|---------|--------|
| Host | Hardcoded `https://genbounty.com` (not in Settings / YAML) |
| API key | `.env` → `GENBOUNTY_API_KEY` (Export tab) |
| User ID | Job/UI → component `config.yaml` `export.user_id` → `.env` `GENBOUNTY_USER_ID` |
| Batch size / delay / retries | `pipeline_settings.yaml` → `export.*` (Settings → Pipeline) |

Import always uses the security schema
(`POST /api/v2/security-assessments/import`); missing severities default to
`indeterminate` in code. JSON export needs none of these. See
[12 - Export & reporting](12-export-and-reporting.md).

### Pipeline settings (`pipeline_settings.yaml`)

Editable under **Settings → Pipeline** / **Cache Control** (not `.env`). Top-level blocks:

| Block | UI | Contents |
|-------|-----|----------|
| `pipeline:` | Settings → Pipeline | Prompt batch sizes, assess concurrency, payloads dir |
| `cache:` | Settings → Cache Control | Per-provider prompt-cache toggles / retention / TTL |
| `export:` | Settings → Pipeline | Genbounty batch/delay/retry knobs (host is hardcoded) |

| Key | Default | Purpose |
|-----|---------|---------|
| `open_loop_prompts` | `6` | Prompts per category on first / open-loop generate |
| `closed_loop_prompts` | `6` | Prompts per category when closed-loop / Enhance routing is active |
| `security_assess_concurrency` | `4` (code default; shipped `pipeline_settings.yaml` may set `6`) | Parallel Risk-assessment workers (runtime caps at entry count) |
| `payloads_output_dir` | `payloads/generate` | Multimodal artifact output root (relative to project root or absolute) |
| `export.batch_size` | `25` | Results per POST |
| `export.delay_seconds` | `2.0` | Pause between batches / multi-report exports |
| `export.max_retries` | `6` | Retries on 429 / rate limit |
| `export.retry_base_seconds` | `5.0` | Exponential backoff base |

Platform submit host is hardcoded to `https://genbounty.com` in
`pipeline.pipeline_settings.GENBOUNTY_EXPORT_HOST` (not stored in YAML).

On first load, leftover non-secret values still present in an old `.env`
(`GEMINI_USE_CACHE`, export batch knobs, etc.) are seeded into
`pipeline_settings.yaml` and then ignored in `.env`.

## Generation-mode constants

These tune how suites are generated. Most are **hardcoded module defaults**; a few
(notably preflight) also accept env overrides. Change the source default if you need
different shipped behavior:

| Constant / behavior | Default | Purpose |
|---------------------|---------|---------|
| Detection floor mode | `optional` | `optional` (floor on first suite / no refusals + closed-loop calibration recheck every 3 refusals), `required`, or `skip` - see `generation_mode.py` |
| Outcome technique ban min | `2` | Soft-demote a REGISTRY technique after this many refused/low hits |
| Auto feedback on Generate | on | Auto-enable feedback when a prior assessment exists |
| Partial stuck threshold | `0.8` | Refusal ratio that triggers partial-stuck escalation |
| Preflight critique | on | Target-aware preflight (`generation_critic` → fast `offensive_critic` by default); skips Enhance `bounty_mutate` rounds; critic `max_output_tokens=1024`. Requires an LLM API key. Override with `GENBOUNTY_PREFLIGHT_CRITIQUE=0` (off) or `=1` (on) |
| Preflight min score / keep floor | `40` / `3` | Drop threshold and minimum kept count; override via `GENBOUNTY_PREFLIGHT_MIN_SCORE` / `GENBOUNTY_PREFLIGHT_KEEP_FLOOR` |
| Gen transforms | off | Comma list of `kind:name` transform variants (empty by default) |
| Gen transform per category | `1` | Base prompts per category to derive each transform variant from |
| Generation debug | off | Verbose batch logging (800-char judge previews, parse diagnostics) |
| Category workers | `min(3, n_categories)` | Parallel category generation threads |
| Playbook refine | create on / regenerate off | `GENBOUNTY_PLAYBOOK_REFINE` (`0` skip, `1` force); unset = critic on Create only |

Job-injected generation flags (set per run by the web UI / CLI, not constants):

| Variable | Purpose |
|----------|---------|
| `GENBOUNTY_GEN_ATTRIBUTES` | Set `1` to attribute-rewrite the suite after generation |
| `GENBOUNTY_GEN_ATTRIBUTES_JSON` | Compact JSON for Temp/Max-tok/Top-k/Top-p |

New learned seeds, breakthrough attempts, and generation history are keyed by a hunt scope
derived from site/component, transport, hashed capabilities, playbook, and
attack-objective hash (recon model hints are excluded so hint churn does not fork scopes).
Reads and writes stay within that scope. Unscoped records are always
ignored, preventing cross-target contamination.

Judge output size is strategy-aware (not env-tunable): default strategies keep each prompt
under **600** characters (~**150** tokens) on a single line - longer is not more advanced;
change mechanism or the completable ask. Mechanism-heavy strategies (`self-reflection`,
`chain-of-thought`, `iterative`, `prompt-chaining`, `multi-shot`) allow up to **1800**
characters and newlines. Bounty invent also soft-drops prompts over **~900** characters
when the batch keep floor still holds, and hard-drops isomorphic asks (same prior ask,
including padded near-copies).

Generation **Attributes** Max-tok is a sampling-style hint for the rewriter: high values
must **not** mandate rhetorical padding to hit a token count (preserve attack goal and
mechanism; prefer compact prompts).

## Adaptive conversation

Adaptive follow-up delivery uses a hardcoded default: unapproved proposals are
**not** sent; the harness continues with a short deterministic sideways pivot.
To change this, edit `_send_unapproved_followups()` in `pipeline/adaptive_attacker.py`.

Adaptive follow-ups only surface the playbook `standard_action` operator follow-up when
the latest target reply looks like an accepted jailbreak/override. Premature embeds are
rejected so the follow-up cannot leak into unrelated harm-domain escalations. This field is
not an exploit oracle. Soft content-policy
rejects from the follow-up judge (e.g. refusing a lethal-dose escalation as "disallowed") are
retried on `defaults.refusal_fallback` in `llm.yaml`, then accepted via harness gates when the
proposal is a non-verbatim same-domain attack step.

## Playbook generalization settings

These settings live in playbook JSON rather than `.env`:

- Category presets may add `required_capabilities`, `optional_capabilities`,
  `capability_profile`, and `category_vectors` to categories. Required entries are hard
  applicability gates; optional entries enrich authoring. `category_vectors` is the sole
  artifact-vector source and sets the multimodal generator set and dynamic batch size.
- New instruction plays leave `generation.standard_action` empty. Configure one only as an
  operator follow-up; it does not establish exploit success.
- Code write→run→return `adaptive.delivery_constraints` are attached by presets only for a
  relevant execution L2 when recon confirms `code_execution` or `tool_use`.
- `playbook_config.assessment.oracles` is a mandatory non-empty list of
  severity-independent exploit predicates. Every category must be covered by at least one
  `semantic_rubric` with valid `category_ids`.
  Deterministic response/field/artifact/tool predicates resolve before judging;
  `semantic_rubric` is adjudicated by the assessment model. Tool oracle context
  contains sanitized matching labels only. The resulting `exploit_status`
  is stored separately from `risk_level`.

Oracle model version/hash values are generated metadata, not operator settings. Missing,
empty, unscoped, or category-incomplete oracle contracts fail playbook validation.

## Browser-bot defaults (`config.defaults.yaml`)

Baseline runtime settings, all overridable per site/component. Notable keys:

| Key | Example | Meaning |
|-----|---------|---------|
| `FETCH_METHOD` | `human` | Page fetch strategy (shipped: human for browser UI targets; `pool` / `cluster` / `auto` for throughput) |
| `POOL_SIZE`, `CONTEXT_COUNT`, `PAGES_PER_CONTEXT` | `1` | Browser pool sizing for concurrent UI prompts (headless). Playbook `stop_words` / canaries do **not** force sequential runs — concurrency wins; markers are still recorded on completed replies. Headed/CDP stays single-browser. |
| `API_CONCURRENCY` | `2` | Concurrent API submissions (Browser Config writes `browser_bot/config.py`, including annotated assignments like `API_CONCURRENCY: int = …`; component `settings:` still overrides at run time). High values can cause null captures under rate limits; failed API rows store `http_status` / `api_error` in the run log. Stop-words likewise do not reduce this concurrency. |
| `EVASION_REQUEST_DELAY_S`, `EVASION_RETRY_WAIT_S`, `EVASION_MAX_RETRIES` | `0.5`, `10.0`, `3` | Pacing / retry behavior. Concurrent API workers also stagger by `EVASION_REQUEST_DELAY_S`; Messages API transport retries once on 429/502/503/529. |
| `RUN_SCREENSHOT_INTERVAL_S` | `0` | Live screenshot cadence during runs (`0` = disabled) |
| `submission.response_stable_ms` | `1200` | How long a streamed reply must stay unchanged before capture is treated as complete; unstable captures are flagged `capture_incomplete` |
| `submission.multi_turn` / `submission.single_turn` | auto / `true` / `false` | Whether the target keeps conversation history. Explicit flags win. Otherwise UI defaults on; API is on only with `{{messages}}` (or `api_context_mode: messages`). When false, generate/run skip multi-turn strategies (`multi_shot`, `iterative`, `prompt_chaining`, …) |
| `HUMAN_*` | styles / scroll / rotate on | Human-tier behavior (country, delays, user agent, styles, scroll, attribute rotation) |
| `HEADLESS` | `false` | Run with a visible browser window (shipped for browser UI targets) |
| `USE_CDP_BROWSER`, `CHROMIUM_EXECUTABLE_PATH`, `CHROME_CHANNEL` | - | Browser binary selection |
| `POOL_CLUSTER_*` | human-like + styles / stealth / Chrome / context on | Pool/cluster stealth/styles/context enhancements. **Does not** shrink `POOL_SIZE` / cluster workers to 1 — human-like and concurrency are independent. Stealth/context also forced on at run time when `FETCH_METHOD=human` or `submission.cloudflare_headed` |
| `submission.cloudflare_headed` | - | Component flag (under `submission:`, not `settings:`). Headed runs for that component auto-use real Chrome via CDP without global `USE_CDP_BROWSER`. After a successful Turnstile clear, clearance cookies are merged into `auth.json` and this flag is persisted if missing |

Component `config.yaml` may also set hunt-feature flags under `settings:` that are not
browser-pool keys, for example:

| Key | Default | Meaning |
|-----|---------|---------|
| `intel_credentials_and_paths` | off | **Premium (Intel).** Credentials/paths inventory helpers (see [01 - Overview](01-overview.md#community-vs-premium)). |
| `BLOCKED_TYPES` | `font, media` | Resource types blocked during fetch (images allowed by default) |
| `*_use_cache` / `*_cache_*` | - | Per-provider prompt cache toggles (globals in `pipeline_settings.yaml`) |

## LLM provider mapping (`llm.yaml`)

`llm.yaml` maps pipeline **roles** to **profiles** (a provider + model), letting you split
generation from assessment and expert from judge across vendors. Copy `llm.yaml.example` to
`llm.yaml` to start. Structure:

```yaml
llm:
  profiles:
    offensive_generator: { provider: openrouter, model: x-ai/grok-4.3 }
    offensive_fallback:  { provider: openrouter, model: nousresearch/hermes-4-70b }
    offensive_fast:      { provider: openrouter, model: x-ai/grok-4.3 }
    offensive_editor:    { provider: openai, model: gpt-5.6-sol }
    offensive_critic:    { provider: openrouter, model: x-ai/grok-4.3 }
    triager:             { provider: anthropic, model: claude-sonnet-5 }
    methodologist:       { provider: anthropic, model: claude-sonnet-5 }
    grounder:            { provider: openrouter, model: tencent/hy3 }
    operator:            { provider: gemini, model: gemini-3.1-flash-lite }
    # ...
  roles:
    generation_expert: offensive_generator
    generation_judge: offensive_editor
    generation_critic: offensive_critic
    assessment_expert: triager
    assessment_judge: triager
    playbook_author: methodologist
    enhance_theory: offensive_fast
    recon: operator
    # ...
  defaults:
    refusal_fallback: offensive_fallback
    retry:      { attempts: 4, backoff_min: 15, backoff_max: 90 }
    rate_limit: { capacity: 4, refill_per_sec: 0.5 }   # global + per_provider RPM (no env override)
```

OpenRouter is optional (Grok 4.3 authoring/transforms/preflight critic/enhance_theory + Hermes 70B
refusal fallback + Hy3 grounder in the shipped map). Native `openai` /
`anthropic` / `gemini` / `grok` stay first-class. See dual layouts in
[`llm.yaml.example`](../llm.yaml.example). Each provider referenced needs its key set
in `.env` (`GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GROK_API_KEY`,
`OPENROUTER_API_KEY`). Roles include generation expert/judge/critic, assessment
expert/judge, playbook author/critic, enhance theory, recon, recon consolidate, grounding
judge, discovery, prompt transforms, technique synthesis, and boilerplate classifier
(`generation_critic` powers the shipped-on preflight critique). The UI exposes this as
**Settings → Configure LLMs**. Role-by-role catalog: [18 - LLM roles](18-llm-roles.md).

### OpenRouter model validation

Every `provider: openrouter` profile model id is checked against OpenRouter’s live
catalog (`GET https://openrouter.ai/api/v1/models`, cached ~1 hour in-process):

| When | Behavior |
|------|----------|
| **Settings → Configure LLMs → Save profiles** | Fail-closed: unknown/removed/deprecated slugs (e.g. retired `x-ai/grok-4-fast`) reject the save with HTTP 400. If the catalog cannot be fetched, save still proceeds and a warning is logged. |
| **Web app startup** | Fail-closed: fetches the live catalog for every `provider: openrouter` profile; unknown/empty slugs **or** catalog fetch failure abort boot with a clear `[llm] OpenRouter model validation failed - refusing to start.` message. Fix `llm.yaml` / Settings, then restart. |
| **GET `/api/llm-config`** | Includes `openrouter_validation` (`checked`, `ok`, `errors`, `warnings`, `unknown_models`) so the UI can show a banner. |

This is a runtime check, not a comment in `llm.yaml`. After fixing slugs, restart the
web server so in-memory LLM config caches reload.

## Factory reset

`POST /api/settings/reset-factory` restores settings to `config.factory.yaml`, clears
site/component `settings:` overrides, and resets global cache toggles in
`pipeline_settings.yaml` (not `.env`).
