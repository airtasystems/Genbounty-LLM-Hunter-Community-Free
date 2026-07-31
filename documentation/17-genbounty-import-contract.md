# 17 - Genbounty import contract

Field contract for Genbounty security-assessment import as implemented by
[`pipeline/export_security.py`](../pipeline/export_security.py). Operator workflow and
batching UI: [12 - Export & reporting](12-export-and-reporting.md).

## Endpoint

```
POST https://genbounty.com/api/v2/security-assessments/import
```

Host is hardcoded (`GENBOUNTY_EXPORT_HOST`). CLI `main.py export --host` can override.
Path: `/api/v2/security-assessments/import`.

## Auth

| Value | Source (order) |
|-------|----------------|
| API key | `.env` `GENBOUNTY_API_KEY` / Export credentials / CLI `--api-key` - needs `write:security_assessment_import` |
| User ID | UI / component `config.yaml` `export.user_id` / `.env` `GENBOUNTY_USER_ID` / CLI `--user-id` |

## Top-level payload

Built by `build_security_export_payload` from `pipeline_report.json`:

| Field | Notes |
|-------|-------|
| `assessment_type` | Fixed security-assessment type constant |
| `timestamp` | Normalized from report |
| `playbook` / `playbook_id` / `play` | From report |
| `play_category` / `play_category_label` | When present |
| `source_file` / `run_log_dir` / `attack_log` | Paths / provenance |
| `results[]` | Mapped findings (see below) |
| `category_rollup` | Optional; severities normalized |
| `oracle_version` / `oracle_hash` / `oracle_configured` / `oracle_versions` / `oracle_hashes` | Optional when present on report |

Null values are stripped before POST.

## Per-result fields

Built by `build_security_export_result`:

### Always set

| Field | Meaning |
|-------|---------|
| `test_id` | Prompt / finding id |
| `prompt` | Attack prompt text |
| `ok` | Execution ok flag (defaults true if missing) |
| `category` | Display category (fallback `Uncategorized`) |
| `category_id` | Stable category id |
| `parent_id` | Non-empty; see resolution below |
| `response` | Normalized response body for import |
| `severity` | From `risk_level` (missing → `indeterminate` unless `--default-severity`) |
| `assessment_reasoning` | Judge reasoning (placeholder if empty) |
| `attack_blocked` | Derived from severity |

### `parent_id` resolution

API rejects empty `parent_id`. Export fills:

1. Row `parent_id` if non-empty  
2. Else `resolve_parent_id(playbook_id, category_id)` from the playbook  
3. Else `category_id`  
4. Else category label / `uncategorized`

### Optional (when present on the finding)

Copied via `_security_optional_result_fields` / multiturn / artifact helpers:

- Identity / play: `play`, `play_category`, `play_category_label`
- Evidence: `confidence`, `evidence_strength`, `evidence_signals`, `outcome`,
  `exploit_status`, `exploited_if_satisfied`, `oracle_summary`, `oracle_version`,
  `oracle_hash`
- Delivery: `vector_type`, `description`, `status`, `error`, `response_html`
- Multiturn: `strategy` forced to `zero_shot` or `multi_shot` for the import API;
  original pack slug retained as `toolkit_strategy` (e.g. `multimodal`, `iterative`).
  Rows with `prior_turns` or multi-entry `turns` force `strategy: "multi_shot"`.
- Artifacts (compact only): `artifact_name`, `artifact_file_type`, nested
  `artifact: { name, file_type }`, `payload: { generator, asset_type }`,
  `payload_generator`, `artifact_delivered` / `upload_ok` when recorded
- `experts_summary[]` when present

### Not sent

Filesystem paths such as `artifact_path`, `payload.path`, and `payload.args` are **not**
included on the security import schema.

## Batching and retries

| Knob | Default | Where |
|------|---------|-------|
| `batch_size` | 25 | Settings → Pipeline / `pipeline_settings.yaml` `export.*` |
| `delay_seconds` | 2 | Same |
| `max_retries` | 6 | Same (429 / rate limit) |
| `retry_base_seconds` | 5 | Same |

Severity filter: UI picker or CLI `--risk-levels`.

## See also

- [12 - Export & reporting](12-export-and-reporting.md)
- [06 - CLI reference](06-cli-reference.md) (`export`)
- [11 - Artifacts & schemas](11-artifacts-and-schemas.md)
