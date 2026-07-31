#!/usr/bin/env python3
"""Create minimal stock background PDFs and PNG for payload overlay tests."""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "assets"


def _minimal_pdf(title: str, lines: list[str]) -> bytes:
    """Build a tiny single-page PDF with Helvetica text."""
    content_lines = ["BT", "/F1 14 Tf", "72 720 Td"]
    content_lines.append(f"({title}) Tj")
    y = 696
    for line in lines:
        content_lines.append(f"0 -24 Td ({line}) Tj")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1", errors="replace")
    objects = []
    objects.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    objects.append(b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n")
    objects.append(
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
    )
    objects.append(
        f"4 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode()
        + stream
        + b"\nendstream\nendobj\n"
    )
    objects.append(
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
    )
    pdf = b"%PDF-1.4\n"
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf))
        pdf += obj
    xref_pos = len(pdf)
    pdf += f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode()
    for off in offsets[1:]:
        pdf += f"{off:010d} 00000 n \n".encode()
    pdf += f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    return pdf


def _minimal_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    raw = b""
    r, g, b = rgb
    row = bytes([0, r, g, b] * width)
    for _ in range(height):
        raw += row
    compressed = zlib.compress(raw, 9)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


def main() -> None:
    pdf_dir = ROOT / "background-pdf"
    img_dir = ROOT / "background-img"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    img_dir.mkdir(parents=True, exist_ok=True)

    specs = [
        ("business_report.pdf", "Quarterly Business Report", ["Revenue: $2.4M", "Growth: 4.2%"]),
        ("resume-v1.pdf", "Jane Doe - Senior Analyst", ["Experience: 8 years", "Skills: Finance, Risk"]),
        ("property_brochure.pdf", "Riverside Development", ["Units: 24 apartments", "Location: City Centre"]),
    ]
    for name, title, lines in specs:
        (pdf_dir / name).write_bytes(_minimal_pdf(title, lines))

    (img_dir / "client_statement.png").write_bytes(_minimal_png(640, 400, (240, 240, 245)))
    print(f"Created assets under {ROOT}")


if __name__ == "__main__":
    main()
