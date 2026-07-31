# API reference (advanced)

> Prefer the live OpenAPI UI at `http://localhost:8000/api/docs` while the server runs.
> Operator docs: [documentation/README.md](../README.md).

The backend is a FastAPI app (`web/app.py` + `web/routers/`) that serves the SPA and a REST
API.

All long-running work (generate, recon, run, assess, export) is dispatched through the
**job system** (`web/jobs.py`) rather than blocking HTTP calls.

## Conventions

- Base URL: `http://localhost:8000`
- A **site** is a host (e.g. `chatgpt.com`); a **component** is a sub-target (e.g. `chat`).
- Most target-scoped routes are under `/api/sites/{site}/{component}/...`.

## Sites & components

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/sites` | List registered sites |
| POST | `/api/sites` | Create a site from a domain/URL |
| PATCH | `/api/sites/{site}` | Rename / update a site |
| DELETE | `/api/sites/{site}` | Remove a site |
| GET | `/api/sites/{site}/components` | List components |
| POST | `/api/sites/{site}/components` | Create a component |
| PATCH | `/api/sites/{site}/components/{component}` | Rename / update a component |
| DELETE | `/api/sites/{site}/components/{component}` | Remove a component |

## Authentication

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/sites/{site}/auth-status`, `/api/sites/{site}/{component}/auth-status` | Auth state |
| POST | `/api/sites/{site}/{component}/auth/reuse` | Copy auth from another component |
| POST | `/api/sites/{site}/auth/public`, `/api/sites/{site}/{component}/auth/public` | Mark as public (no auth) |
| POST | `/api/sites/{site}/auth/api-key`, `/api/sites/{site}/{component}/auth/api-key` | Save target API key to `.env` (`TARGET_API_KEY_*`); metadata in `auth.json` |
| DELETE | `/api/sites/{site}/auth`, `/api/sites/{site}/{component}/auth` | Clear auth (also removes `TARGET_API_KEY_*` from `.env`) |

## Component config, recon, intel, capabilities

| Method | Path | Purpose |
|--------|------|---------|
| GET/POST | `/api/sites/{site}/{component}/config` | Read / write per-component config |
| GET | `/api/sites/{site}/{component}/config/status` | Config status |
| POST | `/api/sites/{site}/{component}/config/reuse` | Copy config from another component |
| GET/PUT/DELETE | `/api/sites/{site}/{component}/recon` | Read / edit / delete `recon.json` |
| GET | `/api/sites/{site}/{component}/capabilities` | Effective capabilities (`file_upload`, `multi_turn`, `code_execution`, `web_browse`, `image_gen`, `retrieval`, `memory`, `tool_use`) |
| GET | `/api/sites/{site}/{component}/intel` | List play intel files |
| GET | `/api/sites/{site}/{component}/intel/{playbook_id}` | Read per-play intel (Recon / report extract write these) |
| GET/PUT | `/api/sites/{site}/{component}/notes` | Read / replace operator Notes for the component |
| POST | `/api/sites/{site}/{component}/notes/append` | Append text to Notes |
| POST | `/api/sites/{site}/{component}/notes/append-manual-query` | Append a Firing Range query/response pair to Notes |
| GET | `/api/sites/{site}/{component}/effective-settings` | Resolved settings |

Intel workspace edits and credentials/paths inventory tools are **Premium** — see
[01 — Overview](../01-overview.md#community-vs-premium).

## Playbooks

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/playbooks`, `/api/playbooks/manage` | List playbooks |
| GET | `/api/plays/categories` | Play category taxonomy |
| GET | `/api/plays/category-presets` | Complete strict catalog containing only `preset_families`, `capability_families`, `leaf_mappings`, `leaf_presets`, and `leaf_count` |
| GET | `/api/plays/category-presets/{l1}/{l2}` | Exact leaf preset with structured capability/vector metadata and `source: "leaf_catalog"`; unknown/incomplete leaves return structured 422 |
| GET | `/api/playbooks/template` | Play template |
| POST | `/api/playbooks/generate` | Author a strict play from title/play/exact leaf (+ locked success/fail rules, `overwrite`, `rebuild_from_objective`, `authoring_mode`=`human`\|`ai`, `site`, `component`). `authoring_mode=ai` injects a structure-only gold craft brief from `playbooks/_template.json` when present (content redacted); otherwise uses the mission craft checklist. Runs off the event loop so the UI stays responsive. Closing the client connection (UI **Stop**) cancels between LLM attempts and returns HTTP 499. With target context, confirmed capabilities gate the leaf and generated categories. Output must include category-scoped semantic oracles, valid `category_vectors`, and authored `attack_techniques` for `mission.hunt`; contract failures return structured 422. Optional `playbook_config.prompt_template` / `prompt_task` / `prompt_format` wrap every seed (`{{input}}` = attack body). Legacy `objective_lexicon` still expands when present on disk. |
| GET | `/api/playbooks/{playbook_id}` | Read a play |
| POST/PUT/DELETE | `/api/playbooks`, `/api/playbooks/{playbook_id}` | Create / update / delete |
| POST | `/api/playbooks/{playbook_id}/rename` | Rename id (`new_playbook_id`, optional `data`); moves file and relinks suites + intel |
| POST | `/api/playbooks/{playbook_id}/convert-text-channel` | Convert channel |

Preset metadata semantics:

- `required_capabilities` are hard applicability gates and may express alternatives such as
  `code_execution|tool_use`.
- `optional_capabilities` enrich authoring but do not make a category applicable.
- `capability_profile` is a stable profile label for the category's intended surface.
- `category_vectors` is the sole artifact-vector source; multimodal generation and delivery
  mapping use it to select generators and dynamic batch size.

The preset catalog endpoints return capability metadata but are not target-scoped.
`POST /api/playbooks/generate` becomes capability-aware when both `site` and `component` are
provided and effective recon is available: it combines that recon with config-derived
capabilities, passes confirmed capabilities into preset resolution and authoring, attaches
write→run→return delivery constraints only to code-runtime execution L2s with confirmed
`code_execution` or `tool_use`, and rejects the full authored result if any category is
capability-incompatible. Without usable
target context, structured metadata is still stamped, but capability-dependent rails are not
inferred.

### Strict playbook errors

Playbook create/update/generate and preset resolution fail closed. Contract violations use
HTTP 422 with:

```json
{
  "code": "invalid_playbook_contract",
  "errors": [{"code": "leaf_contract", "message": "..."}]
}
```

Error codes distinguish leaf, capability, oracle, vector, and general playbook contracts.
Examples include an unknown `L1.L2` leaf, a required capability not confirmed for the target,
missing category-scoped `semantic_rubric` coverage, missing/invalid artifact
`category_vectors`, or absent/invalid `mission.hunt` `attack_techniques`. The generate route
may also include a top-level `message` when an authoring attempt raises a structured
`PlaybookContractError`.

## Strategies, test files & prompt transforms

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/strategies`, `/api/sites/{site}/{component}/strategies` | Available strategies |
| GET | `/api/sites/{site}/{component}/all-playbooks` | Playbooks with test files |
| GET | `/api/sites/{site}/{component}/test-files` | List generated suites |
| GET | `/api/sites/{site}/{component}/strategies/{strategy}/playbooks` | Suites per strategy |
| GET/PUT/DELETE | `/api/sites/{site}/{component}/tests/{strategy}/{playbook}` | Read / edit / delete a suite file |
| POST | `.../tests/{strategy}/{playbook}/obfuscate` | Obfuscate prompts |
| GET | `.../tests/{strategy}/{playbook}/obfuscation-status` | Obfuscation / transform status for a suite |
| POST | `.../tests/{strategy}/{playbook}/cipher` | Cipher-encode prompts |
| POST | `.../tests/{strategy}/{playbook}/translate` | Translate prompts (human languages) |
| POST | `.../tests/{strategy}/{playbook}/native` | Rewrite prompts into a native dialect (`llm_native` pretrain/peer packet, `llm_native_rt` red-team peer packet, `agentic`, `machine`, `planner`, `chat_template`, `wire`) |
| POST | `.../tests/{strategy}/{playbook}/frame` | Rewrite prompts with a frame technique (`persona`, `pretext`, `few_shot`, `format`, `indirection`, `poem`, `song`, `short_story`, `hypothetical`, `exam`, `bug_report`, `continuation`, `screenplay`) |
| POST | `.../tests/{strategy}/{playbook}/code-embed` | Embed prompts in code |
| POST | `.../tests/{strategy}/{playbook}/control-code` | Wrap prompts with a control-code technique (`ctrl_spaced`, `ctrl_padded`, `brace_opcode`, `glossary_then_payload`) |
| POST | `.../tests/{strategy}/{playbook}/iq-rewrite` | Rewrite prompt sophistication |
| POST | `.../tests/{strategy}/{playbook}/emotion-rewrite` | Rewrite emotional tone (`emotion` 0–300: loving → angry) |
| POST | `.../tests/{strategy}/{playbook}/prompt-attributes` | Start async attributes rewrite job (`job_id`; progress on `prompt_attributes` job stream) |
| POST | `.../tests/{strategy}/{playbook}/restore-plain` | Revert transforms |
| GET | `/api/transform-options` | All Prompt Transforms dropdown options in one catalog (`techniques`, `languages`, `native_languages`, `frames`, `code_languages`, `ciphers`, `control_codes`). Preferred by the UI. |

Generate / Enhance job params (from the UI) may include `gen_transforms_enabled` plus
`gen_transforms` (ordered `[{kind, name}, ...]`) and the existing `gen_attributes_*`
fields. The worker sets `GENBOUNTY_GEN_TRANSFORM_PIPELINE*` / `GENBOUNTY_GEN_ATTRIBUTES*`
so `generate-tests/core.py` applies the pipeline then attributes before writing the suite.
| GET | `/api/obfuscation-techniques`, `/api/ciphers`, `/api/code-languages`, `/api/control-codes`, `/api/translation-languages`, `/api/native-languages`, `/api/frame-techniques` | Per-list transform options (legacy; same data as `/api/transform-options`) |
| GET | `/static/transform-options.json` | Static fallback catalog if the API catalog is unavailable |
| POST | `/api/sites/{site}/{component}/flag-prompt` | Flag a prompt |
| POST | `/api/sites/{site}/{component}/prompt-native-rewrite` | Rewrite a single Firing Range prompt into a Native dialect. Body: `{ prompt, language? }` (`language` defaults to `llm_native`; same slugs as suite Native, including `llm_native_rt`). Returns `{ prompt, language }` |
| DELETE | `/api/sites/{site}/{component}/report-entry` | Delete one assessed finding from a `pipeline_report.json` (body: `report_path`, optional `prompt_id` / `position`); recomputes `category_rollup` |
| GET | `/api/sites/{site}/{component}/flagged-prompts` | List flagged prompts |
| POST | `/api/sites/{site}/{component}/tests/import-zero-shot` | Import a zero-shot suite |

## Payloads

See [Missions — multimodal](../05-missions-and-strategies.md#multimodal-strategy) for
operator notes; live routes are listed under `/api/payloads/*` in `/api/docs`.
Standalone payload generation and other Premium-only surfaces respond with an upgrade
message in Community — see [01 — Overview](../01-overview.md#community-vs-premium).

## Logs & files

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/sites/{site}/{component}/logs` | List run logs / reports |
| GET | `/api/log` | Server log tail |
| GET | `/api/files` | Browse output files |

## Settings, config & credentials

| Method | Path | Purpose |
|--------|------|---------|
| GET/POST | `/api/config` | Global config |
| GET | `/api/settings-schema` | Settings schema for the UI |
| POST | `/api/defaults-config` | Update shipped defaults |
| POST | `/api/settings/reset-factory` | Reset to `config.factory.yaml` |
| GET/POST | `/api/llm-config` | Read / write `llm.yaml` role mapping. GET includes `openrouter_validation`. POST rejects unknown OpenRouter model ids when the catalog is reachable. |
| GET/POST | `/api/pipeline-settings` | Read / write `pipeline_settings.yaml` (pipeline + export batching; host is hardcoded) |
| GET/POST/DELETE | `/api/llm-keys` | Provider API keys in `.env` (status only on GET; optional `?provider=` on DELETE) |
| GET | `/api/llm-api-presets` | API transport presets |
| GET/POST/DELETE | `/api/credentials` | Genbounty API key (`.env`); GET returns hardcoded host `https://genbounty.com` |
| GET | `/api/env-defaults` | Legacy: `TARGET`/`COMPONENT` from `.env` (web UI uses browser local storage instead) |
| GET/POST | `/api/cache-settings` | Prompt cache toggles (`pipeline_settings.yaml`) |
| GET | `/api/corpus-stores` | File counts/sizes for corpus stores (learned, breakthrough, history, curated) |
| POST | `/api/corpus-stores/clear` | Delete selected corpus stores (`{ "stores": ["learned", ...] }`; whitelist only) |

## Jobs (async work)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/jobs` | List jobs |
| POST | `/api/jobs` | Start a job (`type`, `site`, `component`, `params`) |
| GET | `/api/jobs/{job_id}` | Job status |
| GET | `/api/jobs/{job_id}/stream` | Stream job output (SSE) |
| GET | `/api/jobs/{job_id}/preview`, `/preview/{slot}` | Live browser screenshots |
| POST | `/api/jobs/{job_id}/theory/accept`, `/theory/reject` | Respond to the interactive theory step |
| POST | `/api/jobs/{job_id}/stdin` | Send stdin to the job |
| DELETE | `/api/jobs/{job_id}` | Cancel a job |
| GET | `/api/jobs/{job_id}/export-result` | Fetch export result |

### Job types

`POST /api/jobs` accepts a `type` field. Supported types (`web/jobs.py`):

`generate`, `login`, `discover`, `manual_discover`, `api_discover`,
`recon`, `run_tests`, `enhance_loop`, `recon_round`, `recon_from_report`,
`sample_request`, `security_assess`, `export`, `clear_cache`, `nuke`,
`prompt_attributes`.

`sample_request` params: `prompt` (required). Optional `assess` (bool) + `playbook` /
`playbook_id` - when `assess` is true, after the one-shot reply the job writes
`logs/manual/<timestamp>/attack_log.json`, runs risk assessment into
`pipeline_report.json` beside it, and emits `[genbounty_manual_assess_result]` JSON
(`attack_log`, `pipeline_report`, `run_dir`, `severity`, `playbook_id`). Firing Range
**Fire** - one-shot send against the connected target. Emits `[genbounty_sample_result]`
JSON with `prompt` and `response`. Does **not** persist Fire history
(`manual_attacks.json` / Attack-tab rows are gone from the product).

`security_assess` params (one of):
- `attack_log` - path to a suite (or synthetic) `attack_log.json`
- `attack_logs` - list of paths
- `time_window` - batch window id (same as Risk UI)

Optional `playbook_id` when assess needs a header fallback. Suite assess may update
playbook intel used by Forge and Enhance.

`generate` accepts a concrete strategy slug or `__all__` (capability-filtered).
`DELETE /api/jobs/{id}` cancels an active generate (or other) job: the current generator
subprocess is killed and multi-strategy loops stop before the next strategy. Cancelled
status is sticky and is not overwritten by a later `done`/`failed` completion path.

A job moves through `pending -> running -> done | failed | cancelled`. Generation and
enhancement jobs may enter an `awaiting_theory` state, where they carry a `theory_state`
and wait for `theory/accept` or `theory/reject`. `enhance_loop` jobs started with
`auto_accept_theory: true` (UI **Enhance and Auto-Run**) skip that pause and record each
theory as auto-accepted. Multi-round Auto-run (`max_rounds > 1`) also enables theory
`auto_escalate`: once prior assessed rows show partial/exploited progress, each new
theory must keep the proven channel and escalate its payload beyond a bare
canary/proof marker within the same leaf. Escalated theories are stamped and the
generator subprocess receives `GENBOUNTY_AUTO_ESCALATE=1` so canary-only
`attack_objective` enforcement (judge override + embed filter) does not force
proof-marker asks back into the suite. Multi-round Auto-run also accepts optional
`stop_levels` (`medium` / `high` / `critical`; default `high`+`critical`) so the loop
exits when the worst assessed severity in a round reaches or exceeds any selected
level. In both modes the full theory text is appended to the job `output` stream
(Experiment Output); progress events no longer rely on embedding the full theory for
display.

### Output buffering and retention

Each job's captured output is held in a bounded in-memory buffer (the oldest lines are
evicted in batches once the cap is exceeded), so long-running jobs cannot grow memory
without limit. `output_lines` in the job payload reports the total lines ever produced, and
`/api/jobs/{job_id}/stream` (SSE) tracks an absolute cursor so streaming stays correct even
after old lines are trimmed. Finished jobs (`done` / `failed` / `cancelled`) are evicted
oldest-first once their count exceeds an in-memory retention limit; active jobs are never
evicted.

## Theory history

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/sites/{site}/{component}/theory-history` | Enhancement theory history |
| DELETE | `/api/sites/{site}/{component}/theory-history` | Clear history |
| DELETE | `/api/sites/{site}/{component}/theory-history/{entry_index}` | Delete one entry |
