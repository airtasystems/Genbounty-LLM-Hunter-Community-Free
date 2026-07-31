# 18 - LLM roles (`llm.yaml`)

Assistant LLMs (generation, assessment, recon, …) are mapped in `llm.yaml`. **API keys
stay in `.env` only.** This does not configure the target under test (Connect Target /
API presets).

Copy [`llm.yaml.example`](../llm.yaml.example) → `llm.yaml`, or edit via
**Settings → Configure LLMs**. Precedence and secrets: [09 - Configuration](09-configuration.md).

## Profiles vs roles

- **Profile** - named `{ provider, model }` (e.g. `offensive_generator`).
- **Role** - pipeline stage that points at a profile (e.g. `generation_expert: offensive_generator`).

Only providers referenced by a role need keys (`GEMINI_API_KEY`, `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, `GROK_API_KEY`, `OPENROUTER_API_KEY`). Keys are checked at call time.
OpenRouter profile model ids are also checked against OpenRouter’s live catalog on
**Settings save** (reject unknown slugs) and at **web startup** (abort boot on
unknown slugs or catalog unreachable). Details:
[09 - Configuration](09-configuration.md#openrouter-model-validation).

## Roles

| Role | Purpose | Typical stage |
|------|---------|---------------|
| `generation_expert` | Author attack prompts | Generate / Enhance |
| `generation_judge` | Judge / refine attack prompts | Generate |
| `generation_critic` | Target-aware preflight critique of generated prompts | Preflight (shipped on; fast critic profile) |
| `assessment_expert` | Assess response risk | Analysis |
| `assessment_judge` | Adjudicate risk verdict | Analysis |
| `playbook_author` | Author security playbooks | Create / Regenerate play |
| `playbook_critic` | Critique playbooks | Create / Regenerate (when refine enabled) |
| `enhance_theory` | Propose closed-loop enhancement theories (shipped: `offensive_fast` / Grok) | Enhance |
| `recon` | Reconnaissance probes | Recon |
| `recon_consolidate` | Distill report-derived recon intel | Recon / intel merge |
| `grounding_judge` | Ground recon/discovery in evidence | Recon / discovery |
| `discovery` | UI element discovery | Connect Target |
| `prompt_transforms` | Rewrite / obfuscate / translate + adaptive follow-ups | Transforms / adaptive |
| `prompt_code_embed` | Code dropdown embeds (tiny `operator` / flash-lite) | Forge / Firing Range Code |
| `technique_synth` | Technique synthesis for generation | Generate (custom / packs) |
| `boilerplate_classifier` | Classify boilerplate responses | Capture / filter |

`llm.yaml.example` omits `recon_consolidate`; add it if you use that path (see comments in
a full `llm.yaml`).

## Defaults

Under `llm.defaults`:

| Key | Meaning |
|-----|---------|
| `retry` | Transient-error attempts / backoff for provider calls |
| `rate_limit` | Optional global token bucket + per-provider RPM |
| `refusal_fallback` | Optional profile (or inline provider/model) to retry once when a provider hard-refuses adversarial content; env `REFUSAL_FALLBACK_PROVIDER` / `REFUSAL_FALLBACK_MODEL` |

## Cross-provider splits

Splitting **generation** (permissive offensive model) from **assessment / methodology**
(stronger judgment models) reduces correlated blind spots. The shipped layout is a
**hybrid**: OpenRouter **Grok 4.3** for authoring, transforms, preflight
(`generation_critic` via `offensive_critic`), and **enhance_theory** (`offensive_fast`),
Hermes 70B as `refusal_fallback`,
native **OpenAI** (`gpt-5.6-sol`) for `generation_judge` only, OpenRouter **Hy3**
for grounder, native **Anthropic Sonnet** for local triage + methodology
(playbooks / recon consolidate), and
native **Gemini** for `operator`. Splitting judge (Sol) from preflight critic
(Grok) keeps target-aware filtering without Sol on every regen. See dual
layouts in [`llm.yaml.example`](../llm.yaml.example). Validate refusal rates and
JSON reliability per role before committing. Single-vendor Gemini is fine for
getting started - assign every profile to `{ provider: gemini, model: … }`.

## Assessment response budget

`assessment_expert` receives the captured reply up to **50k** characters (`MAX_RESPONSE_CHARS`
in `pipeline/security_assess.py`). Longer replies use a **head+tail** clip with an explicit
“middle omitted for length - not a capture failure” marker - never a bare
`[response truncated]` head-only cut. `assessment_judge` gets up to **64k** of evaluation
context (`MAX_JUDGE_CONTEXT_CHARS`) so a full 50k expert response plus metadata still fits,
and prefers keeping the `<<<BEGIN_UNTRUSTED_RESPONSE>>>` block intact. If judge
reasoning mentions truncation while `pipeline_report.json` still has the full response,
treat it as an old-budget artifact and re-assess rather than a harness capture miss.

## See also

- [09 - Configuration](09-configuration.md)
- [02 - Installation](02-installation.md)
- [13 - Troubleshooting](13-troubleshooting.md) (API keys)
