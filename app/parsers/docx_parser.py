"""DOCX parser based on python-docx.

Walks the document body in order (paragraphs and tables interleaved), detects
headings from paragraph styles, code from monospace fonts / code styles, and
wraps inline monospace runs in backticks to preserve "code span" semantics.
Macros and embedded objects are never executed: python-docx only reads XML.
"""

from __future__ import annotations

import io
import zipfile

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.nlp.preprocessing import clean_inline_markup
from app.parsers.blocks import Block, BlockType, DocumentParseError, ParsedDocument

_MONO_FONTS = ("courier", "consolas", "mono", "menlo", "monaco", "source code")
_CODE_STYLES = ("code", "macro", "preformatted", "source")


def _is_mono(run) -> bool:
    name = (run.font.name or "").lower()
    if not name and run.style is not None and run.style.font is not None:
        name = (run.style.font.name or "").lower()
    return any(m in name for m in _MONO_FONTS)


def _paragraph_text(paragraph: Paragraph) -> tuple[str, bool]:
    """Return paragraph text with inline code wrapped in backticks, and whether it is entirely code."""
    parts: list[str] = []
    runs = [r for r in paragraph.runs if r.text]
    all_mono = bool(runs) and all(_is_mono(r) for r in runs)
    for run in runs:
        if _is_mono(run) and not all_mono and run.text.strip():
            parts.append(f"`{run.text.strip()}` " if run.text.endswith(" ") else f"`{run.text.strip()}`")
        else:
            parts.append(run.text)
    text = "".join(parts) if runs else paragraph.text
    return text, all_mono


def _heading_level(style_name: str) -> int:
    lower = style_name.lower()
    if lower == "title":
        return 1
    if lower.startswith("heading"):
        digits = "".join(ch for ch in lower if ch.isdigit())
        return int(digits) if digits else 1
    return 0


def parse_docx(data: bytes, source_name: str = "document.docx") -> ParsedDocument:
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise DocumentParseError("The file is not a valid DOCX document (it is not a ZIP/OOXML package).")
    try:
        document = Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise DocumentParseError(f"Could not open DOCX document: {exc}") from exc

    doc = ParsedDocument(source_name=source_name, source_type="docx")
    code_buffer: list[str] = []
    paragraph_index = 0

    def flush_code() -> None:
        if code_buffer:
            doc.blocks.append(Block(BlockType.CODE, "\n".join(code_buffer), location=f"paragraph {paragraph_index}"))
            code_buffer.clear()

    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph_index += 1
            paragraph = Paragraph(child, document)
            style_name = paragraph.style.name if paragraph.style is not None else ""
            text, all_mono = _paragraph_text(paragraph)
            is_code = all_mono or any(s in style_name.lower() for s in _CODE_STYLES)
            if is_code:
                code_buffer.append(text.rstrip())
                continue
            flush_code()
            if not text.strip():
                continue
            loc = f"paragraph {paragraph_index}"
            level = _heading_level(style_name)
            if level:
                doc.blocks.append(Block(BlockType.HEADING, clean_inline_markup(text), level=level, location=loc))
            elif "list" in style_name.lower():
                doc.blocks.append(Block(BlockType.LIST_ITEM, clean_inline_markup(text), location=loc))
            else:
                doc.blocks.append(Block(BlockType.PARAGRAPH, clean_inline_markup(text), location=loc))
        elif tag == "tbl":
            flush_code()
            table = Table(child, document)
            rows = []
            for row in table.rows:
                cells = [clean_inline_markup(cell.text) for cell in row.cells]
                if any(cells):
                    rows.append(cells)
            if rows:
                doc.blocks.append(Block(BlockType.TABLE, rows=rows, location=f"after paragraph {paragraph_index}"))
    flush_code()

    if not doc.blocks:
        raise DocumentParseError("No readable content was found in the DOCX document.")
    return doc

