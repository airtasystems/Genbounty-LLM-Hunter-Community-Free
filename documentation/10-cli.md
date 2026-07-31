# 10 — CLI

The web UI (`python start.py`) is primary. Use `main.py` for automation and CI:
generate, run, assess, and export. Discovery, login, and Plan Mission stay in the UI.

```bash
python main.py <command> [options]
```

## generate

```bash
python main.py generate --strategy zero_shot --playbook <your_mission_id> \
  --site example.com --component chat
```

| Option | Purpose |
|--------|---------|
| `--strategy` | Strategy slug (default `zero_shot`) |
| `--playbook` | Play id (required unless `--all` / `--all-playbooks`) |
| `--site` / `--component` | Write the suite under that target |
| `--all` | Every strategy × every playbook |
| `--all-playbooks` | All plays for one strategy |
| `--all-strategies` | All strategies for one play |

With `--site`/`--component`, output goes to
`browser-bot/sites/<site>/<component>/tests/<strategy>/<playbook>.json`.

Community strategies include `zero_shot`, `jailbreak`, `multimodal`, multi-turn packs, and
shaping strategies. **Adaptive** is Premium.

## run

```bash
python main.py run path/to/suite.json \
  --site example.com --component chat --assess
```

Produces `run_log.json` → `attack_log.json`, and with `--assess` a `pipeline_report.json`.

## security-assess

```bash
python main.py security-assess path/to/attack_log.json
```

Score an existing attack log without re-running probes.

## export

```bash
python main.py export path/to/pipeline_report.json \
  --api-key <KEY> --user-id <ID> \
  --risk-levels critical,high,medium
```

See [Export & reporting](08-export-and-reporting.md).

## Related

- [Quick start](03-quickstart.md) — UI path
- [Missions & strategies](05-missions-and-strategies.md)
- Live HTTP API: `http://localhost:8000/api/docs` (or [Advanced API notes](advanced/api-reference.md))
