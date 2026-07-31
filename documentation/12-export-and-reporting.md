# 12 - Export & reporting

Once a `pipeline_report.json` exists, the **Report** tab (or `main.py
export`) turns it into a deliverable: a filtered JSON download, or a POST to the Genbounty
platform.

## Export as JSON (no credentials)

From the UI, **Export as JSON** downloads findings without any platform credentials. You can:

- export a single report, or a **batch** of recent reports (last 1h / 4h / 24h), and
- filter by **severity** (e.g. only `critical,high,medium`).

This is the right path for offline evidence, custom reporting, or programs that are not on
Genbounty.

## Submit to Genbounty (credentials required)

Submission POSTs to the Genbounty import API at the hardcoded host
`https://genbounty.com`. It requires:

| Value | Where | Notes |
|-------|-------|-------|
| Host | Hardcoded (`https://genbounty.com`) | Not configurable in Settings; CLI `--host` can override |
| API key | `.env` → `GENBOUNTY_API_KEY` (Export tab credentials section) | Needs the `write:security_assessment_import` scope |
| User ID | UI / component `config.yaml` `export.user_id` / `.env` `GENBOUNTY_USER_ID` / CLI `--user-id` | Program user id; resolved in that order |

### Import endpoint

Always `POST /api/v2/security-assessments/import` (security schema). Missing row
severities default to `indeterminate` in code.

### Batching and retries

Results are sent in **batches** (default 25 per POST) with a delay between batches, and
retried on rate limiting (429). Tunable under **Settings → Pipeline**
(`pipeline_settings.yaml` → `export.*`):

| Key | Default | Purpose |
|-----|---------|---------|
| `batch_size` | `25` | Results per POST |
| `delay_seconds` | `2` | Pause between batches and multi-report exports |
| `max_retries` | `6` | Retries on 429 / rate limit |
| `retry_base_seconds` | `5` | Backoff base for retries |

### Strategy mapping

The Genbounty import API accepts only `zero_shot` or `multi_shot` as **`strategy`**
(interaction mode). Hunter also sends **`toolkit_strategy`**: the original attack-pack
slug (`multimodal`, `iterative`, `tree_of_thoughts`, …). Export maps the toolkit name to
mode without discarding it. Multi-turn rows (`prior_turns` present, or `turns` with more
than one entry) force `strategy: "multi_shot"`.

### `parent_id` (required by import)

Each result must include a non-empty `parent_id`. Export resolves it as: row
`parent_id` → playbook `resolve_parent_id(playbook_id, category_id)` → `category_id` →
category label. Empty `parent_id` values from `pipeline_report.json` are never sent
as-is (the API rejects them with `parent_id is required`).

### Artifact and payload metadata

When a finding used a file vector, security export includes compact metadata only:

- `artifact_name` / `artifact_file_type` and nested `artifact: { name, file_type }`
  (derived from local `artifact_path` when needed)
- `payload: { generator, asset_type }` and flat `payload_generator`
- `artifact_delivered` / `upload_ok` when recorded on the run

Filesystem paths (`artifact_path`, `payload.path`, `payload.args`) are **not** sent on
the security import schema.

## CLI

```bash
python main.py export path/to/pipeline_report.json \
  --api-key <KEY> --user-id <OBJECTID> \
  --risk-levels critical,high,medium \
  --batch-size 25 --batch-delay 2
```

Host defaults to `https://genbounty.com`. Missing API key / user id are prompted
interactively (API key from `.env`). `--default-severity` sets the
fallback level. See [06 - CLI reference](06-cli-reference.md).

## What gets exported

Each exported finding carries the evidence pair (prompt + response), the assigned
severity (`risk_level` → `severity`), the judge reasoning, and category/strategy metadata
from `pipeline_report.json`. Security export also includes `toolkit_strategy`, compact
artifact/payload metadata, and delivery flags when present. Assessment confidence and
evidence fields (`confidence`, `evidence_strength`, `evidence_signals`, `outcome`,
`exploit_status`, `exploited_if_satisfied`) are included when recorded, so a reviewer can see how strongly
the deterministic detectors and expert/judge agreement back the verdict.
Oracle summaries and their version/configuration hash are retained as optional forward-compatible
fields; existing required API/report fields are unchanged.
Severity filtering (UI severity picker or `--risk-levels`) controls which findings are
included. See [11 - Artifacts & schemas](11-artifacts-and-schemas.md) for the underlying
fields. Field-level import contract: [17 - Genbounty import contract](17-genbounty-import-contract.md).
The summary above covers endpoint, batching, `strategy` / `toolkit_strategy`, required
`parent_id`, and artifact metadata rules.

## Responsible disclosure

Export packages offensive prompts and their evidence. Only submit findings for targets and
programs you are authorized to test, and follow the program's disclosure and handling rules.
