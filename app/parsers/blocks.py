"""Format-neutral representation of a parsed document.

PDF, DOCX and Markdown parsers all emit a flat, ordered list of :class:`Block`
objects. The API extractor works only on blocks, so it is independent of the
source format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class BlockType(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE = "table"
    CODE = "code"


@dataclass
class Block:
    type: BlockType
    text: str = ""
    level: int = 0  # heading level (1 = top)
    rows: list[list[str]] = field(default_factory=list)  # table rows, first row = header
    language: str = ""  # code block info string
    location: str = ""  # human-readable position, e.g. "page 2" or "line 14"

    def as_text(self) -> str:
        if self.type == BlockType.TABLE:
            return "\n".join(" | ".join(row) for row in self.rows)
        return self.text


@dataclass
class ParsedDocument:
    source_name: str
    source_type: str
    blocks: list[Block] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n".join(b.as_text() for b in self.blocks)


class DocumentParseError(ValueError):
    """Raised when an uploaded file cannot be parsed. Message is user-facing."""

