# 08 — Export & reporting

After Analysis writes a `pipeline_report.json`, use the **Report** tab (or the CLI) to
download findings or submit them to Genbounty.

> Only export or submit for targets and programs you are authorized to test.

## Export as JSON (no platform credentials)

**Export as JSON** downloads findings for offline evidence or custom reporting:

- One report, or a **batch** of recent reports (last 1h / 4h / 24h)
- Optional filter by severity (for example critical, high, medium)

## Submit to Genbounty

POSTs to `https://genbounty.com` (security-assessment import). You need:

| Value | Where |
|-------|-------|
| API key | `.env` → `GENBOUNTY_API_KEY` (needs import write scope) |
| User ID | Report / component settings, or `.env` → `GENBOUNTY_USER_ID` |

Results are sent in batches (default 25) with retries on rate limits. Batch size and delays
are under **Settings → Pipeline**.

### What Genbounty receives

Each finding includes the prompt/response pair, severity, judge reasoning, and
category/strategy metadata. File-based probes include compact artifact metadata (name,
type, generator) — not local filesystem paths.

Hunter strategies map to Genbounty’s interaction modes (`zero_shot` / `multi_shot`) while
keeping the original pack name as `toolkit_strategy`.

## CLI

```bash
python main.py export path/to/pipeline_report.json \
  --api-key <KEY> --user-id <ID> \
  --risk-levels critical,high,medium
```

See [CLI](10-cli.md).

## Related

- [Quick start](03-quickstart.md) — end of the first hunt
- [Settings, LLMs & data](07-settings-llms-and-data.md) — where reports live on disk
- [Advanced schemas](advanced/schemas.md) — field-level shapes (optional)
