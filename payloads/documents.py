"""
Text and PDF payload generators. Text via stdlib; PDFs via reportlab.
All functions return the absolute Path to the created file.
Unified PDF: up to 3 lines with font_size, color, alpha, position; optional hidden content; optional source PDF.
"""
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from payloads.config import get_output_dir
from payloads._utils import resolve_output_path

# A4 in points (reportlab)
A4_WIDTH, A4_HEIGHT = 595, 842
PDF_PADDING = 50


def _normalize_alpha(value: Any, default: int = 255) -> int:
    """Normalize alpha to 0-255; accepts 0-1 floats or 0-255 ints."""
    if value is None or value == "":
        return default
    try:
        alpha = float(value)
    except (TypeError, ValueError):
        return default
    if 0 <= alpha <= 1:
        alpha *= 255
    return min(255, max(0, int(round(alpha))))


def _coerce_position(value: Any, default: str = "top_left") -> Union[str, tuple[float, float]]:
    """Return named position or absolute (x, y) coordinates from LLM/discovery args."""
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return (float(value[0]), float(value[1]))
        except (TypeError, ValueError):
            pass
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _pdf_parse_color(value: Optional[str]) -> tuple:
    """Return (r, g, b) in 0-1 for reportlab. Supports hex and names."""
    if not value or not str(value).strip():
        return (0, 0, 0)
    s = str(value).strip()
    try:
        from reportlab.lib.colors import toColor
        c = toColor(s)
        return (c.red, c.green, c.blue)
    except Exception:
        return (0, 0, 0)


def _pdf_position_to_xy(
    position: str,
    width: float,
    height: float,
    block_width: float,
    block_height: float,
    padding: float = PDF_PADDING,
) -> tuple:
    """Return (x, y) for reportlab (origin bottom-left). position e.g. top_left, center."""
    pos = (position or "top_left").strip().lower().replace(" ", "_")
    if "_" in pos:
        parts = pos.split("_", 1)
        pos_v = parts[0] if parts[0] in ("top", "center", "bottom") else "top"
        pos_h = parts[1] if len(parts) > 1 and parts[1] in ("left", "center", "right") else "left"
    else:
        pos_v = pos if pos in ("top", "center", "bottom") else "top"
        pos_h = "left"
    if pos_v == "top":
        y = height - padding - block_height
    elif pos_v == "bottom":
        y = padding
    else:
        y = max(0, (height - block_height) / 2)
    if pos_h == "left":
        x = padding
    elif pos_h == "right":
        x = max(padding, width - padding - block_width)
    else:
        x = max(0, (width - block_width) / 2)
    return (x, y)


def _normalize_pdf_line(line: Any, default_font_size: int = 12) -> Optional[Dict[str, Any]]:
    """Return dict with text, font_size, color, alpha, position; alpha 0-255. None if text empty."""
    if isinstance(line, dict):
        text = (line.get("text") or "").strip()[:80]
        if not text:
            return None
        position = _coerce_position(line.get("position"), "top_left")
        row: Dict[str, Any] = {
            "text": text,
            "font_size": max(8, min(72, int(line.get("font_size") or default_font_size))),
            "color": (line.get("color") or "").strip() or None,
            "alpha": _normalize_alpha(line.get("alpha"), 255),
            "position": position if isinstance(position, str) else "top_left",
        }
        if isinstance(position, tuple):
            row["position_xy"] = position
        return row
    text = str(line).strip()[:80]
    if not text:
        return None
    return {"text": text, "font_size": default_font_size, "color": None, "alpha": 255, "position": "top_left"}


def write_text_file(
    content: str,
    filename: Optional[str] = None,
    subdir: str = "docs",
    extension: str = "txt",
) -> Path:
    """Write a plain text file. Returns absolute path. UTF-8."""
    base = get_output_dir()
    path = resolve_output_path(filename, subdir, extension, base)
    path.write_text(content, encoding="utf-8")
    return path


def create_visible_text_pdf(
    content: str,
    filename: Optional[str] = None,
    subdir: str = "docs",
) -> Path:
    """Create a PDF with visible black text. Returns absolute path."""
    from reportlab.pdfgen import canvas
    from reportlab.lib.colors import black
    from reportlab.lib.pagesizes import A4

    base = get_output_dir()
    path = resolve_output_path(filename, subdir, "pdf", base)
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFillColor(black)
    c.setFont("Helvetica", 11)
    width, height = A4
    y = height - 50
    for line in content.replace("\r", "").split("\n"):
        if y < 50:
            c.showPage()
            c.setFillColor(black)
            c.setFont("Helvetica", 11)
            y = height - 50
        c.drawString(50, y, line[:100])
        y -= 14
    c.save()
    return path


def create_pdf_with_lines(
    text_lines: Optional[List[Union[str, Dict[str, Any]]]] = None,
    hidden_content: Optional[str] = None,
    filename: Optional[str] = None,
    subdir: str = "docs",
    source_pdf: Optional[Union[str, Path, bytes]] = None,
) -> Path:
    """
    Create a PDF with up to 3 lines of text (font_size, color, alpha, position).
    Optional hidden_content (white-on-white). Optional source_pdf to overlay text on existing PDF.
    Returns absolute path.
    """
    from reportlab.pdfgen import canvas
    from reportlab.lib.colors import white, Color
    from reportlab.lib.pagesizes import A4

    width, height = A4[0], A4[1]
    base = get_output_dir()
    path = resolve_output_path(filename, subdir, "pdf", base)

    line_configs: List[Dict[str, Any]] = []
    if text_lines:
        for line in text_lines[:3]:
            cfg = _normalize_pdf_line(line, default_font_size=12)
            if cfg:
                line_configs.append(cfg)
    if not line_configs:
        line_configs = [{"text": "Sample PDF text.", "font_size": 12, "color": None, "alpha": 255, "position": "top_left"}]

    def draw_page(c: "canvas.Canvas") -> None:
        for cfg in line_configs:
            text = cfg["text"]
            font_size = max(8, min(72, int(cfg.get("font_size", 12))))
            r, g, b = _pdf_parse_color(cfg.get("color"))
            alpha = _normalize_alpha(cfg.get("alpha"), 255) / 255.0
            # Approximate block size for positioning
            block_w = min(len(text) * font_size * 0.6, width - 2 * PDF_PADDING)
            block_h = font_size + 4
            position_xy = cfg.get("position_xy")
            if isinstance(position_xy, (list, tuple)) and len(position_xy) >= 2:
                x, y = float(position_xy[0]), float(position_xy[1])
            else:
                pos = str(cfg.get("position") or "top_left").strip() or "top_left"
                x, y = _pdf_position_to_xy(pos, width, height, block_w, block_h, PDF_PADDING)
            c.setFont("Helvetica", font_size)
            c.setFillColor(Color(r, g, b, alpha=alpha))
            c.drawString(x, y, text[:100])
        if hidden_content and hidden_content.strip():
            c.setFillColor(white)
            c.setFont("Helvetica", 11)
            hy = height - 50
            for line in hidden_content.replace("\r", "").split("\n"):
                if hy < 50:
                    c.showPage()
                    c.setFillColor(white)
                    c.setFont("Helvetica", 11)
                    hy = height - 50
                c.drawString(50, hy, line[:100])
                hy -= 14

    if source_pdf:
        import tempfile as _tmp
        import PyPDF2
        overlay_path = _tmp.NamedTemporaryFile(suffix=".pdf", delete=False).name
        try:
            c = canvas.Canvas(overlay_path, pagesize=A4)
            draw_page(c)
            c.save()
            # PdfReader(path) keeps the file open; avoid closing before merge_page (PyPDF2 seeks the stream)
            overlay_reader = PyPDF2.PdfReader(overlay_path)
            overlay_page = overlay_reader.pages[0]
            src_path = str(Path(source_pdf).resolve()) if source_pdf else None
            if not src_path or not Path(src_path).is_file():
                raise FileNotFoundError(f"Source PDF not found: {source_pdf}")
            with open(src_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                writer = PyPDF2.PdfWriter()
                first = reader.pages[0]
                first.merge_page(overlay_page)
                writer.add_page(first)
                for i in range(1, len(reader.pages)):
                    writer.add_page(reader.pages[i])
                with open(path, "wb") as out:
                    writer.write(out)
            return Path(path).resolve()
        except Exception as e:
            raise RuntimeError(f"PDF overlay failed: {e}") from e
        finally:
            try:
                Path(overlay_path).unlink(missing_ok=True)
            except OSError:
                pass
    else:
        c = canvas.Canvas(str(path), pagesize=A4)
        draw_page(c)
        c.save()
        return Path(path).resolve()


def create_pdf_with_invisible_text(
    visible_content: str,
    hidden_content: str,
    filename: Optional[str] = None,
    subdir: str = "docs",
) -> Path:
    """Create a PDF with visible text and hidden (white-on-white) text. Returns absolute path. Kept for backward compat."""
    lines = [{"text": ln.strip()[:80], "font_size": 12, "color": None, "alpha": 255, "position": "top_left"}
             for ln in visible_content.replace("\r", "").split("\n") if ln.strip()][:3]
    if not lines:
        lines = [{"text": visible_content.strip()[:80] or "Benign content.", "font_size": 12, "color": None, "alpha": 255, "position": "top_left"}]
    return create_pdf_with_lines(text_lines=lines, hidden_content=hidden_content, filename=filename, subdir=subdir)


def create_pdf_with_metadata(
    body_content: str,
    subject: str = "",
    author: str = "",
    filename: Optional[str] = None,
    subdir: str = "docs",
    source_pdf: Optional[Union[str, Path]] = None,
) -> Path:
    """Create a PDF with optional metadata payload (Subject/Author).
    If source_pdf is set, copy that PDF and set/update metadata; otherwise create new PDF with body_content."""
    base = get_output_dir()
    path = resolve_output_path(filename, subdir, "pdf", base)
    src_path = str(Path(source_pdf).resolve()) if source_pdf and Path(source_pdf).is_file() else None

    if src_path:
        import PyPDF2

        reader = PyPDF2.PdfReader(src_path)
        writer = PyPDF2.PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        meta = {}
        if subject:
            meta["/Title"] = subject[:200]
            meta["/Subject"] = subject[:200]
        if author:
            meta["/Author"] = author[:200]
        if meta:
            writer.add_metadata(meta)
        with open(path, "wb") as out:
            writer.write(out)
        return Path(path).resolve()

    from reportlab.pdfgen import canvas
    from reportlab.lib.colors import black
    from reportlab.lib.pagesizes import A4

    c = canvas.Canvas(str(path), pagesize=A4)
    if subject:
        c.setTitle(subject[:200])
    if author:
        c.setAuthor(author[:200])
    c.setFillColor(black)
    c.setFont("Helvetica", 11)
    width, height = A4
    y = height - 50
    for line in body_content.replace("\r", "").split("\n"):
        if y < 50:
            c.showPage()
            c.setFillColor(black)
            c.setFont("Helvetica", 11)
            y = height - 50
        c.drawString(50, y, line[:100])
        y -= 14
    c.save()
    return path
