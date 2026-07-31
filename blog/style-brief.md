# Genbounty LLM Hunter - Style Brief

**Positioning:** Dark **operator console** for AI bug bounty work-dense, technical, mission-focused. Not a marketing site; a tool UI that feels like a hunt workstation.

Source of truth: `web/static/style.css` (`:root` + layout / button / badge sections).

---

## Mood & personality

- **Dark ops / cyber-teal** with a sharp **hacker-red** CTA punch
- Calm charcoal surfaces, cyan selection glow, red for “go / alert”
- Professional whitehat tooling, not neon cyberpunk clutter
- Dense information, clear hierarchy, live-run feedback

---

## Color system

| Role | Token | Value |
|------|--------|--------|
| Page bg | `--bg` | `#070a0f` |
| Cards / chrome | `--bg-card` | `#0d1118` |
| Inputs | `--bg-input` | `#111722` |
| Hover | `--bg-hover` | `#151d2a` |
| Primary text | `--text` | `#e6edf6` |
| Secondary | `--text-dim` | `#9aa8ba` |
| Faint / labels | `--text-faint` | `#657489` |
| Accent (nav, links, focus) | `--accent` | `#42e8e0` |
| Accent glow | `--accent-glow` | `#a7fff8` |
| Brand teal | `--brand-teal` | `#18d6c7` |
| Success | `--green` | `#7cffb2` |
| Error / soft danger | `--red` | `#ff5c7a` |
| Primary CTA | `--hacker-red` | `#ff2222` |
| Warn / waiting | amber | `#fbbf24` / `--orange` `#f59e0b` |
| Info | `--blue` | `#7dd3fc` |
| Borders | cool blue-gray glass | `rgba(122,162,193,0.14)` → stronger cyan on focus |

**Rule of thumb:** Teal/cyan = navigation, selection, live status. Red = primary actions and troubleshoot alerts. Green = done/success. Amber = waiting/theory. Soft rose = failure.

---

## Typography

- **UI body:** Inter, 14px / 1.55
- **Display / brand titles:** Space Grotesk (header `h1`, section display)
- **Code / console / logs:** JetBrains Mono, ~12px
- **Labels / meta:** 10–11px, uppercase, letter-spacing `0.05–0.08em`, `--text-faint`
- **Sidebar nav:** 13px, weight 600; active 700 + cyan left bar

Loaded via Google Fonts in `web/static/index.template.html`.

---

## Layout

- **Header:** 52px, logo 36×36, site/component selects right-aligned
- **Body:** 3 columns - sidebar **189px** | main (flex) | Experiment Output **~289px**
- Stacks below **1120px**
- Full-height app (`overflow: hidden`); panels scroll internally
- Surfaces: glass-ish cards on near-black; soft borders, not heavy outlines

---

## Shape & depth

- Radius: **14px** (large), **10px** (controls)
- Shadows: deep (`0 24px 80px` black 38%) and soft (`0 12px 34px`)
- Active sidebar: cyan left border + left→right cyan wash gradient
- Console: pure black `#000` with mono type

---

## Components

- **Primary button:** solid hacker-red, white text
- **Secondary:** dark fill + strong border
- **Ghost:** transparent + hairline border
- **Danger:** translucent red fill, bright red text
- **Badges:** tinted fills - running (cyan), done (green), failed (rose), awaiting (amber)
- **Severity chips:** critical ≈ `#f87171`; other levels follow green→amber→red scale
- **Checkboxes:** `accent-color: var(--accent)`

---

## Motion

- Short, functional: **~0.15s** color/background/border transitions
- No decorative animation language; feedback over flourish

---

## Brand assets

- Logo: `/img/Genbounty.png` (header + sidebar CTA)
- Product name in Space Grotesk; optional uppercase micro-tags for status chrome
- Sidebar CTA: “Want to hunt AI bugs professionally?” → Join Genbounty

---

## Do / don’t

- **Do:** stay dark; use CSS variables; keep teal for state and red for action
- **Do:** prefer mono for logs, paths, payloads, JSON
- **Don’t:** light mode, purple-gradient SaaS looks, or soft pastel cards
- **Don’t:** round-full pill clusters or multi-layer glow stacks beyond the existing accent wash
