# 06 — Enhance & Auto-run

After Analysis produces a `pipeline_report.json`, **Enhance** rewrites the next probe suite
using what worked and what failed — then you can Attack again.

**When to use it:** You already assessed a run for this play/strategy and want stronger
High/Critical findings without starting from scratch.

> Community uses Attack **Retarget and keep attacking**. **Start Battle / Deploy Probes**
> is Premium.

## Hunt mode

| Mode | Use when |
|------|----------|
| **Bug Bounty** (default) | Keep mutating winners; invent new angles when stuck; escalate after a solid win |
| **Compliance** | Sharpen wrappers more conservatively around a fixed bar |

## Two ways to enhance

| Control | Behavior |
|---------|----------|
| **Retarget and attack** | One enhance round — review/accept theory, then attack |
| **Retarget and keep attacking** | Auto-run loop until **Stop-at** severity or **Max rounds** |

While Auto-run is checked, plain **Attack** is disabled — start from Retarget and keep
attacking. Progress streams in **Experiment Output**.

## Recommended Bug Bounty loop

1. Finish Attack + Analysis once (never enhance “cold”).
2. Set Hunt mode to **Bug Bounty**.
3. Check **Auto-run**, Max rounds **8**, Stop-at **High** or **Critical**.
4. Start **Retarget and keep attacking**.

Stop when you hit the severity goal, max rounds, or you are satisfied with the evidence.

## Custom enhancement

Optional free-text instructions on Attack apply to both Retarget modes when enabled. Use
them for program-specific constraints (“stay in scope of X”, “prefer Y framing”).

## Tips

- Keep Recon fresh when the product UI or tools change.
- If generation yields **0 prompts**, open Experiment Output for the diagnosis block —
  see [Troubleshooting](09-troubleshooting.md).
- Prefer a clear play hypothesis; Enhance amplifies the play you already wrote.

## Related

- [Missions & strategies](05-missions-and-strategies.md)
- [Using the UI — Attack](04-using-the-ui.md#attack)
