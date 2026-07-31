"""App UI bridge for manual component discovery (no in-page JavaScript).

When bot protection blocks the in-browser helper panel, discovery switches here:
prompts are printed as ``[genbounty_discovery_ui]`` JSON lines for the web UI
Experiment Output panel; the operator clicks targets in the real browser and
confirms steps from the app. Processing (experts, judge, verification) is unchanged.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

DISCOVERY_UI_MARKER = "[genbounty_discovery_ui]"

_stdin_queue: asyncio.Queue[dict[str, Any]] | None = None
_stdin_reader_task: asyncio.Task | None = None


def _parse_stdin_line(text: str) -> dict[str, Any]:
    stripped = (text or "").strip()
    if not stripped:
        return {"type": "continue"}
    try:
        data = json.loads(stripped)
        return data if isinstance(data, dict) else {"type": "continue"}
    except json.JSONDecodeError:
        low = stripped.lower()
        if low in ("continue", "c", "y", "yes"):
            return {"type": "continue"}
        if low in ("skip", "s"):
            return {"type": "skip"}
        if low in ("confirm", "ok"):
            return {"type": "confirm"}
        if low in ("retry", "redo", "n", "no"):
            return {"type": "retry"}
        return {"type": "unknown", "raw": stripped}


async def _ensure_stdin_reader() -> asyncio.Queue[dict[str, Any]]:
    """Single background stdin reader so cancelled pick waits cannot swallow UI clicks."""
    global _stdin_queue, _stdin_reader_task
    if _stdin_queue is not None and _stdin_reader_task is not None and not _stdin_reader_task.done():
        return _stdin_queue

    _stdin_queue = asyncio.Queue()

    async def _reader_loop() -> None:
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                await _stdin_queue.put({"type": "eof"})
                return
            await _stdin_queue.put(_parse_stdin_line(line))

    _stdin_reader_task = asyncio.create_task(_reader_loop())
    return _stdin_queue


async def _read_stdin_json(*, timeout: float | None = None) -> dict[str, Any]:
    queue = await _ensure_stdin_reader()
    if timeout is None:
        return await queue.get()
    return await asyncio.wait_for(queue.get(), timeout=timeout)


class UiDiscoveryRestartRequested(Exception):
    """Raise to close the browser and restart discovery without in-page helper JS."""

    def __init__(self, message: str = "Restart discovery in app UI mode (no in-page helper)."):
        super().__init__(message)


def request_ui_discovery_restart(context) -> None:
    try:
        setattr(context, "_genbounty_ui_restart_requested", True)
    except Exception:
        pass


def check_ui_discovery_restart(context) -> None:
    if getattr(context, "_genbounty_ui_restart_requested", False):
        raise UiDiscoveryRestartRequested()


def clear_ui_discovery_restart(context) -> None:
    try:
        setattr(context, "_genbounty_ui_restart_requested", False)
    except Exception:
        pass
    try:
        delattr(context, "_genbounty_discovery_page")
    except Exception:
        pass


async def run_with_ui_fallback_watch(page, coro) -> Any:
    """
    Run *coro* while polling for in-page 'Not working?' (ui_fallback).
    Cancels the work and raises UiDiscoveryRestartRequested when requested.
    """
    page = resolve_discovery_page(page)
    ctx = page.context
    main = asyncio.create_task(coro)
    try:
        while True:
            check_ui_discovery_restart(ctx)
            if main.done():
                # Task finished between polls - do not fall through and return None.
                return main.result()
            try:
                return await asyncio.wait_for(asyncio.shield(main), timeout=0.2)
            except asyncio.TimeoutError:
                continue
    except UiDiscoveryRestartRequested:
        if not main.done():
            main.cancel()
            try:
                await main
            except asyncio.CancelledError:
                pass
        raise


def emit_ui_mode_banner(*, restarted: bool = False) -> None:
    if restarted:
        print(
            "  [ui] Restarting discovery in app UI mode - fresh browser, no in-page helper JavaScript."
        )
    print(
        f"{DISCOVERY_UI_MARKER}"
        '{"type":"mode","mode":"ui","message":"Follow the steps below. Click in the browser; use the buttons here to continue."}',
        flush=True,
    )


_GUIDED_DISCOVERY_MODAL_SCRIPT = """
(mode) => {
  if (document.getElementById("__genbounty_guided_modal")) return;

  const isRestartConfirm = mode === "confirm_restart";
  const overlay = document.createElement("div");
  overlay.id = "__genbounty_guided_modal";
  overlay.innerHTML = `
    <div class="genbounty-guided-backdrop"></div>
    <div class="genbounty-guided-dialog" role="dialog" aria-modal="true" aria-labelledby="genbounty-guided-title">
      <h2 id="genbounty-guided-title">Guided discovery will now start</h2>
      <p class="genbounty-guided-lead">
        The in-browser helper cannot run on this site (often due to bot protection).
        Genbounty Hunter will switch to guided discovery instead.
      </p>
      <div class="genbounty-guided-section-label">What to do</div>
      <ol class="genbounty-guided-steps">
        <li>Follow the step-by-step instructions in the <strong>Experiment Output</strong> panel in the Genbounty app.</li>
        <li>Click targets on the page in <strong>this browser window</strong> when prompted.</li>
        <li>Use the <strong>Continue</strong> button in Experiment Output to advance each step.</li>
      </ol>
      ${
        isRestartConfirm
          ? "<p class=\\"genbounty-guided-note\\">The browser will close and reopen fresh when you continue.</p>"
          : "<p class=\\"genbounty-guided-note\\">The in-page helper is disabled for this session. Use Experiment Output for all prompts.</p>"
      }
      <div class="genbounty-guided-actions">
        ${
          isRestartConfirm
            ? "<button type=\\"button\\" class=\\"genbounty-guided-btn genbounty-guided-btn-secondary\\" data-action=\\"cancel\\">Cancel</button>"
            : ""
        }
        <button type="button" class="genbounty-guided-btn genbounty-guided-btn-primary" data-action="confirm">
          ${isRestartConfirm ? "Start guided discovery" : "Got it"}
        </button>
      </div>
    </div>
  `;

  const style = document.createElement("style");
  style.id = "__genbounty_guided_modal_style";
  style.textContent = `
    #__genbounty_guided_modal {
      position: fixed; inset: 0; z-index: 2147483647;
      font-family: "Inter", ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    #__genbounty_guided_modal .genbounty-guided-backdrop {
      position: absolute; inset: 0; background: rgba(0, 0, 0, 0.62);
    }
    #__genbounty_guided_modal .genbounty-guided-dialog {
      position: relative; z-index: 1; width: min(520px, calc(100vw - 32px));
      margin: 10vh auto 0; padding: 22px 24px; box-sizing: border-box;
      background: #252525; color: #dcddde; border: 1px solid #333333;
      border-radius: 12px; box-shadow: 0 16px 48px rgba(0, 0, 0, 0.45);
    }
    #__genbounty_guided_modal h2 {
      margin: 0 0 10px; font-size: 20px; font-weight: 600; color: #ffffff;
    }
    #__genbounty_guided_modal .genbounty-guided-lead {
      margin: 0 0 14px; font-size: 14px; line-height: 1.55; color: #b8b8b8;
    }
    #__genbounty_guided_modal .genbounty-guided-section-label {
      margin-bottom: 6px; font-size: 11px; font-weight: 700; letter-spacing: 0.06em;
      text-transform: uppercase; color: #8a8a8a;
    }
    #__genbounty_guided_modal .genbounty-guided-steps {
      margin: 0 0 14px; padding-left: 1.25rem; font-size: 14px; line-height: 1.55; color: #dcddde;
    }
    #__genbounty_guided_modal .genbounty-guided-steps li + li { margin-top: 6px; }
    #__genbounty_guided_modal .genbounty-guided-note {
      margin: 0 0 16px; font-size: 13px; line-height: 1.45; color: #9a9a9a;
    }
    #__genbounty_guided_modal .genbounty-guided-actions {
      display: flex; justify-content: flex-end; gap: 10px; flex-wrap: wrap;
    }
    #__genbounty_guided_modal .genbounty-guided-btn {
      border-radius: 6px; padding: 10px 16px; font-size: 14px; font-weight: 600; cursor: pointer;
    }
    #__genbounty_guided_modal .genbounty-guided-btn-primary {
      background: #7f6df2; color: #fff; border: 1px solid transparent;
    }
    #__genbounty_guided_modal .genbounty-guided-btn-primary:hover { background: #8870ff; }
    #__genbounty_guided_modal .genbounty-guided-btn-secondary {
      background: transparent; color: #dcddde; border: 1px solid #444444;
    }
    #__genbounty_guided_modal .genbounty-guided-btn-secondary:hover { background: #333333; }
  `;
  if (!document.getElementById(style.id)) document.documentElement.appendChild(style);
  document.documentElement.appendChild(overlay);

  overlay.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-action]");
    if (!btn) return;
    event.preventDefault();
    event.stopPropagation();
    const action = btn.getAttribute("data-action");
    overlay.remove();
    if (action === "confirm" && isRestartConfirm && window.genbountyManualEvent) {
      window.genbountyManualEvent({ type: "ui_fallback" });
    }
  }, true);
}
"""


async def show_guided_discovery_welcome_modal(page) -> None:
    """One-shot modal on the target page when guided (UI-only) discovery starts."""
    try:
        await page.evaluate(_GUIDED_DISCOVERY_MODAL_SCRIPT, "welcome")
    except Exception:
        pass

_PROMPT_SEQ = 0

# Shared helpers for building a pick payload from a live DOM element (string body).
# Backslashes match the prior evaluate scripts (Python → JS).
_CLICK_PICK_HELPERS = """
  function norm(s) {
    return (s || "").replace(/\\s+/g, " ").trim();
  }
  function esc(v) {
    return String(v).replace(/\\\\/g, "\\\\\\\\").replace(/"/g, '\\\\"');
  }
  function cssEsc(v) {
    if (window.CSS && typeof window.CSS.escape === "function") return window.CSS.escape(v);
    return String(v).replace(/[^a-zA-Z0-9_-]/g, "\\\\$&");
  }
  function selFor(el) {
    if (!el || el.nodeType !== 1) return "";
    if (el.id) return "#" + cssEsc(el.id);
    for (const attr of ["data-testid", "data-test", "data-cy", "name", "aria-label", "placeholder"]) {
      const v = el.getAttribute(attr);
      if (v) {
        const s = el.tagName.toLowerCase() + `[${attr}="${esc(v)}"]`;
        try { if (document.querySelectorAll(s).length === 1) return s; } catch (_) {}
      }
    }
    const tag = el.tagName.toLowerCase();
    if (el.classList && el.classList.length) {
      const cls = Array.from(el.classList).filter(c => c && !/--/.test(c)).slice(0, 2);
      if (cls.length) {
        const s = tag + "." + cls.map(cssEsc).join(".");
        try { if (document.querySelectorAll(s).length === 1) return s; } catch (_) {}
      }
    }
    return tag;
  }
  function ancestorHtml(el, steps) {
    let cur = el;
    for (let i = 0; i < steps && cur && cur.parentElement; i++) cur = cur.parentElement;
    return cur && cur.outerHTML ? cur.outerHTML : "";
  }
  function looksPointerInteractive(el) {
    if (!el || el.nodeType !== 1) return false;
    try {
      if (window.getComputedStyle(el).cursor === "pointer") return true;
    } catch (_) {}
    return false;
  }
  function resolveAnyElementTarget(el) {
    if (!el || el.nodeType !== 1) return null;
    let cur = el;
    for (let i = 0; i < 8 && cur && cur !== document.documentElement; i++) {
      const role = (cur.getAttribute("role") || "").toLowerCase();
      const tag = (cur.tagName || "").toLowerCase();
      if (
        role === "progressbar" || role === "meter" || role === "img" || role === "presentation"
        || tag === "svg" || tag === "path" || tag === "circle" || tag === "rect"
        || tag === "line" || tag === "polyline" || tag === "polygon"
      ) {
        cur = cur.parentElement;
        continue;
      }
      break;
    }
    if (!cur || cur.nodeType !== 1) return el;
    const tag = cur.tagName.toLowerCase();
    const role = (cur.getAttribute("role") || "").toLowerCase();
    const isControl = tag === "button" || tag === "a" || role === "button" || role === "link"
      || tag === "textarea" || tag === "select" || tag === "input";
    if (isControl) return cur;
    let p = cur.parentElement;
    for (let i = 0; i < 8 && p && p !== document.documentElement; i++) {
      const pText = norm(p.innerText).slice(0, 400);
      if (pText.length > 400) break;
      const pRole = (p.getAttribute("role") || "").toLowerCase();
      const pTag = (p.tagName || "").toLowerCase();
      if (
        looksPointerInteractive(p)
        || pTag === "button" || pTag === "a" || pRole === "button" || pRole === "link"
      ) {
        return p;
      }
      p = p.parentElement;
    }
    return cur;
  }
  function resolveTarget(el) {
    if (!el || el.nodeType !== 1) return null;
    if (pickKind === "response") {
      const r = el.closest('[data-message-author-role], [data-testid*="message"], article, [role="article"]');
      if (r) return r;
    }
    // Pre-steps / allowAction: any element is valid (not only form controls).
    if (allowAction) {
      return resolveAnyElementTarget(el) || el;
    }
    const input = el.closest('textarea, input:not([type="hidden"]), select, [contenteditable="true"], [contenteditable=""]');
    if (input) return input;
    const btn = el.closest(
      'button, [role="button"], input[type="submit"], input[type="button"], a[href], [role="link"], [role="menuitem"], [role="option"]'
    );
    if (btn) return btn;
    const file = el.closest('input[type="file"]');
    if (file) return file;
    return el;
  }
  function buildPayload(el) {
    if (!el || el.nodeType !== 1) return null;
    const tag = el.tagName.toLowerCase();
    const contextSteps = pickKind === "response" ? 3 : 5;
    const contextHtml = ancestorHtml(el, contextSteps);
    const wideContextHtml = pickKind === "response" ? ancestorHtml(el, 8) : "";
    const selector = selFor(el);
    const payload = {
      tag,
      inputType: el.getAttribute("type") || "",
      role: el.getAttribute("role") || "",
      innerText: norm(el.innerText).slice(0, 200),
      pickKind: pickKind || "",
      browserSelector: selector || "",
    };
    if (v2 && contextHtml) {
      payload.type = "pick_context";
      payload.contextHtml = contextHtml.slice(0, 500000);
      if (wideContextHtml) payload.wideContextHtml = wideContextHtml.slice(0, 800000);
      return payload;
    }
    if (!selector) return null;
    payload.type = "selector";
    payload.selector = selector;
    return payload;
  }
"""

# Fallback: resolve click coordinates after the fact (racy when the click advances the UI).
_CLICK_AT_POINT_SCRIPT = (
    """
({ x, y, pickKind, v2, allowAction }) => {
"""
    + _CLICK_PICK_HELPERS
    + """
  let el = document.elementFromPoint(x, y);
  if (!el || el.nodeType !== 1) return null;
  el = resolveTarget(el) || el;
  return buildPayload(el);
}
"""
)

# Capture pick payload in the click capture phase — before the default action mutates
# the DOM. Pre-steps advance the page; resolving via elementFromPoint after the click
# often mis-attributes later gates.
_UI_WAIT_FOR_CLICK_SCRIPT = (
    """
({ pickKind, v2, allowAction }) => new Promise((resolve) => {
"""
    + _CLICK_PICK_HELPERS
    + """
  function resolveFromEvent(event) {
    // Prefer the innermost path node; allowAction accepts any element.
    let origin = null;
    if (event && typeof event.composedPath === "function") {
      for (const node of event.composedPath()) {
        if (!node || node.nodeType !== 1) continue;
        origin = node;
        break;
      }
    }
    if (!origin && event && event.target && event.target.nodeType === 1) {
      origin = event.target;
    }
    if (!origin) {
      const x = Number(event && event.clientX) || 0;
      const y = Number(event && event.clientY) || 0;
      const at = document.elementFromPoint(x, y);
      if (at && at.nodeType === 1) origin = at;
    }
    if (!origin) return null;
    return resolveTarget(origin) || origin;
  }
  const onClick = (event) => {
    try {
      window.removeEventListener("click", onClick, true);
    } catch (_) {}
    const el = resolveFromEvent(event);
    if (!el) {
      resolve({
        type: "pick_failed",
        error: "Click did not land on a recognizable element - try again.",
        x: Number(event && event.clientX) || 0,
        y: Number(event && event.clientY) || 0,
      });
      return;
    }
    const payload = buildPayload(el);
    if (!payload) {
      resolve({
        type: "pick_failed",
        error: "Could not derive a selector from that click.",
        x: Number(event && event.clientX) || 0,
        y: Number(event && event.clientY) || 0,
      });
      return;
    }
    // Keep coordinates as a fallback if Python needs a re-resolve.
    payload.x = Number(event && event.clientX) || 0;
    payload.y = Number(event && event.clientY) || 0;
    resolve(payload);
  };
  window.addEventListener("click", onClick, true);
})
"""
)


def uses_ui_discovery(page) -> bool:
    return bool(getattr(page, "_genbounty_ui_mode", False))


def resolve_discovery_page(page):
    """Return the active discovery page (may differ after UI-mode page swap)."""
    try:
        ctx = page.context
    except Exception:
        return page
    repl = getattr(ctx, "_genbounty_discovery_page", None)
    if repl is not None:
        try:
            if not repl.is_closed():
                return repl
        except Exception:
            pass
    return page


def _lines_from_message(message: str) -> list[str]:
    lines: list[str] = []
    for part in (message or "").replace("\r\n", "\n").split("\n"):
        part = part.strip()
        if not part:
            continue
        if part.startswith("⚠"):
            continue
        lines.append(part)
    return lines


def _humanize_step_title(raw: str | None) -> str:
    import re

    title = (raw or "").strip()
    if not title:
        return "Component discovery"
    title = re.sub(
        r"^Confirm\s+step\s+\d+\s*/\s*\d+\s*[-–-]\s*",
        "",
        title,
        flags=re.I,
    )
    title = re.sub(r"^Confirm\s+step\s+\d+\s*[-–-]\s*", "", title, flags=re.I)
    return title.strip() or "Component discovery"


def _concise_browser_instructions(
    *,
    mode: str,
    message: str = "",
    hint: str = "",
    pick_kind: str = "",
    do_now: str = "",
    tip: str = "",
    warn: str = "",
    saved_lines: list[str] | None = None,
) -> list[str]:
    """Short, scannable lines for the Experiment Output discovery panel."""
    import re

    structured: list[str] = []
    do = (do_now or "").strip()
    if do:
        structured.append(do.rstrip(".") + ".")
    tip_s = (tip or "").strip()
    if tip_s:
        structured.append(f"Tip: {tip_s.rstrip('.')}.")
    warn_s = (warn or "").strip()
    if warn_s:
        structured.append(f"⚠ {warn_s}")
    saved = [str(x).strip() for x in (saved_lines or []) if str(x).strip()]
    if saved:
        structured.append(f"Already saved ({len(saved)}): " + "; ".join(saved[:5]))
    if structured:
        return structured

    kind = (pick_kind or "").strip().lower()
    pick_by_kind = {
        "response": "Click the latest assistant reply (not your prompt).",
        "upload": "Click the upload button or menu that opens upload.",
    }
    if mode == "pick":
        if kind in pick_by_kind:
            return [pick_by_kind[kind]]
        msg_lower = (message or "").lower()
        if "prompt" in msg_lower or "input field" in msg_lower:
            return ["Click the message text box."]
        if "send" in msg_lower or "submit" in msg_lower:
            return ["Click the Send / Submit button."]
        if "reply" in msg_lower or "assistant" in msg_lower:
            return ["Click the latest assistant reply."]
        if "upload" in msg_lower or "file" in msg_lower:
            return ["Click the upload control."]
        if "dropdown" in msg_lower or "menu" in msg_lower:
            return ["Click the menu or dropdown."]
        cleaned = (hint or "").replace("Waiting for click…", "").strip()
        if cleaned:
            cleaned = re.sub(
                r"\s*Genbounty Hunter .*$",
                "",
                cleaned,
                flags=re.I,
            ).strip()
            if cleaned:
                return [cleaned.rstrip(".") + "."]
        return ["Click the target in the browser window."]

    if mode == "busy":
        busy_hint = (hint or "").strip()
        if busy_hint:
            busy_hint = re.sub(
                r"\s*[-–-]\s*do not (click|interact with) (the )?(page|browser)\.?$",
                "",
                busy_hint,
                flags=re.I,
            ).strip()
            if "sample request" in busy_hint.lower():
                return ["Running test prompt - leave the browser alone."]
            if "verification" in busy_hint.lower() or "verify" in busy_hint.lower():
                return ["Verifying response capture…"]
            if "repair" in busy_hint.lower() or "llm" in busy_hint.lower():
                return ["Fixing selectors…"]
            if "waiting for" in busy_hint.lower() and "reply" in busy_hint.lower():
                return ["Waiting for the second reply…"]
            return [busy_hint.rstrip(".") + "…"]
        first = (message or "").split("\n")[0].strip()
        first = re.sub(r"^\d+/\d+\.\s*", "", first)
        if first.lower().startswith("still working"):
            return [first]
        if "sample request" in first.lower():
            return ["Running test prompt…"]
        if "verif" in first.lower():
            return ["Verifying response capture…"]
        return [first.rstrip(".") + "…" if first else "Please wait…"]

    if mode == "confirm":
        return ["Check the captured value below."]

    msg = (message or "").strip()
    if not msg:
        return ["Ready for the next step."]
    first_block = msg.split("\n\n")[0].strip()
    first_line = first_block.split("\n")[0].strip()
    first_line = re.sub(r"^\d+/\d+\.\s*", "", first_line)
    if first_line.lower().startswith("open the llm"):
        return ["Open the chat page and wait until the prompt box is visible."]
    if "no file upload" in first_line.lower():
        return ["No upload control found - continue to the prompt field."]
    if "sample request passed" in msg.lower():
        return ["Test prompt succeeded - discovery is almost done."]
    if "verification failed" in msg.lower():
        return ["Verification failed - review selectors or continue manually."]
    return [first_line]


def _parse_step_title(step_title: str | None) -> tuple[str, int | None, int | None]:
    import re

    title = (step_title or "").strip()
    if not title:
        return "", None, None
    match = re.search(r"step\s+(\d+)\s*/\s*(\d+)", title, re.I)
    if not match:
        return title, None, None
    return title, int(match.group(1)), int(match.group(2))


def _emit_prompt(
    *,
    message: str = "",
    mode: str = "idle",
    action: str = "",
    secondary: str = "",
    hint: str = "",
    pick_kind: str = "",
    title: str | None = None,
    step_title: str | None = None,
    instructions: list[str] | None = None,
    summary: str | None = None,
    step_number: int | None = None,
    step_total: int | None = None,
    step_name: str | None = None,
    do_now: str | None = None,
    tip: str | None = None,
    saved_lines: list[str] | None = None,
    warn: str | None = None,
    **extra: Any,
) -> str:
    global _PROMPT_SEQ
    _PROMPT_SEQ += 1
    heading, parsed_n, parsed_total = _parse_step_title(step_title or title)
    n = step_number if step_number is not None else parsed_n
    total = step_total if step_total is not None else parsed_total
    name = (step_name or "").strip()
    display_title = name or _humanize_step_title(heading or title or step_title)
    browser_steps = instructions if instructions else _concise_browser_instructions(
        mode=mode,
        message=message,
        hint=hint,
        pick_kind=pick_kind,
        do_now=do_now or "",
        tip=tip or "",
        warn=warn or "",
        saved_lines=saved_lines,
    )
    payload: dict[str, Any] = {
        "type": "prompt",
        "id": str(_PROMPT_SEQ),
        "title": display_title,
        "step_title": display_title,
        "step_number": n,
        "step_total": total,
        "step_name": name or display_title,
        "do_now": (do_now or "").strip(),
        "tip": (tip or "").strip(),
        "warn": (warn or "").strip(),
        "saved_lines": [str(x).strip() for x in (saved_lines or []) if str(x).strip()],
        "message": message,
        "instructions": browser_steps,
        "summary": (summary or "").strip(),
        "mode": mode,
        "action": action or "",
        "secondary": secondary or "",
        "hint": hint or "",
        "pick_kind": pick_kind or "",
        **extra,
    }
    print(f"{DISCOVERY_UI_MARKER}{json.dumps(payload, ensure_ascii=False)}", flush=True)
    return payload["id"]


async def _read_playwright_window_size(page) -> tuple[int, int]:
    """Read the current headed browser outer window size via CDP."""
    try:
        cdp = await page.context.new_cdp_session(page)
        window_info = await cdp.send("Browser.getWindowForTarget")
        window_id = window_info.get("windowId")
        if window_id:
            resp = await cdp.send("Browser.getWindowBounds", {"windowId": window_id})
            bounds = resp.get("bounds") or {}
            width = int(bounds.get("width") or 0)
            height = int(bounds.get("height") or 0)
            if width > 200 and height > 200:
                return width, height
    except Exception:
        pass

    try:
        dims = await page.evaluate(
            """() => ({
              width: window.outerWidth || window.innerWidth || 0,
              height: window.outerHeight || window.innerHeight || 0,
            })"""
        )
        width = int((dims or {}).get("width") or 0)
        height = int((dims or {}).get("height") or 0)
        if width > 200 and height > 200:
            return width, height
    except Exception:
        pass

    return 1280, 720


async def _read_discovery_layout_baseline(page) -> tuple[int, int]:
    """
    Baseline for guided layout: the full headed discovery window size.

    Chromium often opens at ~1280px even though the user runs discovery full-width.
    Briefly maximize via CDP, read outer bounds, then restore normal state so
    width ratio is applied to the real full window - not the small default launch size.
    """
    try:
        cdp = await page.context.new_cdp_session(page)
        window_info = await cdp.send("Browser.getWindowForTarget")
        window_id = window_info.get("windowId")
        if not window_id:
            raise ValueError("no window id")

        await cdp.send(
            "Browser.setWindowBounds",
            {"windowId": window_id, "bounds": {"windowState": "maximized"}},
        )
        await asyncio.sleep(0.2)
        resp = await cdp.send("Browser.getWindowBounds", {"windowId": window_id})
        bounds = resp.get("bounds") or {}
        width = int(bounds.get("width") or 0)
        height = int(bounds.get("height") or 0)
        if width > 200 and height > 200:
            await cdp.send(
                "Browser.setWindowBounds",
                {"windowId": window_id, "bounds": {"windowState": "normal"}},
            )
            await asyncio.sleep(0.05)
            return width, height
    except Exception:
        pass

    screen_w = screen_h = 0
    try:
        dims = await page.evaluate(
            """() => ({
              width: window.screen.availWidth || window.screen.width || 0,
              height: window.screen.availHeight || window.screen.height || 0,
            })"""
        )
        screen_w = int((dims or {}).get("width") or 0)
        screen_h = int((dims or {}).get("height") or 0)
    except Exception:
        pass

    window_w, window_h = await _read_playwright_window_size(page)
    base_w = max(screen_w, window_w, 1280)
    base_h = max(screen_h, window_h, 720)
    return base_w, base_h


async def _work_area_origin(page) -> tuple[int, int]:
    """Top-left of the available screen work area (multi-monitor safe)."""
    try:
        origin = await page.evaluate(
            """() => ({
              left: window.screen.availLeft ?? 0,
              top: window.screen.availTop ?? 0,
            })"""
        )
        return int((origin or {}).get("left") or 0), int((origin or {}).get("top") or 0)
    except Exception:
        return 0, 0


async def _set_window_always_on_top(page) -> None:
    """Best-effort keep the discovery browser above other windows (guided mode)."""
    from browser_bot.config import GUIDED_DISCOVERY_ALWAYS_ON_TOP

    if not GUIDED_DISCOVERY_ALWAYS_ON_TOP:
        return

    import shutil
    import subprocess

    try:
        await page.bring_to_front()
    except Exception:
        pass
    await asyncio.sleep(0.05)

    wmctrl = shutil.which("wmctrl")
    if not wmctrl:
        return

    def _wmctrl_above() -> None:
        subprocess.run(
            [wmctrl, "-r", ":ACTIVE:", "-b", "add,above"],
            capture_output=True,
            timeout=2,
            check=False,
        )

    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _wmctrl_above)
    except Exception:
        pass


async def apply_cdp_window_layout(
    page,
    *,
    width_ratio: float = 1.0,
    always_on_top: bool = False,
) -> None:
    """
    Size/position a headed CDP Chrome window to match Playwright headed browsers.

    Maximizes first to learn the full work-area size, then sets width to *width_ratio*
    (1.0 = 100% width, 0.6 = guided discovery panel layout).
    """
    ratio = max(0.5, min(1.0, float(width_ratio)))

    base_w, base_h = await _read_discovery_layout_baseline(page)
    target_w = max(640, int(base_w * ratio))
    target_h = max(480, base_h)
    left, top = await _work_area_origin(page)
    laid_out = False

    try:
        cdp = await page.context.new_cdp_session(page)
        window_info = await cdp.send("Browser.getWindowForTarget")
        window_id = window_info.get("windowId")
        if window_id:
            bounds = {
                "left": left,
                "top": top,
                "width": target_w,
                "height": target_h,
                "windowState": "normal",
            }
            await cdp.send(
                "Browser.setWindowBounds",
                {"windowId": window_id, "bounds": bounds},
            )
            await asyncio.sleep(0.05)
            await cdp.send(
                "Browser.setWindowBounds",
                {
                    "windowId": window_id,
                    "bounds": {
                        "left": left,
                        "top": top,
                        "width": target_w,
                        "height": target_h,
                        "windowState": "normal",
                    },
                },
            )
            try:
                await page.evaluate(
                    """([l, t, w, h]) => {
                      window.moveTo(l, t);
                      window.resizeTo(w, h);
                    }""",
                    [left, top, target_w, target_h],
                )
            except Exception:
                pass
            laid_out = True
    except Exception:
        pass

    if not laid_out:
        try:
            await page.evaluate(
                """([l, t, w, h]) => {
                  window.moveTo(l, t);
                  window.resizeTo(w, h);
                }""",
                [left, top, target_w, target_h],
            )
        except Exception:
            pass

    if always_on_top:
        await _set_window_always_on_top(page)


async def apply_full_cdp_window_layout(page) -> None:
    """Headed CDP Chrome at 100% work-area width (matches Playwright --start-maximized)."""
    await apply_cdp_window_layout(page, width_ratio=1.0, always_on_top=False)


async def apply_guided_discovery_window_layout(page, *, width_ratio: float | None = None) -> None:
    """
    Shrink the headed browser window so the Genbounty Experiment Output panel stays visible.
    Maximizes first to learn the full discovery window size, then sets width to *ratio*.
    """
    from browser_bot.config import GUIDED_DISCOVERY_ALWAYS_ON_TOP, GUIDED_DISCOVERY_WINDOW_WIDTH_RATIO

    ratio = GUIDED_DISCOVERY_WINDOW_WIDTH_RATIO if width_ratio is None else width_ratio
    await apply_cdp_window_layout(
        page,
        width_ratio=ratio,
        always_on_top=GUIDED_DISCOVERY_ALWAYS_ON_TOP,
    )


async def activate_ui_discovery_mode(page) -> Any:
    """Drop in-page helper JS by opening a fresh page without init scripts."""
    from browser_bot.record_submission import _page_uses_v2_discovery

    ctx = page.context
    url = (page.url or "").strip()
    v2 = _page_uses_v2_discovery(page)
    experts = getattr(page, "_genbounty_discovery_experts", None)
    try:
        await page.close()
    except Exception:
        pass
    new_page = await ctx.new_page()
    setattr(new_page, "_genbounty_ui_mode", True)
    if v2:
        setattr(new_page, "_genbounty_v2_discovery", True)
    if experts is not None:
        setattr(new_page, "_genbounty_discovery_experts", experts)
    setattr(ctx, "_genbounty_discovery_page", new_page)
    if url and not url.startswith("about:"):
        try:
            await new_page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass
    print(
        f"{DISCOVERY_UI_MARKER}"
        '{"type":"mode","mode":"ui","message":"In-page helper off - follow the steps below and click in the browser."}',
        flush=True,
    )
    return new_page


def _normalize_pick_payload(raw: Any) -> dict[str, Any]:
    """Validate a pick payload produced at click time (or via coordinate fallback)."""
    if not isinstance(raw, dict):
        return {
            "type": "pick_failed",
            "error": "Click did not land on a recognizable element - try again.",
        }
    if raw.get("type") == "pick_failed":
        return raw
    if raw.get("type") == "pick_context":
        return raw
    if raw.get("type") == "selector" and (raw.get("selector") or "").strip():
        return raw
    # Legacy / partial: coordinates only — caller may re-resolve.
    if "x" in raw and "y" in raw and not (raw.get("selector") or raw.get("browserSelector")):
        return {
            "type": "pick_coords",
            "x": raw.get("x"),
            "y": raw.get("y"),
        }
    return {"type": "pick_failed", "error": "Could not derive a selector from that click."}


async def _build_pick_from_click(
    page, click: Any, *, pick_kind: str, v2: bool, allow_action: bool = False
) -> dict[str, Any]:
    """Normalize a click-time payload, or fall back to elementFromPoint (racy)."""
    if isinstance(click, dict):
        normalized = _normalize_pick_payload(click)
        if normalized.get("type") in ("pick_context", "selector", "pick_failed"):
            return normalized
    x = click.get("x") if isinstance(click, dict) else getattr(click, "x", None)
    y = click.get("y") if isinstance(click, dict) else getattr(click, "y", None)
    if x is None or y is None:
        return {"type": "pick_failed", "error": "Could not read click coordinates."}
    try:
        raw = await page.evaluate(
            _CLICK_AT_POINT_SCRIPT,
            {
                "x": float(x),
                "y": float(y),
                "pickKind": pick_kind or "",
                "v2": bool(v2),
                "allowAction": bool(allow_action),
            },
        )
    except Exception as exc:
        return {"type": "pick_failed", "error": str(exc)}
    return _normalize_pick_payload(raw)


async def _ui_wait_for_pick(
    page,
    message: str,
    *,
    pick_kind: str = "",
    allow_skip: bool = False,
    skip_label: str = "Skip",
    v2: bool = False,
    allow_action: bool = False,
    step_number: int | None = None,
    step_total: int | None = None,
    step_name: str | None = None,
    do_now: str | None = None,
    tip: str | None = None,
    saved_lines: list[str] | None = None,
    warn: str | None = None,
    step_title: str | None = None,
) -> dict[str, Any]:
    _emit_prompt(
        message=message,
        mode="pick",
        action=(skip_label or "Skip") if allow_skip else "",
        hint="Click the target in the browser.",
        pick_kind=pick_kind or "",
        step_number=step_number,
        step_total=step_total,
        step_name=step_name,
        do_now=do_now,
        tip=tip,
        saved_lines=saved_lines,
        warn=warn,
        step_title=step_title,
    )
    click_task = asyncio.create_task(
        page.evaluate(
            _UI_WAIT_FOR_CLICK_SCRIPT,
            {
                "pickKind": pick_kind or "",
                "v2": bool(v2),
                "allowAction": bool(allow_action),
            },
        )
    )
    stdin_task = asyncio.create_task(_read_stdin_json())
    file_chooser_listener = None
    if pick_kind == "upload":
        # Prevent native file picker from interrupting guided selector capture.
        async def _cancel_file_chooser(fc: Any) -> None:
            try:
                await fc.set_files([])
            except Exception:
                pass

        def _on_file_chooser(fc: Any) -> None:
            asyncio.create_task(_cancel_file_chooser(fc))

        file_chooser_listener = _on_file_chooser
        page.on("filechooser", _on_file_chooser)
    try:
        while True:
            done, _pending = await asyncio.wait(
                {click_task, stdin_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if click_task in done:
                try:
                    payload = click_task.result()
                except Exception as exc:
                    return {"type": "pick_failed", "error": str(exc)}
                # Payload is usually complete (built at click time). Coordinate-only
                # leftovers still go through the racy elementFromPoint fallback.
                return await _build_pick_from_click(
                    page,
                    payload,
                    pick_kind=pick_kind,
                    v2=v2,
                    allow_action=allow_action,
                )
            if stdin_task in done:
                try:
                    resp = stdin_task.result()
                except Exception:
                    resp = {"type": "unknown"}
                resp = resp if isinstance(resp, dict) else {}
                rtype = resp.get("type")
                if rtype == "skip" and allow_skip:
                    return {"type": "skip"}
                if rtype in ("continue", "confirm"):
                    stdin_task = asyncio.create_task(_read_stdin_json())
                    continue
                if rtype == "eof":
                    return {"type": "pick_failed", "error": "Discovery input closed."}
                stdin_task = asyncio.create_task(_read_stdin_json())
                continue
    finally:
        if file_chooser_listener is not None:
            try:
                page.remove_listener("filechooser", file_chooser_listener)
            except Exception:
                pass
        for task in (click_task, stdin_task):
            if task.done():
                continue
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


async def _wait_for_panel_response(page, *, timeout: float | None = 0.35) -> dict[str, Any] | None:
    """Wait for the next operator action from the in-page panel or app UI stdin."""
    page = resolve_discovery_page(page)
    check_ui_discovery_restart(page.context)
    if uses_ui_discovery(page):
        try:
            resp = await _read_stdin_json(timeout=timeout)
        except asyncio.TimeoutError:
            return None
        rtype = str(resp.get("type") or "continue")
        if rtype in ("continue", "confirm", "retry", "skip", "ui_fallback"):
            return {"type": rtype}
        if rtype == "eof":
            return {"type": "continue"}
        return {"type": "continue"}

    import browser_bot.record_submission as _rs

    queue = await _rs._ensure_manual_panel_queue(page)
    try:
        if timeout is None:
            event = await queue.get()
        else:
            event = await asyncio.wait_for(queue.get(), timeout=timeout)
    except asyncio.TimeoutError:
        return None
    if isinstance(event, dict) and event.get("type") == "ui_fallback":
        request_ui_discovery_restart(page.context)
        raise UiDiscoveryRestartRequested()
    return event


async def ui_panel_show(
    page,
    message: str,
    *,
    mode: str = "idle",
    action: str = "Continue",
    secondary_action: str | None = None,
    pick_hint: str | None = None,
    pick_kind: str | None = None,
    title: str | None = None,
    step_title: str | None = None,
    instructions: list[str] | None = None,
    summary: str | None = None,
    step_number: int | None = None,
    step_total: int | None = None,
    step_name: str | None = None,
    do_now: str | None = None,
    tip: str | None = None,
    saved_lines: list[str] | None = None,
    warn: str | None = None,
) -> None:
    page = resolve_discovery_page(page)
    _ = page  # page kept for API symmetry; UI mode does not touch the DOM panel
    _emit_prompt(
        title=title,
        step_title=step_title or title,
        message=message,
        instructions=instructions,
        summary=summary,
        mode=mode,
        action=action or "",
        secondary=secondary_action or "",
        hint=pick_hint or "",
        pick_kind=pick_kind or "",
        step_number=step_number,
        step_total=step_total,
        step_name=step_name,
        do_now=do_now,
        tip=tip,
        saved_lines=saved_lines,
        warn=warn,
    )


async def ui_panel_event(
    page,
    message: str,
    *,
    mode: str,
    action: str = "Continue",
    secondary_action: str | None = None,
    allow_action: bool = False,
    pick_hint: str | None = None,
    pick_kind: str | None = None,
    step_title: str | None = None,
    instructions: list[str] | None = None,
    summary: str | None = None,
    step_number: int | None = None,
    step_total: int | None = None,
    step_name: str | None = None,
    do_now: str | None = None,
    tip: str | None = None,
    saved_lines: list[str] | None = None,
    warn: str | None = None,
) -> dict[str, Any]:
    from browser_bot.record_submission import _page_uses_v2_discovery

    page = resolve_discovery_page(page)
    await ui_panel_show(
        page,
        message,
        mode=mode,
        action=action,
        secondary_action=secondary_action,
        pick_hint=pick_hint,
        pick_kind=pick_kind,
        step_title=step_title,
        instructions=instructions,
        summary=summary,
        step_number=step_number,
        step_total=step_total,
        step_name=step_name,
        do_now=do_now,
        tip=tip,
        saved_lines=saved_lines,
        warn=warn,
    )

    if mode == "pick":
        skip_label = (action or "").strip()
        return await _ui_wait_for_pick(
            page,
            message,
            pick_kind=pick_kind or "",
            allow_skip=bool(skip_label),
            skip_label=skip_label or "Skip",
            v2=_page_uses_v2_discovery(page),
            allow_action=allow_action,
            step_number=step_number,
            step_total=step_total,
            step_name=step_name,
            do_now=do_now,
            tip=tip,
            saved_lines=saved_lines,
            warn=warn,
            step_title=step_title,
        )

    if mode == "busy":
        return {"type": "busy"}

    while True:
        resp = await _read_stdin_json()
        rtype = resp.get("type")
        if mode == "confirm":
            if rtype == "confirm":
                return {"type": "confirm"}
            if rtype == "retry":
                return {"type": "retry"}
            continue
        if rtype == "continue":
            return {"type": "continue"}
        if rtype == "skip":
            return {"type": "skip"}
        if rtype == "eof":
            return {"type": "continue"}
