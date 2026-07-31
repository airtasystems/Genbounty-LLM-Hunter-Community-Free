# 05 — Missions & strategies

A **play** is a security hypothesis with clear win/lose rules. Generation and Assessment
share those rules so you measure whether the target failed a defined bar — not whether a
reply merely “looked interesting.”

## What a play contains (in plain language)

- A short **hypothesis** (what failure looks like)
- One or more **categories** (angles on that hypothesis)
- **Success / fail signals** the judge can check in a single run
- Guidance for Enhance (what to ask next if the first pass is weak)

Community stores every custom mission under the leaf **`mission.hunt`**. You name the hunt;
you do not pick a deep taxonomy tree.

Shipped example: `data_system_prompt_leak` in `playbooks/`. Template (UI-excluded):
`playbooks/_template.json`.

## Plan Mission (create a play)

**When:** You want a custom hypothesis for this target.

1. Open **Missions → Plan Mission**.
2. Choose **Human** (you keep the brief verbatim) or **AI** (the author LLM may refine it).
3. Give a hunt **name** and a concrete **brief** (asset + observable failure).
4. On AI path, optionally lock **Use mission brief verbatim**.
5. Confirm and create. On ID conflict, overwrite or pick a new id.

**Tips for a good brief**

- Name a protected asset or behavior (not “try to jailbreak”)
- Describe what a successful leak/bypass would look like in the response
- Keep phase-1 asks measurable; save harsher escalate asks for Enhance

Regenerate from Missions when Recon capabilities change (for example file upload appears).

## Strategies

A **strategy** shapes how probes are written (single-shot, multi-turn framing, jailbreak
style, and so on). Pick one in Forge (or the CLI).

Common Community strategies:

| Strategy | Good starting point when… |
|----------|---------------------------|
| `zero_shot` | First run on a new play |
| `jailbreak` | You want classic bypass framing |
| `few_shot` / `multi_shot` | Examples in-context help |
| `iterative` / `tree_of_thoughts` / `chain_of_thought` | Multi-step reasoning hunts |
| `multimodal` | Target accepts file uploads (see below) |

**Adaptive** is Premium. In Community, use Enhance Auto-run instead of Adaptive for
closed-loop improvement.

## Multimodal strategy

**When:** Recon confirms **file upload**, and you want probes delivered as files
(PDF, image, audio, text file), not only as chat text.

On Forge, enable **Also generate file, image, and audio probes** (or select strategy
`multimodal`). Created/regenerated plays on upload-capable targets get artifact delivery
automatically; older text-only plays are promoted during multimodal Generate.

**Configure tip:** On ChatGPT-like UIs, click **`+` / attach first**, then the file control
if prompted, so Attack can open the menu before attaching. See
[Using the UI — Connect Target](04-using-the-ui.md#connect-target).

Install **ffmpeg** if you need WAV TTS output ([Installation](02-installation.md)).

## After you have a play

1. **Forge** — generate a suite
2. **Attack** — run it
3. **Analysis** — score it
4. **Enhance** — sharpen ([Enhance & Auto-run](06-enhance-and-auto-run.md))

## Related

- [Quick start](03-quickstart.md)
- [CLI](10-cli.md) — `main.py generate --playbook …`
