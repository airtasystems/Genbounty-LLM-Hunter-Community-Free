"""
Add ``response_html`` to each adversarial result when writing ``pipeline_report.json``.

Converts raw ``response`` text into a small HTML fragment (no html/body shell)
using deterministic rules - no LLM calls.
"""

from __future__ import annotations

import html
import re
from typing import Any

_MAX_INPUT_CHARS = 120_000

_FENCED_CODE = re.compile(r"```(\w*)\n?(.*?)```", re.DOTALL)
_BULLET_LINE = re.compile(r"^(\s*[-*•]\s+)(.+)$")
_NUMBERED_LINE = re.compile(r"^(\s*\d+[.)]\s+)(.+)$")
_HEADING_LINE = re.compile(r"^(#{1,4})\s+(.+)$")
# Sentence boundary: period/question/exclamation + space + likely new sentence start
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def _truncate(text: str) -> str:
    text = text.strip()
    if len(text) <= _MAX_INPUT_CHARS:
        return text
    return text[:_MAX_INPUT_CHARS] + "\n\n[…truncated]"


def _inline_format(text: str) -> str:
    """Escape text and apply lightweight ``code`` / **strong** spans."""
    parts: list[str] = []
    pattern = re.compile(r"`([^`]+)`|\*\*([^*]+)\*\*")
    last = 0
    for m in pattern.finditer(text):
        if m.start() > last:
            parts.append(html.escape(text[last : m.start()]))
        if m.group(1) is not None:
            parts.append(f"<code>{html.escape(m.group(1))}</code>")
        else:
            parts.append(f"<strong>{html.escape(m.group(2))}</strong>")
        last = m.end()
    parts.append(html.escape(text[last:]))
    return "".join(parts)


def _wrap_paragraph(body: str) -> str:
    body = body.strip()
    if not body:
        return ""
    return f"<p>{_inline_format(body)}</p>"


def _split_sentences(paragraph: str) -> list[str]:
    """Split prose into sentences; keep short blocks intact."""
    text = paragraph.strip()
    if not text:
        return []
    if len(text) < 220 or "\n" in text:
        return [text]
    if text.startswith("{") or text.startswith("[") or "```" in text:
        return [text]
    parts = _SENTENCE_BREAK.split(text)
    merged: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        merged.append(part)
    return merged if len(merged) > 1 else [text]


def _paragraphs_from_prose(block: str) -> str:
    """Blank-line paragraphs; split long prose at sentence boundaries."""
    chunks = [c.strip() for c in re.split(r"\n\s*\n", block) if c.strip()]
    out: list[str] = []
    for chunk in chunks:
        for sentence in _split_sentences(chunk):
            wrapped = _wrap_paragraph(sentence)
            if wrapped:
                out.append(wrapped)
    return "\n".join(out)


def _format_list(lines: list[str], ordered: bool) -> str:
    tag = "ol" if ordered else "ul"
    items = "".join(f"<li>{_inline_format(line)}</li>" for line in lines if line.strip())
    return f"<{tag}>{items}</{tag}>" if items else ""


def _format_block(block: str) -> str:
    lines = block.split("\n")
    stripped = [ln for ln in lines if ln.strip()]
    if not stripped:
        return ""

    if all(_BULLET_LINE.match(ln) for ln in stripped):
        items = [_BULLET_LINE.match(ln).group(2) for ln in stripped]  # type: ignore[union-attr]
        return _format_list(items, ordered=False)

    if all(_NUMBERED_LINE.match(ln) for ln in stripped):
        items = [_NUMBERED_LINE.match(ln).group(2) for ln in stripped]  # type: ignore[union-attr]
        return _format_list(items, ordered=True)

    if len(stripped) == 1:
        m = _HEADING_LINE.match(stripped[0])
        if m:
            level = min(len(m.group(1)), 4)
            return f"<h{level}>{_inline_format(m.group(2))}</h{level}>"

    # Mixed lines: heading / list runs / prose
    segments: list[str] = []
    buf: list[str] = []
    buf_kind: str | None = None

    def flush_buf() -> None:
        nonlocal buf, buf_kind
        if not buf:
            return
        if buf_kind == "bullet":
            segments.append(_format_list(buf, ordered=False))
        elif buf_kind == "numbered":
            segments.append(_format_list(buf, ordered=True))
        else:
            segments.append(_paragraphs_from_prose("\n".join(buf)))
        buf = []
        buf_kind = None

    for ln in lines:
        if not ln.strip():
            flush_buf()
            continue
        hm = _HEADING_LINE.match(ln)
        if hm:
            flush_buf()
            level = min(len(hm.group(1)), 4)
            segments.append(f"<h{level}>{_inline_format(hm.group(2))}</h{level}>")
            continue
        bm = _BULLET_LINE.match(ln)
        if bm:
            if buf_kind not in (None, "bullet"):
                flush_buf()
            buf_kind = "bullet"
            buf.append(bm.group(2))
            continue
        nm = _NUMBERED_LINE.match(ln)
        if nm:
            if buf_kind not in (None, "numbered"):
                flush_buf()
            buf_kind = "numbered"
            buf.append(nm.group(2))
            continue
        if buf_kind not in (None, "prose"):
            flush_buf()
        buf_kind = "prose"
        buf.append(ln)
    flush_buf()
    return "\n".join(s for s in segments if s)


def _format_fenced_code(body: str, lang: str) -> str:
    escaped = html.escape(body.strip("\n"))
    if lang:
        return f'<pre><code class="language-{html.escape(lang)}">{escaped}</code></pre>'
    return f"<pre><code>{escaped}</code></pre>"


def response_text_to_html(text: str) -> str:
    """
    Convert assistant response text to an HTML fragment.

    - Fenced ``` code blocks → pre/code
    - Bullet / numbered lines → ul/ol
    - Markdown headings → h1–h4
    - Blank lines → new paragraphs; long prose also split at sentence ends
    - Inline `code` and **strong**
    """
    text = _truncate(text)
    if not text:
        return ""

    parts: list[str] = []
    last = 0
    for m in _FENCED_CODE.finditer(text):
        if m.start() > last:
            segment = text[last : m.start()].strip()
            if segment:
                formatted = _format_block(segment)
                if formatted:
                    parts.append(formatted)
        parts.append(_format_fenced_code(m.group(2), m.group(1).strip()))
        last = m.end()
    tail = text[last:].strip()
    if tail:
        formatted = _format_block(tail)
        if formatted:
            parts.append(formatted)

    if not parts:
        return _wrap_paragraph(text)

    return "\n".join(parts)


_PIPELINE_RESPONSE_HTML = True


def enrich_adversarial_results_with_response_html(results: list[dict[str, Any]]) -> None:
    """Mutate each row in place: set ``response_html`` from ``response`` (heuristic, no LLM)."""
    if not _PIPELINE_RESPONSE_HTML:
        return

    n = len(results)
    for i, row in enumerate(results, 1):
        text = row.get("response")
        if not isinstance(text, str) or not text.strip():
            row["response_html"] = ""
            continue
        try:
            row["response_html"] = response_text_to_html(text)
            print(f"  [html {i}/{n}] {row.get('id', '')}", flush=True)
        except Exception as exc:
            print(f"  [!] response_html failed for {row.get('id', i)}: {exc}", flush=True)
            row["response_html"] = ""
