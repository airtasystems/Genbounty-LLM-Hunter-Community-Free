# 04 - Architecture

## High-level flow

```
                +-------------------+
                |   Web UI (SPA)    |  web/static/  (partials/ + js/ modules + thin app.js)
                +---------+---------+
                          | HTTP / SSE
                +---------v---------+
                |  FastAPI backend  |  web/app.py + web/routers/ (~100 endpoints)
                +---------+---------+
                          | starts async jobs
                +---------v---------+
                |   Job manager     |  web/jobs.py  (generate, recon, run, assess, export...)
                +----+----+----+----+
                     |    |    |    |
        +------------+    |    |    +--------------------+
        v                 v    v                         v
  generate-tests/     browser-bot/                   pipeline/
  attack suites       execution runner               convert + assess + export
        |                 |                              |
        v                 v                              v
   suite JSON        run_log.json  ->  attack_log.json  ->  pipeline_report.json
                                                            |
                                          +-----------------+-----------------+
                                          v                                   v
                                   JSON download                       Genbounty import
```

## Components

### Entry points (repo root)

- **`start.py`** - bootstrapper. Creates/uses the project virtualenv, installs
  `requirements.txt`, installs Playwright Chromium (with Ubuntu platform override where
  needed), then launches `web/app.py`.
- **`main.py`** - scripting CLI for automation and CI. Subcommands: `generate`, `run`,
  `security-assess`, `export`. See [06 - CLI reference](06-cli-reference.md).

### Web layer - `web/`

- **`app.py`** - the FastAPI application entrypoint. Mounts static assets and includes
  routers under `web/routers/` for sites, components, auth, config, recon, intel,
  capabilities, playbooks, strategies, test files and prompt transforms, payloads, jobs,
  credentials, cache settings, and logs. See [10 - API reference](10-api-reference.md).
- **`routers/`** - FastAPI route modules (`playbooks.py`, `tests.py`, `sites.py`, …).
  Handlers stay thin; heavier orchestration lives in `web/services/`.
- **`services/`** - shared web-layer helpers. `playbook_authoring.py` owns generate/save
  playbook orchestration (`generate_and_save`) and contract error shaping;
  `suite_io.py` centralizes probe-suite path/load/save and transform apply helpers used by
  Armory prompt-transform endpoints.
- **`spa.py`** - index.html assembly from `index.template.html` + `partials/` (include
  resolution and mtime cache) and `CachedStaticFiles` for `/img`.
- **`paths.py`** - shared `ROOT` / `BB_DIR` / static paths and `sys.path` bootstrap.
- **`port_reclaim.py`** - startup port bind helpers; reclaims prior Genbounty `web/app.py`
  listeners for this checkout before bind.
- **`jobs.py`** - async job manager: spawns, tracks, streams, and cancels long-running
  tasks (cancel kills the active subprocess and stops multi-step generate loops),
  and drives the interactive "theory accept/reject" step for closed-loop generation.
- **`static/`** - the single-page app. The Vue template is split for maintainability:
  `index.template.html` is the shell (`<head>`, layout scaffold) with
  `<!-- @include path.html -->` markers, and `partials/` holds one file per section
  (`partials/header.html`, `partials/output-panel.html`, `partials/jobs-drawer.html`,
  `partials/modals/*.html`, and `partials/tabs/<tab>.html` for each sidebar tab).
  `spa.py` reassembles these into the served HTML at request time (see below). Styles stay
  in `style.css`; payload editing stays in `payload-editor.js`. Vue behaviour is modular
  under `web/static/js/` (IIFE factories on `window.Genbounty`): helpers (`api.js`,
  `format.js`, `storage.js`, `confirm.js`, `ctx.js`), shared `scope.js` / `jobs.js`,
  tab domains in `js/tabs/*.js` (plus `connect-target`, `prompt-transforms`,
  `discover`, `run-starters`), `js/app-lifecycle.js` (mount/watches/poll), thin
  orchestrator `js/app-setup.js` (`useAppSetup` calls factories in order -
  `useConnectTarget` before `useJobs` so `loginRunning` exists for panel output -
  and returns `ctx`), and a thin `app.js` that builds `ctx`, calls `useAppSetup`,
  registers the payload editor, and mounts.
- **Worker shims** - `recon_worker.py`, `login_worker.py`, `discover_worker.py`,
  `manual_discover_worker.py`, `api_discover_worker.py`, `recon_round_worker.py`,
  `recon_from_report_worker.py` run individual job types.
Request serving: `GET /` (in `spa.py`) returns the assembled `index.template.html`
(partials resolved via `_resolve_includes`). The assembled HTML is cached in memory and
rebuilt automatically when the template or any file under `partials/` changes (mtime
check). Set `GENBOUNTY_DEV_NO_CACHE=1` to rebuild on every request. The `/img` and
`/static` assets are returned as file responses (`/img` carries a long `Cache-Control`;
`/static` keeps ETag/304 revalidation so unhashed JS/CSS is never served stale). Read-only GET endpoints that only touch disk are
plain (non-`async`) handlers, which Starlette runs in a threadpool so their file I/O does not
block the event loop. `POST /api/playbooks/generate` is `async` but runs
`generate_playbook_json` via `asyncio.to_thread` and watches `request.is_disconnected` so
Cancel/Stop does not freeze port 8000. Uvicorn auto-reload is opt-in
(`GENBOUNTY_DEV_RELOAD=1`); the default single-process server avoids a reloader parent
keeping `:8000` listening while a wedged worker ignores requests. Startup calls
`reclaim_project_port` so a prior Genbounty `web/app.py` for this checkout (including
Ctrl+Z-stopped orphans) is SIGKILL'd before bind. Playbook directory listings are
cached behind a directory signature (file names + mtimes) and refresh automatically
when a playbook is added, edited, or removed.

### Test generation - `generate-tests/`

- **`core.py`** - suite generation core (`generate_attack_suite`); the CLI batch generate
  path imports and calls this in-process (reusing warm LLM clients), while the web `generate`
  job invokes it via a subprocess for live streaming. Categories run in parallel via
  `ThreadPoolExecutor`; each worker gets a **thread-local** compiled LangGraph app
  (`_thread_local_graph`) to avoid cross-thread `invoke` races. Cross-category dedup uses
  **exact** match against generation-history signatures and **fuzzy** `SequenceMatcher` only
  within the current suite (not against all 240 history sigs).
- **`generator.py`** - the entry invoked as a subprocess by the `generate` job (and the CLI
  fallback).
- **`playbook_generator.py`** - authors playbooks from the create-play wizard
  (hypothesis + category + locked success/fail rules). Category presets live in
  `playbooks/category_presets.py`. New plays use the sole leaf `mission.hunt`
  (internal id) with a required hunt name (`play_category_label`); the wizard defaults
  the mission file id to that name’s slug. `playbooks/taxonomy/category_catalog.json` is the declarative source
  of truth for leaf semantics and family mappings; `playbooks/category_catalog.py` validates
  and materializes it into `LEAF_CATALOG`;
  families are implementation units, never runtime fallbacks. Unknown or incomplete paths
  fail closed. The generate API fills missing rules/strategies from the exact leaf preset
  and stamps structured `required_capabilities`, `optional_capabilities`,
  `capability_profile`, and `category_vectors`. Required capabilities gate applicability,
  and `category_vectors` is the sole source for artifact generator selection.
  New instruction plays receive no implicit `standard_action`, and write→run→return rails
  are attached only to code-runtime execution L2s when `code_execution` or `tool_use` is
  confirmed. Uses recon/intel for feasibility only (fingerprint dumps stripped) and
  enforces attack-vs-proof trigger hygiene so rubrics do not overfit to containment
  checks.
- **Prompt transforms** - `prompt_cipher.py`, `prompt_obfuscation.py`,
  `prompt_translation.py`, `prompt_native.py`, `prompt_frame.py`, `prompt_code_embed.py`,
  `prompt_iq.py`, `prompt_emotion.py`, `prompt_attributes.py`. Human translation stays in
  `prompt_translation.py`; model-native dialects live in `prompt_native.py`
  (`llm_native` is a pretrain/peer-packet text-channel stand-in - JSONL, code/config
  directive, or assistant-continuation stub that translates the ask into native
  directive language while preserving full meaning/context, with a response-dialect
  lock - not tokenizer/latent telepathy; `llm_native_rt` is JSONL-only with typed locks,
  `emit_def`, a pipeline-appended answer stub, and the same meaning-preserving native
  dialect rewrite of the ask - not a softener and not a verbatim English wrap). Native
  rewrites request JSON mode and recover common unescaped `["{...}"]` model wraps via
  `parse_llm_json_string_array`; red-team
  framings (`persona`, `pretext`, `few_shot`, `format`, `indirection`, `poem`, `song`,
  `short_story`, `hypothetical`, `exam`, `bug_report`, `continuation`, `screenplay`)
  live in `prompt_frame.py`; emotional tone (0 loving → 300 angry) lives in
  `prompt_emotion.py`. **Code** embeds (`python` … `cpp`, plus `json` / `html`) are
  rewritten by the tiny `prompt_code_embed` role (shipped: Gemini flash-lite via
  `operator`) into idiomatic code/markup that carries the ask - not a naive string
  assignment wrap (deterministic wrap is only a failure fallback).
  These also run at generation time (not just as manual UI actions): when
  `GENBOUNTY_GEN_TRANSFORMS` is set, `strategies/gen_variants.py` appends a bounded
  set of encoding / multilingual / native / frame / cipher / code-embed variants of base
  prompts to each suite so campaigns cover those bypasses automatically.   Playbooks may
  also set `generation.delivery_transforms` so
  `apply_playbook_delivery_transforms` encodes cleartext seeds via the same
  transform API (`replace` or `variant`) after lexicon expansion and before attributes.
  When the UI **Apply to Generate & Enhance** master checkbox is on, Generate and
  Enhance jobs may set:
  - `GENBOUNTY_GEN_TRANSFORM_PIPELINE=1` + `GENBOUNTY_GEN_TRANSFORM_PIPELINE_JSON`
    (ordered steps from per-row transform checkboxes) →
    `prompt_gen_pipeline.apply_gen_transform_pipeline` stacks those transforms on
    **live** prompt text in panel order (Technique → Emotion) before write, seeding
    `_obfuscation_plain` once so Restore English still works.
  - `GENBOUNTY_GEN_ATTRIBUTES=1` + `GENBOUNTY_GEN_ATTRIBUTES_JSON` →
    `prompt_attributes.attributes_rewrite_suite` applies Temp/Max-tok/Top-k/Top-p
    styling after the transform pipeline. It styles **live** prompt fields (not
    `_obfuscation_plain` backups), skips structural obfuscation/cipher/code-embed/
    control-code payloads and any text that already carries non-ASCII / zero-width /
    bidi delivery encoding, and rolls back a rewrite that strips those characters.
- **`strategies/preflight_critique.py`** - target-aware critique pass
  (`generation_critic` role) that scores freshly generated prompts against the target's
  recon and drops / sharpens the ones unlikely to bypass it. Shipped on; force off with
  `GENBOUNTY_PREFLIGHT_CRITIQUE=0` (or on with `=1`); skips Enhance `bounty_mutate`
  rounds; critic budget 1024 tokens; never empties a batch.
- **`strategies/attack_techniques.py`** - runtime, taxonomy-keyed attack-technique
  registry whose keys exactly equal the canonical leaves loaded from
  `playbooks/taxonomy/category_catalog.json`. Each leaf resolves through
  its declared `technique_family`; unknown/L1-only categories raise an error. For
  `mission.hunt`, every category must provide a non-empty, valid, uniquely named
  `attack_techniques` array, which is the runtime source of truth.
- **`enhance_theory.py`** / **`enhance_theory_history.py`** - interactive enhancement
  theory (accept/reject) that closes the play using assessed reports, effective
  recon/intel, operator custom instructions, and past theories. Theory loading does
  not depend on `GENBOUNTY_FEEDBACK` being set on the parent process. Theories emit
  per-category Next-batch plans (≤ closed-loop batch size); generation slices the
  accepted theory per category via `strategies/theory_fidelity.py`. Drop/burned-token
  avoid-lists are a **silent post-generation metal detector** (`DROP_TOKENS_ENABLED=True`,
  `SILENT_DROP_FILTER=True`): concrete tokens are extracted from theory Drop bullets and
  recon/intel, then finished prompts that still contain them are hard-filtered. The writer
  and judge never receive the ban list (negation bait). Theory steers 1:1 technique slots by
  preferring Next-batch / Machine plan REGISTRY names. Theories include a prefer-only
  Machine plan JSON block; prose→REGISTRY mapping fills prefer when names are absent.
  Prior assessed refusals soft-demote repeatedly failed REGISTRY techniques
  (`outcome_banned_technique_names` in `prior_results.py`).
- **`strategies/prior_results.py`** - closed-loop outcome signal. Classifies each prior
  assessed row as `exploited` / `partial` / `refused` / `inconclusive` (preferring the
  assessment's `exploit_status` / `outcome` fields, with severity-only fallback for legacy
  reports), joins each row to its parent
  suite for `technique` / `probe_class` when the report omitted them, promotes only
  demonstrated exploits to the learned corpus, escalates from refusals *and* near-miss
  partials, and drops capture-failure rows so harness noise can't force breakthrough.
  All-refusal categories advance from observed refusals first; breakthrough only after
  avoid-seeds exist. Techniques refused at least `GENBOUNTY_OUTCOME_TECH_BAN_MIN`
  times (default 2) without a success/partial are soft-demoted on the next batch.
- **`strategies/`** - per-strategy prompt builders. **`corpus/`** - shared source material
  (gitignored locally). Optional curated root leaf JSON (`corpus/<l1>.<l2>.json`) supplies
  exact-leaf exemplars when present; missing leaves yield no curated exemplars (no L1/sibling
  fallback). The closed loop persists two independent stores: `corpus/learned/` holds
  demonstrated-success seeds (mutate-these exemplars, capped highest-severity-first), while
  `corpus/breakthrough/` holds untested divergent attempts as a rolling newest-first
  "already tried" avoid-list (capped so the freshest attempts survive). Keeping them separate
  stops a full avoid-list from evicting proven exemplars and vice versa. Seeds are validated
  at capture for coherence, near-duplicate filtered on persist, and ``load_corpus``
  interleaves curated + learned with per-source caps so feedback seeds are not crowded out.
  Learned and breakthrough data, plus generation history, are isolated by a stable hunt scope
  derived from target site/component, transport, capability signature, playbook, and objective
  hash (not recon model hints). Curated seeds remain global when present. Scoped records
  retain non-sensitive scope provenance; unscoped learned, breakthrough, and history records
  are always ignored.

### Test execution - `browser-bot/`

- **`main.py`** - the runner (`run_posts`).
- **`browser_bot/`** package:
  - **`browser/`** - Playwright `launcher.py`, `human_behavior.py`, `routes.py`.
  - **`fetchers/`** - `pool.py`, `cluster.py`, `human.py`, `ui_bundle.py` (page pools).
  - **`submit/`** - `single.py`, `multi.py`, `adaptive.py`, `api.py`, plus
    `rejection_detection.py` and `response_filters.py` / `response_boilerplate.py`
    (welcome/intro text recorded in Configure → `response_ignore_substrings`, plus
    pre-submit response-surface chrome, so static greeting bubbles are not mistaken
    for the model reply).
  - **`recon*.py`** - discovery and recon graph building.
  - **`auth*.py`** - login and auth-state persistence.
  - **`page_blockers.py`** - Cloudflare/cookie and resource blocking.
  - **`sites.py`** - the on-disk site/component model.
- **`sites/`** - registered targets (see the directory model below).

### Assessment & reporting - `pipeline/` and `risk-level-agent/`

- **`pipeline/convert_log.py`** - normalizes `run_log.json` into `attack_log.json`, carrying
  capture-quality flags (`capture_incomplete`, `artifact_delivered`). Suite binding uses
  stable `id` / `capture_id` first (not suite file order), so probe-class reordering cannot
  mis-pair prompts with responses. Legacy canary tokens and flags receive no special
  extraction or classification.
- **`pipeline/security_assess.py`** - runs the AI-assisted severity assessment. Its fast-path
  is graded: entries with an exploit signal always go to full assessment, while a
  client-side rejection is scored `low`, and a failed/partial capture or an undelivered
  multimodal artifact is scored `indeterminate` (rather than being read as a clean refusal).
  Full assessment uses a single triage call when the expert verdict is solid; see
  `risk-level-agent` below.
- **`pipeline/evidence_signals.py`** - neutral deterministic detectors (anchored multilingual
  refusal, credential/secret-looking output, verbatim-prompt echo) that run before the
  judge, anchor its verdict, and feed `evidence_signals` / `evidence_strength`.
- **`pipeline/oracles.py`** - resolves mandatory play-specific success predicates independently
  from severity, including response markers/regex, structured fields, explicit tool flags,
  artifact delivery, and semantic rubrics. Every authored category must be covered by
  at least one `semantic_rubric` oracle whose non-empty `category_ids` references existing
  category ids. Deterministic predicates resolve before assessment; semantic rubrics remain
  pending until the assessment expert/judge returns a structured exploit verdict. Matching
  tool summaries are opt-in and sanitized before reaching assessment prompts. Each
  suite and assessed row carries oracle model
  `oracle_version` plus an order-independent `oracle_hash`; reports preserve the common
  contract metadata.
- **`pipeline/report.py`** - shared source of truth for severity ordering
  (`SEVERITY_ORDER`, `severity_index`), the per-category `category_rollup`,
  `pipeline_report.json` assembly (`build_pipeline_report`), and pruning a single
  assessed row (`delete_adversarial_result`). Used by the CLI (`main.py`),
  the web job manager (`web/jobs.py`), and the assessment / Risk UI so the severity
  logic is defined once.
- **`pipeline/export_security.py`** / **`export_genbounty.py`** - build the JSON export or
  POST to the Genbounty import API.
- **Recon / intel helpers** - build the capability baseline (`recon.json`) and per-play
  learning that Recon rounds / report extract write for Forge and Enhance. Full target
  response dumps are not stored. The dedicated **Intel** workspace and credentials/paths
  inventory tools are Premium. For API targets, capabilities come from what this request
  can actually do (not hedged platform marketing); multi-turn strategies need a transport
  that can carry chat history.
- **`pipeline/component_settings.py`** - resolves effective browser/runtime settings.
- **`pipeline/llm/`** - the multi-provider LLM abstraction (Gemini/OpenAI/Anthropic/Grok/OpenRouter),
  configured via `llm.yaml`.
- **`risk-level-agent/risk_level_agent.py`** - playbook triage (expert) plus an optional judge
  that assign a normalized severity level and a `confidence` (`low`/`medium`/`high`). The
  expert produces a final-quality verdict in one call; when that triage is solid
  (`parse_ok`, not `indeterminate`, and either `confidence=high` or a clear
  `low`/`informational` level) the judge LLM call is skipped and the expert verdict is
  accepted (`[expert-accepted]` in `judge_reasoning`). The judge still runs when parse
  fails, confidence is weak on elevated risk, or multiple experts disagree. Untrusted
  input (the attack prompt and the model's response) is fenced in explicit delimiters and
  the system prompts instruct the judge/experts to treat it as data, not instructions, so
  a malicious response cannot steer its own verdict. Expert nodes are rediscovered from
  `playbooks/*.json` on each assessment (`refresh_expert_registry`) so plays added after
  process start still get `expert_<stem>`; missing/unknown plays fall back to a synthetic
  `expert_play` node so the LangGraph always has a START→expert edge.

### Strict generalization contracts and verification

Schema v3 playbooks are validated as strict contracts. A valid play uses a canonical
`L1.L2` leaf, has at least one category, gives every category category-scoped semantic-oracle
coverage, and supplies non-empty `category_vectors` plus mapped artifact delivery methods for
each artifact category. `mission.hunt` additionally requires authored `attack_techniques`.
Unknown leaves, capability mismatches, missing oracle coverage, unsupported vector fields, and
invalid artifact vectors fail closed; playbook APIs expose these as structured HTTP 422
`invalid_playbook_contract` responses. Campaign planning removes capability-inapplicable
categories and returns no strategies when none remain runnable. Learning records are written
and read only within their target hunt scope; unscoped records do not participate.

Focused regression coverage lives in `pipeline/tests/test_oracles.py`,
`pipeline/tests/test_oracle_metadata.py`, `pipeline/tests/test_report.py`,
`pipeline/tests/test_mocked_profile_end_to_end.py`,
`generate-tests/tests/test_target_scoped_learning.py`,
`generate-tests/tests/test_category_presets.py`,
`generate-tests/tests/test_capability_profiles.py`, and
`web/tests/test_playbook_capability_api.py`.

### Playbooks & payloads

- **`playbooks/`** - security plays (schema v3 JSON) plus `categories.py`, `registry.py`,
  `campaign.py`, `playbook_config.py` (re-export facade over `playbooks/config/`), and
  `_template.json`.
- **`payloads/`** - multimodal artifact generators (PDF, CSV, image, QR, audio) and their
  schemas. See [08 - Payloads & multimodal](08-payloads-multimodal.md).

## Site / component directory model

Each registered target lives under `browser-bot/sites/<host>/<component>/`:

```
browser-bot/sites/
  <host>/                         e.g. chatgpt.com, gemini.google.com
    config.yaml                   site-wide overrides (optional; tracked)
    auth.json                     site-level session/public auth metadata (optional; gitignored)
    <component>/                  e.g. chat
      config.yaml                 selectors / API transport + settings overrides (tracked)
      auth.json                   session cookies / API-key metadata (secret is in .env; gitignored)
      recon.json                  component baseline (from recon; tracked)
      enhance_theory_history.json closed-loop theory history (gitignored)
      nuke_backups/<timestamp>/   full pre-Nuke snapshot (gitignored)
      intel/                      per-play hunt learning + credentials inventory (gitignored)
      tests/                      generated suites + multimodal artifacts (gitignored)
      logs/                       run captures / reports (gitignored)
      strategy_handoff/           closed-loop handoff artifacts (gitignored)
      .login_profile/             persistent browser profile for login (gitignored)
```

## Configuration precedence

From lowest to highest priority:

1. `config.defaults.yaml` (shipped baseline)
2. `browser-bot/browser_bot/config.py` + `pipeline_settings.yaml` cache block (Settings → Browser Config / Cache Control)
3. `browser-bot/sites/<site>/config.yaml` (site-wide overrides)
4. `browser-bot/sites/<site>/<component>/config.yaml` (per-component overrides)

`.env` holds API secrets only (provider keys, `GENBOUNTY_API_KEY`, `TARGET_API_KEY_*`).
See [09 - Configuration](09-configuration.md) for details.
