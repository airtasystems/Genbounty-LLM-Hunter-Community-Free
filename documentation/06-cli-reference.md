# 06 - CLI reference

The web UI (`python start.py`) is the primary interface. `main.py` exposes a subset for
**automation and CI**: generate, run, assess, and export. Discovery, login, and playbook
authoring are web-UI only.

```bash
python main.py <command> [options]
```

Commands: `generate`, `run`, `security-assess`, `export`.

## generate

Generate adversarial test prompts from playbooks.

```bash
python main.py generate --strategy zero_shot --playbook <your_mission_id> \
  --site example.com --component chat
```

| Option | Default | Purpose |
|--------|---------|---------|
| `--strategy` | `zero_shot` | Prompt strategy (see the strategy list below) |
| `--playbook` | (required unless `--all` / `--all-playbooks`) | Play stem from `playbooks/*.json` (hunt-name slug) |
| `--site` | (none) | Target site (Connect Target host); writes suite under `browser-bot/sites/<site>/...` |
| `--component` | (none) | Target component (used with `--site`) |
| `--all` | off | Generate every strategy x every playbook |
| `--all-playbooks` | off | Generate all playbooks for the given strategy |
| `--all-strategies` | off | Generate all strategies for the given playbook |

With `--site`/`--component`, output goes to
`browser-bot/sites/<site>/<component>/tests/<strategy>/<playbook>.json`. Without them, it
goes to `generate-tests/<strategy>/<playbook>.json`. Passing `--site`/`--component` also
exports `GENBOUNTY_SITE` / `GENBOUNTY_COMPONENT` / `GENBOUNTY_PLAYBOOK` so generation loads
effective recon + playbook intel (same as the web job path).

**Strategies:** `zero_shot`, `multi_shot`, `few_shot`, `iterative`,
`chain_of_thought`, `prompt_chaining`, `tree_of_thoughts`, `self_consistency`,
`self_reflection`, `directional_stimulus`, `jailbreak`, `multimodal`.
**Adaptive** is Premium (not available in the Community CLI). See
[07 - Playbooks & strategies](07-playbooks.md) and
[01 - Overview](01-overview.md#community-vs-premium).

Batch runs (`--all`, `--all-playbooks`, `--all-strategies`) generate in-process, importing
the generation stack once and reusing warm LLM clients/caches across every
strategy x playbook pair; a per-combination subprocess fallback runs automatically if
in-process generation fails. (The web UI generation path stays subprocess-based for live
streaming and isolation.)

## run

Run a generated suite against a target, then optionally assess it.

```bash
python main.py run browser-bot/sites/example.com/chat/tests/zero-shot/data-system-prompt-leak.json \
  --site example.com --component chat --assess
```

| Argument / option | Required | Purpose |
|-------------------|----------|---------|
| `suite` (positional) | yes | Path to the suite JSON |
| `--site` | yes | Target site (domain) |
| `--component` | yes | Target component |
| `--assess` | no | Run security assessment immediately after the run |

The run produces `run_log.json`, converts it to `attack_log.json`, and (with `--assess`)
writes `pipeline_report.json` beside the log with a printed severity summary.

## security-assess

Run the risk assessment on an existing attack log.

```bash
python main.py security-assess path/to/attack_log.json --report-dir reports/
```

| Argument / option | Purpose |
|-------------------|---------|
| `attack_log` (positional) | Path to `attack_log.json` |
| `--report-dir DIR` | Also copy `pipeline_report.json` into this directory (timestamped) |

Writes `pipeline_report.json` next to the attack log with `adversarial_results[]` and a
`category_rollup`.

## export

Export a pipeline report as a security assessment to Genbounty.

```bash
python main.py export path/to/pipeline_report.json \
  --api-key ... --user-id ... \
  --risk-levels critical,high,medium --batch-size 25
```

| Option | Default | Purpose |
|--------|---------|---------|
| `report` (positional) | - | Path to `pipeline_report.json` |
| `--host` | `https://genbounty.com` | Optional override of the hardcoded Genbounty host |
| `--api-key` | `GENBOUNTY_API_KEY` in `.env` | API key with `write:security_assessment_import` (prompted if missing) |
| `--user-id` | `GENBOUNTY_USER_ID` in `.env` | Program user ID (prompted if missing) |
| `--default-severity` / `--default-level` | - | Fallback severity when a row lacks `risk_level` |
| `--batch-size` | Settings `export.batch_size` or 25 | Results per POST |
| `--batch-delay` | Settings `export.delay_seconds` or 2 | Seconds between batches |
| `--risk-levels` | all | Comma-separated severities to export (e.g. `critical,high,medium`) |

Host defaults to `https://genbounty.com`; API key and user ID from `.env`
(`GENBOUNTY_API_KEY` / `GENBOUNTY_USER_ID`) or CLI flags (or prompt).
See [12 - Export & reporting](12-export-and-reporting.md).

## Offline yield report

After generate → run → assess, measure exploit/partial/refuse rates by technique and
framing (no UI):

```bash
python scripts/generation_yield_report.py path/to/pipeline_report.json
python scripts/generation_yield_report.py 'browser-bot/sites/*/chat/logs/probes/*/pipeline_report.json'
```

Joins each assessed row back to the parent suite for `technique` / `probe_class` /
`transform_kind` and infers framing family from prompt text. Prints rate tables by
technique, framing, category, strategy, probe class, and transform kind. See
[07 - Playbooks](07-playbooks.md) (yield measurement) and [20 - Scripts](20-scripts.md).

## Notes

- Secrets are loaded from `.config` then `.env` at startup (provider keys, optional
  `GENBOUNTY_API_KEY`, `TARGET_API_KEY_*`). Non-secret knobs come from
  `pipeline_settings.yaml` / Settings.
- The tool sets job-injected `GENBOUNTY_SITE` / `GENBOUNTY_COMPONENT` and applies
  per-component browser settings for `run`.
- For interactive workflows (discovery, login, playbook authoring, theory accept/reject),
  use `python start.py`.
