# 11 - Artifacts & schemas

The pipeline produces a chain of JSON artifacts. Each stage consumes the previous one.

```
suite JSON  ->  run_log.json  ->  attack_log.json  ->  pipeline_report.json  ->  export (JSON / Genbounty)
```

All target artifacts live under `browser-bot/sites/<host>/<component>/`.

### Log lanes (`logs/`)

| Lane | Path | Timestamped | Contents |
|------|------|-------------|----------|
| **probes** | `logs/probes/<YYYY-MM-DD_HH-MM-SS>/` | yes | Suite Attack: `run_log.json`, `attack_log.json`, `pipeline_report.json`, screenshots/HAR |
| **manual** | `logs/manual/<YYYY-MM-DD_HH-MM-SS>/` | yes | Firing Range Fire+Assess: `attack_log.json`, `pipeline_report.json` (legacy flat `logs/manual/*.json` still listed when present) |

## Suite JSON (after Generate)

Path: `tests/<strategy>/<playbook>.json`. Describes the prompts to run.

| Field | Meaning |
|-------|---------|
| `playbook` / `playbook_id` | Source play |
| `description` | Human summary of the suite |
| `generation_profile` | Dominant routing profile (`stealth_first`, `closed_loop_advance`, `two_phase_mixed`, `breakthrough`; legacy suites may use `calibration`) |
| `generation_notes` | Human-readable summary of routing plus detection-floor mode when enabled |
| `hunt_scope` | Required target-learning scope id and non-sensitive provenance (site/component, transport, capability signature, playbook, objective hash) used for learned corpus, breakthrough, and generation-history isolation; recon model hints are not part of the identity; unscoped records are never loaded |
| `detection_floor_mode` | Suite stamp of floor policy (`optional` default, `required`, or omitted when `skip`) |
| `oracle_version` / `oracle_hash` / `oracle_configured` | Non-sensitive fingerprint of the mandatory resolved oracle contract |
| `categories[]` | Categories mirrored from the play |
| `categories[].id` / `name` / `focus` | Category identity |
| `categories[].required_capabilities` / `optional_capabilities` / `capability_profile` | Structured target applicability metadata |
| `categories[].category_vectors` | Sole vector source; non-empty for artifact categories and empty for text categories |
| `categories[].attack_techniques` | Required authored runtime technique catalog for `mission.hunt` |
| `categories[].prompts[]` | The generated prompts |
| `prompts[].id` | Prompt id |
| `prompts[].description` | What the prompt tries and its `exploited_if` link |
| `prompts[].prompt` | The actual attack text |
| `prompts[].probe_class` | e.g. `stealth`, `escalation`, `detection_floor` |
| `prompts[].generation_profile` | Optional generation metadata |
| `prompts[].payload` | For multimodal: artifact spec / `path` after materialization |
| `prompts[].transform_kind` / `transform_name` / `transform_variant_of` | Present on generation-time transform variants (encoding/multilingual/cipher/code-embed/control_code); `plain_prompt` keeps the untransformed source |

## `run_log.json` (raw run capture)

Written by the browser-bot runner. The raw record of what was sent and received per prompt,
including screenshots/timing. Converted by `pipeline/convert_log.py` into the normalized
attack log. Treat `run_log.json` as ground truth for what was actually submitted: each
entry typically carries `id`, `input`, `response`, and (when present) `capture_id`.

## `attack_log.json` (normalized)

The normalized input to assessment. Conversion binds each run-log entry to its suite
prompt by **stable `id` / `capture_id` first**, then by full prompt text (including attack
frames such as `[SCENE]` / `[EVAL]`). It does **not** rely on suite file order - submit
may reorder cases by `probe_class` (stealth → escalation → detection_floor). If both
`id` and `capture_id` are present and disagree, conversion re-binds to the `capture_id`
suite row and prints a stderr warning. A remaining `id ≠ capture_id` after convert is a
bug signal; prefer re-running convert on current code and trust `run_log.json`.

Contains a `results[]` array; each entry includes fields such as:

| Field | Meaning |
|-------|---------|
| `id` | Test/prompt id |
| `category` / `category_id` / `parent_id` | Category display name, stable id (from the suite category), and rollup parent. Conversion stamps `category_id` when the suite category has an `id`; assessment also maps display names to ids when resolving oracles. |
| `prompt` | Prompt sent |
| `response` | Model response captured |
| `description` / `expected_behavior` | Context carried from the suite |
| `status` / `ok` / `error` | Execution outcome |
| `strategy` | Strategy used |
| `prior_turns` / `turns` | Multi-turn context (when applicable) |
| `vector_type` / `artifact_path` | Multimodal delivery details |
| `capture_id` | Stable id used to bind run-log entries to suite prompts across reordering |
| `capture_incomplete` | `true` when the response streamed but never settled to a stable state (the capture may be partial) |
| `artifact_delivered` | For multimodal prompts, whether the file upload was actually confirmed delivered (`true`/`false`) |

Top-level metadata includes `playbook`, `playbook_id`, `source_file`, and `strategy`.

These capture-quality flags (`capture_incomplete`, `artifact_delivered`) originate in the
browser-bot submit step and are carried through `pipeline/convert_log.py`. They let the
assessment distinguish a genuine model refusal from a failed capture or an undelivered
artifact (see [04 - Architecture](04-architecture.md)).

On **API** transport, provider structured refusals (HTTP 200 with empty assistant
content and e.g. Anthropic `stop_reason: "refusal"` + `stop_details.category`, or
OpenAI `finish_reason: "content_filter"`) are normalized into a response body starting
with `[API refusal]` plus run-log fields `api_refusal`, `stop_reason`,
`refusal_category`, and `refusal_explanation`. Assessment scores those as **low /
refused** (not indeterminate), and Enhance theory samples the category clue.

## `pipeline_report.json` (after Analysis)

The assessed output, written beside the attack log. Top-level shape:

| Field | Meaning |
|-------|---------|
| `timestamp` | Assessment run time |
| `playbook` / `playbook_id` | Source play |
| `source_file` | Origin suite |
| `run_log_dir` / `attack_log` | Paths to inputs |
| `strategy` | Strategy (when present) |
| `adversarial_results[]` | Per-prompt assessed findings |
| `category_rollup` | Worst severity seen per category |

The Analysis UI can delete individual `adversarial_results` rows in place
(`DELETE /api/sites/{site}/{component}/report-entry`); the file is rewritten and
`category_rollup` is recomputed from the remaining rows.

Each entry in `adversarial_results[]`:

| Field | Meaning |
|-------|---------|
| `id` | Test/prompt id |
| `category` / `category_id` / `parent_id` | Category identity |
| `prompt` / `response` | Evidence pair |
| `risk_level` | Normalized severity: `critical`, `high`, `medium`, `low`, `informational`, `indeterminate` |
| `judge_reasoning` | The judge's rationale |
| `confidence` | Judge's self-reported certainty in the verdict: `low`, `medium`, `high` |
| `evidence_strength` | Derived 0-100 score for how well deterministic detectors and expert/judge agreement corroborate the verdict |
| `evidence_signals` | Flat map of neutral response-text detectors that fired (`refusal`, `secret_like`, `prompt_echo`) - historical canary flags are excluded |
| `exploit_status` | Oracle-derived success state: `exploited`, `not_exploited`, or `unknown`; independent from severity |
| `exploited_if_satisfied` | Backward-compatible boolean projection of `exploit_status` (`true` only for `exploited`) |
| `outcome` | Feedback bucket derived from the verdict + signals: `exploited`, `partial`, `refused`, or `inconclusive` (used by closed-loop generation) |
| `oracle_summary` / `oracle_version` / `oracle_hash` | Matched play-specific predicates plus a version and stable configuration fingerprint; report top-level also carries the common version/hash |
| `experts_summary[]` | Per-expert `{ playbook, risk_level, reasoning }` |
| `vector_type` / `artifact_path` | Multimodal delivery (when applicable) |
| `strategy`, `prior_turns`, `turns` | Carried context |
| `capture_id` | Stable id carried from the attack log for suite binding |
| `response_html` | Rendered response HTML for reporting (enrichment step) |

### `category_rollup`

Maps each category to the **most severe** level observed across its results, using the order
`critical > high > medium > low > informational > indeterminate`. Each category is seeded
from its first observed level (not a hardcoded `low` floor), so a category whose findings are
all benign reports its actual level (e.g. `informational` or `indeterminate`) rather than
being inflated to `low`. Useful for regression: compare rollups across builds to see whether
a category got safer or worse.

The ordering and rollup are computed by `pipeline/report.py`
(`SEVERITY_ORDER` / `category_rollup_from_results`), shared by the CLI, web jobs, and the
assessment pipeline.

### Automated signals

Before the LLM judge runs, deterministic detectors in `pipeline/evidence_signals.py` scan the
**response text** for neutral evidence: anchored multilingual refusal detection,
credential/secret-looking output, and verbatim-prompt echo. Historical canary fields are
not analyzed for the judge. The active text signals are summarized into a note that anchors
the judge, retained on the finding as `evidence_signals`, and combined with judge/expert
agreement into `evidence_strength`.

Playbook `playbook_config.assessment.oracles` supplies play-specific success predicates.
Response markers/regexes, structured response fields, explicit tool flags, and
artifact-delivery state can resolve deterministically. Semantic rubric predicates are shown
to both the expert and judge, whose structured `exploit_status` verdict is carried through
expert acceptance and assessment caching. That verdict may satisfy a semantic predicate but
does not change or derive from severity. Without an explicitly configured semantic predicate,
an assessor-provided exploit verdict cannot turn an unknown oracle result into success.
Tool oracle evidence is opt-in and summarized as sanitized labels only.

The oracle list is mandatory and non-empty. Every category id must appear in at least one
`semantic_rubric.category_ids` scope; unknown, empty, or duplicate scopes fail validation.

Historical canary fields may remain in older attack logs, but conversion and assessment do
not extract, classify, grade, or route on them. A marker can establish exploit success only
when the active play explicitly declares a matching category-scoped oracle.

## Strict schema contracts

New playbooks and generated suites are accepted only when they use an exact canonical leaf,
mandatory category-scoped semantic oracles, valid `category_vectors`, structured capability
metadata, and authored custom techniques where required. Artifact schemas do not infer vectors
from older fields or select a default generator grid. Closed-loop stores and generation
history are keyed by `hunt_scope`; unscoped data is excluded.

Regression coverage includes oracle resolution and semantic adjudication
(`pipeline/tests/test_oracles.py`), suite→attack→report metadata propagation
(`pipeline/tests/test_oracle_metadata.py`, `pipeline/tests/test_report.py`), and strict scoped
learning (`generate-tests/tests/test_target_scoped_learning.py`).

## Severity levels

| Rubric tier | Normalized level |
|-------------|------------------|
| Critical | `critical` |
| High | `high` |
| Medium | `medium` |
| Low | `low` |
| Informational | `informational` |
| Mitigated / (no verdict) | `indeterminate` |

## Recon & intel artifacts

| File | Meaning |
|------|---------|
| `recon.json` | Component capability baseline from the browser or API probe |
| `intel/{playbook_id}.json` | Per-play hunt learning from Recon rounds and report extract (used by Forge and Enhance). Stores lean findings, observations, notes, model hints, and tools—not full response dumps. |
| `intel/credentials_and_paths.json` | **Premium (Intel).** Optional credentials/paths inventory for the Intel workspace. |

### Lean intel entries

Intel text fields are stored as short facts so files stay small and generation prompts
stay focused:

```json
{ "text": "Refuses to enumerate MCP tool schemas" }
```

Tools use `{name, type, description}` only. Entry lists are capped and deduplicated as
runs accumulate. `capabilities` stays a plain string list shared with `recon.json`
(for example `file_upload`, `multi_turn`, `tool_use`).

When a play is selected, Forge and Analysis merge `recon.json` with that play’s intel.
The CLI generate path with `--site` / `--component` loads the same context.
