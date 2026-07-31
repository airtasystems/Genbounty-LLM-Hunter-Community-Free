# 15 - Authoring a play

Operator recipe for creating a mission (hunt name + brief). Full schema and rails live in
[07 - Playbooks](07-playbooks.md). Leaf browse: [14 - Taxonomy](14-taxonomy-and-leaves.md).

## Prerequisites

1. Target registered via **Connect Target** (see [19 - Auth](19-auth-and-connect-target.md)).
2. **Recon** run so capabilities gate authoring and generate.
3. Provider keys set (**Settings → Configure LLMs** / `.env`); at minimum the
   `playbook_author` role’s provider.

## Name the hunt

- Every mission uses the sole storage leaf **`mission.hunt`** - operators set a hunt name
  and authored `attack_techniques` ([14 - Taxonomy](14-taxonomy-and-leaves.md)).
- Capability requirements declared on the play are rejected or skipped when recon does
  not confirm those surfaces.

Suggested file stem: `<hunt_name>.json` from the hunt-name slug (Create wizard defaults
the playbook id this way). The on-disk stem **is** the `playbook_id`.

## Plan Mission (UI)

**Missions → Plan Mission**

1. **Mode** - **Human** (edit hypothesis and rules; `play` stays verbatim from the
   operator) or **AI** (author LLM may rewrite the brief into a bounty-reportable claim
   unless **Use mission brief verbatim** is checked).
2. **Name** - hunt name + mission brief. On the AI path, tick **Use mission brief
   verbatim** to lock `play` to the operator text while AI still authors categories,
   triggers, and guidance. Optional **Exact canary string** locks success/fail to
   contains / does-not-contain that literal phrase, sets phase-1 `attack_objective` to
   emit it (when Target is empty), and post-processes a case-sensitive `response_marker`
   oracle plus stop-word. Optional **Prompt template** (JSON / pipe / HTML chips) wraps
   every generated seed: `{{input}}` is the attack body; optional `{{task}}` /
   `{{format}}` come from the companion fields.
3. **Human path** - Brief (refine hypothesis) → Success / fail bullets → Confirm (title, id, attack
   objective / lexicon, overwrite).
4. **AI path** - Preset auto-applied (reportable-claim starter + graded success/fail);
   author runs with a structure-only gold craft brief from `playbooks/_template.json` when
   present; otherwise the mission craft checklist. **Stop** cancels without freezing port
   8000.

On ID conflict (409), choose overwrite or retry.

## Required rails (fail closed)

| Rail | Rule |
|------|------|
| Storage leaf | Fixed `mission.hunt` (+ path `["mission","hunt"]`) |
| Hunt name | Non-empty `play_category_label` |
| Hypothesis | Bounty-reportable claim (asset + observable failure + program relevance); AI may refine unless verbatim lock; Human locks operator text; normalize upgrades lab demos when unlocked |
| Oracles | Non-empty `assessment.oracles`; every category id in a `semantic_rubric.category_ids` scope |
| Exact canary (optional) | Plan Mission **Exact canary string** locks `exploited_if` / `mitigated_if` to contains / does-not-contain prose, adds case-sensitive `response_marker`, phase-1 `attack_objective`, and stop-word. **Kept on Regenerate** (recovered from those stamps and re-applied) |
| Prompt template (optional) | Exact envelope for every seed (`{{input}}` / `{{prompt}}` = attack body; optional `{{task}}` / `{{format}}`); JSON / pipe / HTML chips in Plan Mission |
| `attack_objective` | Concrete phase-1 prohibited ask every seed must demand (paraphrase the asset; do not require literal hunt-name tokens) |
| `escalation_payload` | Required when `attack_objective` is set - exact Critical-shaped post-canary replacement text for Enhance / Auto-run (stricter than phase-1; Critical criteria / Critical `exploited_if` must share ≥2 distinctive content words with it; phase-1 may name the same asset but must not near-copy this string or negation-bait it). Rebuild-from-objective retries and the generator aligner enforce this. |
| Artifact categories | Non-empty valid `category_vectors`; no default vector grid |
| Techniques | Authored `attack_techniques` on every category |
| Reasoning / CoT hunts | When the hypothesis targets proprietary intermediate deliberation / CoT, Create and **Regenerate** apply real-world two-beat seeds (hard short-answer question → prior-deliberation fragment; forbid invented canaries), authenticity High/Critical (not “looks like reasoning”), followup ladder, multi-strategy `seed_guidance`, high deliberation recon, and ≥2 DNA-locked techniques with diversified phase-1 asks (see [07](07-playbooks.md)) |
| Capabilities | Categories must match confirmed target capabilities |

Contract failures return HTTP **422** with `invalid_playbook_contract` (see
[10 - API](10-api-reference.md)). Symptom help: [13 - Troubleshooting](13-troubleshooting.md).

Reference shape: `playbooks/_template.json` (template is UI-excluded).

## After save - hunt loop

1. **Forge** - pick strategy (`zero_shot` is a good first run).
2. **Attack** - execute the suite.
3. **Analysis** - write `pipeline_report.json`.
4. **Enhance** - after a report exists, use closed-loop sharpening
   ([16 - Closed-loop Enhance](16-closed-loop-enhance.md)).
5. **Report** - JSON download or Genbounty submit
   ([12](12-export-and-reporting.md), [17](17-genbounty-import-contract.md)).

For closed-loop sharpening in Community, use Attack **Enhance / Auto-run**
(see [16 - Closed-loop Enhance](16-closed-loop-enhance.md)). **Deploy Probes / Start Battle**
is Premium.

## Editor tips

- **Simple** vs **Advanced** / **JSON** for full `playbook_config`.
- **Regenerate** is a full Create-with-AI rewrite from the play hypothesis; exact canary
  and prompt-template rails are kept. Then **Forge** before Run.
- Renaming playbook id on Save relinks suites and intel across targets.

## See also

- [05 - Web UI guide](05-web-ui-guide.md) (Missions tab)
- [07 - Playbooks & strategies](07-playbooks.md)
- [14 - Taxonomy & leaf catalog](14-taxonomy-and-leaves.md)
