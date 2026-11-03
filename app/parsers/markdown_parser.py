"""Markdown parser based on markdown-it-py (CommonMark + GFM tables).

Inline content is kept in its raw Markdown form so that code spans
(```customer_id```) survive; they are a strong signal for entity extraction.
Raw HTML is never rendered or executed.
"""

from __future__ import annotations

from markdown_it import MarkdownIt

from app.nlp.preprocessing import clean_inline_markup
from app.parsers.blocks import Block, BlockType, DocumentParseError, ParsedDocument


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            text = data.decode(encoding)
            if "\x00" not in text:
                return text
        except UnicodeDecodeError:
            continue
    raise DocumentParseError("The Markdown file is not valid text (unsupported encoding).")


def parse_markdown(data: bytes, source_name: str = "document.md") -> ParsedDocument:
    text = _decode(data)
    if not text.strip():
        raise DocumentParseError("The Markdown file is empty.")
    md = MarkdownIt("commonmark", {"html": False}).enable("table")
    try:
        tokens = md.parse(text)
    except Exception as exc:  # noqa: BLE001
        raise DocumentParseError(f"Could not parse Markdown: {exc}") from exc

    doc = ParsedDocument(source_name=source_name, source_type="markdown")
    i = 0
    list_depth = 0
    table_rows: list[list[str]] = []
    current_row: list[str] = []
    table_start = ""
    while i < len(tokens):
        tok = tokens[i]
        loc = f"line {tok.map[0] + 1}" if tok.map else ""
        if tok.type == "heading_open":
            inline = tokens[i + 1]
            doc.blocks.append(Block(BlockType.HEADING, clean_inline_markup(inline.content),
                                    level=int(tok.tag[1]), location=loc))
            i += 3
            continue
        if tok.type in ("bullet_list_open", "ordered_list_open"):
            list_depth += 1
        elif tok.type in ("bullet_list_close", "ordered_list_close"):
            list_depth -= 1
        elif tok.type == "paragraph_open":
            inline = tokens[i + 1]
            btype = BlockType.LIST_ITEM if list_depth > 0 else BlockType.PARAGRAPH
            content = clean_inline_markup(inline.content.replace("\n", " "))
            if content:
                doc.blocks.append(Block(btype, content, location=loc))
            i += 3
            continue
        elif tok.type in ("fence", "code_block"):
            doc.blocks.append(Block(BlockType.CODE, tok.content.rstrip("\n"),
                                    language=(tok.info or "").strip().lower(), location=loc))
        elif tok.type == "table_open":
            table_rows, table_start = [], loc
        elif tok.type == "tr_open":
            current_row = []
        elif tok.type in ("th_open", "td_open"):
            current_row.append(clean_inline_markup(tokens[i + 1].content))
        elif tok.type == "tr_close":
            table_rows.append(current_row)
        elif tok.type == "table_close":
            if table_rows:
                doc.blocks.append(Block(BlockType.TABLE, rows=table_rows, location=table_start))
        i += 1

    if not doc.blocks:
        raise DocumentParseError("No readable content was found in the Markdown file.")
    return doc

