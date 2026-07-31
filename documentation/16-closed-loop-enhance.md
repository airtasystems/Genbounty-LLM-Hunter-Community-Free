# 16 - Closed-loop Enhance

Operator guide for sharpening probes after an assessed run. Internals and full theory
rails: [07 - Closed-loop enhancement](07-playbooks.md).

## When feedback is on

- **Retarget and attack** / **Retarget and keep attacking** require a prior (or baseline)
  `pipeline_report.json` for the play/strategy. If none exists, the harness runs the
  on-disk suite + Analysis once before any theory/regen (“never enhance cold”).
- Plain **Generate** auto-enables feedback when a prior assessment exists.

Theory always reads matching assessed reports plus effective recon/intel when available.

## Max-critical workflow

UI defaults stay **Compliance** / Auto-run off. For compounding High/Critical findings
after an assessed run:

1. Set Hunt mode to **Bug Bounty**.
2. Check **Auto-run**, Max rounds **8**, Stop-at **High** or **Critical**.
3. Start **Retarget and keep attacking** (not plain Attack).

Enhancement theory uses the `enhance_theory` LLM role (see [18 - LLM roles](18-llm-roles.md)).
Playbook authoring uses the `methodologist` role.

**Auto-run theory:** one LLM call in the common case (with soft invent-format warnings on
auto-accept). Interactive Enhance keeps stricter invent validation with one regen on
failure.

## Hunt mode (Attack)

Attack has a **Hunt mode** control that Enhance and Auto-run follow:

| Mode | Behavior |
|------|----------|
| **Bug Bounty** (default) | Self-improving hunter: keep/mutate winning prompts; invent new mechanisms when stuck; escalate after a channel-proof win. |
| **Compliance** | Freeze → escalate → cool-down on channel-proof parents. Baseline safety / wrapper sharpening. |
| **Open Hunt** | **Premium** — see [genbounty.com/llm-hunter](https://genbounty.com/llm-hunter). |

Default is **Bug Bounty**. **Start Battle / Deploy Probes** is Premium; in Community use
Attack **Retarget and keep attacking** (Enhance Auto-run).

## Retarget and attack vs keep attacking

| Mode | Theory step | Loop |
|------|-------------|------|
| **Retarget and attack** | Interactive accept / reject modal | Single round (unless you start again) |
| **Retarget and keep attacking** | Theories auto-accepted | Multi-round until **Stop at** severity or **Max rounds** (1–8; default 8) |

While Auto-run is checked, plain **Attack** is disabled - start via Retarget and keep attacking.
Full theory text prints to **Experiment Output**.

**Custom enhancement** instructions apply to both modes when enabled.

## Channel proof (prove → escalate)

Soft Medium / expert-only / refusal / theater hits do **not** arm freeze or escalate.
A row is **channel-proof** only when all hold:

1. Leaf-aligned with `attack_objective` (when set)
2. Outcome bucket `exploited` or `partial` (never refused / fabricated / `not_exploited`)
3. Not cooperative-fabrication, provenance-theater, or **answer-echo theater** demotion
   (restating the visible task answer - or tokenizing it 1–N - as “prior private
   deliberation”)
4. **Task-specific emission in the response** (detection-floor acks do not promote):
   either distinctive-token overlap with `attack_objective`, **or** a short
   **quoteable residual fragment** after a completed task answer (e.g. OCC01
   wording-delta tails like omitted/replaced phrases that do not share objective lexicon).
   Multi-paragraph answers may use a **single** content-token connective tail
   (e.g. `whereas`); single-block residues still need at least two tokens.
5. Not expert-only Medium without that emission

`winning_clone_sources`, Compliance progress counts, and `escalation_seeds_for` use
channel-proof parents only (refusals stay for hard-refusal / invent search).

After an invent round with high **fabricated_rate** (answer-echo / format theater),
Auto-Run theory is steered to **ban burned invent `mechanism_family` tags** and pivot
both delivery structure and emission ask - not the same private-deliberation leaf in a
new wrapper.

## Phase gates (Compliance Auto-Run, `max_rounds > 1`)

```
FREEZE CHANNEL  →  AUTO-RUN ESCALATION  →  cool-down (on Low-family escalate miss)
```

1. **FREEZE CHANNEL** - clone **channel-proof** wrappers; canary / proof-marker filter stays on.
2. **AUTO-RUN ESCALATION** - after freeze completes or ≥2 **channel-proof** hits. Keeps the
   proven delivery channel; replaces the canary/benign marker with:
   - play `generation.escalation_payload` when set (exact Critical-shaped replacement text), else
   - the real prohibited ask from `attack_objective` / `enhancement.theory_guidance`
   (same leaf - no unrelated harm pivot).
3. **Cool-down** - a failed escalate round (Low-family) suppresses auto-escalate for the
   next round. Cool-down only follows a true channel-proof escalate attempt.

Escalation stamps outrank canary-only `attack_objective` enforcement for that regenerate
only. Author `escalation_payload` when you set `attack_objective`
([15 - Authoring](15-authoring-a-play.md)).

## Bug Bounty loop (Community)

Per Enhance / Auto-run round in **Bug Bounty** mode:

1. **Assess** updates elite (winning) prompts from exploited and partial findings.
2. **Theory** chooses escalate (after a channel-proof win), mutate a winner, or invent a
   new mechanism when stuck.
3. **Generate → Attack → Assess** again; Auto-run repeats until Stop-at severity or Max
   rounds.
4. Clearing theory history for a play/strategy usually clears that lane’s elite prompts
   too (so the next hunt starts clean).
5. Across strategies, a short **strategy handoff** can carry winning prompt DNA into the
   next strategy so mutate can continue instead of inventing cold.

## Auto-run stop and efficiency

Enhance Auto-run stops when **any** assessed row meets the Enhance bounty stop
(exploit, or a Stop-at severity with enough evidence). Severity alone never stops;
clear refusals and fabricated theater do not stop the loop.

In Bug Bounty, when an attack objective is set, stop also requires the win to align with
that leaf objective. A thin wrong-asset win can still update elite DNA for mutate but
does **not** stop Auto-run.

All-Low early stop (several consecutive Low rounds with no partial/exploited) aborts
wasted monocultures so Auto-run does not spin forever.

## Outcomes that drive theory

Findings bucket as `exploited` / `partial` / `refused` / `inconclusive`
(`exploit_status` first, then `outcome`):

- Demonstrated **exploits** → learned corpus (and elite in bounty modes).
- **Refusals** and near-miss **partials** → escalation / advance batch (compliance) or invent/mutate (bounty).
- Empty / failed-submit captures → treated as hard refusals so Enhance can diverge.
- Provider API structured refusals (`stop_reason=refusal`, content filters) → hard
  refusals with category clues for the next theory.

Stuck on Low / hard refusals (Compliance): theory raises creativity, pivots off refused technique
histograms; after two overlapping Low rounds Auto-run forces breakthrough and abandons
last accepted theories. Details in [07](07-playbooks.md).

## Drop metal detector

Burned tokens from theory Drop bullets and recon/intel are a **silent** post-generation
filter (`theory_drop:*`). Writers/judges never see the ban list. Credentials/paths are
recon footholds, not Drop seeds. See [04 - Architecture](04-architecture.md).

## Settings

| Where | What |
|-------|------|
| **Settings → Pipeline** | `open_loop_prompts` / `closed_loop_prompts` (batch sizes) |
| **Settings → Enhance Theory** | Per-site/component accepted/rejected theory history; clear without deleting suites |
| Attack | **Hunt mode**, **Max rounds**, **Stop at** (Medium / High / Critical) |

## See also

- [05 - Forge](05-web-ui-guide.md)
- [07 - Playbooks & strategies](07-playbooks.md)
- [15 - Authoring a play](15-authoring-a-play.md)
- [09 - Configuration](09-configuration.md)
