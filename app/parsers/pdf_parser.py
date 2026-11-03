"""PDF parser based on PyMuPDF.

Layout reconstruction:

* Tables are detected with ``page.find_tables()`` and emitted as table blocks;
  text inside table areas is excluded from the running text.
* Headings are detected from font size relative to the dominant body size,
  or bold short lines.
* Monospace lines are grouped into code blocks (JSON examples); monospace spans
  inside normal text are wrapped in backticks.

PDF JavaScript, links and embedded files are ignored; only text is read.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import pymupdf as fitz  # PyMuPDF

from app.core.logging_config import get_logger
from app.nlp.preprocessing import clean_inline_markup
from app.parsers.blocks import Block, BlockType, DocumentParseError, ParsedDocument

logger = get_logger(__name__)

_MONO_HINTS = ("courier", "mono", "consolas", "menlo", "code")
_BULLETS = ("\u2022", "\u25cf", "\u25aa", "- ", "* ")


@dataclass
class _Line:
    y0: float
    y1: float
    text: str
    size: float
    bold: bool
    mono: bool
    block_no: int


def _is_mono(span: dict) -> bool:
    return bool(span.get("flags", 0) & 8) or any(h in span.get("font", "").lower() for h in _MONO_HINTS)


def _inside(bbox: tuple, areas: list[tuple]) -> bool:
    x0, y0, x1, y1 = bbox
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return any(a[0] - 1 <= cx <= a[2] + 1 and a[1] - 1 <= cy <= a[3] + 1 for a in areas)


def _page_lines(page: "fitz.Page", table_areas: list[tuple]) -> list[_Line]:
    lines: list[_Line] = []
    data = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    for block_no, block in enumerate(data.get("blocks", [])):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s.get("text", "").strip() or s.get("text") == " "]
            if not spans or _inside(line["bbox"], table_areas):
                continue
            all_mono = all(_is_mono(s) for s in spans if s["text"].strip())
            parts = []
            for s in spans:
                txt = s["text"]
                if _is_mono(s) and not all_mono and txt.strip():
                    parts.append(f"`{txt.strip()}`" + (" " if txt.endswith(" ") else ""))
                else:
                    parts.append(txt)
            text = "".join(parts).rstrip()
            if not text.strip():
                continue
            text_spans = [s for s in spans if s["text"].strip()]
            lines.append(_Line(
                y0=line["bbox"][1], y1=line["bbox"][3], text=text,
                size=round(max(s["size"] for s in text_spans), 1),
                bold=all(bool(s.get("flags", 0) & 16) or "bold" in s.get("font", "").lower() for s in text_spans),
                mono=all_mono, block_no=block_no,
            ))
    return lines


def parse_pdf(data: bytes, source_name: str = "document.pdf") -> ParsedDocument:
    if not data.lstrip().startswith(b"%PDF"):
        raise DocumentParseError("The file is not a valid PDF (missing %PDF header).")
    try:
        pdf = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001
        raise DocumentParseError(f"Could not open PDF: {exc}") from exc
    if pdf.needs_pass:
        raise DocumentParseError("The PDF is password protected.")

    doc = ParsedDocument(source_name=source_name, source_type="pdf")
    pages: list[tuple[int, list[_Line], list[tuple[float, Block]]]] = []
    size_counter: Counter[float] = Counter()
    try:
        for page_index, page in enumerate(pdf, start=1):
            tables: list[tuple[float, Block]] = []
            areas: list[tuple] = []
            try:
                for table in page.find_tables().tables:
                    rows = [[clean_inline_markup(c or "") for c in row] for row in table.extract()]
                    rows = [r for r in rows if any(r)]
                    if len(rows) >= 2:
                        areas.append(tuple(table.bbox))
                        tables.append((table.bbox[1], Block(BlockType.TABLE, rows=rows, location=f"page {page_index}")))
            except Exception as exc:  # noqa: BLE001 - table detection is best effort
                logger.debug("Table detection failed on page %d: %s", page_index, exc)
            lines = _page_lines(page, areas)
            for ln in lines:
                if not ln.mono:
                    size_counter[ln.size] += len(ln.text)
            pages.append((page_index, lines, tables))
    finally:
        pdf.close()

    if not any(lines or tables for _, lines, tables in pages):
        raise DocumentParseError("No extractable text found in the PDF (it may be a scanned image).")

    body_size = size_counter.most_common(1)[0][0] if size_counter else 10.0
    heading_sizes = sorted({s for s in size_counter if s >= body_size * 1.12}, reverse=True)

    def heading_level(line: _Line) -> int:
        if line.mono:
            return 0
        if line.size in heading_sizes:
            return heading_sizes.index(line.size) + 1
        if line.bold and len(line.text) < 90 and not line.text.rstrip().endswith((".", ":", ",")):
            return len(heading_sizes) + 1
        return 0

    for page_index, lines, tables in pages:
        items: list[tuple[float, Block]] = list(tables)
        para: list[_Line] = []
        code: list[_Line] = []

        def flush_para() -> None:
            if para:
                text = clean_inline_markup(" ".join(p.text.strip() for p in para))
                is_bullet = para[0].text.lstrip().startswith(_BULLETS)
                items.append((para[0].y0, Block(BlockType.LIST_ITEM if is_bullet else BlockType.PARAGRAPH,
                                                text, location=f"page {page_index}")))
                para.clear()

        def flush_code() -> None:
            if code:
                items.append((code[0].y0, Block(BlockType.CODE, "\n".join(c.text for c in code),
                                                location=f"page {page_index}")))
                code.clear()

        for line in lines:
            if line.mono:
                flush_para()
                code.append(line)
                continue
            flush_code()
            level = heading_level(line)
            if level:
                flush_para()
                items.append((line.y0, Block(BlockType.HEADING, clean_inline_markup(line.text), level=level,
                                             location=f"page {page_index}")))
                continue
            starts_bullet = line.text.lstrip().startswith(_BULLETS)
            # New paragraph when PyMuPDF block changes, a bullet starts, or there is a vertical gap
            if para and (line.block_no != para[-1].block_no or starts_bullet or line.y0 - para[-1].y1 > line.size * 0.8):
                flush_para()
            para.append(line)
        flush_para()
        flush_code()
        items.sort(key=lambda item: item[0])
        doc.blocks.extend(block for _, block in items)

    return doc

