"""Record UI submission flow: open browser, capture HTML, extract config via AI.

Discovery runs in 7 steps:
  1. Interactive browser - user navigates to page, presses Enter / Continue
  2. Browser automation - detect dropdown menus and file upload support
  3. Prerequisite dropdown + multimodal file input (dropdown before file when both exist)
  4. LLM / manual - prompt input selector
  5. Submit selector
  6. Headless verify submit - fills + clicks, detects response
  7. Response selector
  Config is saved incrementally after the user confirms each step.
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml
from playwright.async_api import async_playwright

from browser_bot.sites import (
    get_component_config_path,
    get_component_path,
    get_storage_state_path,
    load_component_config,
    load_component_config_raw,
    ensure_component_dir,
    ensure_site_config_on_discovery,
    resolve_discovery_launch_url,
    resolve_login_profile_path,
    write_component_config_with_header,
)
from browser_bot.browser.launcher import launch_persistent_context
from browser_bot.config import LOGIN_USE_PERSISTENT_CONTEXT


# ---------------------------------------------------------------------------
# Config persistence
# ---------------------------------------------------------------------------

def _should_use_login_profile(site: str, component: str | None = None) -> bool:
    """Persistent profiles are optional because some sites crash Chromium on reuse.

    Prefer the component login profile (where Login writes), fall back to site-level.
    """
    return LOGIN_USE_PERSISTENT_CONTEXT and resolve_login_profile_path(
        site, component
    ).exists()


def _print_profile_disabled_notice(site: str, component: str | None = None) -> None:
    if resolve_login_profile_path(site, component).exists() and not LOGIN_USE_PERSISTENT_CONTEXT:
        print("  Persistent login profile exists but is disabled; using saved auth state.")

def _save_config_with_comments(site: str, component: str, config: dict) -> None:
    ensure_component_dir(site, component)
    path = get_component_config_path(site, component)
    write_component_config_with_header(path, config)


def _ensure_site_config_for_discovery(site: str, component: str) -> None:
    """Create sites/<site>/config.yaml on first discovery if it does not exist."""
    comp_raw = load_component_config_raw(site, component)
    login_url = comp_raw.get("login_url") if isinstance(comp_raw.get("login_url"), str) else None
    created = ensure_site_config_on_discovery(site, login_url=login_url)
    if created:
        print(f"  Created site config -> sites/{site}/config.yaml")


_CSS_MODULE_TAG_CLASS = re.compile(
    r"(?P<tag>[a-zA-Z][\w-]*)"
    r"\.(?P<prefix>[a-zA-Z][\w-]*?)--[A-Za-z0-9_]{4,}\b"
)
_CSS_MODULE_DOT_CLASS = re.compile(
    r"\.(?P<prefix>[a-zA-Z][\w-]*?)--[A-Za-z0-9_]{4,}\b"
)


def sanitize_discovered_selector(selector: str) -> str:
    """Rewrite CSS-module hashed classes into stable partial class selectors."""
    sel = (selector or "").strip()
    if not sel or "[class*=" in sel:
        return sel

    def _tag_class(match: re.Match[str]) -> str:
        prefix = match.group("prefix")
        if len(prefix) < 3:
            return match.group(0)
        return f"{match.group('tag')}[class*='{prefix}']"

    def _dot_class(match: re.Match[str]) -> str:
        prefix = match.group("prefix")
        if len(prefix) < 3:
            return match.group(0)
        return f"[class*='{prefix}']"

    sel = _CSS_MODULE_TAG_CLASS.sub(_tag_class, sel)
    sel = _CSS_MODULE_DOT_CLASS.sub(_dot_class, sel)
    return sel


def is_fragile_positional_selector(selector: str) -> bool:
    """True when a selector pins one DOM node via nth-of-type/nth-child (breaks in chat lists)."""
    sel = (selector or "").strip()
    if not sel:
        return False
    return ":nth-of-type(" in sel or ":nth-child(" in sel


def is_ephemeral_selector(selector: str) -> bool:
    """True for attributes assigned dynamically after interaction (fail on fresh page load)."""
    sel = (selector or "").strip().lower()
    if not sel:
        return False
    return any(
        token in sel
        for token in (
            "data-gtm-form-interact-id",
            "data-gtm-form-interact",
            "data-reactid",
            "data-radix-",
            "__genbounty",
        )
    )


def _is_stable_css_class_token(cls: str) -> bool:
    """False for Tailwind/shadcn class tokens that break querySelector when dotted."""
    token = str(cls or "").strip()
    if not token or token.startswith("__genbounty"):
        return False
    if token.startswith("!"):
        return False
    if any(ch in token for ch in "[]:#"):
        return False
    if ":" in token:
        return False
    return True


def _is_bare_tag_selector(selector: str) -> bool:
    """True for tag-only selectors (textarea, button) with no attributes - often match hidden nodes first."""
    sel = (selector or "").strip()
    return bool(sel and re.fullmatch(r"[a-z][\w-]*", sel, flags=re.I))


def is_generic_click_selector(selector: str) -> bool:
    """True for selectors that match many unrelated controls (e.g. every header button).

    ``button[type=button]`` is the common failure mode: Configure saves it when the
    type attribute looks unique at pick time, then Run clicks the first header icon.
    """
    sel = (selector or "").strip()
    if not sel:
        return True
    if _is_bare_tag_selector(sel):
        return True
    low = re.sub(r"\s+", "", sel.lower())
    if re.fullmatch(r'button\[type=["\']?button["\']?\]', low):
        return True
    if re.fullmatch(r'input\[type=["\']?button["\']?\]', low):
        return True
    if re.fullmatch(r'\[role=["\']?button["\']?\]', low):
        return True
    if re.fullmatch(r'a\[href\]', low):
        return True
    return False


def is_unreliable_expert_selector(selector: str, *, target_kind: str = "") -> bool:
    """
    True when an LLM-proposed selector is likely invalid or wrong for Playwright.
    Tailwind utilities (colons, brackets, !important) and wrapper div picks are common failures.
    """
    sel = (selector or "").strip()
    if not sel:
        return False
    if _is_bare_tag_selector(sel):
        return True
    if is_ephemeral_selector(sel):
        return True
    if re.search(r"\.!?[\w-]*[:#\[]", sel):
        return True
    kind = (target_kind or "").strip().lower()
    if kind == "prompt_input":
        low = sel.lower()
        if re.match(r"^div\.", low) and "textarea" not in low and "input" not in low:
            return True
    if kind == "response":
        low = sel.lower()
        if re.search(r"(^|[\s>+~])(textarea|input|button|select)(\[|$|\.)", low):
            return True
        if "textarea" in low or " input" in low or low.endswith(" input"):
            return True
        if is_fragile_positional_selector(sel):
            return True
    if kind == "surface_prep":
        low = sel.lower()
        if "textarea" in low:
            return True
        if re.search(r"(^|[\s>+~])(textarea)(\[|$|\.)", low):
            return True
    return False


def sanitize_submission_selectors(submission: dict) -> dict:
    """Normalize brittle selectors anywhere in a submission config dict."""
    if not isinstance(submission, dict):
        return submission
    out = dict(submission)
    for key in ("submit_selector", "response_selector", "response_within_selector",
                "response_text_within_selector", "response_list_selector", "response_role_selector"):
        if out.get(key):
            out[key] = sanitize_discovered_selector(str(out[key]))
    inputs = out.get("inputs")
    if isinstance(inputs, list):
        cleaned_inputs: list[dict] = []
        for inp in inputs:
            if not isinstance(inp, dict):
                continue
            row = dict(inp)
            if row.get("selector"):
                row["selector"] = sanitize_discovered_selector(str(row["selector"]))
            cleaned_inputs.append(row)
        out["inputs"] = cleaned_inputs
    return out


def _save_partial(site: str, component: str, submission: dict) -> None:
    """Write current submission dict to config.yaml without losing existing top-level keys."""
    comp_raw = load_component_config_raw(site, component)
    comp_raw.setdefault("urls", [])
    comp_raw.setdefault("posts", [])
    comp_raw["submission"] = sanitize_submission_selectors(submission)
    _save_config_with_comments(site, component, comp_raw)


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

async def _wait_for_enter() -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, input)


_MANUAL_DISCOVERY_SCRIPT = r"""
(() => {
  if (window.__genbountyManualDiscoveryInstalled) return;
  window.__genbountyManualDiscoveryInstalled = true;

  const STORAGE_KEY = "__genbounty_manual_panel_state";

  function loadPersistedState() {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === "object") return parsed;
      }
    } catch (_) {}
    return null;
  }

  function persistState() {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
        mode: state.mode,
        title: state.title,
        message: state.message,
        summary: state.summary,
        action: state.action,
        secondaryAction: state.secondaryAction,
        allowAction: state.allowAction,
        pickHint: state.pickHint,
        pickKind: state.pickKind,
        stepNumber: state.stepNumber,
        stepTotal: state.stepTotal,
        stepName: state.stepName,
        doNow: state.doNow,
        tip: state.tip,
        savedLines: state.savedLines,
        warn: state.warn,
      }));
    } catch (_) {}
  }

  const DEFAULT_STATE = {
    mode: "busy",
    title: "Genbounty",
    message: "Getting ready…\n\nSit tight.",
    summary: "",
    action: "",
    secondaryAction: "",
    allowAction: false,
    pickHint: "Getting ready…",
    pickKind: "",
    stepNumber: null,
    stepTotal: null,
    stepName: "",
    doNow: "",
    tip: "",
    savedLines: [],
    warn: "",
  };

  const state = { ...DEFAULT_STATE, ...(loadPersistedState() || {}) };

  function cssEscape(value) {
    if (window.CSS && typeof window.CSS.escape === "function") return window.CSS.escape(value);
    return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
  }

  function quoteAttr(value) {
    return String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  }

  /** Collapse whitespace for comparing button/submit labels. */
  function normalizedInnerText(elem) {
    if (!elem || elem.innerText == null) return "";
    return elem.innerText.replace(/\s+/g, " ").trim();
  }

  /** Nearest section-like region that has a uniqueness landmark (preferred for scoped selectors). */
  function nearestLandmarkSelector(startEl) {
    let cur = startEl;
    while (cur && cur.nodeType === Node.ELEMENT_NODE && cur !== document.body) {
      const tag = cur.tagName.toLowerCase();
      const alb = cur.getAttribute("aria-labelledby");
      if (alb && ["section", "aside", "article", "main", "nav"].includes(tag)) {
        const sel = `${tag}[aria-labelledby="${quoteAttr(alb)}"]`;
        try {
          const n = document.querySelectorAll(sel).length;
          if (n === 1) return sel;
        } catch (_) {}
      }
      if (tag === "section" && cur.id) {
        const sel = `section#${cssEscape(cur.id)}`;
        try {
          if (document.querySelectorAll(sel).length === 1) return sel;
        } catch (_) {}
      }
      cur = cur.parentElement;
    }
    return "";
  }

  function landmarkRootEl(landmarkSel) {
    if (!landmarkSel) return null;
    try {
      return document.querySelector(landmarkSel);
    } catch (_) {
      return null;
    }
  }

  /** Buttons whose visible label exactly equals target within root (or entire document when root null). */
  function buttonsMatchingLabel(root, label) {
    const w = label.replace(/\s+/g, " ").trim();
    if (!w) return [];
    const scope = root || document.documentElement || document.body;
    if (!scope) return [];
    return [...scope.querySelectorAll("button")].filter((b) => normalizedInnerText(b) === w);
  }

  /** Tailwind/layout utilities - too many matches to be message list roots. */
  const LAYOUT_UTILITY_REJECT = new Set([
    "flex", "inline-flex", "grid", "inline-grid", "block", "inline-block", "inline",
    "hidden", "relative", "absolute", "fixed", "sticky", "static", "contents",
  ]);

  /** True for class names that are likely build-time hashes (CSS modules, emotion, etc.). */
  function isStableClassName(className) {
    if (!className) return false;
    if (LAYOUT_UTILITY_REJECT.has(className)) return false;
    if (className.startsWith("__genbounty_") || className.startsWith("genbounty-")) return false;
    if (/[0-9]{4,}|:|\/|\[|\]/.test(className)) return false;
    if (/--[A-Za-z0-9_]{4,}/.test(className)) return false;
    if (/^css-[a-z0-9]+$/i.test(className)) return false;
    if (/^sc-[A-Za-z]/.test(className)) return false;
    return true;
  }

  function cssModulePrefix(className) {
    if (!className) return "";
    const m = String(className).match(/^(.+?)--[A-Za-z0-9_]{4,}$/);
    return m ? m[1] : "";
  }

  function selectorFromCssModulePrefix(el) {
    if (!el || !el.classList) return "";
    const tag = el.tagName.toLowerCase();
    for (const cls of el.classList) {
      const prefix = cssModulePrefix(cls);
      if (prefix.length >= 4) {
        const sel = `${tag}[class*='${prefix}']`;
        try {
          if (isUniqueSelector(sel, el)) return sel;
          if (visibleMatchCount(sel) <= 4) return sel;
        } catch (_) {}
      }
    }
    return "";
  }

  function stabilizeSavedSelector(el, raw) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return raw || "";
    const rawSel = (raw || "").trim();
    const moduleInRaw = /\.[A-Za-z][\w-]*--[A-Za-z0-9_]{4,}/.test(rawSel);
    if (isActionButton(el)) {
      const acc = selectorFromAccessibleName(el);
      if (acc) return acc;
    }
    const mod = selectorFromCssModulePrefix(el);
    if (mod) {
      if (moduleInRaw && /\sbutton\b/.test(rawSel) && el.tagName.toLowerCase() !== "button") {
        return `${mod} button`;
      }
      if (moduleInRaw || !rawSel) return mod;
    }
    if (!moduleInRaw) return rawSel;
    return rawSel
      .replace(/([a-zA-Z][\w-]*)\.([A-Za-z][\w-]*?)--[A-Za-z0-9_]{4,}/g, "$1[class*='$2']")
      .replace(/\.([A-Za-z][\w-]*?)--[A-Za-z0-9_]{4,}/g, "[class*='$1']");
  }

  function visibleMatchCount(selector) {
    try {
      return [...document.querySelectorAll(selector)].filter(isVisibleElement).length;
    } catch (_) {
      return 0;
    }
  }

  function isUniqueSelector(selector, el) {
    try {
      const matches = [...document.querySelectorAll(selector)];
      const visible = matches.filter(isVisibleElement);
      if (visible.length === 1) return visible[0] === el;
      if (matches.length === 1) return matches[0] === el;
      return false;
    } catch (_) {
      return false;
    }
  }

  function isActionButton(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return false;
    const tag = el.tagName.toLowerCase();
    if (tag === "button") return true;
    if (tag === "input" && ["submit", "button"].includes(el.getAttribute("type") || "")) return true;
    return (el.getAttribute("role") || "") === "button";
  }

  function visibleActionButtons(root) {
    if (!root || root.nodeType !== Node.ELEMENT_NODE) return [];
    const sel = 'button, [role="button"], input[type="submit"], input[type="button"]';
    const nodes = [];
    if (isActionButton(root)) nodes.push(root);
    if (typeof root.querySelectorAll === "function") {
      root.querySelectorAll(sel).forEach((node) => nodes.push(node));
    }
    return [...new Set(nodes)].filter(isVisibleElement);
  }

  /** Resolve send/submit when the click hits the button or an icon inside it (closest only). */
  function resolveActionButton(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return null;
    if (isActionButton(el)) return el;
    return el.closest(
      'button, [role="button"], input[type="submit"], input[type="button"]'
    );
  }

  /**
   * Click on padding/wrapper around a single button (e.g. Send).
   * Only safe on the innermost click target — never on path ancestors, or a
   * dialog that contains one toolbar button steals a nearby card click.
   */
  function resolveWrappedActionButton(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return null;
    if (isActionButton(el)) return null;
    if (el.closest('button, [role="button"], input[type="submit"], input[type="button"]')) {
      return null;
    }
    const inSubtree = visibleActionButtons(el);
    return inSubtree.length === 1 ? inSubtree[0] : null;
  }

  function selectorFromAccessibleName(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return "";
    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute("role") || "";
    const isButtonLike = isActionButton(el);
    if (!isButtonLike) return "";

    const baseTag = tag === "button" || tag === "input" ? tag : `[role="${quoteAttr(role)}"]`;
    const ariaLabel = (el.getAttribute("aria-label") || "").trim();
    if (ariaLabel.length >= 2) {
      const full = `${baseTag}[aria-label="${quoteAttr(ariaLabel)}"]`;
      if (isUniqueSelector(full, el)) return full;
      if (ariaLabel.length >= 6) {
        const prefix = ariaLabel.slice(0, Math.min(28, ariaLabel.length)).trim();
        const partial = `${baseTag}[aria-label^="${quoteAttr(prefix)}"]`;
        if (isUniqueSelector(partial, el)) return partial;
      }
    }

    const title = (el.getAttribute("title") || "").trim();
    if (title.length >= 2) {
      const full = `${baseTag}[title="${quoteAttr(title)}"]`;
      if (isUniqueSelector(full, el)) return full;
    }
    return "";
  }

  function isVisibleElement(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return false;
    const style = window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden" && !el.hidden;
  }

  function visiblePromptInputs(root) {
    if (!root || root.nodeType !== Node.ELEMENT_NODE) return [];
    const sel = 'textarea, input:not([type="hidden"]), [contenteditable="true"], [contenteditable=""]';
    const nodes = [];
    if (isPromptLikeInput(root)) nodes.push(root);
    if (typeof root.querySelectorAll === "function") {
      root.querySelectorAll(sel).forEach((node) => nodes.push(node));
    }
    return [...new Set(nodes)].filter(isVisibleElement);
  }

  /** Resolve the editable field when the click hits the input, its label, or a wrapper div. */
  function resolvePromptInput(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return null;
    if (isPromptLikeInput(el)) return el;

    const labelControl = resolveLabelControl(el);
    if (labelControl && isPromptLikeInput(labelControl)) return labelControl;

    const fromClosest = el.closest(
      'textarea, input:not([type="hidden"]), select, [contenteditable="true"], [contenteditable=""]'
    );
    if (fromClosest) return fromClosest;

    const inSubtree = visiblePromptInputs(el);
    if (inSubtree.length === 1) return inSubtree[0];

    const parent = el.parentElement;
    if (parent) {
      const inParent = visiblePromptInputs(parent);
      if (inParent.length === 1 && parent.contains(el)) return inParent[0];
    }
    return null;
  }

  function isPromptOrControlElement(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return false;
    const tag = el.tagName.toLowerCase();
    if (tag === "textarea" || tag === "select") return true;
    if (tag === "input" && (el.getAttribute("type") || "text") !== "hidden") return true;
    if (tag === "button") return true;
    return false;
  }

  function isLikelyResponseContent(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return false;
    if (isPromptOrControlElement(el)) return false;
    const tag = el.tagName.toLowerCase();
    if (tag === "code" || tag === "pre" || tag === "article") return true;
    if (el.getAttribute("data-message-author-role")) return true;
    const testId = (el.getAttribute("data-testid") || "").toLowerCase();
    if (testId.includes("message") || testId.includes("response")) return true;
    if (el.classList) {
      for (const cls of el.classList) {
        if (/^language-[\w-]+$/.test(cls)) return true;
      }
    }
    if (el.closest('[data-message-author-role="assistant"], [data-message-author-role]')) return true;
    if ((tag === "p" || tag === "div" || tag === "span") && !isPromptLikeInput(el)) {
      const inFormInput = el.closest("form textarea, form input:not([type='hidden'])");
      if (inFormInput && inFormInput.contains(el)) return false;
      if (normalizedInnerText(el).length >= 8) return true;
    }
    return false;
  }

  function resolveResponseContainer(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return null;
    if (isLikelyResponseContent(el)) return el;

    const semantic = el.closest(
      '[data-message-author-role="assistant"], [data-message-author-role], [data-testid*="message"], [data-testid*="response"], article'
    );
    if (semantic && !isPromptOrControlElement(semantic)) return semantic;

    const codePre = el.closest("code, pre");
    if (codePre && !codePre.closest("form textarea, form input:not([type='hidden'])")) return codePre;

    let cur = el;
    for (let i = 0; i < 8 && cur && cur.parentElement; i++) {
      if (isLikelyResponseContent(cur)) return cur;
      const tag = cur.tagName ? cur.tagName.toLowerCase() : "";
      if (tag === "form") break;
      cur = cur.parentElement;
    }
    return null;
  }

  function usefulTargetFor(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return el;

    if (state.pickKind === "response") {
      const response = resolveResponseContainer(el);
      if (response) return response;
      if (!isPromptOrControlElement(el)) return el;
      return el;
    }

    if (state.pickKind === "upload") {
      const label = el.closest("label");
      if (label && label.control && label.control.type === "file") return label.control;

      const fileInput = el.closest('input[type="file"]');
      if (fileInput) return fileInput;

      const uploadAffordance = el.closest(
        '[data-testid*="upload"], [data-testid*="Upload"], [data-testid*="file"], [data-testid*="File"], [aria-label*="upload"], [aria-label*="Upload"], [aria-label*="file"], [aria-label*="attach"], [aria-label*="Attach"]'
      );
      if (uploadAffordance) return uploadAffordance;

      const menuItem = el.closest('[role="menuitem"], [role="option"], [role="menuitemradio"], [role="menuitemcheckbox"]');
      if (menuItem) return menuItem;
    }

    if (state.pickKind === "menu") {
      const dropdown = el.closest(
        '[role="combobox"], [role="listbox"], button[aria-haspopup="listbox"], [aria-haspopup="listbox"], [aria-haspopup="menu"], button[aria-expanded]'
      );
      if (dropdown) return dropdown;
    }

    // Pre-steps: any clicked element — before control closest() heuristics.
    if (state.allowAction) {
      const any = resolveAnyElementTarget(el);
      if (any) return any;
    }

    const input = resolvePromptInput(el);
    if (input) return input;

    const dropdown = el.closest(
      '[role="combobox"], [role="listbox"], button[aria-haspopup="listbox"], [aria-haspopup="listbox"], [aria-haspopup="menu"]'
    );
    if (dropdown) return dropdown;

    const action = resolveActionButton(el);
    if (action) return action;

    const response = el.closest('[data-message-author-role], [data-testid*="message"], [data-testid*="response"], article');
    if (response) return response;

    const stable = el.closest('[data-testid], [data-test], [data-cy], [name]');
    return stable || el;
  }

  function isPanelElement(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return false;
    const panel = document.getElementById("__genbounty_manual_panel");
    return !!(panel && (el === panel || panel.contains(el)));
  }

  // Radix/shadcn dialogs dismiss on outside pointerdown (document capture).
  // Clicks on the Genbounty helper count as "outside" and would close popups
  // (Congratulations / cookies) without recording them. Stop pointer events at
  // window (before document) so the page never sees them; do not stop "click"
  // so our panel button handlers still fire.
  function shieldPanelFromOutsideDismiss(event) {
    if (!isPanelElement(event.target)) return;
    event.stopPropagation();
  }
  window.addEventListener("pointerdown", shieldPanelFromOutsideDismiss, true);
  window.addEventListener("mousedown", shieldPanelFromOutsideDismiss, true);

  function eventPathElements(event) {
    if (typeof event.composedPath === "function") {
      return event.composedPath().filter((node) => node && node.nodeType === Node.ELEMENT_NODE);
    }
    return event.target && event.target.nodeType === Node.ELEMENT_NODE ? [event.target] : [];
  }

  function isPromptLikeInput(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return false;
    const tag = el.tagName.toLowerCase();
    if (tag === "textarea" || tag === "select") return true;
    if (tag === "input" && (el.getAttribute("type") || "text") !== "hidden") return true;
    const ce = el.getAttribute("contenteditable");
    return ce === "true" || ce === "";
  }

  function resolveLabelControl(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return null;
    if (el.tagName.toLowerCase() !== "label") return null;
    const forId = el.getAttribute("for");
    if (forId) {
      const linked = document.getElementById(forId);
      if (linked) return linked;
    }
    if (el.control) return el.control;
    return null;
  }

  function looksPointerInteractive(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return false;
    try {
      if (window.getComputedStyle(el).cursor === "pointer") return true;
    } catch (_) {}
    return false;
  }

  /**
   * Pre-steps / allowAction picks: record any DOM element the operator clicks.
   * Only light cleanup (skip SVG/progressbar leaves; prefer a compact pointer
   * ancestor when the leaf is decorative) — no site-specific control filters.
   */
  function resolveAnyElementTarget(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return null;
    let cur = el;
    for (let i = 0; i < 8 && cur && cur !== document.documentElement; i++) {
      if (isPanelElement(cur)) break;
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
    if (!cur || cur.nodeType !== Node.ELEMENT_NODE || isPanelElement(cur)) {
      return el.nodeType === Node.ELEMENT_NODE ? el : null;
    }
    // Real controls stay as-is.
    if (isPromptLikeInput(cur) || isActionButton(cur)) return cur;
    // If the leaf is nested under a compact pointer host, use that host
    // (common card/row pattern on any site — not label-specific).
    let p = cur.parentElement;
    for (let i = 0; i < 8 && p && p !== document.documentElement; i++) {
      if (isPanelElement(p)) break;
      const pText = normalizedInnerText(p);
      if (pText.length > 400) break;
      if (looksPointerInteractive(p) || isActionButton(p)) return p;
      p = p.parentElement;
    }
    return cur;
  }

  function usefulTargetFromEvent(event) {
    const path = eventPathElements(event);
    if (state.pickKind === "response") {
      for (const el of path) {
        if (isPanelElement(el)) continue;
        const response = resolveResponseContainer(el);
        if (response) return response;
      }
      for (const el of path) {
        if (isPanelElement(el)) continue;
        if (!isPromptOrControlElement(el)) return el;
      }
      return event.target && event.target.nodeType === Node.ELEMENT_NODE ? event.target : null;
    }
    let origin = null;
    for (const el of path) {
      if (isPanelElement(el)) continue;
      origin = el;
      break;
    }
    // Pre-steps / popup / send: any element is a valid pick target.
    if (state.allowAction && origin) {
      const any = resolveAnyElementTarget(origin);
      if (any) return any;
    }
    // Prompt / button via closest from each path node (safe — does not scan siblings).
    for (const el of path) {
      if (isPanelElement(el)) continue;
      const prompt = resolvePromptInput(el);
      if (prompt) return prompt;
      const action = resolveActionButton(el);
      if (action) return action;
    }
    // Wrapper padding around Send: only the innermost target, never ancestors.
    if (origin) {
      const wrapped = resolveWrappedActionButton(origin);
      if (wrapped) return wrapped;
    }
    for (const el of path) {
      if (isPanelElement(el)) continue;
      const target = usefulTargetFor(el);
      if (target && target.nodeType === Node.ELEMENT_NODE) return target;
    }
    return usefulTargetFor(event.target);
  }

  function roleTextSelector(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return "";
    const role = el.getAttribute("role") || "";
    if (!["menuitem", "option", "menuitemradio", "menuitemcheckbox"].includes(role)) return "";
    const label = normalizedInnerText(el);
    if (label.length < 2 || label.length > 120) return "";
    const w = label.replace(/\s+/g, " ").trim();
    const matches = [...document.querySelectorAll(`[role="${role}"]`)].filter(
      (node) => normalizedInnerText(node) === w
    );
    if (matches.length === 1 && matches[0] === el) {
      const lit = JSON.stringify(w);
      return `[role="${quoteAttr(role)}"]:has-text(${lit})`;
    }
    return "";
  }

  function selectorFor(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return "";

    const roleSel = roleTextSelector(el);
    if (roleSel) return roleSel;

    if (el.id) return `#${cssEscape(el.id)}`;

    const accessibleSel = selectorFromAccessibleName(el);
    if (accessibleSel) return accessibleSel;

    const tag = el.tagName.toLowerCase();
    const landmarkSel = nearestLandmarkSelector(el);
    const landRoot = landmarkRootEl(landmarkSel);

    if (tag === "code" || tag === "pre") {
      if (el.classList) {
        for (const cls of el.classList) {
          if (/^language-[\w-]+$/.test(cls)) {
            const dotted = `${tag}.${cssEscape(cls)}`;
            try {
              if (isUniqueSelector(dotted, el)) return dotted;
              if (document.querySelectorAll(dotted).length === 1) return dotted;
            } catch (_) {}
            const partial = `${tag}[class*='${cls}']`;
            try {
              if (isUniqueSelector(partial, el)) return partial;
              if (visibleMatchCount(partial) <= 6) return partial;
            } catch (_) {}
          }
        }
      }
    }

    const stableAttrs = ["data-testid", "data-test", "data-cy", "data-message-author-role", "aria-label", "name", "role", "placeholder", "contenteditable", "type"];
    for (const attr of stableAttrs) {
      const value = el.getAttribute(attr);
      if (value) {
        // type=button matches nearly every button on the page — never treat as unique.
        if (attr === "type" && String(value).toLowerCase() === "button") continue;
        const selector = `${tag}[${attr}="${quoteAttr(value)}"]`;
        try {
          if (isUniqueSelector(selector, el)) return selector;
        } catch (_) {}
      }
    }

    if (tag === "textarea" || tag === "input") {
      const placeholder = (el.getAttribute("placeholder") || "").trim();
      if (placeholder.length >= 8) {
        const prefix = placeholder.slice(0, Math.min(32, placeholder.length)).trim();
        if (prefix.length >= 8) {
          const sel = `${tag}[placeholder^="${quoteAttr(prefix)}"]`;
          try {
            if (document.querySelectorAll(sel).length === 1) return sel;
          } catch (_) {}
        }
      }
    }

    const moduleSel = selectorFromCssModulePrefix(el);
    if (moduleSel) return moduleSel;

    // For buttons: prefer accessible names (handled above); try type=submit when unique
    if (tag === "button" || el.getAttribute("role") === "button") {
      if (el.getAttribute("type") === "submit") {
        try {
          if (visibleMatchCount("button[type='submit']") === 1) return "button[type='submit']";
          if (document.querySelectorAll("button[type='submit']").length === 1) return "button[type='submit']";
        } catch (_) {}
      }
    }

    if (el.classList && el.classList.length) {
      const classes = Array.from(el.classList)
        .filter(isStableClassName)
        .slice(0, 3);
      if (classes.length) {
        const selector = `${tag}.${classes.map(cssEscape).join(".")}`;
        try {
          if (document.querySelectorAll(selector).length === 1) return selector;
        } catch (_) {}
        // Try just the first class if the combo isn't unique
        if (classes.length > 1) {
          const singleClass = `${tag}.${cssEscape(classes[0])}`;
          try {
            if (document.querySelectorAll(singleClass).length === 1) return singleClass;
          } catch (_) {}
        }
      }
    }

    // Scoped class when the same markup appears several times across distinct regions/widgets.
    if (landRoot && el.classList && el.classList.length) {
      const filtered = Array.from(el.classList)
        .filter(isStableClassName)
        .slice(0, 3);
      if (filtered.length) {
        const selScoped = `${tag}.${filtered.map(cssEscape).join(".")}`;
        try {
          const nGlobal = document.querySelectorAll(selScoped).length;
          let nScoped = 0;
          try { nScoped = landRoot.querySelectorAll(selScoped).length; } catch (_) { nScoped = 999; }
          if (
            nGlobal > 1
            && nScoped === 1
            && landRoot.contains(el)
            && typeof el.matches === "function"
            && el.matches(selScoped)
          ) {
            return `${landmarkSel} ${selScoped}`;
          }
        } catch (_) {}
      }
    }

    // Playwright :has-text (not valid in querySelector); verify uniqueness via DOM text sweep.
    const isButtonLike = tag === "button" || el.getAttribute("role") === "button";
    if (isButtonLike) {
      const label = normalizedInnerText(el);
      if (label.length >= 4 && label.length <= 240) {
        const lit = JSON.stringify(label);
        if (landRoot) {
          const hits = buttonsMatchingLabel(landRoot, label);
          if (hits.length === 1 && hits[0] === el) return `${landmarkSel} button:has-text(${lit})`;
        }
        const allHits = buttonsMatchingLabel(document.documentElement, label);
        if (allHits.length === 1 && allHits[0] === el) return `button:has-text(${lit})`;
      }
    }

    // Structural fallback - walk up but anchor on landmarks / stable ancestor attrs early.
    // Cap at 5 levels to avoid over-specific positional paths.
    const MAX_DEPTH = 5;
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === Node.ELEMENT_NODE && cur !== document.body && parts.length < MAX_DEPTH) {
      let part = cur.tagName.toLowerCase();
      if (cur.id) {
        part += `#${cssEscape(cur.id)}`;
        parts.unshift(part);
        break;
      }
      if (cur !== el) {
        const tagLc = cur.tagName.toLowerCase();
        const alb = cur.getAttribute("aria-labelledby");
        if (alb && ["section", "aside", "article", "main", "nav"].includes(tagLc)) {
          parts.unshift(`${tagLc}[aria-labelledby="${quoteAttr(alb)}"]`);
          break;
        }
        for (const attr of ["data-testid", "data-test", "data-cy", "aria-label", "name"]) {
          const v = cur.getAttribute(attr);
          if (v) {
            parts.unshift(`${cur.tagName.toLowerCase()}[${attr}="${quoteAttr(v)}"]`);
            cur = null;
            break;
          }
        }
        if (cur === null) break;
      }
      const parent = cur.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter(x => x.tagName === cur.tagName);
        if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(cur) + 1})`;
      }
      parts.unshift(part);
      cur = parent;
    }
    let positional = parts.join(" > ");
    if (!positional) return "";

    // Optionally prefix with a semantic landmark only when positional is ambiguous or relies on brittle indexing.
    if (landmarkSel) {
      const scopedTail = `${landmarkSel} ${positional}`;
      try {
        let nPos = 0;
        try {
          nPos = document.querySelectorAll(positional).length;
        } catch (_) {
          nPos = 0;
        }
        const brittle = positional.includes(":nth-of-type");
        const needScope = nPos > 1 || brittle;
        if (needScope && document.querySelector(scopedTail)) return scopedTail;
      } catch (_) {}
    }

    return positional;
  }

  function parseStepFromMessage(message) {
    const first = String(message || "").split("\n")[0].trim();
    const m = first.match(/^(\d+)\s*\/\s*(\d+)\s*\.\s*(.+)$/);
    if (!m) return { stepNumber: null, stepTotal: null, stepName: "" };
    return { stepNumber: Number(m[1]), stepTotal: Number(m[2]), stepName: (m[3] || "").trim() };
  }

  function resolveStepView() {
    const parsed = parseStepFromMessage(state.message);
    const stepNumber = state.stepNumber != null ? Number(state.stepNumber) : parsed.stepNumber;
    const stepTotal = state.stepTotal != null ? Number(state.stepTotal) : parsed.stepTotal;
    let stepName = String(state.stepName || "").trim();
    if (!stepName) stepName = parsed.stepName;
    if (!stepName) {
      const t = String(state.title || "").trim();
      if (t && !/^genbounty/i.test(t) && !/^confirm\s+step/i.test(t)) stepName = t;
    }
    if (!stepName) stepName = "Component discovery";
    let doNow = String(state.doNow || "").trim();
    if (!doNow) {
      const parts = String(state.message || "").split(/\n\n+/);
      if (parts.length >= 2) doNow = parts[1].split("\n")[0].trim();
      else if (parts[0]) {
        const lines = parts[0].split("\n").slice(1).map((l) => l.trim()).filter(Boolean);
        doNow = lines[0] || "";
      }
    }
    const tip = String(state.tip || "").trim();
    const warn = String(state.warn || "").trim();
    const savedLines = Array.isArray(state.savedLines)
      ? state.savedLines.map((s) => String(s || "").trim()).filter(Boolean)
      : [];
    return { stepNumber, stepTotal, stepName, doNow, tip, warn, savedLines };
  }

  function modeChipInfo() {
    if (state.mode === "pick") return { label: "Click on the page", tone: "click" };
    if (state.mode === "busy") return { label: "Please wait", tone: "wait" };
    if (state.mode === "confirm") return { label: "Review", tone: "review" };
    return { label: "Continue when ready", tone: "continue" };
  }

  function footerText(view) {
    if (state.mode === "busy") return state.pickHint || "Working…";
    if (state.mode === "pick") {
      return "Wait for this box to update before the next click.";
    }
    if (state.mode === "confirm") return "Looks right? Save it.";
    return state.pickHint || "Click Continue when ready.";
  }

  function ensurePanel() {
    let panel = document.getElementById("__genbounty_manual_panel");
    if (
      panel
      && panel.querySelector(".genbounty-step-name")
      && panel.querySelector(".genbounty-drag-grip")
    ) {
      return panel;
    }
    if (panel) panel.remove();
    panel = document.createElement("div");
    panel.id = "__genbounty_manual_panel";
    panel.innerHTML = `
      <div class="genbounty-drag" title="Drag to move">
        <div class="genbounty-drag-grip" aria-hidden="true"></div>
        <div class="genbounty-eyebrow">
          <span class="genbounty-brand">Genbounty</span>
          <span class="genbounty-progress"></span>
        </div>
        <div class="genbounty-step-name"></div>
        <div class="genbounty-mode-chip"></div>
        <div class="genbounty-drag-hint">Drag header to move</div>
      </div>
      <div class="genbounty-body">
        <div class="genbounty-do-label">Do this now</div>
        <div class="genbounty-do-now"></div>
        <div class="genbounty-tip" style="display:none;"></div>
        <div class="genbounty-warn" style="display:none;"></div>
        <div class="genbounty-saved" style="display:none;">
          <div class="genbounty-saved-label"></div>
          <ol class="genbounty-saved-list"></ol>
        </div>
        <pre class="genbounty-summary"></pre>
        <div class="genbounty-message" style="display:none;"></div>
      </div>
      <div class="genbounty-actions">
        <button type="button" class="genbounty-button genbounty-button-primary"></button>
        <button type="button" class="genbounty-button genbounty-button-secondary" style="display:none;"></button>
        <button type="button" class="genbounty-button genbounty-button-tertiary" style="display:none;">Not working?</button>
      </div>
      <div class="genbounty-hint"></div>
    `;
    const style = document.createElement("style");
    style.id = "__genbounty_manual_style";
    style.textContent = `
      #__genbounty_manual_panel {
        position: fixed; top: 16px; left: 16px; z-index: 2147483647;
        width: 420px; box-sizing: border-box; padding: 14px 16px 12px;
        background: #1e1f22; color: #e8e8ea; border: 1px solid #3a3b40;
        border-radius: 12px; box-shadow: 0 12px 32px rgba(0,0,0,.45);
        font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        font-size: 14px; line-height: 1.45;
      }
      #__genbounty_manual_panel .genbounty-drag {
        cursor: grab; user-select: none; margin: -6px -8px 12px; padding: 8px 8px 10px;
        border-radius: 8px;
      }
      #__genbounty_manual_panel .genbounty-drag:active { cursor: grabbing; }
      #__genbounty_manual_panel .genbounty-drag-grip {
        width: 36px; height: 4px; border-radius: 999px; background: #52525b;
        margin: 0 auto 8px;
      }
      #__genbounty_manual_panel .genbounty-drag-hint {
        margin-top: 6px; font-size: 11px; color: #71717a; font-weight: 500;
      }
      #__genbounty_manual_panel .genbounty-eyebrow {
        display: flex; align-items: center; justify-content: space-between; gap: 10px;
        margin-bottom: 6px; font-size: 11px; font-weight: 600; letter-spacing: 0.04em;
        text-transform: uppercase; color: #8b8d94;
      }
      #__genbounty_manual_panel .genbounty-brand { color: #8b8d94; }
      #__genbounty_manual_panel .genbounty-progress { color: #b0b3ba; letter-spacing: 0.02em; }
      #__genbounty_manual_panel .genbounty-step-name {
        font-size: 20px; font-weight: 700; line-height: 1.25; color: #f2f3f5; margin-bottom: 8px;
      }
      #__genbounty_manual_panel .genbounty-mode-chip {
        display: inline-flex; align-items: center; gap: 6px;
        padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 650;
        border: 1px solid transparent;
      }
      #__genbounty_manual_panel .genbounty-mode-chip::before {
        content: ""; width: 7px; height: 7px; border-radius: 50%; background: currentColor;
      }
      #__genbounty_manual_panel .genbounty-mode-chip--click {
        color: #93c5fd; background: rgba(37, 99, 235, 0.18); border-color: rgba(59, 130, 246, 0.45);
      }
      #__genbounty_manual_panel .genbounty-mode-chip--continue {
        color: #86efac; background: rgba(22, 163, 74, 0.16); border-color: rgba(34, 197, 94, 0.4);
      }
      #__genbounty_manual_panel .genbounty-mode-chip--wait {
        color: #fcd34d; background: rgba(217, 119, 6, 0.16); border-color: rgba(245, 158, 11, 0.4);
      }
      #__genbounty_manual_panel .genbounty-mode-chip--review {
        color: #d4d4d8; background: rgba(113, 113, 122, 0.2); border-color: rgba(161, 161, 170, 0.35);
      }
      #__genbounty_manual_panel .genbounty-body { margin-bottom: 12px; }
      #__genbounty_manual_panel .genbounty-do-label {
        font-size: 11px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
        color: #8b8d94; margin-bottom: 4px;
      }
      #__genbounty_manual_panel .genbounty-do-now {
        font-size: 16px; font-weight: 650; color: #f8fafc; line-height: 1.4; white-space: pre-wrap;
      }
      #__genbounty_manual_panel .genbounty-tip {
        margin-top: 8px; font-size: 13px; color: #a1a1aa; line-height: 1.45; white-space: pre-wrap;
      }
      #__genbounty_manual_panel .genbounty-warn {
        margin-top: 8px; padding: 8px 10px; border-radius: 8px;
        background: rgba(180, 83, 9, 0.18); border: 1px solid rgba(245, 158, 11, 0.45);
        color: #fde68a; font-size: 13px; line-height: 1.4; white-space: pre-wrap;
      }
      #__genbounty_manual_panel .genbounty-saved { margin-top: 10px; }
      #__genbounty_manual_panel .genbounty-saved-label {
        font-size: 11px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase;
        color: #8b8d94; margin-bottom: 4px;
      }
      #__genbounty_manual_panel .genbounty-saved-list {
        margin: 0; padding-left: 1.2rem; color: #d4d4d8; font-size: 12px;
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        max-height: 120px; overflow: auto;
      }
      #__genbounty_manual_panel .genbounty-saved-list li + li { margin-top: 2px; }
      #__genbounty_manual_panel .genbounty-summary {
        display: none; margin: 10px 0 0; padding: 10px 12px;
        background: #141516; border: 1px solid #3a3b40; border-radius: 8px;
        color: #e8e8e8; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        font-size: 12px; line-height: 1.45; white-space: pre-wrap; word-break: break-word;
        max-height: 220px; overflow: auto;
      }
      #__genbounty_manual_panel .genbounty-summary--visible { display: block; }
      #__genbounty_manual_panel .genbounty-message {
        color: #a1a1aa; margin-top: 8px; white-space: pre-wrap; font-size: 13px;
      }
      #__genbounty_manual_panel .genbounty-actions { display: flex; flex-direction: column; gap: 8px; }
      #__genbounty_manual_panel .genbounty-button {
        width: 100%; background: #2563eb; color: #fff; border: 1px solid transparent; border-radius: 8px;
        padding: 10px 14px; font-size: 14px; font-weight: 650; cursor: pointer;
      }
      #__genbounty_manual_panel .genbounty-button:hover { background: #3b82f6; }
      #__genbounty_manual_panel .genbounty-button--quiet {
        background: transparent; color: #d4d4d8; border: 1px solid #52525b;
      }
      #__genbounty_manual_panel .genbounty-button--quiet:hover { background: #2a2b30; }
      #__genbounty_manual_panel .genbounty-button-secondary {
        background: transparent; color: #e8e8ea; border: 1px solid #52525b;
      }
      #__genbounty_manual_panel .genbounty-button-secondary:hover { background: #2a2b30; }
      #__genbounty_manual_panel .genbounty-button-tertiary {
        background: transparent; color: #9a9a9a; border: none; padding: 4px 0;
        font-size: 12px; font-weight: 500; cursor: pointer; text-decoration: underline;
      }
      #__genbounty_manual_panel .genbounty-button-tertiary:hover { color: #e8e8ea; }
      #__genbounty_manual_panel .genbounty-hint {
        color: #8b8d94; font-size: 12px; margin-top: 10px; line-height: 1.4;
        border-top: 1px solid #33343a; padding-top: 8px;
      }
      .__genbounty_manual_hover { outline: 2px solid #3b82f6 !important; outline-offset: 2px !important; }
      .__genbounty_manual_selected {
        outline: 3px solid #2563eb !important;
        outline-offset: 3px !important;
        background-color: rgba(37, 99, 235, 0.14) !important;
      }
    `;
    const oldStyle = document.getElementById(style.id);
    if (oldStyle) oldStyle.remove();
    document.documentElement.appendChild(style);
    document.documentElement.appendChild(panel);
    // Restore prior position if the operator dragged it earlier this session.
    try {
      const savedPos = sessionStorage.getItem("__genbounty_manual_panel_pos");
      if (savedPos) {
        const pos = JSON.parse(savedPos);
        if (pos && Number.isFinite(pos.left) && Number.isFinite(pos.top)) {
          panel.style.left = `${pos.left}px`;
          panel.style.top = `${pos.top}px`;
          panel.style.right = "auto";
        }
      }
    } catch (_) {}
    // Drag must be wired on window capture: the outside-dismiss shield stops
    // mousedown/pointerdown from reaching panel descendants.
    if (!window.__genbountyPanelDragWired) {
      window.__genbountyPanelDragWired = true;
      let dragging = false;
      let dragOffsetX = 0;
      let dragOffsetY = 0;
      const onDragStart = (event) => {
        const live = document.getElementById("__genbounty_manual_panel");
        if (!live) return;
        const handle = live.querySelector(".genbounty-drag");
        if (!handle) return;
        const t = event.target;
        if (!t || !handle.contains(t)) return;
        if (t.closest && t.closest("button, a, input, textarea, select")) return;
        dragging = true;
        const rect = live.getBoundingClientRect();
        const cx = Number(event.clientX);
        const cy = Number(event.clientY);
        dragOffsetX = cx - rect.left;
        dragOffsetY = cy - rect.top;
        try { event.preventDefault(); } catch (_) {}
      };
      const onDragMove = (event) => {
        if (!dragging) return;
        const live = document.getElementById("__genbounty_manual_panel");
        if (!live) { dragging = false; return; }
        const nextLeft = Math.max(8, Math.min(window.innerWidth - live.offsetWidth - 8, Number(event.clientX) - dragOffsetX));
        const nextTop = Math.max(8, Math.min(window.innerHeight - live.offsetHeight - 8, Number(event.clientY) - dragOffsetY));
        live.style.left = `${nextLeft}px`;
        live.style.top = `${nextTop}px`;
        live.style.right = "auto";
      };
      const onDragEnd = () => {
        if (!dragging) return;
        dragging = false;
        const live = document.getElementById("__genbounty_manual_panel");
        if (!live) return;
        try {
          sessionStorage.setItem("__genbounty_manual_panel_pos", JSON.stringify({
            left: live.offsetLeft,
            top: live.offsetTop,
          }));
        } catch (_) {}
      };
      window.addEventListener("pointerdown", onDragStart, true);
      window.addEventListener("mousedown", onDragStart, true);
      window.addEventListener("pointermove", onDragMove, true);
      window.addEventListener("mousemove", onDragMove, true);
      window.addEventListener("pointerup", onDragEnd, true);
      window.addEventListener("mouseup", onDragEnd, true);
    }
    const primaryBtn = panel.querySelector(".genbounty-button-primary");
    const secondaryBtn = panel.querySelector(".genbounty-button-secondary");
    primaryBtn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (state.mode === "pick" && !state.allowAction && !state.action) {
        return;
      }
      if (state.mode === "confirm") {
        if (window.genbountyManualEvent) window.genbountyManualEvent({ type: "confirm" });
        return;
      }
      // In pick mode the primary button is always Skip/Done (finish the pick loop).
      if (state.mode === "pick" && state.action) {
        if (window.genbountyManualEvent) window.genbountyManualEvent({ type: "skip" });
        return;
      }
      if (window.genbountyManualEvent) window.genbountyManualEvent({ type: "continue" });
    });
    secondaryBtn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (window.genbountyManualEvent) window.genbountyManualEvent({ type: "retry" });
    });
    const tertiaryBtn = panel.querySelector(".genbounty-button-tertiary");
    tertiaryBtn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      showGuidedDiscoveryModal("confirm_restart");
    });
    return panel;
  }

  function render() {
    const panel = ensurePanel();
    const view = resolveStepView();
    const chip = modeChipInfo();
    const progressEl = panel.querySelector(".genbounty-progress");
    if (view.stepNumber != null && view.stepTotal != null) {
      progressEl.textContent = "Step " + view.stepNumber + " of " + view.stepTotal;
    } else {
      progressEl.textContent = "";
    }
    panel.querySelector(".genbounty-step-name").textContent = view.stepName;
    const chipEl = panel.querySelector(".genbounty-mode-chip");
    chipEl.textContent = chip.label;
    chipEl.className = "genbounty-mode-chip genbounty-mode-chip--" + chip.tone;

    const doNowEl = panel.querySelector(".genbounty-do-now");
    doNowEl.textContent = view.doNow || (state.mode === "busy" ? (state.pickHint || "Working…") : "Follow the instruction below.");

    const tipEl = panel.querySelector(".genbounty-tip");
    if (view.tip) {
      tipEl.style.display = "";
      tipEl.textContent = "Tip: " + view.tip;
    } else {
      tipEl.style.display = "none";
      tipEl.textContent = "";
    }

    const warnEl = panel.querySelector(".genbounty-warn");
    if (view.warn) {
      warnEl.style.display = "";
      warnEl.textContent = view.warn;
    } else {
      warnEl.style.display = "none";
      warnEl.textContent = "";
    }

    const savedWrap = panel.querySelector(".genbounty-saved");
    const savedLabel = panel.querySelector(".genbounty-saved-label");
    const savedList = panel.querySelector(".genbounty-saved-list");
    savedList.textContent = "";
    if (view.savedLines.length) {
      savedWrap.style.display = "";
      savedLabel.textContent = "Already saved (" + view.savedLines.length + ")";
      view.savedLines.forEach((line) => {
        const li = document.createElement("li");
        li.textContent = line;
        savedList.appendChild(li);
      });
    } else {
      savedWrap.style.display = "none";
    }

    const summaryEl = panel.querySelector(".genbounty-summary");
    const summaryText = (state.summary || "").trim();
    if (summaryEl) {
      summaryEl.textContent = summaryText;
      summaryEl.classList.toggle("genbounty-summary--visible", state.mode === "confirm" && !!summaryText);
    }

    // Keep raw message hidden unless structured fields are missing (fallback).
    const messageEl = panel.querySelector(".genbounty-message");
    const needFallback = !String(state.doNow || "").trim() && !view.doNow;
    if (needFallback && (state.message || "").trim()) {
      messageEl.style.display = "";
      messageEl.textContent = state.message;
    } else {
      messageEl.style.display = "none";
      messageEl.textContent = "";
    }

    const primaryBtn = panel.querySelector(".genbounty-button-primary");
    const secondaryBtn = panel.querySelector(".genbounty-button-secondary");
    const tertiaryBtn = panel.querySelector(".genbounty-button-tertiary");
    const busy = state.mode === "busy";
    const pickQuiet = state.mode === "pick" && !!(state.action || "").trim();
    primaryBtn.style.display = busy || !state.action ? "none" : "";
    primaryBtn.classList.toggle("genbounty-button--quiet", pickQuiet);
    if (!busy && state.action) {
      primaryBtn.textContent = state.mode === "pick"
        ? (state.action === "Done" ? "Done — none / finished" : state.action)
        : state.action;
    }
    if (state.secondaryAction && !busy) {
      secondaryBtn.style.display = "";
      secondaryBtn.textContent = state.secondaryAction;
    } else {
      secondaryBtn.style.display = "none";
    }
    if (tertiaryBtn) {
      tertiaryBtn.style.display = state.mode === "confirm" ? "none" : "";
    }
    panel.querySelector(".genbounty-hint").textContent = footerText(view);
  }

  let hovered = null;
  let lastPickKey = "";
  let lastPickAt = 0;

  function updateHover(event) {
    if (state.mode !== "pick") return;
    if (isPanelElement(event.target)) return;
    if (hovered) hovered.classList.remove("__genbounty_manual_hover");
    hovered = usefulTargetFromEvent(event);
    if (hovered && hovered.classList) hovered.classList.add("__genbounty_manual_hover");
  }

  function ancestorContextHtml(el, steps) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return "";
    let cur = el;
    for (let i = 0; i < steps && cur && cur.parentElement; i++) {
      cur = cur.parentElement;
    }
    return cur && cur.outerHTML ? cur.outerHTML : "";
  }

  function handlePick(event) {
    if (isPanelElement(event.target)) return;
    if (state.mode !== "pick") return;

    let target = usefulTargetFromEvent(event);
    if (!target || target.nodeType !== Node.ELEMENT_NODE) {
      if (window.__genbountyManualDiscoverV2 && event.target && event.target.nodeType === Node.ELEMENT_NODE) {
        target = event.target;
      } else {
        if (window.genbountyManualEvent) {
          window.genbountyManualEvent({
            type: "pick_failed",
            error: "Click did not land on a recognizable input - try the editable field itself.",
          });
        }
        return;
      }
    }

    const dedupeKey = [
      event.type,
      target.tagName,
      target.id || "",
      target.getAttribute("name") || "",
      target.getAttribute("data-testid") || "",
    ].join("|");
    const now = Date.now();
    if (dedupeKey === lastPickKey && now - lastPickAt < 500) return;
    lastPickKey = dedupeKey;
    lastPickAt = now;

    if (!state.allowAction) {
      const promptLike = isPromptLikeInput(target);
      if (!promptLike) {
        event.preventDefault();
        event.stopPropagation();
      }
    }
    if (hovered) hovered.classList.remove("__genbounty_manual_hover");
    hovered = null;

    if (window.__genbountyManualDiscoverV2) {
      const contextSteps = state.pickKind === "response" ? 3 : 5;
      const contextHtml = ancestorContextHtml(target, contextSteps);
      if (!contextHtml) {
        if (window.genbountyManualEvent) {
          window.genbountyManualEvent({
            type: "pick_failed",
            error: "Could not capture DOM context around the click - try again.",
            tag: target.tagName.toLowerCase(),
          });
        }
        return;
      }
      state.mode = "busy";
      state.action = "";
      state.pickHint = "Analyzing click context…";
      render();
      if (window.genbountyManualEvent) {
        const browserSelector = stabilizeSavedSelector(target, selectorFor(target));
        const payload = {
          type: "pick_context",
          contextHtml: contextHtml.slice(0, 500000),
          tag: target.tagName.toLowerCase(),
          inputType: target.getAttribute("type") || "",
          role: target.getAttribute("role") || "",
          innerText: normalizedInnerText(target).slice(0, 200),
          pickKind: state.pickKind || "",
          browserSelector: browserSelector || "",
        };
        if (state.pickKind === "response") {
          const wideContextHtml = ancestorContextHtml(target, 8);
          if (wideContextHtml) {
            payload.wideContextHtml = wideContextHtml.slice(0, 800000);
          }
        }
        window.genbountyManualEvent(payload);
      } else {
        const hint = document.querySelector("#__genbounty_manual_panel .genbounty-hint");
        if (hint) hint.textContent = "Discovery bridge not ready - close and restart Start Discovery.";
      }
      return;
    }

    const selector = stabilizeSavedSelector(target, selectorFor(target));
    if (!selector) {
      const hint = document.querySelector("#__genbounty_manual_panel .genbounty-hint");
      if (hint) {
        hint.textContent = "Could not build a selector - click the input directly, not a wrapper or toolbar.";
      }
      if (window.genbountyManualEvent) {
        window.genbountyManualEvent({
          type: "pick_failed",
          error: "Could not build a selector - click the input directly, not a wrapper or toolbar.",
          tag: target.tagName.toLowerCase(),
        });
      }
      return;
    }
    state.mode = "busy";
    state.action = "";
    state.pickHint = isPromptLikeInput(target)
      ? "Verifying input…"
      : "Saving selection…";
    render();
    if (window.genbountyManualEvent) {
      window.genbountyManualEvent({
        type: "selector",
        selector,
        tag: target.tagName.toLowerCase(),
        inputType: target.getAttribute("type") || "",
        role: target.getAttribute("role") || "",
        innerText: normalizedInnerText(target).slice(0, 200),
      });
    } else {
      const hint = document.querySelector("#__genbounty_manual_panel .genbounty-hint");
      if (hint) hint.textContent = "Discovery bridge not ready - close and restart Start Discovery.";
    }
  }

  document.addEventListener("mouseover", updateHover, true);
  document.addEventListener("click", handlePick, true);

  window.__genbountyManualClearStep = () => {
    try { sessionStorage.removeItem(STORAGE_KEY); } catch (_) {}
    try { sessionStorage.removeItem("__genbounty_manual_panel_pos"); } catch (_) {}
    Object.assign(state, DEFAULT_STATE);
    if (hovered) {
      hovered.classList.remove("__genbounty_manual_hover");
      hovered = null;
    }
    const panel = document.getElementById("__genbounty_manual_panel");
    if (panel) {
      panel.style.left = "16px";
      panel.style.top = "16px";
      panel.style.right = "auto";
    }
    render();
  };

  window.__genbountyManualSetStep = (next) => {
    if (hovered) {
      hovered.classList.remove("__genbounty_manual_hover");
      hovered = null;
    }
    // Reset structured slots so a prior Saved list / tip does not linger.
    Object.assign(state, {
      stepNumber: null,
      stepTotal: null,
      stepName: "",
      doNow: "",
      tip: "",
      savedLines: [],
      warn: "",
    }, next || {});
    persistState();
    render();
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", render, { once: true });
  } else {
    render();
  }

  window.__genbountyScanUploads = () => {
    const fileInputs = [];
    document.querySelectorAll('input[type="file"]').forEach((el) => {
      if (!el || el.disabled) return;
      const style = window.getComputedStyle(el);
      const visible = style.display !== "none" && style.visibility !== "hidden" && !el.hidden;
      const sel = selectorFor(el);
      if (!sel) return;
      let matchCount = 0;
      try { matchCount = document.querySelectorAll(sel).length; } catch (_) {}
      fileInputs.push({
        selector: sel,
        visible,
        accept: el.getAttribute("accept") || "",
        unique: matchCount === 1,
      });
    });
    return {
      supports_upload: fileInputs.length > 0,
      file_inputs: fileInputs,
    };
  };

  window.__genbountyScanSelects = () => {
    const selectControls = [];
    const seen = new Set();

    function addControl(el, kind) {
      if (!el || el.disabled) return;
      const style = window.getComputedStyle(el);
      const visible = style.display !== "none" && style.visibility !== "hidden" && !el.hidden;
      const sel = selectorFor(el);
      if (!sel || seen.has(sel)) return;
      seen.add(sel);
      let matchCount = 0;
      try { matchCount = document.querySelectorAll(sel).length; } catch (_) {}
      selectControls.push({
        selector: sel,
        kind,
        visible,
        unique: matchCount === 1,
      });
    }

    document.querySelectorAll("select:not([disabled])").forEach((el) => addControl(el, "select"));
    document.querySelectorAll('[role="combobox"]:not([disabled])').forEach((el) => addControl(el, "combobox"));
    document.querySelectorAll('button[aria-haspopup="listbox"], [aria-haspopup="listbox"], [aria-haspopup="menu"]').forEach((el) => {
      if (el.tagName && el.tagName.toLowerCase() === "select") return;
      addControl(el, "combobox");
    });

    return {
      supports_select: selectControls.length > 0,
      select_controls: selectControls,
    };
  };

  function visibleNodesForSelector(sel) {
    try {
      return [...document.querySelectorAll(sel)].filter(isVisibleElement);
    } catch (_) {
      return [];
    }
  }

  function nodeContainsOrEqual(container, el) {
    if (!container || !el) return false;
    return container === el || (typeof container.contains === "function" && container.contains(el));
  }

  function visibleIndexOf(nodes, el) {
    for (let i = 0; i < nodes.length; i++) {
      if (nodeContainsOrEqual(nodes[i], el)) return i;
    }
    const clickedText = normalizedInnerText(el);
    if (clickedText) {
      for (let i = 0; i < nodes.length; i++) {
        if (normalizedInnerText(nodes[i]) === clickedText) return i;
      }
    }
    return -1;
  }

  function messageRoleForNode(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return "";
    const row = el.closest(
      '[data-message-author-role], [data-testid*="message"], [data-testid*="Message"], article, [class*="messageItem"], [class*="MessageItem"], [class*="message-item"], [class*="chat-message"]'
    );
    if (!row) return "";
    const role = row.getAttribute("data-message-author-role");
    if (role) return role.toLowerCase();
    const tid = row.getAttribute("data-testid") || "";
    if (/assistant|bot|ai/i.test(tid)) return "assistant";
    if (/user|human|self|prompt/i.test(tid)) return "user";
    const cls = String(row.className || "");
    if (/assistant|bot|ai-/i.test(cls)) return "assistant";
    if (/user|human|self|prompt/i.test(cls)) return "user";
    return "";
  }

  function isAlternatingRoles(roles) {
    let last = "";
    for (const raw of roles) {
      const r = (raw || "").toLowerCase();
      if (r !== "user" && r !== "assistant") continue;
      if (last && r === last) return false;
      last = r;
    }
    return last !== "";
  }

  function isPositionalSelector(sel) {
    return /:nth-of-type\(|:nth-child\(/.test(sel || "");
  }

  function findRepeatingMessageRowSelector(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return null;

    const roleRow = el.closest("[data-message-author-role]");
    if (roleRow) {
      try {
        if (visibleMatchCount("[data-message-author-role]") >= 2) {
          return {
            list_selector: "[data-message-author-role]",
            role_selector: '[data-message-author-role="assistant"]',
            mode: "role",
          };
        }
      } catch (_) {}
    }

    let cur = el;
    for (let depth = 0; depth < 12 && cur && cur.parentElement; depth++) {
      const tag = cur.tagName.toLowerCase();
      const parent = cur.parentElement;
      const visibleSameTag = [...parent.children].filter(
        (c) => c.tagName === cur.tagName && isVisibleElement(c)
      );
      if (visibleSameTag.length >= 2) {
        if (cur.classList && cur.classList.length) {
          for (const cls of cur.classList) {
            const prefix = cssModulePrefix(cls);
            if (prefix.length >= 4) {
              const sel = `${tag}[class*='${prefix}']`;
              try {
                if (visibleMatchCount(sel) >= 2) return { list_selector: sel };
              } catch (_) {}
            }
            if (isStableClassName(cls)) {
              const sel = `${tag}.${cssEscape(cls)}`;
              try {
                if (visibleMatchCount(sel) >= 2) return { list_selector: sel };
              } catch (_) {}
            }
          }
        }
        const grand = parent.parentElement;
        if (grand) {
          const parentTag = parent.tagName.toLowerCase();
          const rowPeers = [...grand.children].filter(
            (c) => c.tagName === parent.tagName && isVisibleElement(c)
          );
          if (rowPeers.length >= 2 && parent.classList && parent.classList.length) {
            for (const cls of parent.classList) {
              const prefix = cssModulePrefix(cls);
              if (prefix.length >= 4) {
                const sel = `${parentTag}[class*='${prefix}']`;
                try {
                  if (visibleMatchCount(sel) >= 2) return { list_selector: sel };
                } catch (_) {}
              }
            }
          }
        }
      }
      cur = parent;
    }
    return null;
  }

  function buildGeneralizedListSelector(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return "";
    const tag = el.tagName.toLowerCase();

    if (el.classList && el.classList.length) {
      for (const cls of el.classList) {
        const prefix = cssModulePrefix(cls);
        if (prefix.length >= 4) {
          const sel = `${tag}[class*='${prefix}']`;
          try {
            if (visibleMatchCount(sel) >= 2) return sel;
          } catch (_) {}
        }
        if (isStableClassName(cls)) {
          const sel = `${tag}.${cssEscape(cls)}`;
          try {
            if (visibleMatchCount(sel) >= 2) return sel;
          } catch (_) {}
        }
      }
    }

    for (const attr of ["data-testid", "data-message-author-role", "role"]) {
      const value = el.getAttribute(attr);
      if (!value) continue;
      if (attr === "data-testid") {
        const base = value.replace(/[-_.]?(user|assistant|human|bot|ai)[-_.]?\\d*$/i, "");
        if (base.length >= 4 && base !== value) {
          const sel = `${tag}[data-testid*='${quoteAttr(base.slice(0, Math.min(base.length, 24)))}']`;
          try {
            if (visibleMatchCount(sel) >= 2) return sel;
          } catch (_) {}
        }
      }
      const sel = `${tag}[${attr}="${quoteAttr(value)}"]`;
      try {
        if (visibleMatchCount(sel) >= 2) return sel;
      } catch (_) {}
    }

    const repeatingEarly = findRepeatingMessageRowSelector(el);
    if (repeatingEarly && repeatingEarly.list_selector) return repeatingEarly.list_selector;

    const scoped = selectorFor(el);
    try {
      if (scoped && !isPositionalSelector(scoped) && visibleMatchCount(scoped) >= 2) return scoped;
    } catch (_) {}
    if (scoped && isPositionalSelector(scoped)) {
      const repeating = findRepeatingMessageRowSelector(el);
      if (repeating && repeating.list_selector) return repeating.list_selector;
      return "";
    }
    return scoped || "";
  }

  function buildAssistantRoleSelector(el) {
    const roleRow = el.closest('[data-message-author-role="assistant"]');
    if (roleRow) return '[data-message-author-role="assistant"]';
    const roleUser = el.closest('[data-message-author-role="user"]');
    if (roleUser) return "";

    const assistantRow = el.closest(
      '[data-testid*="assistant"], [data-testid*="Assistant"], [class*="assistant"], [class*="Assistant"], [aria-label*="assistant"], [aria-label*="Assistant"]'
    );
    if (assistantRow && assistantRow !== el) {
      const sel = selectorFor(assistantRow);
      if (sel) {
        try {
          if (document.querySelectorAll(sel).length >= 1) return sel;
        } catch (_) {}
      }
    }
    return "";
  }

  window.__genbountyAnalyzeResponseCapture = function(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return { mode: "last" };

    const repeating = findRepeatingMessageRowSelector(el);
    if (repeating && repeating.mode === "role" && repeating.role_selector) {
      return {
        mode: "role",
        role_selector: repeating.role_selector,
        list_selector: repeating.list_selector || "",
      };
    }

    const roleSel = buildAssistantRoleSelector(el);
    let listSel = buildGeneralizedListSelector(el);
    if ((!listSel || isPositionalSelector(listSel)) && repeating && repeating.list_selector) {
      listSel = repeating.list_selector;
    }
    if (listSel && isPositionalSelector(listSel)) {
      const vis = visibleNodesForSelector(listSel);
      if (vis.length < 2) listSel = "";
    }
    const clickedRole = messageRoleForNode(el);

    if (roleSel && (clickedRole === "assistant" || clickedRole === "")) {
      return {
        mode: "role",
        role_selector: roleSel,
        list_selector: listSel || "",
      };
    }

    if (listSel) {
      const visible = visibleNodesForSelector(listSel);
      const idx = visibleIndexOf(visible, el);
      if (visible.length >= 2 && idx >= 0) {
        const roles = visible.map(messageRoleForNode);
        const alternating = isAlternatingRoles(roles);
        // Parity only when user/assistant rows share one list (e.g. [data-message-author-role]).
        // Assistant-only lists (.bot-message) need "last" - parity would stick on the greeting.
        if (alternating) {
          const parity = idx % 2;
          return {
            mode: parity === 1 ? "parity_odd" : "parity_even",
            list_selector: listSel,
            parity_basis: "roles",
          };
        }
      }
      return { mode: "last", list_selector: listSel || "" };
    }

    return { mode: "last", list_selector: listSel || "" };
  };

  window.__genbountyComposerHtmlFromSelector = function(sel, steps) {
    if (!sel) return "";
    let el = null;
    try {
      const nodes = [...document.querySelectorAll(sel)].filter(isVisibleElement);
      if (nodes.length) el = nodes[nodes.length - 1];
      else el = document.querySelector(sel);
    } catch (_) {
      el = null;
    }
    if (!el) return "";
    return ancestorContextHtml(el, Math.max(1, steps || 8));
  };

  /* GUIDED_MODAL_HOOK */
})();
"""

def _resolved_manual_discovery_script() -> str:
    from browser_bot.discovery_ui_bridge import _GUIDED_DISCOVERY_MODAL_SCRIPT

    hook = (
        f"window.__genbountyShowGuidedModal = {_GUIDED_DISCOVERY_MODAL_SCRIPT.strip()};\n"
        "  function showGuidedDiscoveryModal(mode) {\n"
        "    if (window.__genbountyShowGuidedModal) window.__genbountyShowGuidedModal(mode);\n"
        "  }"
    )
    return _MANUAL_DISCOVERY_SCRIPT.replace("/* GUIDED_MODAL_HOOK */", hook)

_V2_DISCOVERY_INIT_SCRIPT = "() => { window.__genbountyManualDiscoverV2 = true; }"

# Lightweight scan helpers for guided (UI-only) discovery - no in-page panel JS.
_DISCOVERY_SCAN_ONLY_SCRIPT = r"""
(() => {
  if (window.__genbountyScanUploads && window.__genbountyScanSelects) return;

  function cssEscape(value) {
    if (window.CSS && typeof window.CSS.escape === "function") return window.CSS.escape(value);
    return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
  }

  function quoteAttr(value) {
    return String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  }

  function normalizedInnerText(elem) {
    if (!elem || elem.innerText == null) return "";
    return elem.innerText.replace(/\s+/g, " ").trim();
  }

  function isUniqueSelector(selector, el) {
    try {
      const nodes = document.querySelectorAll(selector);
      return nodes.length === 1 && nodes[0] === el;
    } catch (_) {
      return false;
    }
  }

  function visibleMatchCount(selector) {
    try {
      return [...document.querySelectorAll(selector)].filter((el) => {
        const style = window.getComputedStyle(el);
        return style.display !== "none" && style.visibility !== "hidden" && !el.hidden;
      }).length;
    } catch (_) {
      return 0;
    }
  }

  function selectorFor(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return "";
    if (el.id) return `#${cssEscape(el.id)}`;

    const tag = el.tagName.toLowerCase();
    const stableAttrs = [
      "data-testid", "data-test", "data-cy", "data-message-author-role",
      "aria-label", "name", "role", "placeholder", "contenteditable", "type", "accept",
    ];
    for (const attr of stableAttrs) {
      const value = el.getAttribute(attr);
      if (value) {
        if (attr === "type" && String(value).toLowerCase() === "button") continue;
        const selector = `${tag}[${attr}="${quoteAttr(value)}"]`;
        try {
          if (isUniqueSelector(selector, el)) return selector;
        } catch (_) {}
      }
    }

    if (tag === "textarea" || tag === "input") {
      const placeholder = (el.getAttribute("placeholder") || "").trim();
      if (placeholder.length >= 8) {
        const prefix = placeholder.slice(0, Math.min(32, placeholder.length)).trim();
        if (prefix.length >= 8) {
          const sel = `${tag}[placeholder^="${quoteAttr(prefix)}"]`;
          try {
            if (document.querySelectorAll(sel).length === 1) return sel;
          } catch (_) {}
        }
      }
    }

    if (el.classList && el.classList.length) {
      const classes = Array.from(el.classList)
        .filter((cls) => cls && !cls.startsWith("__genbounty_") && !/^[a-z]{1,2}$/.test(cls))
        .slice(0, 3);
      if (classes.length) {
        const selector = `${tag}.${classes.map(cssEscape).join(".")}`;
        try {
          if (document.querySelectorAll(selector).length === 1) return selector;
        } catch (_) {}
      }
    }

    if (tag === "button" || el.getAttribute("role") === "button") {
      const label = normalizedInnerText(el);
      if (label.length >= 4 && label.length <= 240) {
        const lit = JSON.stringify(label);
        const hits = [...document.querySelectorAll("button")].filter(
          (node) => normalizedInnerText(node) === label.replace(/\s+/g, " ").trim()
        );
        if (hits.length === 1 && hits[0] === el) return `button:has-text(${lit})`;
      }
      if (el.getAttribute("type") === "submit") {
        try {
          if (visibleMatchCount("button[type='submit']") === 1) return "button[type='submit']";
        } catch (_) {}
      }
    }

    return tag;
  }

  window.__genbountyScanUploads = () => {
    const fileInputs = [];
    document.querySelectorAll('input[type="file"]').forEach((el) => {
      if (!el || el.disabled) return;
      const style = window.getComputedStyle(el);
      const visible = style.display !== "none" && style.visibility !== "hidden" && !el.hidden;
      const sel = selectorFor(el);
      if (!sel) return;
      let matchCount = 0;
      try { matchCount = document.querySelectorAll(sel).length; } catch (_) {}
      fileInputs.push({
        selector: sel,
        visible,
        accept: el.getAttribute("accept") || "",
        unique: matchCount === 1,
      });
    });
    return {
      supports_upload: fileInputs.length > 0,
      file_inputs: fileInputs,
    };
  };

  window.__genbountyScanSelects = () => {
    const selectControls = [];
    const seen = new Set();

    function addControl(el, kind) {
      if (!el || el.disabled) return;
      const style = window.getComputedStyle(el);
      const visible = style.display !== "none" && style.visibility !== "hidden" && !el.hidden;
      const sel = selectorFor(el);
      if (!sel || seen.has(sel)) return;
      seen.add(sel);
      let matchCount = 0;
      try { matchCount = document.querySelectorAll(sel).length; } catch (_) {}
      selectControls.push({
        selector: sel,
        kind,
        visible,
        unique: matchCount === 1,
      });
    }

    document.querySelectorAll("select:not([disabled])").forEach((el) => addControl(el, "select"));
    document.querySelectorAll('[role="combobox"]:not([disabled])').forEach((el) => addControl(el, "combobox"));
    document.querySelectorAll(
      'button[aria-haspopup="listbox"], [aria-haspopup="listbox"], [aria-haspopup="menu"]'
    ).forEach((el) => {
      if (el.tagName && el.tagName.toLowerCase() === "select") return;
      addControl(el, "combobox");
    });

    return {
      supports_select: selectControls.length > 0,
      select_controls: selectControls,
    };
  };
})();
"""

DISCOVERY_MULTITURN_PROBE_TEXT = "capital of France"
DISCOVERY_MULTITURN_PROBE_MANUAL_AFTER_S = 20
DISCOVERY_VERIFY_PROBE_TEXT = "2+2"
DISCOVERY_RESPONSE_REPAIR_MAX = 2
DISCOVERY_VERIFY_RESPONSE_WAIT_MS = 15000
RESPONSE_OVERBROAD_VISIBLE_THRESHOLD = 12

_OVERBROAD_RESPONSE_LIST_RE = re.compile(
    r"^(div|span|section|article|main|header|footer)\."
    r"(flex|grid|block|inline-flex|inline-grid|relative|absolute|fixed|sticky|hidden)$",
    re.I,
)


def _is_overbroad_response_list_selector(selector: str) -> bool:
    return bool(_OVERBROAD_RESPONSE_LIST_RE.match((selector or "").strip()))


async def _visible_locator_count(page, selector: str, *, cap: int = 50) -> int:
    try:
        loc = page.locator(selector)
        total = await loc.count()
        visible = 0
        for i in range(min(total, cap)):
            try:
                if await loc.nth(i).is_visible():
                    visible += 1
            except Exception:
                continue
        return visible
    except Exception:
        return 0


async def _discovery_probe_response_capture(
    page,
    submission: dict,
    *,
    probe_text: str = DISCOVERY_VERIFY_PROBE_TEXT,
    reload: bool = True,
    after_reload=None,
    site: str = "",
    component: str = "",
) -> tuple[bool, str, str]:
    """Submit a probe prompt and return (captured, response_text, detail)."""
    from browser_bot.discovery_ui_bridge import UiDiscoveryRestartRequested, run_with_ui_fallback_watch
    from browser_bot.submit.common import _do_one_submit_step, inputs_for_submission
    from browser_bot.submit.response_filters import (
        filter_context_from_submission,
        is_actionable_response,
        non_actionable_reason,
    )

    inputs = inputs_for_submission(submission.get("inputs") or [])
    submit_sel = (submission.get("submit_selector") or "").strip()
    response_sel = (submission.get("response_selector") or "").strip()
    if not inputs:
        return False, "", "no prompt inputs configured"
    if not submit_sel:
        return False, "", "submit_selector not set"
    if not response_sel:
        return False, "", "response_selector not set"

    start_url = (submission.get("start_url") or "").strip()
    if reload and start_url:
        try:
            await page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(0.35)
            if after_reload:
                try:
                    await after_reload()
                except Exception:
                    pass
        except Exception as exc:
            return False, "", f"could not reload start_url: {exc}"

    upgraded = await upgrade_response_capture_kwargs(page, submission)
    # Discovery verification is text-only and only needs enough time to decide
    # whether selectors are usable. Components with uploads often set
    # response_wait_ms=60000 for real test runs; using that here makes guided
    # discovery look stuck before the LLM self-heal path gets a chance to run.
    wait_ms = min(
        max(int(submission.get("response_wait_ms") or 8000), 15000),
        DISCOVERY_VERIFY_RESPONSE_WAIT_MS,
    )
    filter_ctx = filter_context_from_submission(submission, probe_text, site=site, component=component)

    try:
        _text, response_out, _full, submit_meta = await run_with_ui_fallback_watch(
            page,
            asyncio.wait_for(
            _do_one_submit_step(
                page,
                inputs,
                submit_sel,
                probe_text,
                response_selector=upgraded.get("response_selector") or response_sel,
                response_within_selector=str(submission.get("response_within_selector") or ""),
                response_text_within_selector=str(
                    submission.get("response_text_within_selector") or ""
                ),
                response_capture_mode=upgraded.get("response_capture_mode") or "last",
                response_list_selector=upgraded.get("response_list_selector") or "",
                response_role_selector=upgraded.get("response_role_selector") or "",
                submit_via=str(submission.get("submit_via") or "click"),
                response_wait_ms=wait_ms,
                submission=submission,
                filter_ctx=filter_ctx,
                site=site,
                component=component,
            ),
            timeout=(wait_ms / 1000.0) + max((wait_ms * 0.75) / 1000.0, 6) + 8,
            ),
        )
    except asyncio.TimeoutError:
        return False, "", (
            f"verification timed out after {wait_ms // 1000}s waiting for response selector; "
            "running selector repair"
        )
    except UiDiscoveryRestartRequested:
        raise
    except Exception as exc:
        return False, "", str(exc)

    # Persist healed Send when discovery saved attach/More actions as submit.
    if isinstance(submit_meta, dict):
        healed = str(submit_meta.get("healed_submit_selector") or "").strip()
        if healed and healed != "enter" and healed != submit_sel:
            print(
                f"  [~] Healed submit_selector after probe: {submit_sel} → {healed}"
            )
            submission["submit_selector"] = healed
            if site and component:
                try:
                    _save_partial(site, component, submission)
                except Exception:
                    pass

    preview = (response_out or "").strip()
    if preview:
        if not is_actionable_response(preview, filter_ctx):
            reason = non_actionable_reason(preview, filter_ctx) or "non_actionable"
            short = preview[:120] + ("…" if len(preview) > 120 else "")
            return False, preview, f"non-actionable ({reason}): {short!r}"
        short = preview[:120] + ("…" if len(preview) > 120 else "")
        return True, preview, f"captured {len(preview)} chars: {short!r}"
    return False, "", "no response text captured with current selectors"


def _llm_repair_response_capture(
    html: str,
    page_url: str,
    submission: dict,
    *,
    original_pick: str = "",
    captured_text: str = "",
    failure_detail: str = "",
    visible_match_count: int | None = None,
) -> dict:
    """Ask the grounding LLM to fix response capture selectors after a failed probe."""
    sub = submission or {}
    cleaned = _clean_html_for_llm(html)
    context = {
        "page_url": page_url,
        "probe_prompt": DISCOVERY_VERIFY_PROBE_TEXT,
        "failure": failure_detail,
        "captured_text_from_selectors": captured_text or "",
        "original_user_pick": original_pick or "",
        "current_response_selector": sub.get("response_selector") or "",
        "response_capture_mode": sub.get("response_capture_mode") or "last",
        "response_list_selector": sub.get("response_list_selector") or "",
        "response_role_selector": sub.get("response_role_selector") or "",
        "visible_nodes_current_selector": visible_match_count,
        "prompt_input_selectors": [
            i.get("selector") for i in (sub.get("inputs") or []) if isinstance(i, dict)
        ],
    }

    prompt = f"""A browser automation probe submitted a test prompt but FAILED to read the assistant reply.

Context (JSON):
{json.dumps(context, indent=2)[:8000]}

HTML after probe (assistant reply should be visible):
{cleaned[:100000]}

Return ONLY valid JSON:
{{
  "response_selector": "css-selector",
  "response_capture_mode": "last|role|parity_odd|parity_even",
  "response_list_selector": "optional repeating row selector or empty string",
  "response_role_selector": "optional when mode is role, else empty",
  "reasoning": "one sentence"
}}

Rules:
- response_selector MUST match the element whose inner text IS the latest assistant/model reply.
- Prefer semantic classes (#id, .answer, [data-testid], role markers) over layout utilities.
- NEVER use Tailwind layout utilities alone (div.flex, div.grid, span.block) - they match chrome, not replies.
- If the user's original pick (original_user_pick) is visible in HTML and holds reply text, prefer it over current_response_selector.
- Use response_list_selector only for true repeating message rows (user/assistant alternating in ONE list).
- For assistant-only lists (.answer, .bot-message), use mode last and omit list/role selectors unless HTML shows a shared list attribute.
- Do not return prompt input, submit button, or empty containers.
"""
    raw = _discovery_complete(prompt, role="grounding_judge", json_mode=True)
    if not raw:
        return {}
    try:
        data = _parse_json_response(raw)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        print(f"  [!] Response capture repair parse error: {exc}")
        return {}


def _apply_response_capture_repair(submission: dict, repair: dict) -> list[str]:
    """Apply LLM-suggested response capture fields to submission. Returns log lines."""
    lines: list[str] = []
    if not isinstance(repair, dict):
        return lines

    sel = sanitize_discovered_selector(str(repair.get("response_selector") or "").strip())
    if not sel:
        return lines

    submission["response_selector"] = sel
    lines.append(f"    response_selector: {sel}")

    mode = str(repair.get("response_capture_mode") or "last").strip().lower()
    list_sel = sanitize_discovered_selector(str(repair.get("response_list_selector") or "").strip())
    role_sel = sanitize_discovered_selector(str(repair.get("response_role_selector") or "").strip())

    if list_sel and _is_overbroad_response_list_selector(list_sel):
        list_sel = ""
    if list_sel and is_fragile_positional_selector(list_sel):
        list_sel = ""

    if mode in ("role", "parity_odd", "parity_even") and list_sel:
        submission["response_capture_mode"] = mode
        submission["response_list_selector"] = list_sel
        lines.append(f"    response_capture_mode: {mode}")
        lines.append(f"    response_list_selector: {list_sel}")
        if role_sel and mode == "role":
            submission["response_role_selector"] = role_sel
            lines.append(f"    response_role_selector: {role_sel}")
        else:
            submission.pop("response_role_selector", None)
    else:
        submission.pop("response_capture_mode", None)
        submission.pop("response_list_selector", None)
        submission.pop("response_role_selector", None)

    reasoning = str(repair.get("reasoning") or "").strip()
    if reasoning:
        lines.append(f"    repair reasoning: {reasoning[:200]}")
    return lines


async def _discovery_verify_and_repair_response_capture(
    page,
    submission: dict,
    *,
    original_pick: str = "",
    site: str = "",
    component: str = "",
    interactive: bool = True,
) -> bool:
    """
    End-of-discovery probe: submit test prompt, capture response text.
    On failure, LLM-diagnose and retry with repaired selectors (same browser session).
    """
    panel_title = "Final verification"
    total_attempts = 1 + DISCOVERY_RESPONSE_REPAIR_MAX
    response_sel = (submission.get("response_selector") or "").strip()
    verify_intro = (
        "Final check - sit tight\n\n"
        f"We’ll reload, send {DISCOVERY_VERIFY_PROBE_TEXT!r}, and read the reply.\n"
        f"Response selector:\n{response_sel or '(not set)'}\n\n"
        "Don’t click the page. Click Continue when this finishes."
    )

    if interactive:
        await _manual_panel_show(
            page,
            verify_intro,
            mode="busy",
            title=panel_title,
            pick_hint="Starting sample request…",
        )
    print("\n" + "─" * 50)
    print("  Verifying response capture (post-discovery sample request)...")
    if interactive:
        print("  Browser opened for automatic verification - no action needed during the test.")
    print("─" * 50)

    pick = (original_pick or "").strip()
    for attempt in range(total_attempts):
        attempt_no = attempt + 1
        if interactive:
            await _manual_panel_show(
                page,
                f"Checking ({attempt_no}/{total_attempts})\n\n"
                f"Sending {DISCOVERY_VERIFY_PROBE_TEXT!r}…\n"
                f"Response: {submission.get('response_selector') or '(not set)'}\n\n"
                "Don’t click the page.",
                mode="busy",
                title=panel_title,
                pick_hint="Running - don’t click the page.",
            )

        async def _after_reload():
            if not interactive:
                return
            await _manual_panel_show(
                page,
                f"Checking ({attempt_no}/{total_attempts})\n\n"
                f"Page reloaded - submitting {DISCOVERY_VERIFY_PROBE_TEXT!r}…",
                mode="busy",
                title=panel_title,
                pick_hint="Running - don’t click the page.",
            )

        verify_heartbeat = asyncio.create_task(
            _guided_busy_heartbeat(
                page,
                title=panel_title,
                message=(
                    f"Checking ({attempt_no}/{total_attempts})\n\n"
                    f"Sending {DISCOVERY_VERIFY_PROBE_TEXT!r} and waiting for a reply…"
                ),
                pick_hint="Sit tight - no action needed.",
            )
        )
        try:
            ok, text, detail = await _discovery_probe_response_capture(
                page,
                submission,
                reload=True,
                after_reload=_after_reload if interactive else None,
                site=site,
                component=component,
            )
        finally:
            verify_heartbeat.cancel()
            try:
                await verify_heartbeat
            except asyncio.CancelledError:
                pass
        if ok:
            print(f"  ✓ Response capture verified - {detail}")
            if interactive:
                await _manual_panel_show(
                    page,
                    "Check passed\n\n"
                    f"Prompt: {DISCOVERY_VERIFY_PROBE_TEXT!r}\n"
                    f"Reply ({len(text)} chars):\n"
                    f"{text[:200]}{'…' if len(text) > 200 else ''}\n\n"
                    f"response_selector: {submission.get('response_selector')}\n\n"
                    "Continue to finish.",
                    mode="idle",
                    title=panel_title,
                    action="Continue",
                    pick_hint="Verified - Continue.",
                )
                await _manual_panel_event(
                    page,
                    "Check passed. Discovery complete.",
                    mode="idle",
                    action="Continue",
                )
                await _manual_panel_clear_persisted(page)
            return True

        print(f"  ✗ Response capture failed (attempt {attempt_no}): {detail}")
        if attempt >= DISCOVERY_RESPONSE_REPAIR_MAX:
            break

        response_sel = (submission.get("response_selector") or "").strip()
        visible_count = await _visible_locator_count(page, response_sel) if response_sel else 0
        if visible_count > RESPONSE_OVERBROAD_VISIBLE_THRESHOLD:
            detail = (
                f"{detail}; {response_sel!r} matches {visible_count}+ visible nodes "
                "(likely layout chrome, not the reply bubble)"
            )

        if interactive:
            await _manual_panel_show(
                page,
                f"Check failed ({attempt_no}/{total_attempts})\n\n"
                f"{detail}\n\n"
                "Finding a better response selector…",
                mode="busy",
                title=panel_title,
                pick_hint="Repairing - sit tight.",
            )
        try:
            html = await page.content()
        except Exception:
            html = ""

        repair_heartbeat = asyncio.create_task(
            _guided_busy_heartbeat(
                page,
                title=panel_title,
                message=(
                    "Repairing selectors\n\n"
                    "Looking for a better response selector on this page…"
                ),
                pick_hint="Repairing - sit tight.",
            )
        )
        try:
            repair = _llm_repair_response_capture(
                html,
                page.url,
                submission,
                original_pick=pick,
                captured_text=text,
                failure_detail=detail,
                visible_match_count=visible_count or None,
            )
        finally:
            repair_heartbeat.cancel()
            try:
                await repair_heartbeat
            except asyncio.CancelledError:
                pass
        new_sel = sanitize_discovered_selector(
            str(repair.get("response_selector") or "").strip()
        )
        if not new_sel:
            print("  [!] Response capture repair: LLM returned no selector.")
            break
        ok_sel, reason, _ = await _validate_context_selector_for_step(
            page, new_sel, "response"
        )
        if not ok_sel or not await _verify_selector_on_page(page, new_sel):
            print(
                f"  [!] Response capture repair rejected {new_sel!r}: "
                f"{reason or 'not visible'}"
            )
            if interactive:
                await _manual_panel_show(
                    page,
                    f"Repair attempt rejected\n\n"
                    f"Suggested selector {new_sel!r} was not usable "
                    f"({reason or 'not visible on page'}).\n\n"
                    "Trying another repair…",
                    mode="busy",
                    title=panel_title,
                    pick_hint="Retrying repair…",
                )
            continue

        repair_lines = _apply_response_capture_repair(submission, repair)
        for line in repair_lines:
            print(f"  [repair] {line.strip()}")
        if site and component:
            _save_partial(site, component, submission)

        reasoning = str(repair.get("reasoning") or "").strip()
        if interactive:
            await _manual_panel_show(
                page,
                "Selector updated - retrying\n\n"
                f"New response_selector:\n{submission.get('response_selector')}\n\n"
                + (f"Reason: {reasoning}\n\n" if reasoning else "")
                + f"Sending {DISCOVERY_VERIFY_PROBE_TEXT!r} again…",
                mode="busy",
                title=panel_title,
                pick_hint="Retrying…",
            )

    print(
        "  [!] Response capture verification failed after repair attempts. "
        "Edit response_selector in config.yaml or re-run discovery."
    )
    if interactive:
        await _manual_panel_show(
            page,
            "Could not verify the reply\n\n"
            f"Tried {total_attempts} time(s) including auto-repair.\n\n"
            "Fix response_selector in Settings → Manual entry, then Send Sample Request.",
            mode="idle",
            title=panel_title,
            action="Continue",
            pick_hint="Verification failed - edit selector if needed.",
        )
        await _manual_panel_event(
            page,
            "Verification failed - edit response_selector if needed.",
            mode="idle",
            action="Continue",
        )
        await _manual_panel_clear_persisted(page)
    return False


async def _capture_composer_html_from_selector(
    page, selector: str, *, levels: int = 8
) -> str:
    """Capture ancestor HTML around the latest visible match for a response selector."""
    sel = (selector or "").strip()
    if not sel:
        return ""
    await _ensure_response_capture_analyze(page)
    try:
        html = await page.evaluate(
            """([s, steps]) => {
              if (typeof window.__genbountyComposerHtmlFromSelector === 'function') {
                return window.__genbountyComposerHtmlFromSelector(s, steps) || '';
              }
              const el = document.querySelector(s);
              if (!el) return '';
              let cur = el;
              for (let i = 0; i < steps && cur && cur.parentElement; i++) {
                cur = cur.parentElement;
              }
              return cur && cur.outerHTML ? cur.outerHTML : '';
            }""",
            [sel, levels],
        )
        return html if isinstance(html, str) else ""
    except Exception:
        return ""


async def _discovery_multiturn_manual_pick(
    page,
    submission: dict,
    probe_response_sel: str,
    lines: list[str],
) -> tuple[bool, str, list[str]]:
    """User clicks the second assistant reply after automatic multi-turn detection timed out."""
    v2 = _page_uses_v2_discovery(page)
    lines.append("  [~] Multi-turn probe: switching to manual reply selection.")
    pick_event = await _manual_pick_selector(
        page,
        "Multi-turn probe is taking longer than expected.\n\n"
        f"Click on the second assistant reply (the answer to {DISCOVERY_MULTITURN_PROBE_TEXT!r}), "
        "not your prompt.",
        step_title="Multi-turn probe - select reply manually",
        v2=v2,
        context_target="response",
        pick_kind="response" if v2 else None,
    )
    wide_html = (pick_event.get("wideContextHtml") or "").strip()
    if not wide_html:
        pick_sel = (pick_event.get("selector") or probe_response_sel).strip()
        wide_html = await _capture_composer_html_from_selector(page, pick_sel, levels=8)
    if not wide_html.strip():
        lines.append("  [~] Multi-turn manual pick: could not capture composer HTML.")
        return False, "", lines
    pick_sel = (pick_event.get("selector") or "").strip()
    if pick_sel:
        lines.append(f"  [+] Multi-turn manual pick selector: {pick_sel}")
    lines.append(f"  [+] Multi-turn composer HTML (manual): {len(wide_html):,} chars")
    return True, wide_html, lines


async def _discovery_multiturn_response_probe(
    page,
    submission: dict,
) -> tuple[bool, str, list[str]]:
    """
    After the user picks a response container, send a second probe prompt so the
    composer DOM contains multiple user/assistant turns for list/parity analysis.
    """
    from browser_bot.discovery_ui_bridge import UiDiscoveryRestartRequested, run_with_ui_fallback_watch
    from browser_bot.submit.common import _do_one_submit_step, inputs_for_submission

    lines: list[str] = []
    inputs = inputs_for_submission(submission.get("inputs") or [])
    submit_sel = (submission.get("submit_selector") or "").strip()
    response_sel = (submission.get("response_selector") or "").strip()
    if not inputs or not submit_sel or not response_sel:
        lines.append("  [~] Multi-turn probe skipped: inputs, submit, or response not set.")
        return False, "", lines

    upgraded = await upgrade_response_capture_kwargs(page, submission)
    probe_response_sel = upgraded.get("response_selector") or response_sel
    wait_ms = max(int(submission.get("response_wait_ms") or 8000), 15000)

    await _manual_panel_show(
        page,
        "Multi-turn probe\n\n"
        f"Waiting for the chat to free up, then sending {DISCOVERY_MULTITURN_PROBE_TEXT!r}…",
        mode="busy",
        pick_hint="Waiting for chat…",
    )
    print(f"  [~] Multi-turn probe: waiting for composer idle, then sending {DISCOVERY_MULTITURN_PROBE_TEXT!r}…")

    from browser_bot.submit.common import wait_for_composer_idle_before_submit

    idle_ok = await wait_for_composer_idle_before_submit(
        page,
        submit_selector=submit_sel,
        inputs=inputs,
        response_selector=probe_response_sel,
        response_within_selector=str(submission.get("response_within_selector") or ""),
        response_text_within_selector=str(submission.get("response_text_within_selector") or ""),
        response_capture_mode=upgraded.get("response_capture_mode") or "last",
        response_list_selector=upgraded.get("response_list_selector") or "",
        response_role_selector=upgraded.get("response_role_selector") or "",
        timeout_ms=max(wait_ms, 120_000),
    )
    if not idle_ok:
        lines.append(
            "  [~] Multi-turn probe: timed out waiting for the previous reply to finish "
            "(send button stayed disabled)."
        )
        return False, "", lines

    await _manual_panel_show(
        page,
        "Multi-turn probe\n\n"
        f"Sending {DISCOVERY_MULTITURN_PROBE_TEXT!r}…",
        mode="busy",
        pick_hint="Waiting for the second reply…",
    )

    progress_msg = (
        "Multi-turn probe\n\n"
        f"Sent {DISCOVERY_MULTITURN_PROBE_TEXT!r} - waiting for the second reply…"
    )
    heartbeat = asyncio.create_task(
        _guided_busy_heartbeat(
            page,
            title="Multi-turn probe",
            message=progress_msg,
            pick_hint="Waiting for reply…",
        )
    )

    manual_after_s = max(5, int(DISCOVERY_MULTITURN_PROBE_MANUAL_AFTER_S))

    async def _wait_for_manual_select() -> str:
        from browser_bot.discovery_ui_bridge import _wait_for_panel_response, resolve_discovery_page

        await asyncio.sleep(manual_after_s)
        heartbeat.cancel()
        try:
            await heartbeat
        except asyncio.CancelledError:
            pass
        offer_msg = (
            f"{progress_msg}\n\nStill waiting ({manual_after_s}s).\n"
            "Select manually to click the reply yourself, or keep waiting."
        )
        await _manual_panel_show(
            page,
            offer_msg,
            mode="idle",
            action="Select manually",
            step_title="Multi-turn probe",
            pick_hint="Still detecting in the background…",
        )
        poll_page = resolve_discovery_page(page)
        while True:
            event = await _wait_for_panel_response(poll_page, timeout=0.25)
            if event and event.get("type") == "continue":
                return "manual"
            await asyncio.sleep(0)

    submit_task = asyncio.create_task(
        run_with_ui_fallback_watch(
            page,
            _do_one_submit_step(
                page,
                inputs,
                submit_sel,
                DISCOVERY_MULTITURN_PROBE_TEXT,
                response_selector=probe_response_sel,
                response_within_selector=str(submission.get("response_within_selector") or ""),
                response_text_within_selector=str(
                    submission.get("response_text_within_selector") or ""
                ),
                response_capture_mode=upgraded.get("response_capture_mode") or "last",
                response_list_selector=upgraded.get("response_list_selector") or "",
                response_role_selector=upgraded.get("response_role_selector") or "",
                submit_via=str(submission.get("submit_via") or "click"),
                response_wait_ms=wait_ms,
                submission=submission,
                composer_idle_timeout_ms=max(wait_ms, 120_000),
            ),
        )
    )
    manual_task = asyncio.create_task(_wait_for_manual_select())

    try:
        done, _pending = await asyncio.wait(
            {submit_task, manual_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if manual_task in done and manual_task.result() == "manual":
            if not submit_task.done():
                submit_task.cancel()
                try:
                    await submit_task
                except (asyncio.CancelledError, Exception):
                    pass
            return await _discovery_multiturn_manual_pick(
                page, submission, probe_response_sel, lines
            )

        manual_task.cancel()
        try:
            await manual_task
        except asyncio.CancelledError:
            pass

        _text, response_out, _full, *_ = await submit_task
    except UiDiscoveryRestartRequested:
        raise
    except Exception as exc:
        lines.append(f"  [~] Multi-turn probe failed: {exc}")
        return False, "", lines
    finally:
        if not heartbeat.done():
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass

    preview = (response_out or "").strip()
    if not preview:
        lines.append("  [~] Multi-turn probe: no new response text detected.")
        return False, "", lines

    short = preview[:120] + ("…" if len(preview) > 120 else "")
    lines.append(f"  [+] Multi-turn probe reply: {short}")

    wide_html = await _capture_composer_html_from_selector(
        page, probe_response_sel, levels=8
    )
    if not wide_html.strip():
        lines.append("  [~] Multi-turn probe: could not capture composer HTML.")
        return True, "", lines

    lines.append(f"  [+] Multi-turn composer HTML: {len(wide_html):,} chars")
    return True, wide_html, lines


async def _ask_discovery_multiturn_opt_in(page, *, step_label: str) -> bool:
    """Ask whether to run the second probe prompt for multi-turn selector analysis."""
    message = (
        f"{step_label}. Multi-turn? (optional)\n\n"
        "Send a second test prompt to learn multi-message chat layouts?\n\n"
        "Most targets: Skip."
    )
    while True:
        event = await _manual_panel_event(
            page,
            message,
            mode="idle",
            action="Run multi-turn",
            secondary_action="Skip",
        )
        if event.get("type") in ("continue", "confirm"):
            print("    multi-turn probe: enabled")
            return True
        if event.get("type") in ("retry", "skip"):
            print("    multi-turn probe: skipped (single-turn)")
            return False


def _page_uses_v2_discovery(page) -> bool:
    return bool(getattr(page, "_genbounty_v2_discovery", False))


async def _ensure_v2_discovery_mode(page) -> None:
    """Re-apply v2 click handler after navigation (init script alone is not enough on SPA hops)."""
    from browser_bot.discovery_ui_bridge import resolve_discovery_page, uses_ui_discovery

    page = resolve_discovery_page(page)
    if uses_ui_discovery(page):
        return
    if not _page_uses_v2_discovery(page):
        return
    for frame in page.frames:
        try:
            await frame.evaluate(_V2_DISCOVERY_INIT_SCRIPT)
        except Exception:
            pass
    try:
        await page.evaluate(_V2_DISCOVERY_INIT_SCRIPT)
    except Exception:
        pass


async def _install_manual_discovery_panel(page, *, v2: bool = False) -> None:
    from browser_bot.discovery_ui_bridge import resolve_discovery_page, uses_ui_discovery

    page = resolve_discovery_page(page)
    if uses_ui_discovery(page):
        return
    if v2:
        setattr(page, "_genbounty_v2_discovery", True)
    use_v2 = v2 or _page_uses_v2_discovery(page)

    await page.add_init_script(_resolved_manual_discovery_script())
    if use_v2 and not getattr(page, "_genbounty_v2_init_script_added", False):
        await page.add_init_script(_V2_DISCOVERY_INIT_SCRIPT)
        setattr(page, "_genbounty_v2_init_script_added", True)

    async def _inject(frame) -> None:
        try:
            await frame.evaluate(_resolved_manual_discovery_script())
            if use_v2:
                await frame.evaluate(_V2_DISCOVERY_INIT_SCRIPT)
        except Exception:
            pass

    for frame in page.frames:
        await _inject(frame)
    if use_v2:
        try:
            await page.evaluate(_V2_DISCOVERY_INIT_SCRIPT)
        except Exception:
            pass
    await _ensure_manual_panel_queue(page)


async def _ensure_manual_panel_queue(page) -> asyncio.Queue:
    queue = getattr(page, "_genbounty_manual_queue", None)
    if queue is None:
        queue = asyncio.Queue()
        setattr(page, "_genbounty_manual_queue", queue)

        async def _handler(_source, payload):
            data = payload or {}
            if data.get("type") == "ui_fallback":
                from browser_bot.discovery_ui_bridge import request_ui_discovery_restart

                request_ui_discovery_restart(page.context)
            await queue.put(data)

        try:
            await page.expose_binding("genbountyManualEvent", _handler)
        except Exception:
            pass
    return queue


async def _manual_panel_clear_persisted(page) -> None:
    """Drop saved panel state after discovery finishes (avoids stale panel on next visit)."""
    try:
        await page.evaluate(
            """() => {
              if (window.__genbountyManualClearStep) window.__genbountyManualClearStep();
            }"""
        )
    except Exception:
        pass


def _parse_step_label(step_label: str | None) -> tuple[int | None, int | None]:
    """Parse ``3/8`` or ``3/8. Name`` into (number, total)."""
    import re

    raw = (step_label or "").strip()
    if not raw:
        return None, None
    m = re.match(r"^(\d+)\s*/\s*(\d+)", raw)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def _panel_step_fields(
    step_label: str | None,
    step_name: str,
    do_now: str,
    *,
    tip: str = "",
    saved_lines: list[str] | None = None,
    warn: str = "",
) -> dict:
    """Structured fields for the in-browser helper (and UI discovery emit)."""
    n, total = _parse_step_label(step_label)
    name = (step_name or "").strip()
    do = (do_now or "").strip()
    # Plain-text fallback for logs / older paths that only read ``message``.
    head = f"{n}/{total}. {name}" if n is not None and total is not None else name
    parts = [head, do] if head and do else ([do] if do else [head] if head else [])
    if tip:
        parts.append(tip)
    if saved_lines:
        parts.append(
            f"Saved ({len(saved_lines)}):\n"
            + "\n".join(f"  {i + 1}. {line}" for i, line in enumerate(saved_lines))
        )
    if warn:
        parts.append(f"⚠ {warn}")
    return {
        "stepNumber": n,
        "stepTotal": total,
        "stepName": name,
        "doNow": do,
        "tip": (tip or "").strip(),
        "savedLines": [str(x).strip() for x in (saved_lines or []) if str(x).strip()],
        "warn": (warn or "").strip(),
        "message": "\n\n".join(p for p in parts if p),
        "step_title": f"Confirm step {n}/{total} - {name}" if n is not None and total is not None else name,
    }


async def _manual_panel_show(
    page,
    message: str,
    *,
    mode: str = "idle",
    action: str = "Continue",
    secondary_action: str | None = None,
    allow_action: bool = False,
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
    """Update the in-page panel without waiting for a click."""
    from browser_bot.discovery_ui_bridge import (
        check_ui_discovery_restart,
        resolve_discovery_page,
        ui_panel_show,
        uses_ui_discovery,
    )

    page = resolve_discovery_page(page)
    check_ui_discovery_restart(page.context)
    if uses_ui_discovery(page):
        await ui_panel_show(
            page,
            message,
            mode=mode,
            action=action,
            secondary_action=secondary_action,
            pick_hint=pick_hint,
            pick_kind=pick_kind,
            title=title,
            step_title=step_title or title,
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
        return
    await _ensure_manual_panel_queue(page)
    payload: dict = {
        "message": message,
        "mode": mode,
        "action": action,
        "secondaryAction": secondary_action or "",
        "allowAction": allow_action,
        "pickHint": pick_hint or "",
        "pickKind": pick_kind or "",
        "summary": (summary or "").strip(),
        "stepNumber": step_number,
        "stepTotal": step_total,
        "stepName": (step_name or "").strip(),
        "doNow": (do_now or "").strip(),
        "tip": (tip or "").strip(),
        "savedLines": [str(x).strip() for x in (saved_lines or []) if str(x).strip()],
        "warn": (warn or "").strip(),
    }
    panel_title = (step_title or title or step_name or "").strip()
    if panel_title:
        payload["title"] = panel_title
    if instructions:
        payload["instructions"] = instructions
    await page.evaluate(
        """(next) => {
          window.__genbountyManualSetStep(next);
        }""",
        payload,
    )


async def _manual_panel_event(
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
) -> dict:
    from browser_bot.discovery_ui_bridge import (
        UiDiscoveryRestartRequested,
        check_ui_discovery_restart,
        request_ui_discovery_restart,
        resolve_discovery_page,
        ui_panel_event,
        uses_ui_discovery,
    )

    page = resolve_discovery_page(page)
    check_ui_discovery_restart(page.context)
    if uses_ui_discovery(page):
        return await ui_panel_event(
            page,
            message,
            mode=mode,
            action=action,
            secondary_action=secondary_action,
            allow_action=allow_action,
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
    if _page_uses_v2_discovery(page):
        await _ensure_v2_discovery_mode(page)
    await _manual_panel_show(
        page,
        message,
        mode=mode,
        action=action,
        secondary_action=secondary_action,
        allow_action=allow_action,
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
    queue = await _ensure_manual_panel_queue(page)
    event = await queue.get()
    if event.get("type") == "ui_fallback":
        request_ui_discovery_restart(page.context)
        raise UiDiscoveryRestartRequested()
    return event


async def _manual_step_confirm(page, step_title: str, record_summary: str) -> bool:
    """Review captured value; return True when user confirms saving to config.yaml."""
    from browser_bot.discovery_ui_bridge import resolve_discovery_page, uses_ui_discovery

    page = resolve_discovery_page(page)
    if uses_ui_discovery(page):
        summary = (record_summary or "").strip()
        print(f"    [ui] Auto-confirmed {step_title}.")
        if summary:
            for line in summary.splitlines():
                if line.strip():
                    print(f"      {line}")
        return True

    n, total = _parse_step_label(step_title)
    event = await _manual_panel_event(
        page,
        "Review the captured value below, then save or redo this step.",
        mode="confirm",
        action="Confirm & save",
        secondary_action="Redo step",
        step_title=step_title,
        summary=record_summary,
        step_number=n,
        step_total=total,
        step_name="Looks right?",
        do_now="Check the captured value, then save it",
        tip="Redo if the wrong element was selected",
    )
    return event.get("type") == "confirm"


async def _guided_busy_heartbeat(
    page,
    *,
    title: str,
    message: str,
    pick_hint: str,
    interval_s: float = 8.0,
) -> None:
    """Refresh the helper panel during long browser/LLM operations."""
    from browser_bot.discovery_ui_bridge import resolve_discovery_page, uses_ui_discovery

    page = resolve_discovery_page(page)
    ui = uses_ui_discovery(page)
    elapsed = 0
    while True:
        await asyncio.sleep(interval_s)
        elapsed += int(interval_s)
        if ui:
            panel_message = f"Still working… ({elapsed}s)"
        else:
            panel_message = f"{message}\n\nStill working - {elapsed}s elapsed."
        await _manual_panel_show(
            page,
            panel_message,
            mode="busy",
            title=title,
            pick_hint=pick_hint,
        )


async def _manual_continue(page, message: str, action: str = "Continue") -> None:
    await _manual_panel_event(page, message, mode="idle", action=action)


async def _manual_continue_confirmed(
    page,
    message: str,
    *,
    step_title: str,
    build_summary,
    action: str = "Continue",
    step_number: int | None = None,
    step_total: int | None = None,
    step_name: str | None = None,
    do_now: str | None = None,
    tip: str | None = None,
) -> bool:
    """Wait for Continue, then require explicit confirm before the step is considered done."""
    while True:
        await _manual_panel_event(
            page,
            message,
            mode="idle",
            action=action,
            step_title=step_title,
            step_number=step_number,
            step_total=step_total,
            step_name=step_name,
            do_now=do_now,
            tip=tip,
        )
        summary = build_summary()
        if asyncio.iscoroutine(summary):
            summary = await summary
        if await _manual_step_confirm(page, step_title, summary):
            return True


async def _manual_pick_or_skip(
    page,
    message: str,
    *,
    step_title: str = "Confirm file upload",
    skip_summary: str | None = None,
    skip_use_auto: bool = False,
    allow_action: bool = False,
    confirm_label: str = "File input selector",
    v2: bool = False,
    context_target: str = "file_input",
    skip_action: str = "Skip",
    pick_hint: str | None = None,
    step_number: int | None = None,
    step_total: int | None = None,
    step_name: str | None = None,
    do_now: str | None = None,
    tip: str | None = None,
) -> dict | None:
    """Wait for element pick or Skip; confirm before returning.

    skip_summary: confirmation text shown after Skip (does not imply saving).
    skip_use_auto: when True, confirmed Skip keeps the auto-detected selector (file upload only).
    skip_action: panel button label for finishing without another pick (e.g. Done).
    """
    prompt = message
    cur_warn = ""
    while True:
        event = await _manual_panel_event(
            page,
            prompt,
            mode="pick",
            action=skip_action,
            allow_action=allow_action,
            step_title=step_title,
            pick_hint=pick_hint,
            step_number=step_number,
            step_total=step_total,
            step_name=step_name,
            do_now=do_now,
            tip=tip,
            warn=cur_warn,
        )
        if event.get("type") == "skip":
            summary = skip_summary or "No file upload field will be saved for this component."
            if await _manual_step_confirm(page, step_title, summary):
                return {"use_auto": True} if skip_use_auto else None
            continue
        # Legacy: pick-mode Done used to emit continue instead of skip.
        if event.get("type") == "continue" and (skip_action or "").strip():
            summary = skip_summary or "No file upload field will be saved for this component."
            if await _manual_step_confirm(page, step_title, summary):
                return {"use_auto": True} if skip_use_auto else None
            continue
        event = await _process_manual_pick_event(
            page, event, v2=v2, target_kind=context_target
        )
        if event.get("type") == "pick_failed":
            cur_warn = (event.get("error") or "Could not register that click.").strip()
            continue
        selector = (event.get("selector") or "").strip()
        if not selector:
            continue
        cur_warn = ""
        tag = (event.get("tag") or "").strip()
        summary = f"{confirm_label}:\n{selector}"
        if tag:
            summary += f"\n\nElement: <{tag}>"
        inp_type = _manual_input_type(event)
        if inp_type in ("select", "combobox"):
            summary += (
                "\n\nThis menu opens before upload on test runs. "
                "Pick the option your UI needs if it stays open."
            )
        if await _manual_step_confirm(page, step_title, summary):
            return event


async def _dismiss_transient_ui(page) -> None:
    """Close open menus/popovers so prompt verification targets the composer only."""
    try:
        for _ in range(2):
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.12)
    except Exception:
        pass


async def _detect_input_type_on_page(page, selector: str, event: dict) -> str:
    """Resolve fill/read strategy from the live DOM, not just the pick event metadata."""
    try:
        loc = await _first_visible_locator(page, selector)
        if not loc:
            raise RuntimeError("no visible match")
        meta = await loc.evaluate(
            """(el) => ({
              tag: (el.tagName || '').toLowerCase(),
              type: (el.getAttribute('type') || '').toLowerCase(),
              contenteditable: el.getAttribute('contenteditable'),
            })"""
        )
        tag = (meta.get("tag") or "").lower()
        if tag == "textarea":
            return "textarea"
        if tag == "input":
            return (meta.get("type") or "text").lower() or "text"
        ce = meta.get("contenteditable")
        if ce in ("true", ""):
            return "contenteditable"
    except Exception:
        pass
    return _manual_input_type(event)


async def _verify_input_on_live_page(
    page,
    inp: dict,
    *,
    probe_text: str = "Hello",
) -> tuple[bool, str]:
    """
    Try filling the selector on the current discovery page (same session/auth).
    Does not replay earlier discovery inputs (menu/upload) - only the prompt field.
    Returns (ok, detail_message).
    """
    from browser_bot.submit.common import (
        _clear_text_control,
        _fill_text_control,
        _first_visible_locator,
        _read_text_control,
        _refire_text_input_events,
    )

    selector = inp.get("selector") or ""
    inp_type = inp.get("type", "text")

    try:
        await _dismiss_transient_ui(page)

        loc = await _first_visible_locator(page, selector)
        if not await loc.is_visible():
            return False, f"Element not visible: {selector}"

        if inp_type == "file":
            return True, "File input is visible (upload not probed during discovery)."

        await _clear_text_control(page, loc, inp_type)
        await _fill_text_control(page, loc, inp_type, probe_text)
        await asyncio.sleep(0.5 if inp_type == "contenteditable" else 0.35)
        if inp_type in _TEXT_TYPES:
            await _refire_text_input_events(page, [inp])

        if inp_type in _DROPDOWN_INPUT_TYPES:
            return True, "Dropdown/combobox accepted automation fill."

        value = await _read_text_control(loc, inp_type)
        normalized = (value or "").strip()
        ok = probe_text.lower() in normalized.lower()
        if ok:
            return True, f"Probe text {probe_text!r} is present in the field."
        return False, f"Fill did not stick (read back: {repr(normalized[:120])}, type={inp_type})."
    except Exception as exc:
        return False, str(exc)


async def _manual_pick_prompt_input(
    page,
    message: str,
    *,
    step_title: str,
    site: str,
    component: str,
    v2: bool = False,
    step_number: int | None = None,
    step_total: int | None = None,
    step_name: str | None = None,
    do_now: str | None = None,
    tip: str | None = None,
) -> dict:
    """Pick prompt input, verify with test text, auto-advance on success."""
    cur_warn = ""
    pick_hint = (
        "Click the prompt box - we verify with \"Hello\" and continue."
        if v2
        else "Click the prompt box once - we verify and continue."
    )
    while True:
        event = await _manual_panel_event(
            page,
            message,
            mode="pick",
            action="",
            pick_hint=pick_hint,
            step_title=step_title,
            step_number=step_number,
            step_total=step_total,
            step_name=step_name or "Prompt box",
            do_now=do_now or "Click the text field where you type messages",
            tip=tip,
            warn=cur_warn,
        )
        event = await _process_manual_pick_event(
            page, event, v2=v2, target_kind="prompt_input"
        )
        if event.get("type") == "pick_failed":
            cur_warn = (event.get("error") or "Could not register that click.").strip()
            continue
        selector = (event.get("selector") or "").strip()
        if not selector:
            continue
        cur_warn = ""

        resolved_type = await _detect_input_type_on_page(page, selector, event)
        input_config = {
            "selector": selector,
            "type": resolved_type,
        }

        await _manual_panel_show(
            page,
            f"Verifying prompt input…\n\n{selector}\n(type={resolved_type})",
            mode="busy",
            pick_hint="Filling test text - no click needed.",
            step_number=step_number,
            step_total=step_total,
            step_name="Prompt box",
            do_now="Verifying the prompt field with a test message…",
        )
        ok, detail = await _verify_input_on_live_page(page, input_config)

        if ok:
            print(f"    input verify: passed - {detail}")
            return {**event, "fillType": resolved_type}

        print(f"    input verify: failed - {detail}")
        cur_warn = f"Verification failed: {detail}. Click the correct prompt field."


async def _analyze_response_capture_on_page(page, pick_selector: str) -> dict:
    """Infer list/role/parity response capture strategy from a discovery pick."""
    try:
        result = await page.evaluate(
            """(sel) => {
              const el = document.querySelector(sel);
              if (!el || !window.__genbountyAnalyzeResponseCapture) return { mode: "last" };
              return window.__genbountyAnalyzeResponseCapture(el);
            }""",
            pick_selector,
        )
        return result if isinstance(result, dict) else {"mode": "last"}
    except Exception:
        return {"mode": "last"}


def _merge_response_capture_analysis(submission: dict, pick_selector: str, analysis: dict) -> list[str]:
    """Apply discovered capture strategy to submission dict. Returns log lines."""
    lines: list[str] = []
    mode = str(analysis.get("mode") or "last").strip().lower()
    list_sel = str(analysis.get("list_selector") or "").strip()
    role_sel = str(analysis.get("role_selector") or "").strip()

    pick_selector = sanitize_discovered_selector(pick_selector)
    list_sel = sanitize_discovered_selector(list_sel)
    role_sel = sanitize_discovered_selector(role_sel)

    if list_sel and is_fragile_positional_selector(list_sel):
        list_sel = ""
    if list_sel and _is_overbroad_response_list_selector(list_sel):
        lines.append(f"    [!] ignored overbroad list selector: {list_sel}")
        list_sel = ""
    if pick_selector and is_fragile_positional_selector(pick_selector) and not list_sel:
        submission["response_selector"] = pick_selector
        submission.pop("response_capture_mode", None)
        submission.pop("response_list_selector", None)
        submission.pop("response_role_selector", None)
        lines.append(
            "    [!] response_selector is a brittle nth-of-type path - "
            "re-run discovery or set a repeating list selector manually."
        )
        return lines

    effective_root = list_sel or pick_selector
    submission["response_selector"] = effective_root

    if mode in ("role", "parity_odd", "parity_even"):
        submission["response_capture_mode"] = mode
        lines.append(f"    response_capture_mode: {mode}")
    else:
        submission.pop("response_capture_mode", None)

    if list_sel:
        submission["response_list_selector"] = list_sel
        lines.append(f"    response_list_selector: {list_sel}")
    else:
        submission.pop("response_list_selector", None)

    if role_sel and mode == "role":
        submission["response_role_selector"] = role_sel
        lines.append(f"    response_role_selector: {role_sel}")
    else:
        submission.pop("response_role_selector", None)

    basis = analysis.get("parity_basis")
    if basis:
        lines.append(f"    (capture pattern: {basis})")
    return lines


async def _ensure_response_capture_analyze(page) -> None:
    """Install response list/role/parity analysis helpers when missing (e.g. during test runs)."""
    try:
        ready = await page.evaluate(
            "() => typeof window.__genbountyAnalyzeResponseCapture === 'function'"
        )
        if ready:
            return
    except Exception:
        pass
    try:
        await page.evaluate(_resolved_manual_discovery_script())
    except Exception:
        pass


async def upgrade_response_capture_kwargs(page, submission: dict | None) -> dict[str, str]:
    """
    Upgrade fragile single-node response selectors to list/role/parity capture when the
    chat UI renders multiple user/assistant turns in one view.
    """
    from browser_bot.submit.common import response_capture_kwargs

    base = response_capture_kwargs(submission)
    sub = submission or {}
    sel = str(sub.get("response_selector") or "").strip()
    if not sel:
        return {"response_selector": "", **base}

    mode = base["response_capture_mode"]
    list_sel = base["response_list_selector"]
    role_sel = base["response_role_selector"]

    if list_sel and is_fragile_positional_selector(list_sel):
        list_sel = ""
    if is_fragile_positional_selector(sel) or (
        list_sel and list_sel == sel and is_fragile_positional_selector(sel)
    ):
        mode = ""
        list_sel = ""

    if mode in ("role", "parity_odd", "parity_even") and list_sel:
        return {
            "response_selector": sel,
            "response_capture_mode": mode,
            "response_list_selector": list_sel,
            "response_role_selector": role_sel,
        }

    if list_sel and not is_fragile_positional_selector(list_sel):
        try:
            if await page.locator(list_sel).count() >= 2:
                return {
                    "response_selector": sel,
                    **base,
                }
        except Exception:
            pass

    if not is_fragile_positional_selector(sel):
        try:
            if await page.locator(sel).count() >= 2:
                return {
                    "response_selector": sel,
                    "response_capture_mode": mode or "last",
                    "response_list_selector": list_sel or sel,
                    "response_role_selector": role_sel,
                }
        except Exception:
            pass
        if not list_sel:
            return {"response_selector": sel, **base}

    await _ensure_response_capture_analyze(page)
    try:
        analysis = await page.evaluate(
            """(sel) => {
              const el = document.querySelector(sel);
              if (!el || !window.__genbountyAnalyzeResponseCapture) return null;
              return window.__genbountyAnalyzeResponseCapture(el);
            }""",
            sel,
        )
    except Exception:
        return {"response_selector": sel, **base}
    if not isinstance(analysis, dict):
        return {"response_selector": sel, **base}

    tmp_sub = dict(sub)
    _merge_response_capture_analysis(tmp_sub, sel, analysis)
    out = response_capture_kwargs(tmp_sub)
    out["response_selector"] = str(tmp_sub.get("response_selector") or sel).strip()
    return out


async def _manual_pick_selector(
    page,
    message: str,
    *,
    step_title: str = "Confirm selector",
    allow_action: bool = False,
    v2: bool = False,
    context_target: str = "submit",
    pick_kind: str | None = None,
    step_number: int | None = None,
    step_total: int | None = None,
    step_name: str | None = None,
    do_now: str | None = None,
    tip: str | None = None,
) -> dict:
    cur_warn = ""
    pick_hint = (
        "Click the target - we analyze nearby elements."
        if v2
        else "Click the target element."
    )
    while True:
        event = await _manual_panel_event(
            page,
            message,
            mode="pick",
            action="",
            allow_action=allow_action,
            pick_hint=pick_hint,
            pick_kind=pick_kind,
            step_title=step_title,
            step_number=step_number,
            step_total=step_total,
            step_name=step_name,
            do_now=do_now,
            tip=tip,
            warn=cur_warn,
        )
        event = await _process_manual_pick_event(
            page, event, v2=v2, target_kind=context_target
        )
        if event.get("type") == "pick_failed":
            cur_warn = (event.get("error") or "Could not register that click.").strip()
            continue
        selector = (event.get("selector") or "").strip()
        if not selector:
            continue
        cur_warn = ""
        tag = (event.get("tag") or "").strip()
        inp_type = (event.get("inputType") or "").strip()
        summary = f"Selector:\n{selector}"
        if tag:
            summary += f"\n\nElement: <{tag}>"
        if inp_type:
            summary += f"\nInput type: {inp_type}"
        if await _manual_step_confirm(page, step_title, summary):
            return event


async def _get_page_html(page) -> str:
    return await page.evaluate(
        """() => {
          const body = document.body;
          if (!body) return '';
          const clone = body.cloneNode(true);
          clone.querySelectorAll('script').forEach(el => el.remove());
          clone.querySelectorAll('[hidden]').forEach(el => el.remove());
          return clone.innerHTML;
        }"""
    )


def _save_html(site: str, component: str, html: str, suffix: str = "") -> Path:
    ensure_component_dir(site, component)
    html_dir = get_component_path(site, component) / "html"
    html_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = html_dir / f"{ts}{suffix}.html"
    path.write_text(html, encoding="utf-8")
    return path


def _clean_html_for_llm(html: str) -> str:
    """Strip noise while preserving form-critical attributes for CSS selector derivation."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return html

    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(["script", "style", "svg", "head", "noscript",
                               "link", "meta", "iframe", "template", "img"]):
        tag.decompose()

    for tag in soup.find_all(True):
        # Some malformed nodes can carry attrs=None; treat as empty attrs.
        if getattr(tag, "attrs", None) is None:
            tag.attrs = {}
        style = tag.get("style", "")
        if "display:none" in style.replace(" ", "") or "visibility:hidden" in style.replace(" ", ""):
            tag.decompose()
            continue
        if tag.has_attr("hidden"):
            tag.decompose()

    _KEEP_ATTRS = {
        "id", "class", "name", "type", "role", "contenteditable",
        "placeholder", "aria-label", "for", "href", "action", "method",
    }
    for tag in soup.find_all(True):
        if getattr(tag, "attrs", None) is None:
            tag.attrs = {}
        keep = {a: tag.attrs[a] for a in list(tag.attrs)
                if a in _KEEP_ATTRS or a.startswith("data-") or a.startswith("aria-")}
        tag.attrs = keep

    return str(soup)


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

_DISCOVERY_SELECTOR_ATTEMPTS = 3

def _ensure_pipeline_path() -> None:
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _discovery_complete(prompt: str, *, role: str = "discovery", json_mode: bool = True) -> str:
    """Run a discovery/grounding LLM call through the shared multi-provider layer.

    Provider + model are resolved from llm.yaml (role ``discovery`` for selector
    extraction, ``grounding_judge`` for repair). Returns the response text, or
    "" when the role is unconfigured (missing key) or the call fails.
    """
    _ensure_pipeline_path()
    try:
        from pipeline.llm import complete
    except Exception as exc:  # pragma: no cover - import guard
        print(f"  [!] LLM layer unavailable: {exc}")
        return ""
    try:
        return complete(
            role,
            user=prompt,
            json_mode=json_mode,
            max_output_tokens=8192,
        ).text or ""
    except Exception as exc:
        print(f"  LLM error ({role}): {exc}")
        return ""


def _discovery_llm_ready() -> bool:
    """True when the discovery + grounding_judge roles resolve to a usable key."""
    _ensure_pipeline_path()
    try:
        from pipeline.llm import resolve_role
        from pipeline.llm.config import LLMConfigError
    except Exception:  # pragma: no cover - import guard
        return False
    try:
        resolve_role("discovery")
        resolve_role("grounding_judge")
        return True
    except LLMConfigError as exc:
        print(f"  [!] Discovery LLM not configured: {exc}")
        return False
    except Exception:
        return False


def _parse_json_response(text: str) -> dict:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if m:
        return json.loads(m.group(1))
    m = re.search(r"\{[\s\S]*\}", text)
    return json.loads(m.group()) if m else json.loads(text)


def _llm_extract_inputs(html: str, page_url: str) -> list[dict]:
    """Ask the discovery LLM for input field selectors only (no submit button)."""
    cleaned = _clean_html_for_llm(html)
    print(f"  HTML cleaned: {len(html):,} → {len(cleaned):,} chars")
    prompt = f"""Analyze this HTML from an AI chat or form page.

Page URL: {page_url}

HTML:
{cleaned[:120000]}

Return ONLY valid JSON identifying the text input field(s) where a user types a prompt:
{{
  "inputs": [
    {{"selector": "css-selector", "type": "text|textarea|contenteditable|select|combobox|click|file", "upload_prep": true, "value": "optional-for-select", "path_from": "payload when type is file"}}
  ]
}}

Rules:
- List fields in ORDER: upload/menu prep clicks first, prerequisite dropdown (model/mode menu) next, then file upload, then text prompt when multiple exist.
- Many chat UIs hide file upload until a model or attachment menu is opened - save those controls as type click with upload_prep: true (NOT type text).
- Upload menu items: prefer [role="menuitem"]:has-text("Upload") style selectors over long Radix div paths.
- Menu/attachment buttons (#composer-plus-btn, aria-haspopup=menu): type click with upload_prep: true.
- Many chat UIs hide file upload until a model or attachment mode is chosen from a dropdown - include that control as type select or combobox with upload_prep: true before the file input.
- Include text inputs, textareas, contenteditable divs, native select dropdowns, custom combobox triggers ([role="combobox"], buttons with aria-haspopup), and file inputs (type: file with path_from: payload).
- EXCLUDE hidden inputs and submit/send buttons.
- NEVER use type text for buttons or menu items - use type click with upload_prep: true instead.
- Prefer stable selectors: #id, [data-testid="x"], [name="x"], tag.class, [role="menuitem"]:has-text("...")
- NEVER use CSS-module hashed classes (e.g. .button--a1B2c3D or div.foo--XyZ123). Use partial class instead: button[class*='button'] or [class*='foo'].
- Never use bare "div" or "span" - qualify with attribute or class.
- For contenteditable: use div[contenteditable="true"] or the most specific stable selector.
- NEVER produce a selector with more than 4 levels of nesting.
- NEVER use nth-of-type more than once in a selector.
- If the page has several distinct forms or chat composers, anchor the field with a nearby landmark (section[aria-labelledby], heading id, form[action], main) so the selector does not match a different widget.
"""
    raw = _discovery_complete(prompt, role="discovery", json_mode=True)
    if not raw:
        return []
    try:
        data = _parse_json_response(raw)
        inputs = data.get("inputs", [])
        out = []
        for i in inputs:
            if not isinstance(i, dict):
                continue
            row = _normalize_discovered_input(dict(i))
            if row:
                out.append(row)
        return out
    except Exception as e:
        print(f"  LLM parse error (inputs): {e}")
        return []


def _llm_extract_submit(html: str, page_url: str, prompt_input_selectors: list[str] | None = None) -> str:
    """Ask the discovery LLM for the submit/send button selector only."""
    cleaned = _clean_html_for_llm(html)
    region_hint = ""
    if prompt_input_selectors:
        joined = ", ".join(s.strip() for s in prompt_input_selectors if s and str(s).strip())
        if joined:
            region_hint = f"""
Region anchoring - these prompt/input field selector(s) are already verified:
  {joined}
The submit button MUST lie in the SAME closest landmark/card/section subtree as those fields
(wraps both the field and the button in the DOM). If the page repeats the same button pattern
in multiple regions, pick the control that belongs to this subtree, not a similar one elsewhere.
"""

    prompt = f"""Analyze this HTML from an AI chat or form page.

Page URL: {page_url}
{region_hint}
HTML:
{cleaned[:120000]}

Return ONLY valid JSON identifying the button that submits/sends the user's prompt:
{{
  "submit_selector": "css-selector"
}}

Rules:
- Target the send/submit control that pairs with THAT prompt/input, not an unrelated CTA on the page.
- Prefer scope from HTML landmarks when needed: section[aria-labelledby], heading ids, form boundaries, [role="region"], main, or a card/article that uniquely wraps the composer.
- You MAY use Playwright CSS: spaces for descendants, and :has-text("visible label") on buttons/links when the label is distinctive (still scope when similar labels could exist elsewhere).
  Example pattern: section[aria-labelledby="x"] .action-row button:has-text("Send")
- Prefer attributes (data-testid=\"send-button\", type=submit, aria-label Send/Send message) when unique in that region.
- NEVER pick attach/menu chrome: More actions, +, composer-plus, upload/attach triggers, aria-haspopup=menu plus buttons.
- NEVER use CSS-module hashed classes (pattern name--Hash). Use [class*='namePrefix'] or button[aria-label=\"...\"] instead.
- Avoid long chains of generic divs with nth-of-type - prefer landmark + short path to the control.
- Keep selectors short: at most a few descendant steps from the chosen landmark (or from document root if globally unique).
"""
    raw = _discovery_complete(prompt, role="discovery", json_mode=True)
    if not raw:
        return ""
    try:
        data = _parse_json_response(raw)
        sel = sanitize_discovered_selector(data.get("submit_selector", "").strip())
        reject = _is_attach_menu_submit_chrome(sel)
        if reject:
            print(f"  [~] Rejected submit selector (attach/menu chrome): {sel} - {reject}")
            return ""
        return sel
    except Exception as e:
        print(f"  LLM parse error (submit): {e}")
        return ""


def _llm_extract_response_selector(html: str, page_url: str, prompt_input_selectors: list[str] | None = None) -> str:
    """Ask the discovery LLM for the AI response container selector."""
    cleaned = _clean_html_for_llm(html)
    print(f"  HTML cleaned: {len(html):,} → {len(cleaned):,} chars")

    region_hint = ""
    if prompt_input_selectors:
        joined = ", ".join(s.strip() for s in prompt_input_selectors if s and str(s).strip())
        if joined:
            region_hint = f"""
Region anchoring - verified prompt/input selector(s):
  {joined}
The response container MUST stay inside the SAME landmark/section/card subtree as those fields.
If the page has multiple similar chat UIs, do not match messages from another region.
"""

    prompt = f"""Analyze this HTML captured AFTER a test prompt was submitted and an AI response was rendered.

Page URL: {page_url}
{region_hint}

HTML:
{cleaned[:120000]}

Return ONLY valid JSON identifying the element that contains the AI's text response:
{{
  "response_selector": "css-selector"
}}

Rules:
- Prefer the model/assistant message container within the SAME region as the prompt (use heading ids, aria-labelledby, form or main boundaries visible in the HTML).
- The selector SHOULD match each assistant turn in THAT conversation when possible (automation uses the last visible match) - still avoid crossing into another parallel widget on the same page.
- Prefer stable signals: [data-message-author-role], data-testid, roles, or short class paths that are not build hashes.
- Avoid deep nth-of-type ladders; use a landmark + narrow subtree.
- You MAY use Playwright :has-text only on static chrome, not on free-form model output.
- Never return an empty string - pick the best candidate if uncertain.
"""
    raw = _discovery_complete(prompt, role="discovery", json_mode=True)
    if not raw:
        return ""
    try:
        data = _parse_json_response(raw)
        return sanitize_discovered_selector(data.get("response_selector", "").strip())
    except Exception as e:
        print(f"  LLM parse error (response selector): {e}")
        return ""


def _retry_extract_inputs(html: str, page_url: str) -> list[dict]:
    for attempt in range(1, _DISCOVERY_SELECTOR_ATTEMPTS + 1):
        inputs = _llm_extract_inputs(html, page_url)
        if inputs:
            return inputs
        if attempt < _DISCOVERY_SELECTOR_ATTEMPTS:
            print(f"  [~] Input selector not found; retrying ({attempt + 1}/{_DISCOVERY_SELECTOR_ATTEMPTS})...")
    return []


def _retry_extract_submit(
    html: str,
    page_url: str,
    prompt_input_selectors: list[str] | None = None,
) -> str:
    for attempt in range(1, _DISCOVERY_SELECTOR_ATTEMPTS + 1):
        selector = _llm_extract_submit(html, page_url, prompt_input_selectors)
        if selector:
            return selector
        if attempt < _DISCOVERY_SELECTOR_ATTEMPTS:
            print(f"  [~] Submit selector not found; retrying ({attempt + 1}/{_DISCOVERY_SELECTOR_ATTEMPTS})...")
    return ""


def _retry_extract_response_selector(
    html: str,
    page_url: str,
    prompt_input_selectors: list[str] | None = None,
) -> str:
    for attempt in range(1, _DISCOVERY_SELECTOR_ATTEMPTS + 1):
        selector = _llm_extract_response_selector(html, page_url, prompt_input_selectors)
        if selector:
            return selector
        if attempt < _DISCOVERY_SELECTOR_ATTEMPTS:
            print(f"  [~] Response selector not found; retrying ({attempt + 1}/{_DISCOVERY_SELECTOR_ATTEMPTS})...")
    return ""


_CONTEXT_TARGET_PROMPTS: dict[str, str] = {
    "prompt_input": """STEP: Prompt / chat text input.
The user clicked near where they type their message.

Return ONLY valid JSON:
{{"selector": "css-selector", "type": "text|textarea|contenteditable"}}

You MUST pick a selector for ONE of these element types ONLY:
- textarea
- input (type text, search, email, password, or no type attribute)
- [contenteditable="true"] ONLY if no textarea/text input exists in the fragment

NEVER return selectors for: button, input[type=submit|button|file|hidden], select, menu items.""",
    "submit": """STEP: Send / submit control.
The user clicked near the control that sends the prompt.

Return ONLY valid JSON:
{{"selector": "css-selector"}}

You MUST pick a selector for ONE of these element types ONLY:
- button
- input[type="submit"] or input[type="button"]
- [role="button"] when it acts as the send/submit control

Prefer [data-testid="send-button"] or aria-label Send / Send message / Send prompt when present.

NEVER return selectors for: textarea, text inputs, contenteditable fields, file inputs,
generic div/span containers, or attach/menu chrome (More actions, +, composer-plus,
upload/attach triggers, aria-haspopup=menu plus buttons).""",
    "response": """STEP: Assistant response container.
The user clicked on or near the AI/model reply text.

Return ONLY valid JSON:
{{"selector": "css-selector"}}

Find a container element (div, article, section, p) that holds the assistant's message text.
Prefer [data-message-author-role="assistant"] or similar message markers.
NEVER return the prompt input or submit button.""",
    "file_input": """STEP: File upload control.
Return ONLY valid JSON:
{{"selector": "css-selector", "type": "file|click"}}

Prefer input[type="file"]. Otherwise a button or menuitem that triggers upload.""",
    "dropdown": """STEP: Dropdown / model picker.
Return ONLY valid JSON:
{{"selector": "css-selector", "type": "select|combobox"}}

Find select or [role="combobox"] / button with aria-haspopup that opens a model/mode menu.""",
    "upload_prep": """STEP: Menu / attachment trigger (reveals upload).
Return ONLY valid JSON:
{{"selector": "css-selector", "type": "click|combobox|select"}}

Find a button or menuitem that opens attachment/upload options - NOT the text prompt field.""",
    "surface_prep": """STEP: Surface pre-step (any on-page element).
Return ONLY valid JSON:
{{"selector": "css-selector", "type": "click"}}

Identify the exact element the operator clicked — button, link, tab, card/div, notice dismiss,
or any other host that must be clicked before the prompt is ready. Prefer role+text,
has-text, or text= when a short visible label exists. NOT the chat textarea, NOT Send/Submit.""",
}

_PROMPT_TEXT_INPUT_TYPES = frozenset({"text", "search", "email", "password", "tel", "url", ""})
_SUBMIT_INPUT_TYPES = frozenset({"submit", "button"})


def _element_summary(tag) -> str:
    """One-line summary of a BeautifulSoup element for LLM candidate lists."""
    name = (getattr(tag, "name", None) or "").lower()
    parts = [f"<{name}"]
    for attr in ("id", "name", "type", "role", "placeholder", "aria-label", "data-testid",
                 "data-message-author-role"):
        val = tag.get(attr) if hasattr(tag, "get") else None
        if val:
            parts.append(f'{attr}="{str(val)[:80]}"')
    classes = tag.get("class") if hasattr(tag, "get") else None
    if classes:
        cls_str = " ".join(classes) if isinstance(classes, list) else str(classes)
        cls_str = cls_str.strip()
        if cls_str:
            parts.append(f'class="{cls_str[:120]}"')
    ce = tag.get("contenteditable") if hasattr(tag, "get") else None
    if ce is not None:
        parts.append(f'contenteditable="{ce}"')
    text = tag.get_text(strip=True) if hasattr(tag, "get_text") else ""
    summary = " ".join(parts) + ">"
    if text and name in ("button", "a", "label", "code", "pre", "p"):
        summary += f' text="{text[:60]}"'
    return summary


def _is_prompt_or_control_soup_element(el) -> bool:
    tag = (el.name or "").lower()
    if tag in ("textarea", "button", "select"):
        return True
    if tag == "input":
        return (el.get("type") or "text").lower() not in ("hidden",)
    return False


def _is_likely_response_soup_element(el) -> bool:
    if _is_prompt_or_control_soup_element(el):
        return False
    tag = (el.name or "").lower()
    if tag in ("code", "pre", "article"):
        return True
    if el.get("data-message-author-role"):
        return True
    test_id = str(el.get("data-testid") or "").lower()
    if "message" in test_id or "response" in test_id:
        return True
    classes = el.get("class") or []
    if isinstance(classes, str):
        classes = classes.split()
    if any(str(c).startswith("language-") for c in classes):
        return True
    if tag in ("p", "div", "span") and len(el.get_text(strip=True)) >= 8:
        return True
    return False


def _build_focused_context_for_llm(html: str, target_kind: str) -> tuple[str, list[str]]:
    """
    Narrow the click-context fragment to element types we expect for this step.
    Returns (html_for_prompt, candidate_summaries).
    """
    elements = _collect_context_candidate_elements(html, target_kind)
    if elements:
        snippets = [str(el) for el in elements[:24]]
        summaries = [_element_summary(el) for el in elements[:24]]
        focused = "\n".join(snippets)
        return focused[:80000], summaries[:24]
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        cleaned = _clean_html_for_llm(html)
        return cleaned[:80000], []
    cleaned = _clean_html_for_llm(html)
    return cleaned[:80000], []


def _collect_context_candidate_elements(html: str, target_kind: str) -> list:
    """Parse click-context HTML and return candidate elements for this discovery step."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    cleaned = _clean_html_for_llm(html)
    soup = BeautifulSoup(cleaned, "html.parser")
    elements: list = []
    seen: set[str] = set()

    def _add(el) -> None:
        key = str(el)[:500]
        if key not in seen:
            seen.add(key)
            elements.append(el)

    if target_kind == "prompt_input":
        for el in soup.find_all("textarea"):
            _add(el)
        for el in soup.find_all("input"):
            inp_type = (el.get("type") or "text").lower()
            if inp_type in ("hidden", "file", "submit", "button", "checkbox", "radio", "range", "color"):
                continue
            _add(el)
        if not elements:
            for el in soup.find_all(True):
                ce = el.get("contenteditable")
                if ce is not None and str(ce).lower() in ("true", ""):
                    _add(el)
    elif target_kind == "submit":
        for el in soup.find_all("button"):
            _add(el)
        for el in soup.find_all("input"):
            if (el.get("type") or "").lower() in _SUBMIT_INPUT_TYPES:
                _add(el)
        for el in soup.find_all(attrs={"role": "button"}):
            if el.name != "button":
                _add(el)
    elif target_kind == "response":
        for el in soup.find_all(attrs={"data-message-author-role": True}):
            _add(el)
        for el in soup.find_all(["code", "pre"]):
            if _is_likely_response_soup_element(el):
                _add(el)
        for el in soup.find_all(["article", "section"]):
            if el.get("data-testid") or el.get("data-message-author-role"):
                _add(el)
        if not elements:
            for el in soup.find_all(["div", "article", "section", "p", "code", "pre", "span"]):
                if _is_likely_response_soup_element(el):
                    _add(el)
        if not elements:
            for el in soup.find_all(["div", "article", "section", "p"]):
                if el.get("data-testid") or el.get("role") == "article":
                    _add(el)
    elif target_kind == "file_input":
        for el in soup.find_all("input", type="file"):
            _add(el)
        for el in soup.find_all(["button", "a", "label"]):
            blob = _element_summary(el).lower()
            if any(k in blob for k in ("upload", "attach", "file")):
                _add(el)
    elif target_kind == "dropdown":
        for el in soup.find_all("select"):
            _add(el)
        for el in soup.find_all(attrs={"role": "combobox"}):
            _add(el)
        for el in soup.find_all(["button", "div"]):
            if (el.get("aria-haspopup") or "").lower() in ("listbox", "menu", "true"):
                _add(el)
    elif target_kind == "upload_prep":
        for el in soup.find_all(["button", "a"]):
            blob = _element_summary(el).lower()
            if any(k in blob for k in ("upload", "attach", "file", "plus", "menu")) or el.get("aria-haspopup"):
                _add(el)
        for el in soup.find_all(attrs={"role": "menuitem"}):
            _add(el)
    elif target_kind == "surface_prep":
        for el in soup.find_all(["button", "a"]):
            _add(el)
        for el in soup.find_all(attrs={"role": True}):
            role = (el.get("role") or "").lower()
            if role in ("button", "link", "tab", "menuitem", "option", "radio"):
                _add(el)
        # Cards/rows are often plain div/li hosts (tabindex / onclick / short label).
        for el in soup.find_all(["div", "section", "li", "article", "span", "label"]):
            text = " ".join(el.get_text(" ", strip=True).split())
            if (
                el.get("onclick") is not None
                or el.get("tabindex") is not None
                or (1 < len(text) <= 120)
            ):
                _add(el)

    return elements


def _quote_attr_value(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _selector_variants_from_soup_element(el) -> list[str]:
    """Build stable CSS selector variants from a parsed HTML element, best first."""
    if not el or not getattr(el, "name", None):
        return []
    tag = el.name.lower()
    out: list[str] = []
    seen: set[str] = set()

    def _push(sel: str) -> None:
        s = (sel or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)

    el_id = el.get("id")
    if el_id:
        sid = str(el_id).strip()
        if re.match(r"^[a-zA-Z][\w-]*$", sid):
            _push(f"#{sid}")
        else:
            _push(f'[id="{_quote_attr_value(sid)}"]')
    for attr in (
        "data-testid", "name", "aria-label", "placeholder",
        "aria-describedby", "role", "type",
    ):
        val = el.get(attr)
        if val and str(val).strip():
            _push(f'{tag}[{attr}="{_quote_attr_value(str(val).strip())}"]')
    placeholder = (el.get("placeholder") or "").strip()
    if tag in ("textarea", "input") and len(placeholder) >= 8:
        prefix = placeholder[:32].strip()
        if len(prefix) >= 8 and prefix != placeholder:
            _push(f'{tag}[placeholder^="{_quote_attr_value(prefix)}"]')
    classes = el.get("class") or []
    if isinstance(classes, str):
        classes = classes.split()
    for cls in classes:
        cls = str(cls).strip()
        if not cls or not _is_stable_css_class_token(cls):
            continue
        if cls.startswith("language-"):
            _push(f"{tag}.{cls}")
            _push(f"{tag}[class*='{cls}']")
            continue
        m = re.match(r"^(.+?)--[A-Za-z0-9_]{4,}$", cls)
        if m and len(m.group(1)) >= 4:
            _push(f"{tag}[class*='{m.group(1)}']")
        elif not re.search(r"--[A-Za-z0-9_]{4,}", cls) and not re.search(r"[0-9]{5,}", cls):
            _push(f"{tag}.{cls}")
    return out


def _selector_from_soup_element(el) -> str:
    """Build a stable CSS selector from a parsed HTML element."""
    variants = _selector_variants_from_soup_element(el)
    return variants[0] if variants else ""


def _input_type_from_soup_element(el) -> str:
    tag = (el.name or "").lower()
    if tag == "textarea":
        return "textarea"
    if tag == "input":
        return (el.get("type") or "text").lower() or "text"
    ce = el.get("contenteditable")
    if ce is not None and str(ce).lower() in ("true", ""):
        return "contenteditable"
    if tag == "select":
        return "select"
    role = (el.get("role") or "").lower()
    if role == "combobox":
        return "combobox"
    if tag == "button" or role == "button":
        return "click"
    return "text"


def _score_context_candidate(el, target_kind: str, click_hint: dict | None) -> int:
    """Rank candidates - prefer elements matching the user's click metadata."""
    score = 0
    hint = click_hint or {}
    tag = (hint.get("tag") or "").lower()
    el_tag = (el.name or "").lower()
    if tag and el_tag == tag:
        score += 15
    hint_type = (hint.get("inputType") or "").lower()
    el_type = (el.get("type") or "").lower()
    if hint_type and el_type == hint_type:
        score += 10
    hint_text = " ".join(str(hint.get("innerText") or "").split()).lower()
    placeholder = (el.get("placeholder") or "").lower()
    aria = (el.get("aria-label") or "").lower()
    if hint_text:
        if hint_text in placeholder or placeholder in hint_text:
            score += 25
        if hint_text in aria or aria in hint_text:
            score += 20
        btn_text = el.get_text(strip=True).lower() if el_tag in ("button", "a") else ""
        if btn_text and (hint_text in btn_text or btn_text in hint_text):
            score += 20
    for attr in ("data-testid", "id", "name", "placeholder", "aria-label"):
        if el.get(attr):
            score += 3
    if target_kind == "response":
        role_attr = (el.get("data-message-author-role") or "").lower()
        if role_attr == "assistant":
            score += 30
        if el_tag in ("code", "pre"):
            score += 20
        classes = el.get("class") or []
        if isinstance(classes, str):
            classes = classes.split()
        if any(str(c).startswith("language-") for c in classes):
            score += 25
    if target_kind == "submit" and el_tag == "button":
        score += 5
        if _is_attachment_menu_trigger(el) or _is_attach_menu_submit_chrome(
            "",
            label=el.get_text(strip=True) if hasattr(el, "get_text") else "",
            meta={
                "ariaLabel": el.get("aria-label") or "",
                "dataTestId": el.get("data-testid") or "",
                "ariaHaspopup": el.get("aria-haspopup") or "",
                "id": el.get("id") or "",
            },
        ):
            score -= 40
        testid = (el.get("data-testid") or "").lower()
        aria = (el.get("aria-label") or "").lower()
        if "send" in testid or "send" in aria:
            score += 35
    return score


def deterministic_selector_candidates_from_context(
    context_html: str,
    target_kind: str,
    click_hint: dict | None = None,
) -> list[dict]:
    """
    Rank click-context elements and build stable selectors deterministically.
    Returns one entry per distinct selector, best match first.
    """
    elements = _collect_context_candidate_elements(context_html, target_kind)
    if not elements:
        return []

    ranked = sorted(
        elements,
        key=lambda el: _score_context_candidate(el, target_kind, click_hint),
        reverse=True,
    )
    out: list[dict] = []
    seen: set[str] = set()
    inp_type = ""
    for el in ranked:
        inp_type = _input_type_from_soup_element(el)
        for raw_sel in _selector_variants_from_soup_element(el):
            sel = sanitize_discovered_selector(raw_sel)
            if not sel or sel in seen or is_unreliable_expert_selector(sel, target_kind=target_kind):
                continue
            seen.add(sel)
            out.append({
                "expert_id": target_kind,
                "selector": sel,
                "type": inp_type,
                "confidence": "medium",
                "reasoning": "Deterministic fallback from click-context HTML candidates.",
                "source": "deterministic_fallback",
                "limitations": "",
            })
    return out


def deterministic_selector_from_context(
    context_html: str,
    target_kind: str,
    click_hint: dict | None = None,
) -> dict:
    """Best deterministic selector from click-context HTML, or empty dict."""
    candidates = deterministic_selector_candidates_from_context(
        context_html, target_kind, click_hint
    )
    return candidates[0] if candidates else {}


def _build_verified_selector_attempts(
    *,
    llm_selector: str,
    llm_type: str,
    html: str,
    target_kind: str,
    click_hint: dict | None,
    browser_selector: str = "",
) -> list[tuple[str, str, dict]]:
    """Ordered (source, selector, meta) pairs to try on the live page."""
    attempts: list[tuple[str, str, dict]] = []
    seen: set[str] = set()

    def _add(source: str, selector: str, meta: dict) -> None:
        sel = (selector or "").strip()
        if not sel or sel in seen:
            return
        if is_unreliable_expert_selector(sel, target_kind=target_kind):
            return
        seen.add(sel)
        attempts.append((source, sel, meta))

    browser_sel = (browser_selector or "").strip()
    if browser_sel:
        _add("browser_pick", browser_sel, {"selector": browser_sel, "type": llm_type or ""})

    llm_sel = (llm_selector or "").strip()
    if llm_sel:
        _add("llm", llm_sel, {"selector": llm_sel, "type": llm_type or ""})

    for fb in deterministic_selector_candidates_from_context(html, target_kind, click_hint):
        fb_sel = (fb.get("selector") or "").strip()
        if fb_sel:
            _add(
                "deterministic_fallback",
                fb_sel,
                {"selector": fb_sel, "type": fb.get("type") or ""},
            )

    return attempts


async def _element_metadata_at_selector(page, selector: str) -> dict:
    try:
        loc = await _first_visible_locator(page, selector)
        if not loc:
            return {}
        return await loc.evaluate(
            """(el) => ({
              tag: (el.tagName || '').toLowerCase(),
              type: (el.getAttribute('type') || '').toLowerCase(),
              role: (el.getAttribute('role') || '').toLowerCase(),
              contenteditable: el.getAttribute('contenteditable'),
              ariaHaspopup: (el.getAttribute('aria-haspopup') || '').toLowerCase(),
              ariaLabel: (el.getAttribute('aria-label') || '').toLowerCase(),
              dataTestId: (el.getAttribute('data-testid') || '').toLowerCase(),
              id: (el.id || '').toLowerCase(),
              innerText: ((el.innerText || el.textContent || '') + '').trim().slice(0, 80),
            })"""
        )
    except Exception:
        return {}


async def _validate_context_selector_for_step(
    page,
    selector: str,
    target_kind: str,
) -> tuple[bool, str, str | None]:
    """Ensure the resolved selector matches the element type expected for this discovery step."""
    meta = await _element_metadata_at_selector(page, selector)
    if not meta:
        return False, "Could not inspect the matched element on the page.", None

    tag = (meta.get("tag") or "").lower()
    inp_type = (meta.get("type") or "").lower()
    role = (meta.get("role") or "").lower()
    ce = meta.get("contenteditable")
    ce_true = ce is not None and str(ce).lower() in ("true", "")

    if target_kind == "prompt_input":
        if tag == "textarea":
            return True, "", "textarea"
        if tag == "input":
            if inp_type in ("hidden", "file", "submit", "button", "checkbox", "radio"):
                return False, f"Expected a text field (textarea or text input), not input[type={inp_type or 'text'}].", None
            return True, "", inp_type or "text"
        if ce_true:
            return True, "", "contenteditable"
        return False, f"Expected textarea or text input, got <{tag}>. Click closer to the prompt box.", None

    if target_kind == "submit":
        reject = _is_attach_menu_submit_chrome(
            selector,
            label=str(meta.get("innerText") or meta.get("ariaLabel") or ""),
            meta=meta,
        )
        if reject:
            return False, reject, None
        if tag == "button":
            return True, "", None
        if tag == "input" and inp_type in _SUBMIT_INPUT_TYPES:
            return True, "", None
        if role == "button":
            return True, "", None
        return False, f"Expected a button (send/submit), got <{tag}>. Click the Send/Submit button.", None

    if target_kind == "response":
        if tag in ("button", "input", "textarea", "select"):
            return False, f"Expected a response container, not <{tag}>. Click the assistant reply text.", None
        if ce_true and tag in ("div", "span", "p") and not role:
            return False, "Expected a response container, not the prompt input.", None
        return True, "", None

    if target_kind == "file_input":
        if tag == "input" and inp_type == "file":
            return True, "", "file"
        if tag in ("button", "a", "label") or role in ("button", "menuitem"):
            return True, "", "click"
        return False, f"Expected file input or upload button, got <{tag}>.", None

    if target_kind == "dropdown":
        if tag == "select" or role == "combobox":
            return True, "", "combobox" if role == "combobox" else "select"
        haspopup = (meta.get("ariaHaspopup") or "").lower()
        if tag == "button" and haspopup in ("listbox", "menu", "true"):
            return True, "", "combobox"
        return False, f"Expected dropdown/combobox, got <{tag}>.", None

    if target_kind == "upload_prep":
        if tag in ("button", "a") or role in ("button", "menuitem", "option"):
            return True, "", "click"
        return False, f"Expected menu/button trigger, got <{tag}>.", None

    if target_kind == "surface_prep":
        # Any on-page element is valid except the chat prompt field itself.
        if tag in ("textarea",) or (
            tag == "input" and inp_type not in ("button", "submit", "checkbox", "radio", "file")
        ):
            return False, f"Expected a prepare-page element, not the prompt field <{tag}>.", None
        return True, "", "click"

    return True, "", None


def _click_hint_block(click_hint: dict | None) -> str:
    if not click_hint:
        return ""
    parts = []
    tag = (click_hint.get("tag") or "").strip()
    role = (click_hint.get("role") or "").strip()
    input_type = (click_hint.get("inputType") or "").strip()
    inner = (click_hint.get("innerText") or "").strip()
    pick_kind = (click_hint.get("pickKind") or "").strip()
    if tag:
        parts.append(f"tag={tag}")
    if role:
        parts.append(f"role={role}")
    if input_type:
        parts.append(f"type={input_type}")
    if inner:
        parts.append(f'visible text="{inner[:120]}"')
    if pick_kind:
        parts.append(f"pick_kind={pick_kind}")
    if not parts:
        return ""
    return "User click metadata: " + ", ".join(parts) + "\n"


def _llm_extract_selector_from_click_context(
    html: str,
    page_url: str,
    *,
    target_kind: str,
    click_hint: dict | None = None,
) -> dict:
    """Derive a CSS selector via LangGraph step expert (legacy wrapper)."""
    from browser_bot.discovery_graph import run_discovery_expert

    expert = run_discovery_expert(
        target_kind,
        html,
        page_url,
        click_hint=click_hint,
    )
    selector = (expert.get("selector") or "").strip()
    if not selector:
        return {}
    out: dict = {"selector": selector}
    inp_type = str(expert.get("type") or "").strip().lower()
    if inp_type:
        out["type"] = inp_type
    return out


def _discovery_expert_log(page) -> list:
    log = getattr(page, "_genbounty_discovery_experts", None)
    if log is None:
        log = []
        setattr(page, "_genbounty_discovery_experts", log)
    return log


def _reset_discovery_expert_log(page) -> None:
    setattr(page, "_genbounty_discovery_experts", [])


async def _try_selector_attempts_for_step(
    page,
    attempts: list[tuple[str, str, dict]],
    *,
    target_kind: str,
) -> tuple[str, dict, str, str | None] | None:
    """
    Try ordered (source, selector, meta) pairs.
    Returns (selector, meta, source, fill_type) for the first visible + valid match.
    """
    failures: list[str] = []
    for source, selector, meta in attempts:
        if not await _verify_selector_on_page(page, selector):
            print(f"    {source} selector not visible on page: {selector}")
            failures.append(f"{source}: {selector} (not visible)")
            continue
        ok, reason, fill_type = await _validate_context_selector_for_step(
            page, selector, target_kind
        )
        if not ok:
            print(f"    Rejected {source} selector for {target_kind}: {reason}")
            failures.append(f"{source}: {selector} ({reason})")
            continue
        return selector, meta, source, fill_type
    if failures:
        setattr(page, "_genbounty_selector_attempt_failures", failures)
    return None


async def _resolve_llm_pick_event(
    page,
    event: dict,
    *,
    target_kind: str,
) -> dict | None:
    """Turn a pick_context browser event into a verified selector event via LLM."""
    html = (event.get("contextHtml") or "").strip()
    if not html:
        return None

    click_hint = {
        "tag": event.get("tag"),
        "innerText": event.get("innerText"),
        "inputType": event.get("inputType"),
        "role": event.get("role"),
        "pickKind": event.get("pickKind"),
    }
    await _manual_panel_show(
        page,
        "Discovery expert analyzing your click…",
        mode="busy",
        pick_hint="LangGraph expert extracting selector from nearby DOM context.",
    )
    from browser_bot.discovery_graph import run_discovery_expert

    try:
        expert = run_discovery_expert(
            target_kind,
            html,
            page.url,
            click_hint=click_hint,
        )
    except RuntimeError as exc:
        print(f"    [!] Discovery expert failed: {exc}")
        return {
            "type": "pick_failed",
            "error": f"Discovery expert unavailable: {exc}",
        }
    _discovery_expert_log(page).append(expert)
    llm_selector = (expert.get("selector") or "").strip()
    if llm_selector and is_unreliable_expert_selector(llm_selector, target_kind=target_kind):
        print(f"    expert {target_kind}: skipping unreliable LLM selector {llm_selector}")

    attempts = _build_verified_selector_attempts(
        llm_selector=llm_selector,
        llm_type=str(expert.get("type") or ""),
        html=html,
        target_kind=target_kind,
        click_hint=click_hint,
        browser_selector=str(event.get("browserSelector") or ""),
    )
    if not attempts:
        n_candidates = len(_collect_context_candidate_elements(html, target_kind))
        detail = expert.get("limitations") or expert.get("reasoning") or "no selector returned"
        if llm_selector:
            detail = f"LLM selector unusable ({llm_selector!r}); {detail}"
        return {
            "type": "pick_failed",
            "error": (
                f"Expert found no usable selector ({detail}). "
                f"{n_candidates} candidate(s) in click context - try clicking directly on the field."
            ),
        }

    picked = await _try_selector_attempts_for_step(page, attempts, target_kind=target_kind)
    if not picked:
        failures = getattr(page, "_genbounty_selector_attempt_failures", None) or []
        if failures:
            err_detail = "; ".join(failures[:4])
            if len(failures) > 4:
                err_detail += f" (+{len(failures) - 4} more)"
        else:
            tried = ", ".join(sel for _, sel, _ in attempts[:3])
            extra = f" (+{len(attempts) - 3} more)" if len(attempts) > 3 else ""
            err_detail = f"Tried: {tried}{extra}"
        return {
            "type": "pick_failed",
            "error": (
                f"No selector matched a visible target on the page. {err_detail} "
                + (
                    "Click the assistant reply text (not the prompt box)."
                    if target_kind == "response"
                    else "Click the on-page element to prepare (not the prompt box)."
                    if target_kind == "surface_prep"
                    else "Click directly on the editable field."
                )
            ),
        }

    selector, result, source, fill_type = picked
    if source in ("deterministic_fallback", "browser_pick"):
        print(f"    expert {target_kind}: using {source} {selector}")
        expert = {
            **expert,
            "selector": selector,
            "type": result.get("type") or expert.get("type"),
            "source": source,
            "confidence": "medium",
            "reasoning": (
                "Browser-computed selector from click target."
                if source == "browser_pick"
                else "Deterministic fallback from click-context HTML candidates."
            ),
        }
        log = _discovery_expert_log(page)
        if log:
            log[-1] = expert

    resolved = dict(event)
    resolved["type"] = "selector"
    resolved["selector"] = selector
    if event.get("wideContextHtml"):
        resolved["wideContextHtml"] = event["wideContextHtml"]
    if fill_type:
        resolved["fillType"] = fill_type
    elif result.get("type"):
        resolved["fillType"] = result["type"]
    meta = await _element_metadata_at_selector(page, selector)
    if meta.get("tag"):
        resolved["tag"] = meta["tag"]
    if meta.get("type"):
        resolved["inputType"] = meta["type"]
    if meta.get("role"):
        resolved["role"] = meta["role"]
    print(f"    {source} selector ({target_kind}): {selector}")
    return resolved


async def _process_manual_pick_event(
    page,
    event: dict,
    *,
    v2: bool,
    target_kind: str,
) -> dict:
    """Normalize v1/v2 pick events to a selector-bearing event or failure/skip."""
    if event.get("type") == "skip":
        return event
    if event.get("type") == "pick_failed":
        return event
    if v2 and event.get("type") == "pick_context":
        resolved = await _resolve_llm_pick_event(page, event, target_kind=target_kind)
        if not resolved:
            return {
                "type": "pick_failed",
                "error": "LLM could not identify a valid selector from that click.",
            }
        if resolved.get("type") == "pick_failed":
            return resolved
        return resolved
    if v2:
        got = event.get("type") or ("selector" if event.get("selector") else "unknown")
        return {
            "type": "pick_failed",
            "error": (
                f"V2 discovery expected a DOM context click (got {got!r}). "
                "The v2 handler may have been lost after navigation - try clicking again."
            ),
        }
    selector = (event.get("selector") or "").strip()
    if selector:
        return event
    return {"type": "pick_failed", "error": "No selector was captured from that click."}


def _input_validation_kind(inp: dict) -> str:
    """Map a saved input row to a context validation kind."""
    t = (inp.get("type") or "text").lower()
    if inp.get("upload_prep") or t == "click":
        return "upload_prep"
    if t == "file":
        return "file_input"
    if t in _DROPDOWN_INPUT_TYPES:
        return "dropdown"
    return "prompt_input"


def _submission_for_llm_reconcile(submission: dict) -> dict:
    """Snapshot of selectors Gemini should review/correct."""
    inputs_out = []
    for inp in submission.get("inputs") or []:
        if not isinstance(inp, dict):
            continue
        row = {"selector": inp.get("selector", ""), "type": inp.get("type", "text")}
        if inp.get("upload_prep"):
            row["upload_prep"] = True
        if inp.get("surface_prep"):
            row["surface_prep"] = True
        if inp.get("path_from"):
            row["path_from"] = inp["path_from"]
        inputs_out.append(row)
    return {
        "inputs": inputs_out,
        "submit_selector": submission.get("submit_selector") or "",
        "response_selector": submission.get("response_selector") or "",
        "response_capture_mode": submission.get("response_capture_mode") or "",
        "response_list_selector": submission.get("response_list_selector") or "",
        "response_role_selector": submission.get("response_role_selector") or "",
    }


def _llm_reconcile_submission_selectors(
    wide_html: str,
    page_url: str,
    submission: dict,
    step_expert_responses: list | None = None,
    *,
    multiturn: bool = False,
) -> dict:
    """Run LangGraph judge on wide composer HTML; returns final_submission dict."""
    from browser_bot.discovery_graph import run_discovery_judge

    judge_result = run_discovery_judge(
        wide_html,
        page_url,
        submission,
        step_expert_responses=step_expert_responses,
        multiturn=multiturn,
    )
    final = judge_result.get("final_submission")
    return final if isinstance(final, dict) else {}


async def _apply_reconciled_submission(
    page,
    submission: dict,
    reconciled: dict,
) -> list[str]:
    """Apply Gemini-corrected selectors when they validate on the live page."""
    lines: list[str] = []
    if not reconciled:
        return lines

    old_inputs = list(submission.get("inputs") or [])
    new_inputs = reconciled.get("inputs")
    if isinstance(new_inputs, list) and len(new_inputs) == len(old_inputs):
        for i, new_inp in enumerate(new_inputs):
            if not isinstance(new_inp, dict):
                continue
            new_sel = sanitize_discovered_selector(str(new_inp.get("selector") or "").strip())
            if not new_sel or is_ephemeral_selector(new_sel):
                if new_sel and is_ephemeral_selector(new_sel):
                    print(f"    reconcile: rejected input[{i}] {new_sel!r} - ephemeral/session-only attribute")
                continue
            old_sel = str(old_inputs[i].get("selector") or "").strip()
            if new_sel == old_sel:
                continue
            kind = _input_validation_kind(old_inputs[i])
            ok, reason, fill_type = await _validate_context_selector_for_step(
                page, new_sel, kind
            )
            if not ok or not await _verify_selector_on_page(page, new_sel):
                print(f"    reconcile: rejected input[{i}] {new_sel!r} - {reason or 'not visible'}")
                continue
            old_inputs[i]["selector"] = new_sel
            if fill_type and kind == "prompt_input":
                old_inputs[i]["type"] = fill_type
            lines.append(f"    reconcile input[{i}]: {old_sel} → {new_sel}")
        submission["inputs"] = old_inputs

    for key, kind in (("submit_selector", "submit"), ("response_selector", "response")):
        new_sel = sanitize_discovered_selector(
            str(reconciled.get(key) or submission.get(key) or "").strip()
        )
        old_sel = str(submission.get(key) or "").strip()
        if not new_sel or new_sel == old_sel:
            continue
        if is_ephemeral_selector(new_sel):
            print(f"    reconcile: rejected {key} {new_sel!r} - ephemeral/session-only attribute")
            continue
        ok, reason, _ = await _validate_context_selector_for_step(page, new_sel, kind)
        if not ok or not await _verify_selector_on_page(page, new_sel):
            print(f"    reconcile: rejected {key} {new_sel!r} - {reason or 'not visible'}")
            continue
        submission[key] = new_sel
        lines.append(f"    reconcile {key}: {old_sel} → {new_sel}")
        if key == "response_selector":
            analysis = await _analyze_response_capture_on_page(page, new_sel)
            for cap_line in _merge_response_capture_analysis(submission, new_sel, analysis):
                lines.append(f"    reconcile {cap_line.strip()}")

    for cap_key in (
        "response_capture_mode",
        "response_list_selector",
        "response_role_selector",
    ):
        if cap_key not in reconciled:
            continue
        val = reconciled.get(cap_key)
        if val is None or val == "":
            submission.pop(cap_key, None)
            continue
        if cap_key.endswith("_selector"):
            val = sanitize_discovered_selector(str(val).strip())
            if is_fragile_positional_selector(val):
                continue
        else:
            val = str(val).strip()
        old = submission.get(cap_key)
        if old == val:
            continue
        submission[cap_key] = val
        lines.append(f"    reconcile {cap_key}: {old} → {val}")

    return lines


async def _reconcile_v2_submission_from_wide_context(
    page,
    submission: dict,
    wide_html: str,
    *,
    multiturn: bool = False,
) -> list[str]:
    """Run LangGraph judge after response click; apply validated fixes."""
    if not (wide_html or "").strip():
        print(
            "  [~] Discovery judge skipped: no 8-level composer HTML "
            "(response click must use v2 pick_context)."
        )
        return []

    await _manual_panel_show(
        page,
        "Discovery judge reviewing full composer…",
        mode="busy",
        pick_hint=(
            "LangGraph wide experts + judge validating all selectors "
            + ("(multi-turn HTML)." if multiturn else "(single-turn HTML).")
        ),
    )
    step_experts = _discovery_expert_log(page)
    try:
        reconciled = _llm_reconcile_submission_selectors(
            wide_html,
            page.url,
            submission,
            step_expert_responses=step_experts,
            multiturn=multiturn,
        )
    except RuntimeError as exc:
        print(f"  [!] Discovery judge failed: {exc}")
        return []
    if not reconciled:
        print("  [~] Discovery judge: no final submission - keeping step-by-step selectors.")
        return []

    lines = await _apply_reconciled_submission(page, submission, reconciled)
    if lines:
        print("  [+] Discovery judge applied fixes:")
        for line in lines:
            print(line)
    else:
        print("  [+] Discovery judge: no selector changes needed.")
    return lines


def _manual_input_type(event: dict) -> str:
    override = (event.get("fillType") or "").strip().lower()
    if override:
        return override
    tag = (event.get("tag") or "").lower()
    input_type = (event.get("inputType") or "").lower()
    role = (event.get("role") or "").lower()
    if role == "combobox" or input_type == "combobox":
        return "combobox"
    if tag == "select":
        return "select"
    if tag == "textarea":
        return "textarea"
    if tag == "input":
        return input_type or "text"
    return "contenteditable" if tag in ("div", "span", "p") else "text"


_DROPDOWN_INPUT_TYPES = frozenset({"select", "combobox"})
_MENUITEM_ROLES = frozenset({"menuitem", "option", "menuitemradio", "menuitemcheckbox"})
_UPLOAD_MENU_KEYWORDS = (
    "upload",
    "file",
    "attach",
    "attachment",
    "photo",
    "document",
    "media",
)
_ATTACHMENT_TRIGGER_KEYWORDS = (
    "attach",
    "upload",
    "file",
    "plus",
    "composer-plus",
    "add",
)

# ChatGPT / chat UIs often put attach/menu next to Send; discovery must not save those.
_SUBMIT_ATTACH_CHROME_SEL_RE = re.compile(
    r"composer-plus|more[\s_-]*actions|#composer-plus|"
    r"data-testid\s*=\s*[\"'][^\"']*(attach|upload|plus|file)|"
    r"aria-label\s*=\s*[\"'][^\"']*(attach|upload|more\s+actions)|"
    r"aria-haspopup\s*=\s*[\"']?menu",
    re.IGNORECASE,
)
_SUBMIT_ATTACH_CHROME_LABEL_RE = re.compile(
    r"^\s*(\+|more\s+actions|attach(\s+file)?|upload(\s+file)?|"
    r"add\s+(files?|photos?|images?|media)|open\s+.*(menu|actions))\s*$",
    re.IGNORECASE,
)
_SUBMIT_SEND_SIGNAL_RE = re.compile(
    r"send(-button)?|submit|data-testid\s*=\s*[\"']send",
    re.IGNORECASE,
)


def _is_attach_menu_submit_chrome(
    selector: str,
    *,
    label: str = "",
    meta: dict | None = None,
) -> str | None:
    """Return reject reason when selector/label is attach/menu chrome, not Send."""
    sel = (selector or "").strip()
    blob_parts = [sel, label or ""]
    if isinstance(meta, dict):
        blob_parts.extend(
            str(meta.get(k) or "")
            for k in (
                "ariaLabel",
                "aria-label",
                "dataTestId",
                "data-testid",
                "id",
                "innerText",
                "ariaHaspopup",
            )
        )
    blob = " ".join(blob_parts).strip()
    label_probe = " ".join(str(label or meta and meta.get("innerText") or "").split())
    if _SUBMIT_SEND_SIGNAL_RE.search(sel) or _SUBMIT_SEND_SIGNAL_RE.search(blob):
        # Explicit send markers win over a nearby haspopup=menu false positive.
        if "send" in sel.lower() or "send" in blob.lower():
            return None
    if label_probe and _SUBMIT_ATTACH_CHROME_LABEL_RE.match(label_probe):
        return f"attach/menu chrome {label_probe!r} - click Send, not More actions / attach"
    if _SUBMIT_ATTACH_CHROME_SEL_RE.search(sel):
        return "attach/menu chrome selector - click Send, not More actions / attach"
    meta = meta or {}
    haspopup = str(meta.get("ariaHaspopup") or meta.get("aria-haspopup") or "").lower()
    aria = str(meta.get("ariaLabel") or meta.get("aria-label") or "").lower()
    testid = str(meta.get("dataTestId") or meta.get("data-testid") or "").lower()
    if haspopup == "menu" and not _SUBMIT_SEND_SIGNAL_RE.search(aria + testid + sel):
        return "menu trigger (aria-haspopup=menu) - click Send, not the attach/plus control"
    if any(k in aria or k in testid for k in ("attach", "upload", "more actions", "composer-plus")):
        return f"attach/menu chrome {aria or testid!r} - click Send, not More actions / attach"
    return None


def _file_input_config(selector: str) -> dict:
    return {
        "selector": selector,
        "type": "file",
        "path_from": "payload",
    }


def _role_text_selector(event: dict) -> str | None:
    """Prefer Playwright role+label selectors for menu items over brittle DOM paths."""
    role = (event.get("role") or "").lower()
    if role not in ("menuitem", "option", "menuitemradio", "menuitemcheckbox"):
        return None
    text = " ".join(str(event.get("innerText") or "").split()).strip()
    if len(text) < 2 or len(text) > 120:
        return None
    return f'[role="{role}"]:has-text({json.dumps(text)})'


_HAS_TEXT_LABEL_RE = re.compile(
    r"""has-text\(\s*(['"])(.*?)\1\s*\)""",
    re.IGNORECASE | re.DOTALL,
)

_SCORE_NOISE_RE = re.compile(r"\b\d+\s*/\s*\d+\b|\b\d+%\b")


def _clean_visible_label(text: str) -> str:
    """Normalize visible text and drop trailing score fractions (e.g. 17/100)."""
    s = _SCORE_NOISE_RE.sub(" ", text or "")
    return " ".join(s.split()).strip()


def _gate_label_from_event(event: dict) -> str:
    """Short stable label from clicked element text (site-agnostic).

    Prefers the first short line (card/button titles usually lead), strips score
    fractions, and truncates long single-line blobs to a compact prefix.
    """
    raw = str(event.get("innerText") or "").strip()
    if not raw:
        sel = str(event.get("selector") or event.get("browserSelector") or "")
        m = _HAS_TEXT_LABEL_RE.search(sel)
        return (m.group(2).strip() if m else "")
    lines = [" ".join(ln.split()) for ln in raw.splitlines() if ln.strip()]
    cleaned = [_clean_visible_label(ln) for ln in lines]
    short_lines = [ln for ln in cleaned if 1 < len(ln) <= 60]
    if short_lines:
        picked = short_lines[0]
        words = picked.split()
        # Long single-line blobs: keep a compact title prefix for :text-is leaves.
        if len(words) > 3 or len(picked) > 36:
            return " ".join(words[:2]).strip()
        return picked
    collapsed = _clean_visible_label(" ".join(raw.split()))
    if 1 < len(collapsed) <= 60:
        return collapsed
    words = collapsed.split()
    return " ".join(words[:5]).strip()


def _labeled_gate_selector(event: dict, *, loose: bool = False) -> str | None:
    """Build a replay-friendly has-text / :text-is selector for any click host.

    ``loose`` is accepted for call-site compatibility; any short visible label is
    enough for non-control hosts (cards, rows, tabs).
    """
    del loose  # all short labels are eligible
    menu = _role_text_selector(event)
    if menu:
        return menu
    label = _gate_label_from_event(event)
    if len(label) < 2 or len(label) > 80:
        return None
    role = (event.get("role") or "").lower()
    tag = (event.get("tag") or "").lower()
    lit = json.dumps(label)
    if tag == "button" or role == "button":
        return f"button:has-text({lit}), [role=\"button\"]:has-text({lit})"
    if tag == "a" or role == "link":
        return f"a:has-text({lit}), [role=\"link\"]:has-text({lit})"
    # Cards / divs / plain hosts — prefer exact leaf text (:text-is) so Run can
    # promote to the nearest pointer host. Bare text=/has-text also match
    # ancestor panels that merely contain the label.
    parts: list[str] = [f":text-is({lit})"]
    words = label.split()
    if len(words) >= 3:
        short = " ".join(words[:2])
        if 1 < len(short) <= 60:
            parts.insert(0, f":text-is({json.dumps(short)})")
    if tag and tag not in ("html", "body"):
        parts.append(f"{tag}:has-text({lit})")
    parts.extend(
        [
            f"button:has-text({lit})",
            f"[role=\"button\"]:has-text({lit})",
            f"a:has-text({lit})",
            f"[role=\"link\"]:has-text({lit})",
            f"text={label}",
        ]
    )
    return ", ".join(parts)


def _best_action_selector(event: dict) -> str:
    """Best selector for a click/upload-prep pick (role+text beats Radix structural paths)."""
    labeled = _labeled_gate_selector(event)
    if labeled:
        return labeled
    raw = sanitize_discovered_selector(
        str(event.get("selector") or event.get("browserSelector") or "").strip()
    )
    return raw


def _upload_prep_input_config(event: dict, *, surface: bool = False) -> dict | None:
    """Map a menu/upload pick to a click-or-dropdown prep step (not a prompt field)."""
    sel = _best_action_selector(event)
    if not sel:
        return None
    manual_type = _manual_input_type(event)
    if manual_type in _DROPDOWN_INPUT_TYPES:
        row = {"selector": sel, "type": manual_type, "upload_prep": True}
    else:
        row = {"selector": sel, "type": "click", "upload_prep": True}
    if surface:
        row["surface_prep"] = True
        label = _gate_label_from_event(event)
        if label:
            row["name"] = label
            role = (event.get("role") or "").lower()
            tag = (event.get("tag") or "").lower()
            if role in ("button", "link", "menuitem", "option"):
                row["role"] = role
            elif tag == "button":
                row["role"] = "button"
            elif tag == "a":
                row["role"] = "link"
            # Plain div/span cards: leave role unset (do not invent role=button).
    return row


def _select_input_config(selector: str, kind: str = "select") -> dict:
    return {
        "selector": selector,
        "type": kind if kind in ("select", "combobox") else "select",
    }


def _upload_prep_config(
    selector: str, *, kind: str = "click", surface: bool = False
) -> dict:
    """Upload/menu prep step saved before file or prompt inputs.

    When ``surface=True``, also marks ``surface_prep`` so text-only runs still
    replay the click (level / Start / notice gates).
    """
    if kind in _DROPDOWN_INPUT_TYPES:
        row = {"selector": selector, "type": kind, "upload_prep": True}
    else:
        row = {"selector": selector, "type": "click", "upload_prep": True}
    if surface:
        row["surface_prep"] = True
    return row


_START_SURFACE_EXCLUDE_RE = re.compile(
    r"^\s*(send|submit|post|ask|go|save|next|continue|cancel|close|ok)\s*$",
    re.IGNORECASE,
)


def _detect_start_surface_from_html(html: str) -> list[dict]:
    """Heuristic Start/Begin challenge CTAs (same labels as ensure_submission_surface_ready)."""
    from browser_bot.submit.common import (
        _START_SURFACE_BUTTON_RE,
        _normalize_menu_label,
    )

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html or "", "html.parser")
    out: list[dict] = []
    seen: set[str] = set()
    candidates = []
    for tag in soup.find_all(["button", "a"]):
        candidates.append(tag)
    for tag in soup.find_all(attrs={"role": True}):
        role = (tag.get("role") or "").lower()
        if role in ("button", "link"):
            candidates.append(tag)

    for tag in candidates:
        label = _normalize_menu_label(tag.get_text(" ", strip=True))
        if not label or len(label) > 80:
            continue
        if _START_SURFACE_EXCLUDE_RE.match(label):
            continue
        if not _START_SURFACE_BUTTON_RE.match(label):
            continue
        sel = ""
        if tag.get("id"):
            sel = f"#{tag['id']}"
        else:
            role = (tag.get("role") or "").lower()
            name = (tag.name or "button").lower()
            if role == "button" or name == "button":
                sel = f'button:has-text({json.dumps(label)}), [role="button"]:has-text({json.dumps(label)})'
            elif name == "a" or role == "link":
                sel = f'a:has-text({json.dumps(label)}), [role="link"]:has-text({json.dumps(label)})'
            else:
                sel = f'{name}:has-text({json.dumps(label)})'
        if not sel or sel in seen:
            continue
        seen.add(sel)
        out.append(_upload_prep_config(sel, kind="click", surface=True))
    return out


def _surface_gate_label_key(selector: str) -> str:
    """Normalize has-text / quoted label from a selector for dedupe across variants."""
    sel = (selector or "").strip()
    if not sel:
        return ""
    labels = [m.group(2).strip().lower() for m in _HAS_TEXT_LABEL_RE.finditer(sel)]
    if labels:
        return " | ".join(labels)
    # text=… Playwright selector
    m = re.match(r"^text=(.+)$", sel, re.IGNORECASE)
    if m:
        return m.group(1).strip().lower()
    return sel.lower()


def _merge_surface_pre_steps(
    recorded: list[dict] | None,
    heuristic: list[dict] | None,
) -> list[dict]:
    """Prefer operator-recorded gates; add heuristic Start CTAs only when label is new."""
    out: list[dict] = []
    seen_sel: set[str] = set()
    seen_labels: set[str] = set()
    for row in recorded or []:
        if not isinstance(row, dict):
            continue
        sel = str(row.get("selector") or "").strip()
        if not sel or sel in seen_sel:
            continue
        seen_sel.add(sel)
        label = _surface_gate_label_key(sel)
        if label:
            seen_labels.add(label)
        out.append(dict(row))
    for row in heuristic or []:
        if not isinstance(row, dict):
            continue
        sel = str(row.get("selector") or "").strip()
        if not sel or sel in seen_sel:
            continue
        label = _surface_gate_label_key(sel)
        if label and label in seen_labels:
            continue
        # Also skip if any recorded label is a substring match (CTA wording variants).
        if label and any(label in prev or prev in label for prev in seen_labels if prev):
            continue
        seen_sel.add(sel)
        if label:
            seen_labels.add(label)
        out.append(dict(row))
    return out


_SURFACE_PREP_CHROME_LABEL_RE = re.compile(
    r"^\s*(collapse|expand|close|cancel|back|go\s+back|menu|share|info|preview|"
    r"log\s*in|sign\s*in|log\s*in\s+or\s+sign\s*up|sign\s*up|register)\s*$",
    re.IGNORECASE,
)


def _is_rejected_surface_prep_selector(selector: str, *, inner_text: str = "") -> str | None:
    """Return a short reject reason when the pick is UI chrome (not a prepare element).

    Pre-steps intentionally allow brittle nth-of-type paths: configure rewrites them
    to has-text/text= when any short label is available. Only empty selectors and
    obvious chrome (Collapse/Close/…) are rejected here.
    """
    sel = (selector or "").strip()
    if not sel:
        return "empty selector"
    label = " ".join(str(inner_text or "").split()).strip() or _surface_gate_label_key(sel)
    chrome_probe = " ".join((label.splitlines() or [label])[0].split()).strip()
    if chrome_probe and _SURFACE_PREP_CHROME_LABEL_RE.match(chrome_probe):
        return f"UI chrome {chrome_probe!r} - pick a different on-page element"
    return None


def _is_rejected_initial_popup_selector(selector: str) -> str | None:
    """Reject only empty/brittle selectors - Close/Accept are valid popup dismissals."""
    sel = (selector or "").strip()
    if not sel:
        return "empty selector"
    if _HAS_TEXT_LABEL_RE.search(sel) or sel.lower().startswith("text="):
        return None
    if is_fragile_positional_selector(sel):
        return "brittle nth-of-type path - click Accept / Close / Got it on the popup"
    return None


def _surface_prep_row_from_pick(event: dict) -> dict | None:
    """Build a surface_prep click row from a pick event (v1 or v2)."""
    # Normalize browserSelector onto selector so labeled rewrite sees it.
    ev = dict(event)
    if not (ev.get("selector") or "").strip() and (ev.get("browserSelector") or "").strip():
        ev["selector"] = str(ev.get("browserSelector") or "").strip()

    def _with_name_role(row: dict) -> dict:
        label = _gate_label_from_event(ev)
        if label:
            row["name"] = label
            role = (ev.get("role") or "").lower()
            tag = (ev.get("tag") or "").lower()
            if role in ("button", "link", "menuitem", "option"):
                row["role"] = role
            elif tag == "button":
                row["role"] = "button"
            elif tag == "a":
                row["role"] = "link"
            # Plain div/span cards: leave role unset (do not invent role=button).
        return row

    # Prefer a loose labeled rewrite first (any short visible text → has-text/text=).
    labeled = _labeled_gate_selector(ev, loose=True)
    if labeled:
        return _with_name_role(_upload_prep_config(labeled, kind="click", surface=True))

    cfg = _upload_prep_input_config(ev, surface=True)
    if cfg:
        sel = str(cfg.get("selector") or "").strip()
        # Rewrite brittle / generic paths (button[type=button]) to has-text when possible.
        if (
            is_fragile_positional_selector(sel)
            or is_generic_click_selector(sel)
            or not sel
        ):
            labeled2 = _labeled_gate_selector(ev, loose=True)
            if labeled2:
                cfg = dict(cfg)
                cfg["selector"] = labeled2
                return _with_name_role(cfg)
        if is_generic_click_selector(sel):
            return None
        return _with_name_role(cfg)
    browser_sel = sanitize_discovered_selector(
        str(ev.get("browserSelector") or ev.get("selector") or "").strip()
    )
    if browser_sel and not is_generic_click_selector(browser_sel):
        return _with_name_role(_upload_prep_config(browser_sel, kind="click", surface=True))
    labeled3 = _labeled_gate_selector(ev, loose=True)
    if labeled3:
        return _with_name_role(_upload_prep_config(labeled3, kind="click", surface=True))
    return None


async def _manual_pick_action_once(
    page,
    message: str,
    *,
    skip_action: str = "Skip",
    allow_action: bool = True,
    pick_hint: str | None = None,
    step_number: int | None = None,
    step_total: int | None = None,
    step_name: str | None = None,
    do_now: str | None = None,
    tip: str | None = None,
    saved_lines: list[str] | None = None,
    warn: str | None = None,
    step_title: str | None = None,
) -> dict | None:
    """One action click or Skip; keep raw pick_context/selector (no LLM rewrite).

    Used for initial popup dismiss so the click is saved even when v2 discovery is on.
    """
    base_message = message
    cur_warn = (warn or "").strip()
    while True:
        event = await _manual_panel_event(
            page,
            base_message,
            mode="pick",
            action=skip_action,
            allow_action=allow_action,
            pick_hint=pick_hint,
            step_number=step_number,
            step_total=step_total,
            step_name=step_name,
            do_now=do_now,
            tip=tip,
            saved_lines=saved_lines,
            warn=cur_warn,
            step_title=step_title,
        )
        et = (event.get("type") or "").strip()
        if et in ("skip", "continue"):
            return None
        if et == "pick_failed":
            cur_warn = (event.get("error") or "Could not register that click.").strip()
            continue
        if et == "pick_context":
            if (event.get("browserSelector") or event.get("selector") or "").strip():
                # Promote browserSelector so _surface_prep_row_from_pick can use it.
                if not (event.get("selector") or "").strip():
                    event = dict(event)
                    event["selector"] = str(event.get("browserSelector") or "").strip()
                return event
            cur_warn = f"No selector from that click. Click the control again, or {skip_action}."
            continue
        if et == "selector" or (event.get("selector") or "").strip():
            return event
        cur_warn = f"Click not recognized. Try again, or {skip_action}."


async def _page_has_open_modal_overlay(page) -> bool:
    """True when a blocking dialog/backdrop is open (same idea as runtime dismiss)."""
    try:
        from browser_bot.submit.common import _page_has_blocking_overlay

        return bool(await _page_has_blocking_overlay(page))
    except Exception:
        return False


async def _configure_initial_popup_pre_step(
    page,
    *,
    step_label: str,
    v2: bool = False,
    require_if_overlay: bool = True,
) -> dict | None:
    """Record at most one click for the first landing popup (cookie/consent/modal).

    One click saves immediately (no confirm). Skip if none.
    Does not use the v2 LLM expert - raw click selector is enough and more reliable.

    When ``require_if_overlay`` is True and a modal is still open after Skip, re-prompt
    once so Continue cannot be used as the only way to clear it.
    """
    del v2
    print(f"  [{step_label}] Initial popup (one click or Skip)...")

    async def _once(
        *,
        step_name: str,
        do_now: str,
        tip: str,
        hint: str,
    ) -> dict | None:
        fields = _panel_step_fields(step_label, step_name, do_now, tip=tip)
        event = await _manual_pick_action_once(
            page,
            fields["message"],
            skip_action="Skip",
            allow_action=True,
            pick_hint=hint,
            step_number=fields["stepNumber"],
            step_total=fields["stepTotal"],
            step_name=fields["stepName"],
            do_now=fields["doNow"],
            tip=fields["tip"],
            step_title=fields["step_title"],
        )
        if not event:
            return None
        cfg = _surface_prep_row_from_pick(event)
        if not cfg:
            print("    [~] Could not build a popup selector - try Close / Accept on the dialog.")
            return None
        sel = str(cfg.get("selector") or "").strip()
        reject = _is_rejected_initial_popup_selector(sel)
        if reject:
            print(f"    [~] Rejected popup click ({reject}): {sel}")
            return None
        print(
            f"    initial popup: {sel} "
            f"(type={cfg.get('type', 'click')}, surface_prep=true)"
        )
        return cfg

    cfg = await _once(
        step_name="Close a popup",
        do_now="Click the close / accept control on any blocking dialog",
        tip="Skip if nothing is blocking the page",
        hint="Click the dialog control once — or Skip.",
    )
    if cfg:
        return cfg

    if require_if_overlay and await _page_has_open_modal_overlay(page):
        print("    [!] Popup still open after Skip - asking again so it can be recorded.")
        cfg = await _once(
            step_name="Popup still open",
            do_now="Click close / accept on the modal that is still blocking the page",
            tip="Skip again only if runs should handle it without a recorded click",
            hint="Click close / accept on the open modal — or Skip again.",
        )
        if cfg:
            return cfg

    print("    initial popup: (none)")
    return None


async def _manual_continue_after_popup(
    page,
    *,
    step_label: str,
    step_title: str,
    message: str,
    inputs: list[dict],
    continue_step_label: str | None = None,
) -> dict | None:
    """Continue for start URL, but re-record popup first if a modal is still open."""
    popup_extra: dict | None = None
    has_prep = any(
        isinstance(r, dict) and r.get("surface_prep") and (r.get("type") or "click") == "click"
        for r in inputs
    )
    if (not has_prep) and await _page_has_open_modal_overlay(page):
        print("  [!] Modal still open - record popup dismiss before Continue.")
        popup_extra = await _configure_initial_popup_pre_step(
            page,
            step_label=step_label,
            v2=False,
            require_if_overlay=False,
        )
        if not popup_extra and await _page_has_open_modal_overlay(page):
            print("    [~] Continuing with popup still open (not recorded).")

    cont_label = continue_step_label or "2/8"
    fields = _panel_step_fields(
        cont_label,
        "Confirm the page",
        "Make sure you are on the chat UI, then Continue",
    )
    await _manual_continue_confirmed(
        page,
        fields["message"] or message,
        step_title=step_title or fields["step_title"],
        build_summary=lambda: f"start_url:\n{page.url}",
        action="Continue",
        step_number=fields["stepNumber"],
        step_total=fields["stepTotal"],
        step_name=fields["stepName"],
        do_now=fields["doNow"],
    )
    return popup_extra


async def _configure_surface_pre_steps(
    page,
    *,
    step_label: str,
    v2: bool = False,
    ui_only: bool = False,
) -> list[dict]:
    """Record ordered click gates (tabs/levels/Start) as surface_prep inputs.

    One page click = one saved pre-step (no confirm dialog per click). Done finishes.
    Clicks are allowed through so the live UI advances.
    Uses raw browser selectors (no v2 LLM) so clicks that advance the page are
    actually persisted — same reliability path as the initial popup step.
    Initial cookie/consent popups belong in `_configure_initial_popup_pre_step`.
    """
    del ui_only, v2
    rows: list[dict] = []
    seen: set[str] = set()
    seen_labels: set[str] = set()
    last_warn = ""
    print(f"  [{step_label}] Recording surface pre-steps (one click each; Done when finished)...")
    while True:
        saved_lines = [str(r.get("selector") or "").strip() for r in rows if r.get("selector")]
        if rows:
            do_now = "Click on any additional blocking elements, then wait"
        else:
            do_now = "Some chat interfaces require additional steps like clicking a tab or toggle, do this now, then wait"
        fields = _panel_step_fields(
            step_label,
            "Prepare the page",
            do_now,
            tip=(
                "Any element that blocks the prompt — tabs, cards, buttons, notices. "
                "Done if none. Wait for Saved (N) before the next click"
            ),
            saved_lines=saved_lines,
            warn=last_warn,
        )
        event = await _manual_pick_action_once(
            page,
            fields["message"],
            skip_action="Done",
            allow_action=True,
            pick_hint="One click, then wait — or Done.",
            step_number=fields["stepNumber"],
            step_total=fields["stepTotal"],
            step_name=fields["stepName"],
            do_now=fields["doNow"],
            tip=fields["tip"],
            saved_lines=fields["savedLines"],
            warn=fields["warn"],
            step_title=fields["step_title"],
        )
        if not event:
            break
        last_warn = ""

        cfg = _surface_prep_row_from_pick(event)
        if not cfg:
            last_warn = "Could not build a selector - click the element again (prefer labeled text)."
            print(f"    [~] {last_warn}")
            continue
        sel = str(cfg.get("selector") or "").strip()
        inner = str(event.get("innerText") or cfg.get("name") or "")
        reject = _is_rejected_surface_prep_selector(sel, inner_text=inner)
        if reject:
            # Last chance: rebuild from any short visible label.
            labeled = _labeled_gate_selector(event, loose=True)
            if labeled:
                cfg = dict(cfg)
                cfg["selector"] = labeled
                sel = labeled
                reject = _is_rejected_surface_prep_selector(sel, inner_text=inner)
            if reject:
                last_warn = f"Rejected ({reject}). Click a different element."
                print(f"    [~] Rejected pre-step ({reject}): {sel}")
                continue
        label_key = _surface_gate_label_key(sel) or (cfg.get("name") or "").strip().lower()
        if sel in seen or (label_key and label_key in seen_labels):
            last_warn = (
                f"That looked like an element already saved ({sel}). "
                "Click the next distinct element."
            )
            print(f"    [~] Duplicate pre-step skipped: {sel}")
            continue
        seen.add(sel)
        if label_key:
            seen_labels.add(label_key)
        rows.append(cfg)
        print(
            f"    pre-step: {sel} "
            f"(type={cfg.get('type', 'click')}, upload_prep=true, surface_prep=true)"
        )
    if rows:
        print(f"    surface pre-steps: {len(rows)} click(s)")
    else:
        print("    surface pre-steps: (none)")
    return rows


def _phrase_for_response_ignore(text: str) -> str:
    """Normalize clicked intro/welcome text into a response_ignore_substrings phrase."""
    from browser_bot.submit.response_boilerplate import _normalize_block_substring

    s = " ".join((text or "").split()).strip()
    if len(s) < 8:
        return ""
    if len(s) > 240:
        s = s[:240]
        if " " in s:
            s = s.rsplit(" ", 1)[0].strip()
    return _normalize_block_substring(s)


def _merge_response_ignore_into_submission(submission: dict, text: str) -> str | None:
    """Append an ignore phrase to submission.response_ignore_substrings. Return phrase or None."""
    phrase = _phrase_for_response_ignore(text)
    if not phrase:
        return None
    raw = submission.get("response_ignore_substrings") or []
    items: list[str] = []
    if isinstance(raw, str):
        items = [p.strip() for p in raw.split(",") if p.strip()]
    elif isinstance(raw, list):
        items = [str(x).strip() for x in raw if str(x or "").strip()]
    lower = {x.lower() for x in items}
    if phrase.lower() in lower:
        return None
    items.append(phrase)
    submission["response_ignore_substrings"] = items
    return phrase


async def _intro_text_from_pick(page, event: dict) -> str:
    """Best-effort visible text from an intro/welcome click (panel clip may be short)."""
    raw = " ".join(str(event.get("innerText") or "").split()).strip()
    sel = sanitize_discovered_selector(
        str(event.get("browserSelector") or event.get("selector") or "").strip()
    )
    if not sel:
        return raw
    try:
        loc = page.locator(sel).first
        if await loc.count() < 1:
            return raw
        fuller = " ".join((await loc.inner_text(timeout=2000) or "").split()).strip()
        if len(fuller) > len(raw):
            return fuller
    except Exception:
        pass
    return raw


async def _manual_pick_text_once(
    page,
    message: str,
    *,
    skip_action: str = "Done",
    pick_hint: str | None = None,
    step_number: int | None = None,
    step_total: int | None = None,
    step_name: str | None = None,
    do_now: str | None = None,
    tip: str | None = None,
    saved_lines: list[str] | None = None,
    warn: str | None = None,
    step_title: str | None = None,
) -> dict | None:
    """Wait for one text-bubble click or Done; keep raw pick_context/selector (no LLM rewrite).

    Guided v2 pages emit pick_context - accepting that payload is required so welcome
    clicks are not treated as a silent Done.
    """
    cur_warn = (warn or "").strip()
    while True:
        event = await _manual_panel_event(
            page,
            message,
            mode="pick",
            action=skip_action,
            allow_action=False,
            pick_hint=pick_hint,
            # response pickKind → hover/target resolution for message bubbles
            pick_kind="response",
            step_number=step_number,
            step_total=step_total,
            step_name=step_name,
            do_now=do_now,
            tip=tip,
            saved_lines=saved_lines,
            warn=cur_warn,
            step_title=step_title,
        )
        et = (event.get("type") or "").strip()
        if et in ("skip", "continue"):
            return None
        if et == "pick_failed":
            cur_warn = (event.get("error") or "Could not register that click.").strip()
            continue
        if et == "pick_context":
            if (event.get("innerText") or "").strip() or (
                event.get("browserSelector") or ""
            ).strip():
                return event
            cur_warn = f"No text on that click. Try the greeting bubble, or {skip_action}."
            continue
        if et == "selector" or (event.get("selector") or "").strip():
            return event
        cur_warn = f"Click not recognized. Try again, or {skip_action}."


async def _configure_response_intro_ignore(
    page,
    submission: dict,
    *,
    site: str,
    component: str,
    step_label: str,
    v2: bool = False,
) -> list[str]:
    """Record welcome/intro bubbles to ignore before picking the real response container.

    One click = one ignored phrase (saved to response_ignore_substrings). Done finishes.
    Does not run the v2 selector expert - only the clicked text matters.
    """
    del v2
    saved: list[str] = []
    last_warn = ""
    print(
        f"  [{step_label}] Recording welcome/intro ignores "
        "(one click each; Done when finished)..."
    )
    while True:
        do_now = (
            "Click the next static welcome/intro text (not a real reply)"
            if saved
            else "Click static welcome/intro text (not a real reply)"
        )
        fields = _panel_step_fields(
            step_label,
            "Ignore greeting",
            do_now,
            tip="Done if none; one at a time",
            saved_lines=[repr(p) for p in saved],
            warn=last_warn,
        )
        event = await _manual_pick_text_once(
            page,
            fields["message"],
            skip_action="Done",
            pick_hint="Click the greeting once — or Done.",
            step_number=fields["stepNumber"],
            step_total=fields["stepTotal"],
            step_name=fields["stepName"],
            do_now=fields["doNow"],
            tip=fields["tip"],
            saved_lines=fields["savedLines"],
            warn=fields["warn"],
            step_title=fields["step_title"],
        )
        if not event:
            break
        last_warn = ""
        text = await _intro_text_from_pick(page, event)
        phrase = _merge_response_ignore_into_submission(submission, text)
        if not phrase:
            last_warn = (
                "Could not derive an ignore phrase (need ~8+ characters of visible text)."
            )
            print(f"    [~] {last_warn} Try again or Done.")
            continue
        saved.append(phrase)
        try:
            from browser_bot.submit.response_boilerplate import (
                persist_response_ignore_substring,
            )

            persist_response_ignore_substring(site, component, phrase)
        except Exception:
            pass
        print(f"    ignore intro: {phrase!r}")
    if saved:
        print(f"    welcome/intro ignores: {len(saved)}")
    else:
        print("    welcome/intro ignores: (none)")
    return saved


def _tag_attr_blob(tag) -> str:
    parts = [
        tag.get("id") or "",
        tag.get("aria-label") or "",
        tag.get("data-testid") or "",
        tag.get("name") or "",
        " ".join(tag.get("class") or []) if tag.has_attr("class") else "",
    ]
    return " ".join(parts).lower()


def _is_attachment_menu_trigger(tag) -> bool:
    if not tag or not getattr(tag, "name", None):
        return False
    blob = _tag_attr_blob(tag)
    if any(k in blob for k in _ATTACHMENT_TRIGGER_KEYWORDS):
        return True
    haspopup = (tag.get("aria-haspopup") or "").lower()
    return tag.name.lower() == "button" and haspopup == "menu"


def _is_upload_related_menuitem(text: str, tag) -> bool:
    from browser_bot.submit.common import (
        _UPLOAD_MENU_EXCLUDE_PATTERNS,
        _UPLOAD_MENU_LABEL_PATTERNS,
    )

    label = " ".join(text.split()).lower()
    if any(p.search(label) for p in _UPLOAD_MENU_EXCLUDE_PATTERNS):
        return False
    if any(p.search(label) for p in _UPLOAD_MENU_LABEL_PATTERNS):
        return True
    if any(k in label for k in _UPLOAD_MENU_KEYWORDS):
        return True
    blob = _tag_attr_blob(tag)
    return any(k in blob for k in _UPLOAD_MENU_KEYWORDS)


def _looks_like_click_target(selector: str) -> bool:
    sel = (selector or "").lower()
    return any(
        token in sel
        for token in (
            "button",
            "aria-haspopup",
            "composer-plus",
            "composer-plus-btn",
            '[role="button"]',
            "#composer-plus",
        )
    )


def _normalize_discovered_input(inp: dict, *, before_file: bool = False) -> dict | None:
    """Normalize HTML/LLM/live-scan rows into runtime input configs."""
    from browser_bot.submit.common import is_unstable_selector

    if not isinstance(inp, dict):
        return None
    row = dict(inp)
    sel = sanitize_discovered_selector(str(row.get("selector") or "").strip())
    if not sel:
        return None
    row["selector"] = sel

    inp_type = (row.get("type") or "text").lower()
    if inp_type == "file":
        row.setdefault("path_from", "payload")
        return row

    if inp_type == "click" or row.get("upload_prep"):
        row["upload_prep"] = True
        row["type"] = "click" if inp_type not in _DROPDOWN_INPUT_TYPES else inp_type
        return row

    if '[role="menuitem"]' in sel or '[role="option"]' in sel:
        return _upload_prep_config(sel, kind="click")

    if inp_type in _DROPDOWN_INPUT_TYPES:
        if before_file or row.get("upload_prep"):
            row["upload_prep"] = True
        return row

    if inp_type in {"text", "textarea", "contenteditable"} and _looks_like_click_target(sel):
        return _upload_prep_config(sel, kind="click")

    if inp_type in {"text", "textarea", "contenteditable"}:
        if is_unstable_selector(sel) and inp_type not in {"contenteditable", "textarea"}:
            if _looks_like_click_target(sel):
                return _upload_prep_config(sel, kind="click")
        return row

    return row


def _control_kind_for_html_tag(tag) -> str:
    tag_name = (tag.name or "").lower()
    role = (tag.get("role") or "").lower()
    haspopup = (tag.get("aria-haspopup") or "").lower()
    if tag_name == "select":
        return "select"
    if _is_attachment_menu_trigger(tag):
        return "click"
    if role == "combobox" or haspopup in ("listbox", "menu"):
        return "combobox"
    return "combobox"


async def _ensure_discovery_scan_helpers(page, *, v2: bool = False) -> None:
    """Ensure upload/dropdown scan functions exist (panel mode or guided UI-only mode)."""
    from browser_bot.discovery_ui_bridge import resolve_discovery_page, uses_ui_discovery

    page = resolve_discovery_page(page)
    if uses_ui_discovery(page):
        try:
            ready = await page.evaluate(
                "() => typeof window.__genbountyScanUploads === 'function'"
                " && typeof window.__genbountyScanSelects === 'function'"
            )
            if ready:
                return
        except Exception:
            pass
        try:
            await page.evaluate(_DISCOVERY_SCAN_ONLY_SCRIPT)
        except Exception:
            pass
        return
    await _install_manual_discovery_panel(page, v2=v2)


async def _detect_upload_capabilities(page) -> dict:
    """Scan the live page for file upload controls."""
    await _ensure_discovery_scan_helpers(page, v2=_page_uses_v2_discovery(page))
    try:
        result = await page.evaluate(
            """() => {
              if (typeof window.__genbountyScanUploads === "function") {
                return window.__genbountyScanUploads();
              }
              return { supports_upload: false, file_inputs: [] };
            }"""
        )
        if isinstance(result, dict):
            return result
    except Exception as exc:
        print(f"  [!] Upload scan failed: {exc}")
    return {"supports_upload": False, "file_inputs": []}


async def _detect_select_capabilities(page) -> dict:
    """Scan the live page for native selects and custom dropdown triggers."""
    await _ensure_discovery_scan_helpers(page, v2=_page_uses_v2_discovery(page))
    try:
        result = await page.evaluate(
            """() => {
              if (typeof window.__genbountyScanSelects === "function") {
                return window.__genbountyScanSelects();
              }
              return { supports_select: false, select_controls: [] };
            }"""
        )
        if isinstance(result, dict):
            return result
    except Exception as exc:
        print(f"  [!] Dropdown scan failed: {exc}")
    return {"supports_select": False, "select_controls": []}


def _pick_best_select_control(detection: dict) -> str | None:
    candidates = detection.get("select_controls") or []
    if not candidates:
        return None
    visible_unique = [c for c in candidates if c.get("visible") and c.get("unique")]
    if visible_unique:
        return str(visible_unique[0].get("selector") or "").strip() or None
    visible = [c for c in candidates if c.get("visible")]
    if visible:
        return str(visible[0].get("selector") or "").strip() or None
    return str(candidates[0].get("selector") or "").strip() or None


def _selector_for_html_tag(tag) -> str:
    return _selector_for_html_element(tag)


def _selector_for_html_element(tag) -> str:
    if tag.get("id"):
        return f"#{tag['id']}"
    name = tag.name or "div"
    for attr in ("data-testid", "name", "aria-label", "type", "role"):
        value = tag.get(attr)
        if value:
            return f'{name}[{attr}="{value}"]'
    return ""


def _detect_upload_menuitems_from_html(html: str) -> list[dict]:
    """Detect visible upload menu items (when the attachment menu is open at capture time)."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html, "html.parser")
    counts: dict[tuple[str, str], int] = {}
    candidates: list[tuple[str, str, object]] = []

    for tag in soup.find_all(attrs={"role": True}):
        role = (tag.get("role") or "").lower()
        if role not in _MENUITEM_ROLES:
            continue
        text = " ".join(tag.get_text().split()).strip()
        if len(text) < 2 or len(text) > 120:
            continue
        if not _is_upload_related_menuitem(text, tag):
            continue
        key = (role, text)
        counts[key] = counts.get(key, 0) + 1
        candidates.append((role, text, tag))

    out: list[dict] = []
    seen: set[str] = set()
    for role, text, _tag in candidates:
        if counts.get((role, text), 0) != 1:
            continue
        sel = f'[role="{role}"]:has-text({json.dumps(text)})'
        if sel in seen:
            continue
        seen.add(sel)
        out.append(_upload_prep_config(sel, kind="click"))
    return out


def _detect_uploads_from_html(html: str) -> list[dict]:
    """Detect file inputs from captured HTML (automated troubleshoot flow)."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    seen: set[str] = set()
    for tag in soup.find_all("input"):
        if (tag.get("type") or "").lower() != "file":
            continue
        selector = _selector_for_html_tag(tag)
        if not selector or selector in seen:
            continue
        seen.add(selector)
        out.append(_file_input_config(selector))
    return out


def _detect_selects_from_html(html: str) -> list[dict]:
    """Detect native selects and custom dropdown triggers from captured HTML."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    seen: set[str] = set()

    def add(tag, kind: str | None = None) -> None:
        if tag.has_attr("disabled"):
            return
        resolved_kind = kind or _control_kind_for_html_tag(tag)
        selector = _selector_for_html_element(tag)
        if not selector or selector in seen:
            return
        seen.add(selector)
        row = _upload_prep_config(selector, kind=resolved_kind)
        if resolved_kind in _DROPDOWN_INPUT_TYPES and not _is_attachment_menu_trigger(tag):
            row = _select_input_config(selector, resolved_kind)
            row["upload_prep"] = True
        out.append(row)

    for tag in soup.find_all("select"):
        add(tag, "select")

    for tag in soup.find_all(attrs={"role": "combobox"}):
        add(tag, "combobox")

    popup_selectors = (
        '[aria-haspopup="listbox"]',
        '[aria-haspopup="menu"]',
        'button[aria-haspopup="listbox"]',
    )
    for css in popup_selectors:
        for tag in soup.select(css):
            if tag.name and tag.name.lower() == "select":
                continue
            add(tag, "combobox")

    return out


def _inputs_from_live_scan(upload_info: dict, select_info: dict) -> tuple[list[dict], list[dict]]:
    """Convert live page scans (same JS as manual discovery) into input configs."""
    dropdown_rows: list[dict] = []
    file_rows: list[dict] = []

    best_file = _pick_best_file_input(upload_info or {})
    if best_file:
        file_rows.append(_file_input_config(best_file))

    controls = (select_info or {}).get("select_controls") or []
    auto_dropdown = _pick_best_select_control(select_info or {})
    if auto_dropdown:
        kind = next(
            (c.get("kind") for c in controls if c.get("selector") == auto_dropdown),
            "combobox",
        )
        dropdown_rows.append(_upload_prep_config(auto_dropdown, kind=kind or "combobox"))

    return dropdown_rows, file_rows


def _pick_best_file_input(detection: dict) -> str | None:
    candidates = detection.get("file_inputs") or []
    if not candidates:
        return None
    visible_unique = [c for c in candidates if c.get("visible") and c.get("unique")]
    if visible_unique:
        return str(visible_unique[0].get("selector") or "").strip() or None
    visible = [c for c in candidates if c.get("visible")]
    if visible:
        return str(visible[0].get("selector") or "").strip() or None
    return str(candidates[0].get("selector") or "").strip() or None


def _merge_detected_inputs(
    detected_dropdowns: list[dict],
    detected_files: list[dict],
    llm_inputs: list[dict],
    *,
    prep_menuitems: list[dict] | None = None,
    surface_pre_steps: list[dict] | None = None,
) -> list[dict]:
    """Place surface gates, upload prep, file inputs, then text prompt inputs in order."""
    has_files = bool(detected_files) or any(
        isinstance(inp, dict) and inp.get("type") == "file" for inp in llm_inputs
    )

    def _append(row: dict | None, bucket: list[dict], seen: set[str]) -> None:
        if not row:
            return
        selector = row.get("selector")
        if not selector or selector in seen:
            return
        bucket.append(row)
        seen.add(selector)

    seen: set[str] = set()
    surface_rows: list[dict] = []
    dropdown_rows: list[dict] = []
    prep_rows: list[dict] = []
    file_rows: list[dict] = []
    text_rows: list[dict] = []

    for raw in surface_pre_steps or []:
        _append(_normalize_discovered_input(raw, before_file=has_files), surface_rows, seen)
    for raw in detected_dropdowns:
        _append(_normalize_discovered_input(raw, before_file=has_files), dropdown_rows, seen)
    for raw in prep_menuitems or []:
        _append(_normalize_discovered_input(raw, before_file=has_files), prep_rows, seen)
    for raw in detected_files:
        _append(_normalize_discovered_input(raw, before_file=has_files), file_rows, seen)

    for inp in llm_inputs:
        if not isinstance(inp, dict):
            continue
        row = _normalize_discovered_input(inp, before_file=has_files)
        if not row:
            continue
        selector = row.get("selector")
        if not selector or selector in seen:
            continue
        inp_type = (row.get("type") or "text").lower()
        if row.get("upload_prep") or inp_type == "click":
            _append(row, prep_rows, seen)
        elif inp_type in _DROPDOWN_INPUT_TYPES:
            _append(row, dropdown_rows, seen)
        elif inp_type == "file":
            _append(row, file_rows, seen)
        else:
            _append(row, text_rows, seen)

    return surface_rows + dropdown_rows + prep_rows + file_rows + text_rows


def _merge_input_rows(*groups: list[dict]) -> list[dict]:
    """Dedupe input rows by selector, preserving first occurrence order."""
    out: list[dict] = []
    seen: set[str] = set()
    for group in groups:
        for row in group:
            if not isinstance(row, dict):
                continue
            selector = row.get("selector")
            if not selector or selector in seen:
                continue
            seen.add(selector)
            out.append(dict(row))
    return out


def _merge_upload_inputs(detected_files: list[dict], llm_inputs: list[dict]) -> list[dict]:
    """Backward-compatible wrapper for dropdown-less merge."""
    return _merge_detected_inputs([], detected_files, llm_inputs)


async def _first_visible_locator(page, selector: str):
    """Return the first visible Playwright locator for selector, or None."""
    if not selector:
        return None
    try:
        loc = page.locator(selector)
        count = await loc.count()
        if count == 0:
            return None
        for i in range(min(count, 25)):
            item = loc.nth(i)
            try:
                if await item.is_visible():
                    return item
            except Exception:
                continue
        return None
    except Exception:
        return None


async def _verify_selector_on_page(page, selector: str) -> bool:
    return (await _first_visible_locator(page, selector)) is not None


async def _configure_prerequisite_dropdown(
    page,
    *,
    step_label: str,
    select_info: dict,
    supports_upload: bool,
    v2: bool = False,
) -> dict | None:
    """
    Manual discovery step: optional dropdown/menu before file upload.
    Returns input config dict or None when skipped.
    """
    candidates = select_info.get("select_controls") or []
    auto_selector = _pick_best_select_control(select_info)
    upload_hint = (
        "Needed if upload sits behind a model/mode menu.\n\n"
        if supports_upload
        else ""
    )
    detected_hint = ""
    if candidates:
        detected_hint = f"Found {len(candidates)} dropdown(s)."
        if auto_selector:
            detected_hint += f" Suggested:\n{auto_selector}\n"
        detected_hint += "\n"

    tip_bits = [p for p in (upload_hint.strip(), detected_hint.strip(), "Skip if none") if p]
    fields = _panel_step_fields(
        step_label,
        "Dropdown (optional)",
        "Click the dropdown once to save it",
        tip=" ".join(tip_bits),
    )
    pick_event = await _manual_pick_or_skip(
        page,
        fields["message"],
        step_title=fields["step_title"],
        skip_summary="No dropdown will be saved.",
        allow_action=True,
        confirm_label="Dropdown selector",
        v2=v2,
        context_target="dropdown",
        step_number=fields["stepNumber"],
        step_total=fields["stepTotal"],
        step_name=fields["stepName"],
        do_now=fields["doNow"],
        tip=fields["tip"],
    )
    if not pick_event:
        return None
    if pick_event.get("use_auto") and auto_selector:
        verified = await _verify_selector_on_page(page, auto_selector)
        if verified:
            kind = next(
                (c.get("kind") for c in candidates if c.get("selector") == auto_selector),
                "select",
            )
            if supports_upload:
                return _upload_prep_input_config(
                    {"selector": auto_selector, "tag": kind or "select", "role": kind or ""}
                )
            return {"selector": auto_selector, "type": kind or "select"}
        return None
    selector = (pick_event.get("selector") or "").strip()
    if not selector:
        return None
    if supports_upload:
        return _upload_prep_input_config(pick_event)
    return {"selector": selector, "type": _manual_input_type(pick_event)}


async def _configure_multimodal_upload(
    page,
    *,
    step_label: str,
    auto_selector: str | None,
    dropdown_configured: bool = False,
    v2: bool = False,
) -> dict | None:
    """
    Manual discovery step: confirm or override auto-detected file input selector.
    Returns file input config dict or None when no upload should be configured.
    """
    dropdown_note = (
        "Open the menu from the previous step first if needed.\n\n"
        if dropdown_configured
        else "Open any model/mode menu first if upload is hidden.\n\n"
    )
    if auto_selector:
        verified = await _verify_selector_on_page(page, auto_selector)
        hint = "verified on page" if verified else "could not verify visibility"
        print(f"    suggested file selector ({hint}): {auto_selector}")
        fields = _panel_step_fields(
            step_label,
            "Upload setup",
            "Click the upload control to confirm, or Skip to keep the suggestion",
            tip=f"{dropdown_note.strip()} Suggested: {auto_selector}".strip(),
        )
        file_event = await _manual_pick_or_skip(
            page,
            fields["message"],
            step_title=fields["step_title"],
            skip_summary=f"Use auto-detected file selector:\n{auto_selector}",
            skip_use_auto=True,
            v2=v2,
            context_target="file_input",
            step_number=fields["stepNumber"],
            step_total=fields["stepTotal"],
            step_name=fields["stepName"],
            do_now=fields["doNow"],
            tip=fields["tip"],
        )
        if file_event:
            if file_event.get("use_auto") and verified:
                return _file_input_config(auto_selector)
            selector = (file_event.get("selector") or "").strip()
            if selector:
                return _file_input_config(selector)
        print("    auto file selector not verified - skipping file upload config")
        return None

    fields = _panel_step_fields(
        step_label,
        "Upload setup",
        "Click the upload control, or the menu that reveals it",
        tip=f"{dropdown_note.strip()} Skip if this target has no uploads".strip(),
    )
    file_event = await _manual_pick_or_skip(
        page,
        fields["message"],
        step_title=fields["step_title"],
        v2=v2,
        context_target="file_input",
        step_number=fields["stepNumber"],
        step_total=fields["stepTotal"],
        step_name=fields["stepName"],
        do_now=fields["doNow"],
        tip=fields["tip"],
    )
    if not file_event:
        return None
    selector = (file_event.get("selector") or "").strip()
    return _file_input_config(selector) if selector else None


async def _manual_pick_once(
    page,
    message: str,
    *,
    skip_action: str = "Skip",
    allow_action: bool = False,
    pick_hint: str | None = None,
    pick_kind: str | None = None,
    v2: bool = False,
    target_kind: str | None = None,
    step_number: int | None = None,
    step_total: int | None = None,
    step_name: str | None = None,
    do_now: str | None = None,
    tip: str | None = None,
    step_title: str | None = None,
) -> dict | None:
    """Wait for one element pick or skip; no confirm dialog."""
    resolved_kind = (target_kind or "").strip() or {
        "menu": "upload_prep",
        "upload": "file_input",
    }.get(pick_kind or "", "prompt_input")
    cur_warn = ""
    while True:
        event = await _manual_panel_event(
            page,
            message,
            mode="pick",
            action=skip_action,
            allow_action=allow_action,
            pick_hint=pick_hint,
            pick_kind=pick_kind,
            step_number=step_number,
            step_total=step_total,
            step_name=step_name,
            do_now=do_now,
            tip=tip,
            warn=cur_warn,
            step_title=step_title,
        )
        # Done/Skip; also accept continue (legacy primary-button mis-wire).
        if event.get("type") in ("skip", "continue"):
            return None
        event = await _process_manual_pick_event(
            page, event, v2=v2, target_kind=resolved_kind
        )
        if event.get("type") in ("skip", "continue"):
            return None
        if event.get("type") == "pick_failed":
            if not v2:
                return None
            cur_warn = (event.get("error") or "Could not register that click.").strip()
            continue
        selector = (event.get("selector") or "").strip()
        if not selector:
            return None
        return event


async def _resolve_upload_file_config(page, file_event: dict) -> dict | None:
    """Map an upload pick to a config input (file input, or click target when needed)."""
    sel = _best_action_selector(file_event)
    if not sel:
        return None

    tag = (file_event.get("tag") or "").lower()
    input_type = (file_event.get("inputType") or "").lower()
    role = (file_event.get("role") or "").lower()

    if tag == "input" and input_type == "file":
        return _file_input_config(sel)

    upload_info = await _detect_upload_capabilities(page)
    best = _pick_best_file_input(upload_info)
    if best and await _verify_selector_on_page(page, best):
        return _file_input_config(best)

    if role in ("menuitem", "option", "menuitemradio", "menuitemcheckbox"):
        return _upload_prep_input_config(file_event)

    return _file_input_config(sel)


async def _configure_upload_discovery_combined(
    page,
    *,
    step_label: str,
    select_info: dict,
    auto_file_selector: str | None,
    v2: bool = False,
) -> tuple[dict | None, dict | None]:
    """
    Adaptive upload discovery: 1-step when upload is directly visible, 2-step when
    a menu/dropdown click is required first.
    """
    step_title = f"Confirm step {step_label} - file upload setup"
    auto_dropdown = _pick_best_select_control(select_info)
    auto_block = ""
    if auto_dropdown:
        auto_block += f"Suggested menu:\n{auto_dropdown}\n\n"
    if auto_file_selector:
        auto_block += f"Suggested upload:\n{auto_file_selector}\n\n"

    while True:
        first_fields = _panel_step_fields(
            step_label,
            "Upload setup",
            "Click the upload control, or the menu that reveals it",
            tip=f"{auto_block.strip()} Skip if this target has no uploads".strip(),
        )
        first_event = await _manual_pick_once(
            page,
            first_fields["message"],
            skip_action="Skip",
            allow_action=True,
            pick_hint="Click upload or its menu — or Skip.",
            pick_kind="upload",
            v2=v2,
            step_number=first_fields["stepNumber"],
            step_total=first_fields["stepTotal"],
            step_name=first_fields["stepName"],
            do_now=first_fields["doNow"],
            tip=first_fields["tip"],
            step_title=step_title,
        )
        if not first_event:
            summary = "No menu or file upload will be saved for this component."
            if await _manual_step_confirm(page, step_title, summary):
                return None, None
            continue

        first_cfg = await _resolve_upload_file_config(page, first_event)
        if first_cfg and (first_cfg.get("type") == "file"):
            summary = f"Upload control (file):\n{first_cfg['selector']}"
            if await _manual_step_confirm(page, step_title, summary):
                return None, first_cfg
            continue

        dropdown_cfg = _upload_prep_input_config(first_event)
        file_fields = _panel_step_fields(
            step_label,
            "File upload",
            "Open the menu if needed, then click the upload control",
            tip=(
                f"Suggested: {auto_file_selector}. Skip if no file upload"
                if auto_file_selector
                else "Skip if no file upload"
            ),
        )
        file_event = await _manual_pick_once(
            page,
            file_fields["message"],
            skip_action="Skip",
            allow_action=False,
            pick_hint="Open the menu if needed, then click upload.",
            pick_kind="upload",
            v2=v2,
            step_number=file_fields["stepNumber"],
            step_total=file_fields["stepTotal"],
            step_name=file_fields["stepName"],
            do_now=file_fields["doNow"],
            tip=file_fields["tip"],
            step_title=step_title,
        )

        file_cfg = None
        if file_event:
            file_cfg = await _resolve_upload_file_config(page, file_event)
        elif auto_file_selector and await _verify_selector_on_page(page, auto_file_selector):
            file_cfg = _file_input_config(auto_file_selector)
        elif first_cfg and first_cfg.get("type") == "file":
            file_cfg = first_cfg

        summary_parts = []
        if dropdown_cfg:
            summary_parts.append(
                f"Menu/dropdown ({dropdown_cfg.get('type', 'select')}):\n{dropdown_cfg['selector']}"
            )
        if file_cfg:
            summary_parts.append(
                f"Upload control ({file_cfg.get('type', 'file')}):\n{file_cfg['selector']}"
            )
        summary = "\n\n".join(summary_parts)
        if await _manual_step_confirm(page, step_title, summary):
            return dropdown_cfg, file_cfg


# ---------------------------------------------------------------------------
# Headless verification helpers
# ---------------------------------------------------------------------------

_TEXT_TYPES = {"text", "textarea", "contenteditable", "password", "email", "search"}


async def _headless_verify_input(
    site: str,
    component: str,
    page_url: str,
    inp: dict,
    storage_path: str,
) -> bool:
    """
    Navigate headlessly, fill the input with 'Hello', read the value back.
    ok=True  if the filled value is readable in the element after fill.
    ok=False if element not found, not visible, or fill did not stick.
    """
    from browser_bot.submit.common import _first_visible_locator, _fill_input

    result: dict = {"ok": False, "error": ""}

    async def _run(page):
        await page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(2)

        selector = inp["selector"]
        inp_type = inp.get("type", "text")

        try:
            loc = await _first_visible_locator(page, selector)
            visible = await loc.is_visible()
            if not visible:
                result["error"] = f"element not visible: {selector}"
                return

            if inp_type == "file":
                import tempfile
                from payloads.generators import generate_payload

                probe_dir = Path(tempfile.mkdtemp(prefix="genbounty_probe_"))
                artifact = generate_payload(
                    "text",
                    {"content": "Genbounty Hunter probe upload", "filename": "probe.txt"},
                    out_dir=probe_dir,
                )
                await loc.set_input_files(str(artifact))
                result["ok"] = True
            elif inp_type in _DROPDOWN_INPUT_TYPES:
                await _fill_input(page, inp, "Hello")
                result["ok"] = True
            else:
                await loc.fill("Hello")
                await asyncio.sleep(0.3)

                if inp_type == "contenteditable":
                    value = await loc.inner_text()
                else:
                    try:
                        value = await loc.input_value()
                    except Exception:
                        value = await loc.inner_text()

                result["ok"] = "Hello" in (value or "")
                if not result["ok"]:
                    result["error"] = f"fill did not stick (got: {repr(value[:80])})"
        except Exception as exc:
            result["error"] = str(exc)

    profile_path = resolve_login_profile_path(site, component)
    if _should_use_login_profile(site, component):
        async with async_playwright() as p:
            browser, context = await launch_persistent_context(
                p, str(profile_path), headless=True, site=site, component=component
            )
            page = await context.new_page()
            try:
                await _run(page)
            finally:
                await context.close()
                if browser:
                    await browser.close()
    else:
        async with async_playwright() as p:
            from main import run_with_page_from_fetchers
            await run_with_page_from_fetchers(
                p,
                site,
                _run,
                storage_path=storage_path,
                interactive=False,
                headless=True,
                human_only=True,
            )

    return result["ok"]


async def _headless_capture_with_input_filled(
    site: str,
    page_url: str,
    inputs: list[dict],
    storage_path: str,
    component: str | None = None,
) -> str | None:
    """
    Navigate headlessly, fill all inputs with 'Hello' (do NOT submit),
    then capture and return the page HTML.
    Used so the LLM can see the submit button that only appears after text is entered.
    Returns HTML string, or None on failure.
    """
    from browser_bot.submit.common import _fill_input, inputs_for_submission

    result: dict = {"html": None}
    prompt_inputs = inputs_for_submission(inputs)

    async def _run(page):
        await page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(2)
        for inp in prompt_inputs:
            try:
                if inp.get("type") == "file":
                    import tempfile
                    from payloads.generators import generate_payload

                    probe_dir = Path(tempfile.mkdtemp(prefix="genbounty_probe_"))
                    artifact = generate_payload(
                        "text",
                        {"content": "Genbounty Hunter probe upload", "filename": "probe.txt"},
                        out_dir=probe_dir,
                    )
                    await _fill_input(page, inp, "Hello", artifact_path=artifact)
                else:
                    await _fill_input(page, inp, "Hello")
                await asyncio.sleep(0.2)
            except Exception:
                pass
        await asyncio.sleep(0.5)  # let UI react (e.g. show send button)
        result["html"] = await _get_page_html(page)

    profile_path = resolve_login_profile_path(site, component)
    if _should_use_login_profile(site, component):
        async with async_playwright() as p:
            browser, context = await launch_persistent_context(
                p, str(profile_path), headless=True, site=site, component=component
            )
            page = await context.new_page()
            try:
                await _run(page)
            finally:
                await context.close()
                if browser:
                    await browser.close()
    else:
        async with async_playwright() as p:
            from main import run_with_page_from_fetchers
            await run_with_page_from_fetchers(
                p,
                site,
                _run,
                storage_path=storage_path,
                interactive=False,
                headless=True,
                human_only=True,
            )

    return result["html"]


async def _headless_verify_submit(
    site: str,
    component: str,
    page_url: str,
    inputs: list[dict],
    submit_selector: str,
    storage_path: str,
    response_wait_ms: int = 15000,
) -> tuple[bool, str | None]:
    """
    Navigate headlessly, fill inputs and click submit. Detect success via:
      - any POST/PUT/PATCH request captured after click, OR
      - page URL change after click.
    Captures full page HTML after the wait.
    Returns (ok, response_html).
    """
    from browser_bot.submit.common import _do_one_submit_step, inputs_for_submission

    result: dict = {"ok": False, "html": None, "error": ""}
    prompt_inputs = inputs_for_submission(inputs)

    async def _run(page):
        pre_url = page.url
        captured_posts: list = []

        def _on_response(response):
            if response.request.method in ("POST", "PUT", "PATCH"):
                captured_posts.append(response.url)

        await page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(2)
        page.on("response", _on_response)

        try:
            await _do_one_submit_step(
                page,
                prompt_inputs,
                submit_selector,
                "Hello",
                response_selector="",
                submit_via="click",
                response_wait_ms=response_wait_ms,
            )
        except Exception as exc:
            result["error"] = str(exc)

        post_url = page.url
        url_changed = post_url != pre_url
        had_post = bool(captured_posts)

        result["ok"] = had_post or url_changed
        if not result["ok"]:
            result["error"] = "no POST request and URL did not change"

        result["html"] = await _get_page_html(page)

    profile_path = resolve_login_profile_path(site, component)
    if _should_use_login_profile(site, component):
        async with async_playwright() as p:
            browser, context = await launch_persistent_context(
                p, str(profile_path), headless=True, site=site, component=component
            )
            page = await context.new_page()
            try:
                await _run(page)
            finally:
                await context.close()
                if browser:
                    await browser.close()
    else:
        async with async_playwright() as p:
            from main import run_with_page_from_fetchers
            await run_with_page_from_fetchers(
                p,
                site,
                _run,
                storage_path=storage_path,
                interactive=False,
                headless=True,
                human_only=True,
            )

    return result["ok"], result["html"]


# ---------------------------------------------------------------------------
# API discovery - probe endpoint and save submission config
# ---------------------------------------------------------------------------

def run_api_discovery(
    site: str,
    component: str,
    *,
    api_url: str,
    api_method: str = "POST",
    api_headers: dict | None = None,
    api_body: dict | None = None,
    api_response_path: str = "response",
    api_model: str = "",
    probe_prompt: str = "Hello from Genbounty Hunter",
    transport: str = "api",
    upload_url: str = "",
    upload_file_field: str = "file",
    upload_response_path: str = "document_id",
    multipart_prompt_field: str = "prompt",
    multipart_file_field: str = "file",
) -> bool:
    """Configure component for direct API submission by probing the endpoint."""
    from browser_bot.submit.api_helpers import (
        do_api_document_request,
        do_api_multipart_request,
        do_api_request,
        resolve_api_url,
    )

    api_url = (api_url or "").strip()
    api_model = (api_model or "").strip()
    transport = (transport or "api").strip().lower()
    if "{{model}}" in api_url and not api_model:
        print("  [!] Model is required when api_url contains {{model}}")
        return False
    if transport == "api" and not api_url:
        print("  [!] api_url is required for API discovery")
        return False
    if transport == "api_document" and (not upload_url or not api_url):
        print("  [!] upload_url and api_url are required for api_document discovery")
        return False
    if transport == "api_multipart" and not api_url:
        print("  [!] api_url is required for api_multipart discovery")
        return False

    _ensure_site_config_for_discovery(site, component)

    api_body = api_body if isinstance(api_body, dict) else {"prompt": "{{prompt}}"}
    api_headers = dict(api_headers or {})
    api_response_path = (api_response_path or "response").strip()

    print("\n" + "─" * 50)
    print("  API endpoint discovery")
    print(f"  Transport: {transport}")
    print("─" * 50)

    if transport == "api_document":
        import tempfile
        from payloads.generators import generate_payload

        probe_dir = Path(tempfile.mkdtemp(prefix="genbounty_api_probe_"))
        artifact = generate_payload(
            "text",
            {"content": "Genbounty Hunter API upload probe", "filename": "probe.txt"},
            out_dir=probe_dir,
        )
        submission = {
            "transport": "api_document",
            "upload_url": upload_url.strip(),
            "upload_file_field": upload_file_field or "file",
            "upload_response_path": upload_response_path or "document_id",
            "api_url": api_url,
            "api_method": (api_method or "POST").upper(),
            "api_headers": api_headers,
            "api_body": api_body if "document_id" in str(api_body) else {
                **api_body,
                "prompt": "{{prompt}}",
                "document_id": "{{document_id}}",
                "context_from": "upload",
            },
            "api_response_path": api_response_path,
        }
        test_case = {
            "id": "api-discover-probe",
            "prompt": probe_prompt,
            "payload": {"path": str(artifact)},
        }
        status, response_text, err = do_api_document_request(
            submission, probe_prompt, site=site, component=component, test_case=test_case
        )
    elif transport == "api_multipart":
        submission = {
            "transport": "api_multipart",
            "api_url": api_url,
            "multipart_prompt_field": multipart_prompt_field or "prompt",
            "multipart_file_field": multipart_file_field or "file",
            "api_response_path": api_response_path,
            "api_headers": api_headers,
        }
        import tempfile
        from payloads.generators import generate_payload

        probe_dir = Path(tempfile.mkdtemp(prefix="genbounty_api_probe_"))
        artifact = generate_payload(
            "text",
            {"content": "Genbounty Hunter multipart probe", "filename": "probe.txt"},
            out_dir=probe_dir,
        )
        test_case = {
            "id": "api-discover-probe",
            "prompt": probe_prompt,
            "payload": {"path": str(artifact)},
        }
        status, response_text, err = do_api_multipart_request(
            submission, probe_prompt, site=site, component=component, test_case=test_case
        )
    else:
        submission = {
            "transport": "api",
            "api_url": api_url,
            "api_method": (api_method or "POST").upper(),
            "api_headers": api_headers,
            "api_body": api_body,
            "api_response_path": api_response_path,
        }
        if api_model:
            submission["api_model"] = api_model
        try:
            probe_url = resolve_api_url(submission, site=site, component=component)
        except ValueError as exc:
            print(f"  [!] {exc}")
            return False
        print(f"  Probing {submission['api_method']} {probe_url}")
        status, response_text, err, *_ = do_api_request(
            submission, probe_prompt, site=site, component=component
        )
        if status == 403 and "generativelanguage.googleapis.com" in probe_url:
            print("  [~] Gemini 403: use x-goog-api-key header or ?key= query param in Step 1 API key")

    if err and not response_text:
        print(f"  [!] Probe failed ({status}): {err}")
        return False
    if not response_text:
        print("  [!] Probe returned empty response - check api_response_path")
        return False

    comp_raw = load_component_config_raw(site, component)
    comp_raw.setdefault("urls", [])
    comp_raw.setdefault("posts", [])
    comp_raw["submission"] = submission
    _save_config_with_comments(site, component, comp_raw)

    print(f"  [+] API connection OK (HTTP {status})")
    preview = (response_text[:200] + "…") if len(response_text) > 200 else response_text
    print(f"  [+] Response preview: {preview}")
    print(f"  [+] Saved -> sites/{site}/{component}/config.yaml")
    print("═" * 50)
    return True


# ---------------------------------------------------------------------------
# run_training - 6-step discovery pipeline
# ---------------------------------------------------------------------------

def _fresh_discovery_submission() -> dict:
    return {
        "start_url": "",
        "inputs": [],
        "submit_selector": "",
        "response_selector": "",
        "submit_via": "click",
        "response_wait_ms": 8000,
    }


def run_manual_training(
    site: str,
    component: str,
    *,
    v2: bool = True,
    guided: bool = False,
    use_cdp: bool = False,
) -> bool:
    """Manual browser-guided selector discovery using LangGraph experts + judge."""
    profile_path = resolve_login_profile_path(site, component)
    has_profile = _should_use_login_profile(site, component)
    storage_path = get_storage_state_path(site, component)
    if not has_profile and not storage_path:
        print("  No auth for this site. Run 'Add login' first.")
        return False
    _print_profile_disabled_notice(site, component)
    _ensure_site_config_for_discovery(site, component)

    config = load_component_config(site, component)
    start_url = resolve_discovery_launch_url(config, site)

    submission: dict = _fresh_discovery_submission()

    print("\n" + "─" * 50)
    if v2:
        print("  Manual component discovery")
        print("  LangGraph step experts on each click; judge validates full composer at the end.")
    else:
        print("  Manual component discovery (legacy)")
        print("  A browser will open with a Genbounty Hunter guide panel.")
    print("─" * 50)

    async def _run_manual():
        from browser_bot.discovery_ui_bridge import (
            UiDiscoveryRestartRequested,
            check_ui_discovery_restart,
            clear_ui_discovery_restart,
            emit_ui_mode_banner,
        )

        ui_only = bool(guided)
        from browser_bot.config import USE_CDP_BROWSER, use_cdp_browser as should_use_cdp

        launch_via_cdp = bool(USE_CDP_BROWSER or (guided and should_use_cdp(use_cdp)))

        def _prepare_ui_restart() -> None:
            nonlocal ui_only
            ui_only = True
            submission.clear()
            submission.update(_fresh_discovery_submission())
            _save_partial(site, component, submission)

        for _session in range(2):
            try:
                async with async_playwright() as p:
                    from main import run_with_page_from_fetchers

                    async def _capture(page):
                        from browser_bot.discovery_ui_bridge import resolve_discovery_page

                        page = resolve_discovery_page(page)
                        check_ui_discovery_restart(page.context)
                        clear_ui_discovery_restart(page.context)

                        if ui_only:
                            setattr(page, "_genbounty_ui_mode", True)
                            if v2:
                                setattr(page, "_genbounty_v2_discovery", True)
                            _reset_discovery_expert_log(page)
                            emit_ui_mode_banner(restarted=_session > 0)
                        else:
                            await _install_manual_discovery_panel(page, v2=v2)
                            if v2:
                                _reset_discovery_expert_log(page)
                        await page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
                        if ui_only:
                            from browser_bot.discovery_ui_bridge import (
                                apply_guided_discovery_window_layout,
                                show_guided_discovery_welcome_modal,
                            )

                            await apply_guided_discovery_window_layout(page)
                            await show_guided_discovery_welcome_modal(page)

                        print("  [1/?] Initial popup, then start URL...")
                        inputs: list[dict] = []
                        # Base steps: initial popup, start URL, surface pre-steps, page scan,
                        # prompt, submit, welcome/intro ignore, response
                        # (+1 when upload/menu step is present).
                        extra_upload_steps = 0  # updated after scan
                        total_steps = 8

                        # Popup first - while it is still on screen. Continue must not clear it.
                        if v2 and not ui_only:
                            await _install_manual_discovery_panel(page, v2=True)
                            await _ensure_v2_discovery_mode(page)
                        print("  [1/?] Initial popup (cookie / consent / success modal)...")
                        popup_step = await _configure_initial_popup_pre_step(
                            page,
                            step_label=f"1/{total_steps}",
                            v2=v2,
                        )
                        if popup_step:
                            inputs.append(popup_step)
                            submission["inputs"] = inputs
                            _save_partial(site, component, submission)

                        extra_popup = await _manual_continue_after_popup(
                            page,
                            step_label=f"1/{total_steps}",
                            step_title=f"Confirm step 2/{total_steps} - start URL",
                            message=(
                                f"2/{total_steps}. Confirm the page\n\n"
                                "Make sure you are on the chat UI, then Continue."
                            ),
                            inputs=inputs,
                            continue_step_label=f"2/{total_steps}",
                        )
                        if extra_popup and extra_popup not in inputs:
                            inputs.insert(0, extra_popup)
                            submission["inputs"] = inputs
                            _save_partial(site, component, submission)
                        submission["start_url"] = page.url
                        _save_partial(site, component, submission)
                        print(f"    start_url: {page.url}")

                        if v2:
                            if not ui_only:
                                await _install_manual_discovery_panel(page, v2=True)
                                await _ensure_v2_discovery_mode(page)
                            if not _discovery_llm_ready():
                                print("  [!] Discovery v2 requires a configured LLM (llm.yaml roles + API keys).")
                                return False
                            print("  [v2] LangGraph experts active (LLM configured).")

                        print("  [3/?] Surface pre-steps (tabs / cards / Start)...")
                        pre_steps = await _configure_surface_pre_steps(
                            page,
                            step_label=f"3/{total_steps}",
                            v2=v2,
                            ui_only=ui_only,
                        )
                        if pre_steps:
                            inputs.extend(pre_steps)
                            submission["inputs"] = inputs
                            _save_partial(site, component, submission)

                        print("  [4/?] Scanning page for file upload and dropdown controls...")
                        upload_info = await _detect_upload_capabilities(page)
                        select_info = await _detect_select_capabilities(page)
                        supports_upload = bool(upload_info.get("supports_upload"))
                        supports_select = bool(select_info.get("supports_select"))
                        combined_upload_step = ui_only or (supports_upload and supports_select)
                        extra_upload_steps = 1 if (supports_upload or supports_select or ui_only) else 0
                        total_steps = 8 + extra_upload_steps
                        auto_file_selector = _pick_best_file_input(upload_info)
                        if supports_upload:
                            count = len(upload_info.get("file_inputs") or [])
                            print(f"    upload support: yes ({count} file input(s) found)")
                            for row in upload_info.get("file_inputs") or []:
                                vis = "visible" if row.get("visible") else "hidden"
                                uniq = "unique" if row.get("unique") else "ambiguous"
                                print(f"      - {row.get('selector')} ({vis}, {uniq})")
                        else:
                            print("    upload support: no")
                        if supports_select:
                            count = len(select_info.get("select_controls") or [])
                            print(f"    dropdown support: yes ({count} control(s) found)")
                            for row in select_info.get("select_controls") or []:
                                vis = "visible" if row.get("visible") else "hidden"
                                uniq = "unique" if row.get("unique") else "ambiguous"
                                kind = row.get("kind") or "select"
                                print(f"      - {row.get('selector')} ({kind}, {vis}, {uniq})")
                        else:
                            print("    dropdown support: no")

                        if not supports_upload and not ui_only:
                            scan_fields = _panel_step_fields(
                                f"4/{total_steps}",
                                "No file upload found",
                                "Continue to pick the prompt box",
                                tip=(
                                    "You can still pick a dropdown next if needed"
                                    if supports_select
                                    else "No upload control will be saved"
                                ),
                            )
                            await _manual_continue_confirmed(
                                page,
                                scan_fields["message"],
                                step_title=scan_fields["step_title"],
                                build_summary=lambda: (
                                    "No file upload will be saved.\n"
                                    + (
                                        "Next: optional dropdown.\n"
                                        if supports_select
                                        else "Next: prompt box."
                                    )
                                ),
                                action="Continue",
                                step_number=scan_fields["stepNumber"],
                                step_total=scan_fields["stepTotal"],
                                step_name=scan_fields["stepName"],
                                do_now=scan_fields["doNow"],
                                tip=scan_fields["tip"],
                            )

                        dropdown_cfg: dict | None = None
                        file_cfg: dict | None = None
                        current_step = 5
                        if combined_upload_step:
                            print(f"  [{current_step}/{total_steps}] Configuring menu + file upload (one step)...")
                            dropdown_cfg, file_cfg = await _configure_upload_discovery_combined(
                                page,
                                step_label=f"{current_step}/{total_steps}",
                                select_info=select_info,
                                auto_file_selector=auto_file_selector,
                                v2=v2,
                            )
                            if dropdown_cfg:
                                inputs.append(dropdown_cfg)
                                print(
                                    f"    dropdown: {dropdown_cfg['selector']} "
                                    f"(type={dropdown_cfg.get('type', 'select')})"
                                )
                            else:
                                print("    dropdown: (not configured)")
                            if file_cfg:
                                inputs.append(file_cfg)
                                submission["response_wait_ms"] = max(
                                    int(submission.get("response_wait_ms") or 8000), 60000
                                )
                                print(f"    file input: {file_cfg['selector']} (path_from=payload)")
                            else:
                                print("    file input: (not configured)")
                            if dropdown_cfg or file_cfg:
                                submission["inputs"] = inputs
                                _save_partial(site, component, submission)
                            current_step += 1
                        elif supports_select:
                            print(f"  [{current_step}/{total_steps}] Configuring prerequisite dropdown...")
                            dropdown_cfg = await _configure_prerequisite_dropdown(
                                page,
                                step_label=f"{current_step}/{total_steps}",
                                select_info=select_info,
                                supports_upload=supports_upload,
                                v2=v2,
                            )
                            if dropdown_cfg:
                                inputs.append(dropdown_cfg)
                                submission["inputs"] = inputs
                                _save_partial(site, component, submission)
                                print(
                                    f"    dropdown: {dropdown_cfg['selector']} "
                                    f"(type={dropdown_cfg.get('type', 'select')})"
                                )
                            else:
                                print("    dropdown: (not configured)")
                            current_step += 1

                        if supports_upload and not combined_upload_step:
                            print(f"  [{current_step}/{total_steps}] Configuring multimodal file upload...")
                            file_cfg = await _configure_multimodal_upload(
                                page,
                                step_label=f"{current_step}/{total_steps}",
                                auto_selector=auto_file_selector,
                                dropdown_configured=bool(dropdown_cfg),
                                v2=v2,
                            )
                            if file_cfg:
                                inputs.append(file_cfg)
                                submission["inputs"] = inputs
                                submission["response_wait_ms"] = max(
                                    int(submission.get("response_wait_ms") or 8000), 60000
                                )
                                _save_partial(site, component, submission)
                                print(f"    file input: {file_cfg['selector']} (path_from=payload)")
                            else:
                                print("    file input: (not configured)")
                            current_step += 1

                        print(f"  [{current_step}/{total_steps}] Waiting for prompt input selection...")
                        prompt_fields = _panel_step_fields(
                            f"{current_step}/{total_steps}",
                            "Prompt box",
                            "Click the text field where you type messages",
                        )
                        input_event = await _manual_pick_prompt_input(
                            page,
                            prompt_fields["message"],
                            step_title=prompt_fields["step_title"],
                            site=site,
                            component=component,
                            v2=v2,
                            step_number=prompt_fields["stepNumber"],
                            step_total=prompt_fields["stepTotal"],
                            step_name=prompt_fields["stepName"],
                            do_now=prompt_fields["doNow"],
                        )
                        input_selector = input_event["selector"]
                        input_config = {
                            "selector": input_selector,
                            "type": _manual_input_type(input_event),
                        }
                        inputs.append(input_config)
                        submission["inputs"] = inputs
                        _save_partial(site, component, submission)
                        print(f"    input: {input_selector} (type={input_config['type']})")
                        current_step += 1

                        print(f"  [{current_step}/{total_steps}] Waiting for submit button selection...")
                        send_fields = _panel_step_fields(
                            f"{current_step}/{total_steps}",
                            "Send button",
                            "Click the control that sends the message",
                            tip="The click is allowed through",
                        )
                        submit_event = await _manual_pick_selector(
                            page,
                            send_fields["message"],
                            step_title=send_fields["step_title"],
                            allow_action=True,
                            v2=v2,
                            context_target="submit",
                            step_number=send_fields["stepNumber"],
                            step_total=send_fields["stepTotal"],
                            step_name=send_fields["stepName"],
                            do_now=send_fields["doNow"],
                            tip=send_fields["tip"],
                        )
                        submission["submit_selector"] = submit_event["selector"]
                        _save_partial(site, component, submission)
                        print(f"    submit_selector: {submit_event['selector']}")
                        current_step += 1

                        print(
                            f"  [{current_step}/{total_steps}] "
                            "Waiting for welcome/intro ignore selection..."
                        )
                        await _configure_response_intro_ignore(
                            page,
                            submission,
                            site=site,
                            component=component,
                            step_label=f"{current_step}/{total_steps}",
                            v2=v2,
                        )
                        _save_partial(site, component, submission)
                        current_step += 1

                        print(f"  [{current_step}/{total_steps}] Waiting for response text selection...")
                        reply_fields = _panel_step_fields(
                            f"{current_step}/{total_steps}",
                            "Assistant reply",
                            "Click the latest real reply",
                            tip="Not your prompt; not the greeting",
                        )
                        response_event = await _manual_pick_selector(
                            page,
                            reply_fields["message"],
                            step_title=reply_fields["step_title"],
                            v2=v2,
                            context_target="response",
                            pick_kind="response" if v2 else None,
                            step_number=reply_fields["stepNumber"],
                            step_total=reply_fields["stepTotal"],
                            step_name=reply_fields["stepName"],
                            do_now=reply_fields["doNow"],
                            tip=reply_fields["tip"],
                        )
                        analysis = await _analyze_response_capture_on_page(page, response_event["selector"])
                        capture_lines = _merge_response_capture_analysis(
                            submission, response_event["selector"], analysis
                        )
                        if v2:
                            wide_html = (response_event.get("wideContextHtml") or "").strip()
                            multiturn = False
                            if await _ask_discovery_multiturn_opt_in(
                                page, step_label=f"{current_step}/{total_steps}"
                            ):
                                probe_ok, multiturn_html, probe_lines = await _discovery_multiturn_response_probe(
                                    page, submission
                                )
                                for line in probe_lines:
                                    print(line)
                                if probe_ok and multiturn_html.strip():
                                    wide_html = multiturn_html
                                    multiturn = True
                                    analysis = await _analyze_response_capture_on_page(
                                        page, submission["response_selector"]
                                    )
                                    capture_lines = _merge_response_capture_analysis(
                                        submission, submission["response_selector"], analysis
                                    )
                                    print("  [+] Multi-turn response capture analysis applied.")
                            reconcile_lines = await _reconcile_v2_submission_from_wide_context(
                                page, submission, wide_html, multiturn=multiturn
                            )
                            if reconcile_lines and submission.get("response_selector"):
                                analysis = await _analyze_response_capture_on_page(
                                    page, submission["response_selector"]
                                )
                                capture_lines = _merge_response_capture_analysis(
                                    submission, submission["response_selector"], analysis
                                )
                        _save_partial(site, component, submission)
                        print(f"    response_selector: {response_event['selector']}")
                        for line in capture_lines:
                            print(line)

                        original_response_pick = (response_event.get("selector") or "").strip()
                        print("\n  Final step: automatic sample request to verify response capture.")
                        print("  Sit tight during the test - Continue in the panel when it finishes.")
                        await _discovery_verify_and_repair_response_capture(
                            page,
                            submission,
                            original_pick=original_response_pick,
                            site=site,
                            component=component,
                        )
                        _save_partial(site, component, submission)
                        return True

                    if launch_via_cdp:
                        from browser_bot.browser.launcher import (
                            close_login_chrome_cdp,
                            open_cdp_browser_session,
                            open_guided_discovery_cdp,
                        )

                        try:
                            if ui_only:
                                browser, context, page, chrome_proc = await open_guided_discovery_cdp(
                                    p,
                                    site=site,
                                    component=component,
                                    start_url=start_url,
                                    auto_launch=True,
                                )
                            else:
                                browser, context, page, chrome_proc = await open_cdp_browser_session(
                                    p,
                                    site=site,
                                    component=component,
                                    start_url=start_url,
                                    auto_launch=True,
                                    log_tag="discovery",
                                    window_width_ratio=1.0,
                                    window_always_on_top=False,
                                )
                        except RuntimeError as exc:
                            print(f"  [!] CDP browser failed: {exc}")
                            return False
                        try:
                            return await _capture(page)
                        finally:
                            await close_login_chrome_cdp(browser, chrome_proc)
                            print("[discovery] Closed CDP Chrome.", flush=True)

                    if has_profile:
                        browser, context = await launch_persistent_context(
                            p,
                            str(profile_path),
                            headless=False,
                            site=site,
                            component=component,
                            always_on_top=ui_only,
                        )
                        page = await context.new_page()
                        try:
                            return await _capture(page)
                        finally:
                            await context.close()
                            if browser:
                                await browser.close()

                    return await run_with_page_from_fetchers(
                        p,
                        site,
                        _capture,
                        storage_path=str(storage_path) if storage_path else None,
                        interactive=True,
                        human_only=True,
                        guided_discovery=ui_only,
                    )
            except UiDiscoveryRestartRequested:
                if ui_only:
                    print("  [!] Discovery restart requested again - aborting.")
                    return False
                print(
                    "  [ui] Not working? - closing browser and restarting discovery "
                    "without in-page helper JavaScript."
                )
                _prepare_ui_restart()
                continue
        return False

    ok = bool(asyncio.run(_run_manual()))
    if not ok:
        print("  [!] Manual discovery failed.")
        return False

    print("\n" + "═" * 50)
    print(f"  Manual discovery complete -> sites/{site}/{component}/config.yaml")
    print(f"    start_url:         {submission.get('start_url') or '(unset)'}")
    print(f"    inputs:            {len(submission['inputs'])} field(s)")
    file_inputs = [i for i in submission["inputs"] if i.get("type") == "file"]
    dropdown_inputs = [
        i for i in submission["inputs"] if i.get("type") in ("select", "combobox")
    ]
    if dropdown_inputs:
        print(
            f"    prerequisite dropdown: {dropdown_inputs[0].get('selector')} "
            f"(type={dropdown_inputs[0].get('type')})"
        )
    if file_inputs:
        print(f"    multimodal upload: {file_inputs[0].get('selector')}")
    print(f"    submit_selector:   {submission['submit_selector']}")
    print(f"    response_selector: {submission['response_selector']}")
    print("═" * 50)
    return True


def run_training(site: str, component: str) -> bool:
    """
    Bulletproof 7-step discovery - fully automated after the first Enter:

    1. Interactive browser   - record surface pre-steps, navigate, Continue
    2. Dropdown + upload scan - scan page HTML for prerequisite menus and file inputs
    3. LLM extracts inputs   - printed, saved immediately (gates, dropdown, file, then text)
    4. Headless verify input - fills dropdown/file/text
    5. LLM extracts submit   - from filled-input HTML so send button is visible
    6. Headless verify submit - fills + clicks, detects POST/URL change, captures response HTML
    7. LLM extracts response selector - from post-response HTML
    Config saved incrementally; edit config.yaml manually if any selector is wrong.
    """
    profile_path = resolve_login_profile_path(site, component)
    has_profile = _should_use_login_profile(site, component)
    storage_path = get_storage_state_path(site, component)
    if not has_profile and not storage_path:
        print("  No auth for this site. Run 'Add login' first.")
        return False
    _print_profile_disabled_notice(site, component)
    _ensure_site_config_for_discovery(site, component)

    config = load_component_config(site, component)
    start_url = resolve_discovery_launch_url(config, site)

    # Submission dict built up incrementally
    submission: dict = {
        "start_url": "",
        "inputs": [],
        "submit_selector": "",
        "response_selector": "",
        "submit_via": "click",
        "response_wait_ms": 8000,
    }

    # -----------------------------------------------------------------------
    # Step 1 - Interactive browser: user navigates, presses Enter
    # -----------------------------------------------------------------------
    print("\n" + "─" * 50)
    print("  [1/7] Opening browser - record surface pre-steps, then confirm the page")
    print("        Click notices/tabs/levels/Start first; then Continue when the composer is ready.")
    print("        Open the attachment menu first if upload is hidden behind it.")
    if has_profile:
        print("        Using persistent login profile for session restoration.")
    print("─" * 50)

    form_html: str = ""
    page_url: str = ""
    live_upload_info: dict = {}
    live_select_info: dict = {}
    step1_pre_steps: list[dict] = []

    async def _step1():
        async with async_playwright() as p:
            from main import run_with_page_from_fetchers

            async def _capture(page):
                await _install_manual_discovery_panel(page)
                await page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
                print("\n  Browser opened. Record initial popup + surface pre-steps, then confirm...")
                popup = await _configure_initial_popup_pre_step(
                    page,
                    step_label="1a/7",
                    v2=False,
                )
                pre_steps = await _configure_surface_pre_steps(
                    page,
                    step_label="1b/7",
                    v2=False,
                    ui_only=False,
                )
                if popup:
                    pre_steps = [popup, *pre_steps]
                await _manual_continue_confirmed(
                    page,
                    "1/7. Start page\n\n"
                    "Popup + pre-steps are saved. Open any upload menu if needed,\n"
                    "then Continue when the prompt box is visible.",
                    step_title="Confirm step 1/7 - capture page",
                    build_summary=lambda: f"start_url:\n{page.url}",
                    action="Continue",
                )
                upload_info = await _detect_upload_capabilities(page)
                select_info = await _detect_select_capabilities(page)
                body_html = await _get_page_html(page)
                full_html = await page.content()
                return body_html, full_html, page.url, upload_info, select_info, pre_steps

            if has_profile:
                browser, context = await launch_persistent_context(
                    p, str(profile_path), headless=False, site=site, component=component
                )
                page = await context.new_page()
                try:
                    return await _capture(page)
                finally:
                    await context.close()
                    if browser:
                        await browser.close()
            return await run_with_page_from_fetchers(
                p,
                site,
                _capture,
                storage_path=str(storage_path) if storage_path else None,
                interactive=True,
                human_only=True,
            )

    step1_result = asyncio.run(_step1())
    if step1_result is None:
        print("  [!] Browser capture failed.")
        return False
    (
        form_html,
        full_html,
        page_url,
        live_upload_info,
        live_select_info,
        step1_pre_steps,
    ) = step1_result

    html_path = _save_html(site, component, form_html, "_form")
    print(f"  HTML saved -> {html_path}")

    submission["start_url"] = page_url
    _save_partial(site, component, submission)

    # -----------------------------------------------------------------------
    # Step 2 - Detect dropdown menus and file upload support from captured HTML
    # -----------------------------------------------------------------------
    print("\n" + "─" * 50)
    print("  [2/7] Detecting dropdown menus, upload prep, and file inputs...")
    print("─" * 50)

    live_dropdown_inputs, live_file_inputs = _inputs_from_live_scan(
        live_upload_info, live_select_info
    )
    detected_dropdown_inputs = _merge_input_rows(
        live_dropdown_inputs,
        _detect_selects_from_html(form_html),
    )
    detected_menuitems = _detect_upload_menuitems_from_html(form_html)
    detected_start_surface = _detect_start_surface_from_html(form_html)
    detected_file_inputs = _merge_input_rows(
        live_file_inputs,
        _detect_uploads_from_html(form_html),
    )

    if step1_pre_steps:
        print(f"  Surface pre-steps (recorded): yes ({len(step1_pre_steps)} click(s))")
        for row in step1_pre_steps:
            print(f"    pre-step: {row['selector']} (type={row.get('type', 'click')})")
    else:
        print("  Surface pre-steps (recorded): none")
    if detected_start_surface:
        print(f"  Start/Begin CTA (heuristic): yes ({len(detected_start_surface)})")
        for row in detected_start_surface:
            print(f"    start surface: {row['selector']}")
    else:
        print("  Start/Begin CTA (heuristic): no")
    if detected_dropdown_inputs:
        print(f"  Menu/dropdown prep: yes ({len(detected_dropdown_inputs)} control(s))")
        for row in detected_dropdown_inputs:
            print(
                f"    prep: {row['selector']} "
                f"(type={row.get('type', 'click')}, upload_prep={bool(row.get('upload_prep'))})"
            )
    else:
        print("  Menu/dropdown prep: no")
    if detected_menuitems:
        print(f"  Upload menu item(s): yes ({len(detected_menuitems)})")
        for row in detected_menuitems:
            print(f"    menu item: {row['selector']} (type={row.get('type', 'click')})")
    else:
        print("  Upload menu item(s): no (open attachment menu before Enter to capture)")
    if detected_file_inputs:
        print(f"  Upload support: yes ({len(detected_file_inputs)} file input(s))")
        for row in detected_file_inputs:
            print(f"    file input: {row['selector']} (path_from=payload)")
        submission["response_wait_ms"] = max(int(submission.get("response_wait_ms") or 8000), 60000)
        _save_partial(site, component, submission)
    else:
        print("  Upload support: no")

    # -----------------------------------------------------------------------
    # Step 3 - LLM extracts input selector(s)
    # -----------------------------------------------------------------------
    print("\n" + "─" * 50)
    print("  [3/7] Extracting input selector via AI...")
    print("        (dropdown before file before text prompt when multimodal)")
    print("─" * 50)

    llm_inputs = _retry_extract_inputs(form_html, page_url)
    surface_pre_steps = _merge_surface_pre_steps(step1_pre_steps, detected_start_surface)
    merged_inputs = _merge_detected_inputs(
        detected_dropdown_inputs,
        detected_file_inputs,
        llm_inputs,
        prep_menuitems=detected_menuitems,
        surface_pre_steps=surface_pre_steps,
    )

    if not merged_inputs:
        print("  [!] Input selector not found after retries. Discovery cannot continue.")
        submission["inputs"] = []
        _save_partial(site, component, submission)
        return False

    for inp in merged_inputs:
        if inp.get("upload_prep") or inp.get("type") == "click":
            suffix = " (upload prep)"
        elif inp.get("type") in _DROPDOWN_INPUT_TYPES:
            suffix = " (prerequisite dropdown)"
        elif inp.get("type") == "file":
            suffix = " (multimodal)"
        else:
            suffix = ""
        print(f"    input: {inp['selector']} (type={inp.get('type', 'text')}){suffix}")

    submission["inputs"] = merged_inputs
    _save_partial(site, component, submission)
    print(f"  Saved {len(merged_inputs)} input(s).")

    # -----------------------------------------------------------------------
    # Step 4 - Headless verify each input
    # -----------------------------------------------------------------------
    print("\n" + "─" * 50)
    print("  [4/7] Verifying input selector(s) headlessly...")
    print("─" * 50)

    confirmed_inputs = merged_inputs
    for i, inp in enumerate(confirmed_inputs):
        if inp.get("upload_prep") or (inp.get("type") or "").lower() == "click":
            print(
                f"\n  Skipping headless verify for upload prep [{i + 1}/{len(confirmed_inputs)}]: "
                f"{inp['selector']}"
            )
            continue
        print(f"\n  Verifying input [{i + 1}/{len(confirmed_inputs)}]: {inp['selector']}")
        ok = asyncio.run(
            _headless_verify_input(site, component, page_url, inp, str(storage_path))
        )
        if ok:
            print("  ✓ Input verified.")
        else:
            print("  ✗ Verification failed.")
            print("    Proceeding - edit config.yaml if selector is wrong.")

    submission["inputs"] = confirmed_inputs
    _save_partial(site, component, submission)

    # -----------------------------------------------------------------------
    # Step 5 - LLM extracts submit selector
    # Capture HTML with text already in the input so the send button is visible
    # -----------------------------------------------------------------------
    print("\n" + "─" * 50)
    print("  [5/7] Extracting submit selector via AI...")
    print("        (capturing page with input filled so send button is visible)")
    print("─" * 50)

    filled_html = asyncio.run(
        _headless_capture_with_input_filled(
            site, page_url, confirmed_inputs, str(storage_path), component=component
        )
    )
    submit_source_html = filled_html or form_html
    if filled_html:
        _save_html(site, component, filled_html, "_filled")

    from browser_bot.submit.common import inputs_for_submission

    prompt_sel_hints = [
        i["selector"].strip()
        for i in inputs_for_submission(confirmed_inputs)
        if i.get("selector")
    ]

    llm_submit = _retry_extract_submit(
        submit_source_html,
        page_url,
        prompt_sel_hints or None,
    )

    if not llm_submit:
        print("  [!] Submit selector not found after retries. Discovery cannot continue.")
        submission["submit_selector"] = ""
        _save_partial(site, component, submission)
        return False
    else:
        print(f"    submit_selector: {llm_submit}")

    submit_selector = llm_submit
    submission["submit_selector"] = submit_selector
    _save_partial(site, component, submission)

    # -----------------------------------------------------------------------
    # Step 6 - Headless verify submit + capture response HTML
    # -----------------------------------------------------------------------
    print("\n" + "─" * 50)
    print("  [6/7] Verifying submit selector and capturing response headlessly...")
    print("─" * 50)

    response_html: str | None = None

    print(f"  Submitting test prompt with: {submit_selector}")
    ok, response_html = asyncio.run(
        _headless_verify_submit(
            site, component, page_url,
            confirmed_inputs, submit_selector,
            str(storage_path),
        )
    )
    if ok:
        print("  ✓ Submit verified.")
        if response_html:
            rhtml_path = _save_html(site, component, response_html, "_response")
            print(f"  Response HTML saved -> {rhtml_path}")
    else:
        print("  ✗ Submit verification failed.")
        print("    Proceeding - edit config.yaml if selector is wrong.")

    # -----------------------------------------------------------------------
    # Step 7 - LLM extracts response selector
    # -----------------------------------------------------------------------
    print("\n" + "─" * 50)
    print("  [7/7] Extracting response selector via AI...")
    print("─" * 50)

    response_selector = ""
    if response_html:
        response_selector = _retry_extract_response_selector(
            response_html,
            page_url,
            prompt_sel_hints or None,
        )
        if response_selector:
            print(f"    response_selector: {response_selector}")
        else:
            print("  [!] Response selector not found after retries. Discovery cannot complete.")
            submission["response_selector"] = ""
            _save_partial(site, component, submission)
            return False
    else:
        print("  No response HTML available - response selector cannot be extracted.")
        submission["response_selector"] = ""
        _save_partial(site, component, submission)
        return False

    submission["response_selector"] = response_selector
    submission["start_url"] = page_url
    _save_partial(site, component, submission)

    print("\n  Final step: verifying response capture with an automatic sample request.")
    print("  If a browser window opens, Genbounty Hunter controls it - no action needed until the panel asks you to Continue.")

    async def _verify_capture_headless():
        from pipeline.component_settings import playwright_headless_kwarg

        verify_headless = playwright_headless_kwarg(site=site, component=component)
        show_verify_panel = verify_headless is False

        async def _run(page):
            if show_verify_panel:
                await _install_manual_discovery_panel(page)
            await _discovery_verify_and_repair_response_capture(
                page,
                submission,
                original_pick=response_selector,
                site=site,
                component=component,
                interactive=show_verify_panel,
            )

        profile_path = resolve_login_profile_path(site, component)
        if _should_use_login_profile(site, component):
            async with async_playwright() as p:
                browser, context = await launch_persistent_context(
                    p,
                    str(profile_path),
                    headless=verify_headless if verify_headless is not None else True,
                    site=site,
                    component=component,
                )
                page = await context.new_page()
                try:
                    await _run(page)
                finally:
                    await context.close()
                    if browser:
                        await browser.close()
        else:
            async with async_playwright() as p:
                from main import run_with_page_from_fetchers

                await run_with_page_from_fetchers(
                    p,
                    site,
                    _run,
                    storage_path=str(storage_path),
                    interactive=False,
                    headless=verify_headless,
                    human_only=True,
                    component=component,
                )

    try:
        asyncio.run(_verify_capture_headless())
    except Exception as exc:
        print(f"  [!] Response capture verification skipped: {exc}")

    _save_partial(site, component, submission)

    print("\n" + "═" * 50)
    print(f"  Discovery complete -> sites/{site}/{component}/config.yaml")
    print(f"    inputs:            {len(confirmed_inputs)} field(s)")
    prep_inputs = [i for i in confirmed_inputs if i.get("upload_prep") or i.get("type") == "click"]
    dropdown_inputs = [i for i in confirmed_inputs if i.get("type") in _DROPDOWN_INPUT_TYPES]
    file_inputs = [i for i in confirmed_inputs if i.get("type") == "file"]
    if prep_inputs:
        print(
            f"    upload prep:       {prep_inputs[0].get('selector')} "
            f"(type={prep_inputs[0].get('type', 'click')})"
        )
    if dropdown_inputs:
        print(
            f"    prerequisite dropdown: {dropdown_inputs[0].get('selector')} "
            f"(type={dropdown_inputs[0].get('type')})"
        )
    if file_inputs:
        print(f"    multimodal upload: {file_inputs[0].get('selector')}")
    print(f"    submit_selector:   {submit_selector or '(none)'}")
    print(f"    response_selector: {submission.get('response_selector') or '(empty)'}")
    print("═" * 50)
    return True
