# 05 - Web UI guide

The web UI (`python start.py`, then `http://localhost:8000`) is the primary interface. It
covers everything the CLI does plus discovery, login, playbook authoring, and interactive
runs. The sidebar is the **Ops** menu (all sections **open** by default):

```
Connect Target
Recon → Recon, Intel
Operations → War Room, Missions, Forge, Armory, Attack,
             Analysis, Firing Range
Report → Report, Notes
Artifacts → Multimodal
Settings
```

**Community edition:** some sidebar items and controls are **Premium** (Start Battle,
Adaptive strategy, Intel, Open Hunt, standalone Multimodal builder). They show an upgrade
prompt instead of running. Everything else in Ops — including Enhance Auto-run — works in
Community. See [01 - Overview](01-overview.md#community-vs-premium) or
[genbounty.com/llm-hunter](https://genbounty.com/llm-hunter).

**Firing Range** (Operations → Firing Range) is a main-view tab for one-shot
queries to the in-scope LLM via Connect Target. The UI is a flat split editor
(Prompt | Target response) under a shared **Prompt Transforms** panel. On Firing Range the
transform controls are a compact strip (Technique / Language / Native / Frame / Code /
Cypher / Control code / IQ / Emotion): choosing a value **auto-rewrites** the prompt box
from a Human backup (empty selection restores English). The Temp / Max-tok / Top-k / Top-p
**Attributes** row still uses **Apply Attributes** / **Restore English**. Pipeline /
“Apply when generating” checkboxes stay Forge-only. The flame **Fire** icon sends the
**current** box text; replies show under **Target response**. Optional **Assess** (after
Fire) runs risk assessment for that Q→A against the header playbook and writes
`logs/manual/<timestamp>/attack_log.json` + `pipeline_report.json`. There is no Fire history
lane (no `manual_attacks.json` / Attack-tab persistence). Optional **Add to notes** keeps
a copy in Notes. **Ctrl/⌘+Enter** also sends from the prompt box (Enter alone inserts a
newline).

## Frontend layout (for contributors)

The Vue template is not one giant file. `web/static/index.template.html` is the shell and
pulls in fragments from `web/static/partials/` via `<!-- @include ... -->` markers, which
`web/spa.py` resolves at serve time. When editing the UI:

- A sidebar tab lives in `partials/tabs/<tab>.html` (for example the Attack tab is
  `partials/tabs/run.html`, Settings is `partials/tabs/settings.html`).
- Modals live in `partials/modals/*.html`.
- Chrome shared across tabs: `partials/header.html`, `partials/output-panel.html`,
  `partials/jobs-drawer.html`. The Jobs drawer stays minimized until the user
  manually expands it (Show); it does not auto-open when jobs start. While
  minimized, the bar is tone-colored (active / awaiting / failed / done / idle)
  and shows the focus job (`type · site/component · status · #id`) plus status
  count chips.
- Behaviour (state, methods) lives in `web/static/js/` modules plus thin `app.js`;
  styles in `style.css`. Script order in `index.template.html`: helpers (`api`,
  `format`, `storage`, `confirm`, `ctx`) → `scope` / `jobs` → `tabs/*`
  (including `prompt-transforms`, `discover`, `run-starters`, `pipeline`) →
  `app-lifecycle` → `app-setup` → `payload-editor` → `app.js`. Each domain exports
  `Genbounty.useX(ctx)` and `Object.assign`s its API onto `ctx`. `useAppSetup` only
  calls factories in dependency order and **returns `ctx`** for Vue `setup()`.
  Cross-cutting pieces: `tabs/prompt-transforms.js` (Apply-to-suite transforms),
  `tabs/discover.js` (Discover transport/API presets), `tabs/run-starters.js`
  (generate / run / enhance / sample / assess starters), `app-lifecycle.js`
  (onMounted, tab watches, job poll). Cross-module helpers used inside a domain
  factory must come from `ctx` (destructure stable functions like `isConfirmArmed` /
  `armConfirm`, or read/write shared mutable flags as `ctx._skip…` - never a local
  `let` copied via `Object.assign`, which freezes the boolean by value). Late-bound
  state owned by `useDiscover` (for example `discoverTransport`, `apiDiscover`) must
  be assigned onto `ctx` before other modules evaluate it at runtime (access via
  `ctx.apiDiscover`, not a local copy). After editing JS modules, hard-refresh or
  rely on `spa.py` cache-bust query params (`?v=<mtime>` on `/static/js/...`).
  Assembled index HTML is invalidated when `js/**`, `app.js`, `style.css`, or
  partials change (not only HTML partials).
- The header holds **site → component → category → playbook in scope**.
  `activeCategoryL1` and `activePlaybookId` are the shared source of truth
  (`setActiveCategory` / `setActivePlaybook`). Generate, Run, and Armory share
  one compact outlined **single-row** table (`partials/scope-readonly-table.html`) at the
  top of Generate / Run / Armory controls (content-width, not full-bleed).
  Each cell has a ⚙ that opens the matching header dropdown (`openHeaderScopeSelect`).
  Create missions from the **Missions** tab (Operations), not these tabs. Intel follows
  the header play directly (no file list section).
- Stacked picker rows (Generate / Armory / Attack) use a CSS grid
  (`max-content label | 300px control | trailing`) with a 12px gap so dropdowns sit
  tight against labels while sharing one control column within each section.
- Three-column body: fixed sidebar, flex-growing **main** center panel, fixed-width
  **Experiment Output** (289px desktop; stacks full-width below 1120px). The sidebar
  is **Ops** only: a red header (click the bar or the icon to show/hide the
  menu) and a **grouped menu panel** under it (Connect Target, Recon, Operations, Report,
  Artifacts, Settings - all sections open by default; each can be minimized independently).
  The group that owns the current tab keeps an **active** header accent.
  Singleton groups select their tab on header click. **Firing Range** is an Operations
  main-view tab (prompt + Fire/Ask + reply). **Fire** / Reuse navigate to
  that tab. Replies stay in its Target response / Guidance pane (not Experiment Output);
  **Add to notes** is under the reply. **Notes**
  (under Report) is a hunter scratchpad for freeform notes and captured Manual
  Command replies.
- **Experiment Output** is the single right-hand terminal for every Ops tab (same
  black console chrome whether idle or live). Idle shows a dim placeholder line for
  that tab; live jobs stream colored console lines. **Follow on/off** controls
  auto-scroll: when off, new lines do not force-scroll; when on, it auto-scrolls
  while you stay at the bottom; scrolling up pauses follow until you return to the
  bottom (or click **Follow on** again).
- **Firing Range** Q→A stays in its Target response / Guidance pane (not dumped into
  Experiment Output). Login temporarily owns the terminal as a foreground process from
  any tab. **Plan Mission** shows chip + phase in the modal;
  the full `[playbook]` stream lives only in Experiment Output.
- Status lines stay lean: action labels, counts, and semantic context (playbook,
  confirmation) without filesystem paths. Paths and artifacts live in the Jobs /
  file views, not the console.
- The output console uses light padding (6–8px) so it still reads as a terminal
  without a large inset gutter. Console lines have no left accent bar; color alone
  marks status / namespace.
-   Console lines are color-coded by prefix (`lineClass` in `js/format.js`): `[+]`/`[*]` success,
  `[!]`/`[error]` errors, `[generate]` / `[playbook]` / `[pipeline]` / `[enhance]` /
  `[sample]` / `[attack]` / `[recon]` / `[intel]` namespaces, and `[sample] Prompt|Response|…`
  meta lines. Phase headers
  (`Starting…`, `[enhance] === … ===`) get extra top spacing. Auto-run / Enhance
  `[enhance] Round N worst severity: …` lines stay gold-boxed
  (`line-severity-highlight`).
- Destructive / discard actions use **double-confirm** instead of native `confirm()`
  dialogs: the first click switches the button to `btn-primary` with label **Confirm**;
  the second click within ~4s runs the action (shared helper `isConfirmArmed` /
  `armConfirm` in `js/confirm.js`). Idle destructive controls also use `btn-primary` (not
  red-outline `btn-danger`). A few navigation dirty-discard prompts (selecting another
  playbook/intel while unsaved) and the Missions **Save** category-change choice still use
  a native confirm because they are not single-button actions.

The assembled HTML is rebuilt when a partial or the template changes. After changing
`web/spa.py` or any `web/routers/` module, restart the server once.
`GENBOUNTY_DEV_NO_CACHE=1` forces a rebuild on every request.

## Site, component, category, and playbook (top bar)

Use **Manage** or the header dropdowns to pick the active **site**, **component**,
**playbook category**, and **playbook in scope**. Changing category or playbook in the
header updates Generate, Run, Armory, Missions, and Intel together. Those tabs
mirror the in-scope category and play as a single-row outlined table; ⚙ opens the
  matching header dropdown.

- Site/component are saved in browser local storage and restored on the next visit
  (not from `.env`).
- A **quick connect** icon sits beside the component dropdown. With a site/component
  selected it starts Discovery or Connect via API using the component’s saved
  Connection type (Configure Component → `submission.transport`), without leaving
  the current tab. Changing the header **component** dropdown **auto-connects only
  for API endpoints** (plain JSON / `api_document` / `api_multipart`) - Browser UI
  components never auto-launch Playwright; use the quick-connect icon or Start
  Discovery explicitly. Solid glowing green when connected; bright pulsing orange
  while connecting; red when the last connect attempt failed (retry on click).
- In-scope category + playbook are saved per site+component
  (`genbounty_playbook:{site}:{component}` as `{ category, playbook }`), with a one-time
  migrate from older Run/Armory keys when missing. If the saved playbook id no
  longer exists (renamed/deleted, e.g. leftover `custom_hunt`), the header falls back to
  the first catalog play and rewrites storage - browser “clear cache” alone does not clear
  `localStorage` (use Settings → Cache Control → clear browser localStorage, or DevTools).
- Category and playbook lists come from the Missions catalog. The header playbook dropdown is
  filtered to the active category. Run/Armory still need a suite on disk for
  strategies; if none exists yet, generate probes for the in-scope play first.
- Changing category selects the first play in that category when the current play is not
  in it. Run **category** scope uses the same in-scope category for the suite batch.
- **Cache / Nuke** (header gear menu, two-click confirm each) - **Clear Cache** clears
  server caches and sticky `localStorage`, then reloads. **Nuke** wipes experiment
  artifacts for the in-scope site/component (tests, logs, intel, theory history, html,
  login profile, and legacy `recon.har` / `recon-network.json` if present). It **keeps**
  `config.yaml`, `auth.json`, and `recon.json`, writes a full pre-wipe backup under
  `nuke_backups/<timestamp>/`, then clears sticky `localStorage` and reloads. The **?**
  beside Nuke opens a short help modal with the same explanation.

## Connect Target

Register a target and describe how to talk to it. A target is a `<host>` (e.g.
`chatgpt.com`) with one or more `<component>` (e.g. `chat`).

- **Browser discovery** - opens the target UI and probes for the message input, send
  button, response container, and file upload control. The in-browser helper shows
  **Step N of M**, a short step name, a mode chip (Click / Continue / Wait / Review),
  and one bold **Do this now** line (plus an optional tip). Early in Configure you can
  record an optional **initial popup** click first (cookie/consent/success modal - one click,
  saved before Continue; do not use Continue to clear it - that can dismiss the dialog without
  recording), then **surface pre-steps** (any on-page element that must be clicked before the
  prompt is ready — tabs, cards, Start buttons, notices, etc.) as ordered `type: click` +
  `surface_prep: true` inputs - click **one element at a time** and wait until
  **Already saved (N)** increments before the next click (do not click several in a row);
  each click is saved as a leading `surface_prep` input (confirm they appear in
  `config.yaml` before Run); headless runs replay them after every reload before the prompt.
  After submit, Configure also lets you click **welcome/intro** bubbles (one at a time) so
  their text is saved to `response_ignore_substrings` before you pick the real assistant
  response. Gated challenge pages also auto-click common Start/Begin labels when text inputs
  are still missing.
- **Manual discovery** - you point out selectors when auto-probing is not enough
  (same pre-step recording, then prompt/submit/response picks).
- **API probe** - point at an HTTP chat endpoint instead of a browser UI. Modes include
  plain JSON, `api_document`, and `api_multipart` for file delivery. Configure Component
  ships API presets: Custom, OpenAI, **OpenRouter** (OpenAI-compatible
  `https://openrouter.ai/api/v1/chat/completions`, Bearer key, model slugs like
  `openai/gpt-4o-mini`), Gemini, Anthropic, Azure OpenAI, and the local test target.
- **Connection type** (Configure Component) follows the component’s saved
  `submission.transport` (`ui` → Browser UI; `api` / `api_document` /
  `api_multipart` → API). Loading a component syncs the dropdown from that config
  (and updates sticky `localStorage`). Empty/new components still default to Browser UI.

The result is a per-component `config.yaml` (selectors or API transport). You can also save
authentication here:

- **Login** - drive a real browser login; the session is stored in a persistent
  `.login_profile/` and/or `auth.json`. Login / Start URLs auto-normalize on blur
  and whenever auth status reloads: prepend `https://` when missing (or `http://`
  for localhost/IP) and append `.com` when the hostname has no TLD (e.g. `chatgpt`
  → `https://chatgpt.com`). The normalized Login URL is persisted to
  `config.yaml`’s `login_url`. **Configure Component** (browser discovery) opens
  `submission.start_url` when set, otherwise `login_url`, otherwise the site
  folder name - so a deep chat path is not replaced by a brand-folder default
  (e.g. `https://Lakera` → `lakera.com`). Manual discovery, login jobs, and headed
  browser launches apply the same normalization server-side so Configure Component
  does not open `https://chatgpt/` when the site folder lacks a TLD.
- **Reuse auth** - copy saved auth from another component on the same site. Sibling auth
  can also apply via site fallback without copying; you can still set up a UI login, API
  key, or public access for this component instead.
- **Public** - mark a component as needing no auth.
- **API key** - store a target LLM API key in `.env` as `TARGET_API_KEY_<SITE>_<COMPONENT>` (auth.json keeps header/query metadata only).

See also [19 - Auth & Connect Target](19-auth-and-connect-target.md).

## Recon

Builds the model of what the target can do.

- **Component baseline** uses the same **Overview | JSON** sub-tabs as Notes: Overview
  shows every baseline field (empty values as -); JSON edits `recon.json` directly.
  Save / Revert sit on the section header.
- **Probe mode** puts the connected-target Transport / Target / Model / Auth table at the
  top (content-width). A primary-red ⚙ at the end of the row toggles the manual URL
  input (click again to return to the connected target). Phase help is on a **?** next
  to Run Recon. **Recon from assessment report** uses tight controls and **?** help
  (no summary table).
- **Browser / API probe** writes `recon.json` - the component baseline (capabilities such as
  file upload, streaming, tool traces). For API transport, recon asks what tools work in
  **this** request and a YES/NO verify pass; hedged platform marketing ("some interfaces…",
  "when enabled…") is stripped so plain chat endpoints are not treated as having code
  execution or file upload.
- **Recon Round** and **Extract from report** update per-play intel used by Forge and
  Enhance (lean findings and observations, not full response dumps).
- **Intel tab** is **Premium** (upgrade prompt). **Recon** remains fully available.

When a playbook is selected, Forge and Analysis merge the baseline plus
the playbook's intel. Recon capabilities also gate strategy selection (for example,
`multimodal` is skipped when the component has no file upload; on stateless APIs without
conversation history, multi-turn strategies and `multimodal` stay in Strategy dropdowns
as disabled “(out of scope for API)” options, with a Strategy **?** help icon on Generate
and Run.

## Missions

Author and edit attack hypotheses (playbooks). Layout matches **Attack / Armory /
Report**: compact control panel on top, then a **Workspace** results panel (catalog +
editor) with Minimize / Maximize (no findings Window).

- **Control panel** - **Plan Mission**, Blank mission, Import JSON, Regenerate, Delete,
  Save, and Refresh.
- **Workspace** panel - category catalog on the left and Brief / Full / JSON editor on the
  right.
- **Plan Mission** opens a stepped wizard (header + progress pills + sticky Cancel/Back/Next).
  Step 1 is **Mode** (**Human** by hand or **AI** build using agent) with selectable cards;
  then **Name** (hunt name + mission brief). Human continues
  **Brief** (refine hypothesis) → success/fail → confirm & generate.
  AI auto-fills the preset and runs mission planning with structure-only gold craft (no
  hypothesis/rules screens for shipped stems). Enter a **Hunt name** and **Mission brief**
  (required for AI - this is the hypothesis ops plans from). Optional
  **Use mission brief verbatim** keeps that brief exactly as written (AI still builds
  categories/rules; no bounty-claim rewrite). Optional **Exact canary string** (Name step,
  human and AI) replaces success/fail with “Response contains / does not contain the exact
  string: '…'”, sets phase-1 **Attack objective** to emit that string when Target is empty,
  and stamps a case-sensitive `response_marker` oracle plus stop-word for deterministic
  canary grading.
  After create, the header follows the new play. **Deploy probes after create** is Premium
  (same family as Start Battle). On Human, if Instruction stays on **Direct jailbreak** while
  the hypothesis describes persona/roleplay or few-shot hijack, the wizard warns and blocks
  Generate until you switch. While planning, **Stop** cancels without freezing the UI.
  AI path offers overwrite/retry if the playbook ID already exists. Progress streams in
  **Experiment Output**.
- The editor defaults to **Simple** (play, hunt name, success/fail). **Advanced** and
  **JSON** expose the full rubric and `playbook_config`, including **Attack objective**
  (concrete information/instruction every seed must demand), **Objective lexicon**
  (optional `KEY=value` lines for `{{KEY}}` deferred terms), and **Standard action to try**
  (an optional operator-supplied follow-up, never embedded in seeds and never an exploit
  oracle). Plan Mission confirm step includes these fields. New instruction plays leave it empty.
- **Playbook ID** defaults from the hunt name slug (e.g. `hidden_reasoning_leak`),
  not a taxonomy prefix. The ID is editable after
  create (Simple + Advanced). Change it and **Save** to rename the play file and relink
  matching probe suites across targets. Target ID must not already exist; reference
  templates (`_*`) cannot be renamed.
- Changing the custom hunt name on Save asks before applying the new preset and regenerating
  mission plans (Cancel keeps current rules and only saves the label).
- **Regenerate** is a full Create-with-AI rewrite from the current play hypothesis
  (categories, triggers, assessment, guidance). Structural rails such as the prompt
  template envelope and Plan Mission **exact canary** are kept. Overwrite also invalidates
  cached probe suites. Use **Stop** next to Regenerate to abort mid-rebuild. Re-**Forge**
  afterward; Run still uses the last suite on disk until then.
- **Start Battle** (header) is **Premium**. In Community, use Attack **Enhance / Auto-run**
  for closed-loop improve → attack → assess. See
  [16 - Closed-loop Enhance](16-closed-loop-enhance.md).

See [07 - Playbooks & strategies](07-playbooks.md). Operator recipes:
[14 - Taxonomy](14-taxonomy-and-leaves.md), [15 - Authoring a play](15-authoring-a-play.md),
[16 - Closed-loop Enhance](16-closed-loop-enhance.md).

## Forge

Turns a **play** (attack hypothesis) plus a **strategy** into a probe suite. Layout matches
**Run / Armory**: compact control panel on top, then a results-style panel below.

- Category and play come from the header (shown read-only at the top of this tab).
- **Control panel** - Strategy select (`zero_shot`, `jailbreak`, `multimodal`, etc.; **All
  strategies** available). **Adaptive** is Premium (shown disabled with an upgrade note).
  On API targets without conversation history, multi-turn / multimodal options stay listed
  but marked out of scope (see Strategy **?**). Prefer `zero_shot`, `few_shot`,
  `jailbreak`, `tree_of_thoughts`, or **Enhance**. Optional **Also generate file, image,
  and audio probes** checkbox (hidden when multi-turn/media is out of scope).
  **Generate** starts the job.
- **Prompt Transforms** panel - shared partial (`partials/prompt-transforms-panel.html`),
  compact header (no Minimize / Maximize). Configure Technique / Language / Native / Frame /
  Code / Cypher / Control code / IQ / Emotion / Attributes. On **Forge**, labeled rows with
  Apply buttons; **Apply when generating or improving** auto-rewrites suites after
  generation. On **Firing Range**, a compact dropdown/slider strip auto-converts the prompt
  box on change (Attributes row still uses Apply / Restore English). **Code** includes
  Python…C++ plus **JSON** and **HTML**; embeds use the tiny `prompt_code_embed` LLM
  (flash-lite) so the ask is rewritten as idiomatic code/markup. Option lists load from
  `/api/transform-options` (with a `/static/transform-options.json` fallback).
- Strategy defaults to the first available concrete strategy for the selected play (or
  **All strategies** when you choose that explicitly). Multi-strategy generate is only via
  **All strategies**.
- **First run** is stealth-first: prompts avoid mandatory direct probes so they read like
  legitimate requests.
- **Enhance and Run** uses closed-loop feedback from a prior `pipeline_report.json`.
- Plain **Generate** auto-enables feedback when a prior assessment exists
  (`GENBOUNTY_AUTO_FEEDBACK`).

**Enhance and Run** (single round) pauses for an interactive **theory** step: the tool
proposes an enhancement theory and waits for you to **accept** or **reject** before
continuing. **Enhance and Auto-Run** (`Auto-run` checked) skips that modal and
auto-accepts each proposed theory so the unattended loop can continue until a finding
meets the Enhance **bounty stop** at a selected **Stop at** level (**Medium** /
**High** / **Critical**; default High+Critical) - `exploited`, or severity-in-Stop-at
plus `partial` / evidence≥40; severity alone never stops; `refused`/`fabricated` never
stop - or the selected **Max rounds** budget is exhausted
(1–8; default 8). Once a round
shows partial or exploited progress, subsequent Auto-run theories **automatically
escalate** by replacing the canary/benign proof marker with the play’s
`escalation_payload` (or the real ask from `attack_objective` /
`enhancement.theory_guidance`) while keeping the proven wrapper - still within the same
leaf. That escalated theory also overrides canary-only `attack_objective` enforcement
for the regenerate step so prompts are not forced back to proof-marker asks. When
Auto-run stays on hard refusals / Low, theories raise creativity (hard-refusal temp bump),
pivot away from refused technique histograms, and after two overlapping Low rounds force
breakthrough + abandon last accepted theories; a self-critique regenerates once if the
Machine plan only reuses outcome-banned techniques. **Custom enhancement** instructions
apply to both Retarget and attack and Retarget and keep attacking when enabled. While Auto-run is
checked, the plain **Attack** button is disabled so you start the multi-round loop via
**Retarget and keep attacking** instead. In both modes the full theory text is printed to
**Experiment Output**.

Theory and enhanced prompt generation **always** read recon `capabilities` / `tools`
(and derived flags such as `code_execution`, `tool_use`, `file_upload`) before proposing
moves. Empty lists are treated as absences - theories must not invent interpreters or
script-execution paths the target does not have.

Output: `browser-bot/sites/<host>/<component>/tests/<strategy>/<playbook>.json`. See
[07 - Playbooks & strategies](07-playbooks.md).

## Multimodal

The Artifacts → **Multimodal** tab’s standalone payload builder is **Premium**. You can
still use the **`multimodal` strategy** in Forge to produce file/media probes with your
suite. See [08 - Payloads & multimodal](08-payloads-multimodal.md).

## Armory

Category and play are the shared top-of-tab table (header scope). Layout matches **Attack**:
a compact control panel on top, then a probes results panel below.

- **Control panel** - Strategy select, plus compact **Import** (JSON array, `{ prompts }`,
  or a full suite → `tests/zero-shot/`). Save / Delete suite actions sit in the title row.
- **Probes panel** - title **Probes (N)** with Minimize / Maximize icons (same chrome as
  Run / Risk). There is **no** findings **Window** filter (Inspect edits the on-disk suite,
  not run-log time windows). Maximized hides the control panel.
- **Table** - per-category sections with expand / `#` / Prompt / delete (Run-like skin).
  Click a row to inline-edit; expand opens the row-detail modal. ID stays editable in the
  expanded editor. **Delete test** (double-click confirm) removes the suite JSON for the
  selected strategy
  (`browser-bot/sites/{site}/{component}/tests/{strategy}/{playbook}.json`).

Bulk Prompt Transforms for Generate / Enhance live on **Forge**; the same panel also
rewrites the live prompt on **Firing Range**. You can also import a zero-shot suite here.

## Attack

Executes the selected suite against the target.

- **Run scope** - Single play (header category + play → strategy) or All probes in
  category (header category only; locked to all available strategies for that group).
  Category/play are read-only here; strategy remains a dropdown.
- **Hunt mode** (single play) - **Bug Bounty** (default) or **Compliance**. **Open Hunt**
  is Premium. Enhance and Auto-run follow this setting. Bug Bounty keeps/mutates winning
  prompts and invents new mechanisms when stuck. Compliance keeps freeze → escalate rails.
  See [16 - Closed-loop Enhance](16-closed-loop-enhance.md).
- **Run security assessment after** - on by default for plain **Attack** (persisted per
  site/component with other Attack selections). Uncheck to skip assess after a run.
- **Auto-run** (single play) - disables the plain **Attack** button; use **Retarget and
  keep attacking** for the closed-loop enhance → attack → assess cycle. Checking Auto-run also
  checks and locks **Run security assessment after** - each round must be assessed so
  the next enhance pass can learn from refusals and outcomes. In **Compliance** mode,
  after the first partial/success hit, enhance theory keeps the proven channel and
  replaces the canary/benign marker with the play’s `escalation_payload` (or
  `attack_objective`) - same leaf only. **Add improvement guidance** works with Auto-run
  too; guidance and
  **Always apply my guidance** are persisted per site/component. Always-apply maps to
  `custom_overrides_freeze` (default off = advisory on freeze/cool-down; on = required
  every round). Guidance is snapshotted when you start Retarget - plain Attack ignores it.
  Inline **Stop at** checkboxes set the severity gate for the early-exit threshold
  (**Medium**, **High**, **Critical**; default High+Critical; at least one must stay
  selected). **Max rounds** (1–8, default 8) caps how many enhance → run → assess cycles
  run. The loop stops when any row meets the Enhance bounty stop at those levels
  (exploit, or severity-in-Stop-at plus partial/evidence≥40 - not severity alone;
  Critical alone continues past high-only partials below the evidence bar). Details and
  availability notes live in the
  inline **?** help. Requires a concrete strategy; visually disabled for
  **All strategies**.
- **Enhance phase badge** - live progress shows Freeze / Escalate / Cool-down /
  Hard-refusal / Theory / Bounty invent / Bounty mutate / Open broaden from SSE
  `enhance_phase` during Enhance loops.
- **Troubleshoot** - opens Attack troubleshooting tips (manual sample fire via
  **Operations → Firing Range**).
- While a run / enhance / recon job is active, progress text appears on the primary
  **Attack** button (e.g. `Enhance loop · Single · 3 / 5 prompts`); **Single** /
  **Multi-turn** is strategy mode, not pool concurrency. Action-only controls
  such as **Skip current** or **Open theory review** stay below when relevant.
- Live operations **screenshots** stream while the run proceeds when enabled
  (`RUN_SCREENSHOT_INTERVAL_S`; `0` disables, default). Frames appear in
  **Operations → War Room → Live operations** (Worker slots when Fetch Method is
  pool/cluster; with headless `POOL_SIZE`>1 you should see multiple workers busy).
  Click a thumbnail to open all slots in a live-updating modal. Soft-reload after
  UI fixes so preview URLs resolve.
- A **results table** shows each prompt, its response, and pass/refuse status.
  The results panel matches Analysis: shared findings **Window** (Last run /
  Last hour / Last 3 hours / All), compact Minimize / Maximize icons in the toolbar,
  and Prompt / Response columns. **Last run** pins to the newest (or selected) run log;
  period windows merge prompts from all run logs in range. Opening the Run tab (or
  finishing a run) always selects the **latest** run log when Window is Last run;
  use the Run log dropdown to peek at older runs. Non-executed outcomes
  (e.g. Submit failed) show as a badge above the prompt text.
- **Cloudflare / Turnstile:** Auto-click runs first; if a visible browser is required,
  the Run modal can set `submission.cloudflare_headed`, turn Headless off, and enable
  pool/cluster stealth. Remembered `cloudflare_headed` components use real Chrome via
  CDP when available, and a successful challenge clear merges `cf_clearance` (and related
  cookies) into `auth.json` for later runs.

Output: `run_log.json`, normalized into `attack_log.json`. See
[11 - Artifacts & schemas](11-artifacts-and-schemas.md).

## War Room

Operations → **War Room** is a live campaign monitor for the active **Attack** /
**Enhance** job (the same job tracked as `activeJobs.run_tests`), plus live risk
severity chips when assess-after or a standalone Risk assess job streams
`risk_result` events. It **auto-switches** to this tab when a Run / Enhance job starts.

- **Header rail** - compact callsign / status / mode chips and target tags (no prose).
- **KPIs** - progress %, track (with in-flight judges as `done+N/total` during
  Analysis), wall-clock elapsed, and a wide live **status** strip. PROGRESS matches
  the status-strip soft % (including in-flight credit). Severity tiles follow the
  shared findings **Window** and clear at Analysis start so prior-run counts do not
  linger. Status strip also covers standalone Analysis jobs (not only Attack/Enhance).
- **Live operations** - screenshot previews for the active Attack/Enhance run
  (when `RUN_SCREENSHOT_INTERVAL_S` > 0), stacked above a short COMMS strip in the
  **left** column. Worker slots lay out in a responsive grid sized to `POOL_SIZE` /
  cluster workers (and expand if more live slots arrive). Click any thumbnail to open
  a modal with **all** pool screens, each updating live. TRAFFIC on the right keeps
  full remaining height.
- **COMMS** - newest-first activity strip (latest ~6 events): probes, enhance rounds,
  risk rows, and blockers — compact height under the preview.
- **TRAFFIC** - newest-first feed of **risk-assessed** findings only (rows appear as
  `risk_result` events land; raw probe TX/RX stays in COMMS until assess). Full-height
  right column. Each row shows full **TX** / **RX** plus **JX** (assessment reasoning
  when present), severity/outcome chips, and actions: **Flag** (same flagged probe set
  as Analysis) and a flame icon that opens **Firing Range** with the TX prompt filled
  (does not auto-Fire).
- **Experiment Output** - while War Room is open, the right-hand terminal follows the active
  Run/Enhance job and appends a **Assessment overview** from `security_assess` (assessment
  lines) when Analysis is running or recently finished.

With nothing running (and no prior snapshot this session), War Room shows a quiet
**No activity** notice. After a job finishes, the last snapshot stays visible for
post-mortem until the next Run/Enhance/Risk start. Data comes from existing SSE
`[genbounty_progress]` events already handled in `jobs.js` - no extra backend in v1.
Firing Range Fire one-shots and recon_round are out of scope for this monitor.

## Analysis

Runs AI-assisted severity triage over `attack_log.json`. Each result gets a severity level
(`indeterminate`, `informational`, `low`, `medium`, `high`, `critical`) with reasoning and
forensic quotes, per the play's rubric (`exploited_if` / `mitigated_if` and
`severity_tiers`). Solid expert triage is accepted in one assessment pass; a second assessment pass runs only when
the triage is ambiguous or failed to parse.

Alongside the severity, each finding shows a **confidence** (`low`/`medium`/`high`) and an
**evidence strength** score, plus badges for neutral response-text detectors that fired
(refusal, secret-like output, prompt echo). If a play explicitly configures a matching
`tool_flag` oracle, only the sanitized matching label is included in oracle context.

The assessment results table supports **Minimize** / **Maximize** via compact icons in the
results panel toolbar (same pattern as Attack): Maximize hides the assess controls and
fills the main panel; Restore brings them back. The shared findings **Window** defaults to
**Last run**: opening, refreshing,
or finishing Assess / pipeline always selects the **latest** `pipeline_report.json` in the
dropdown and loads that report into the table (you can still pick an older report from the
dropdown while staying on the tab). If you manually set Window to a period (**Last hour** /
**Last 3 hours** / **All**), the table merges findings across reports in that period instead
of pinning to the latest run alone. Severity summary chips/tiles for period windows
still update live as each `risk_result` arrives (the merged table refreshes on Window
change and when assess finishes).

Each row has icon actions: **☆ Flag**
(copy into `{parent}-flagged.json` for regression), and **✕ Delete** (remove the
finding from the selected `pipeline_report.json`). Delete is two-click: the first
click turns the icon solid red (armed); the second click within a few seconds
confirms and removes the row (no dialog). The report is rewritten and
`category_rollup` is recomputed so severity summaries stay accurate. Use this to
drop false positives or noise before export.

Output: `pipeline_report.json` containing `adversarial_results[]` and a `category_rollup`
(the worst severity seen per category).

## Report

Package findings for disclosure. Layout matches **Attack / Forge / Armory**: compact
control panel on top, then a **Last Export** results panel with Minimize / Maximize (no
findings Window).

- **Control panel** - Pipeline Report (batch time windows or individual reports), risk-level
  filter, auto-submit after assess, User ID / API key, **Save settings**, **Submit to
  Genbounty**, and **Export as JSON**.
- **Last Export** panel - status / total / created / failed metrics table; errors listed as
  `#` / Error rows when present.
- **Export as JSON** - download a single report, or batch recent reports (last 1h / 4h /
  24h). No platform credentials needed.
- **Submit to Genbounty** - POST to `https://genbounty.com` when
  `GENBOUNTY_API_KEY` and a program `user_id` are configured. Results are batched.

See [12 - Export & reporting](12-export-and-reporting.md).

## Notes

Under the **Report** sidebar group. Per **site + component** scratchpad stored at
`browser-bot/sites/<site>/<component>/notes.json`. The UI is a flat Obsidian-style split
editor (same chrome as Firing Range): **New note** | **Vault**, with Notes/JSON mode tabs
and a primary Save.

- **Notes** view - compose freeform notes (optional title + body), edit existing entries,
  delete with double-confirm.
- **JSON** view - edit the full `notes.json` document when you need raw control.
- **Add to notes** under Firing Range’s Target response pane prepends a `manual_llm` entry
  with Prompt/Response body - separate from playbook intel.

## Settings

Global and per-component settings are editable in the UI:

- **Configure LLMs** (first Settings tab) - provider API keys (Gemini, Anthropic, OpenAI,
  Grok) saved to `.env` (password fields; secrets never returned to the browser), plus
  provider/model assignment per role (`llm.yaml`).
- **Pipeline** - open/closed-loop prompt batch sizes, Risk-assessment concurrency,
  payloads output directory, and Genbounty export batching (`pipeline_settings.yaml`,
  not `.env`). Platform host is hardcoded to `https://genbounty.com`.
- **Component Config** - per-component setting overrides (inherit = use global).
- **Browser Config** - headless, fetch method, pool sizes, evasion delays, user agent, etc.
- **Shipped Defaults** - edit `config.defaults.yaml` baseline (factory profile: headed
  `FETCH_METHOD=human` with human-tier / pool-cluster human features on); **Reset all to
  factory** restores `config.factory.yaml` into defaults/browser, clears per-target
  `settings:` overrides, and resets global cache toggles (selectors/export config kept).
- **Cache Control** - per-provider prompt caching toggles (`pipeline_settings.yaml`).
  **Corpus stores** lets you selectively delete `generate-tests/corpus/` stores
  (learned, breakthrough, history, and/or curated root `*.json`) with a two-click confirm;
  file counts refresh from `GET /api/corpus-stores`.
  **Clear All Caches** removes provider cache handles, local risk-assessment result files,
  and common project tool caches (skips virtualenvs, `node_modules`, and `.git`).
  Optionally also clear browser `localStorage` (saved site/component, playbook, and tab
  selections) and reload - useful after playbook renames when a stale id sticks in the header.
- **Enhance Theory** - per-site/component history of accepted/rejected Enhance theories
  (`enhance_theory_history.json`); clear filtered or all entries without deleting suites
  or run logs.
- **Credentials** - Genbounty API key (`.env`) and program User ID on Report
  (host is hardcoded to `https://genbounty.com`; both fields share one credentials section).

See [09 - Configuration](09-configuration.md).
