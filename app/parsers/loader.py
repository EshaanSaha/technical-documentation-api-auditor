"""Entry points that dispatch uploaded files to the correct parser."""

from __future__ import annotations

from pathlib import Path

from app.core.models import ApiModel
from app.parsers.blocks import DocumentParseError, ParsedDocument
from app.parsers.docx_parser import parse_docx
from app.parsers.documentation_extractor import extract_api_from_document
from app.parsers.markdown_parser import parse_markdown
from app.parsers.openapi_parser import parse_openapi
from app.parsers.pdf_parser import parse_pdf

_DOC_PARSERS = {".pdf": parse_pdf, ".docx": parse_docx, ".md": parse_markdown, ".markdown": parse_markdown}


def parse_document_blocks(data: bytes, filename: str) -> ParsedDocument:
    ext = Path(filename).suffix.lower()
    parser = _DOC_PARSERS.get(ext)
    if parser is None:
        raise DocumentParseError(f"Unsupported documentation format '{ext}'. Use PDF, DOCX or Markdown.")
    return parser(data, filename)


def parse_documentation(data: bytes, filename: str) -> ApiModel:
    """Parse documentation (PDF/DOCX/Markdown) into an ApiModel."""
    return extract_api_from_document(parse_document_blocks(data, filename))


def parse_specification(data: bytes, filename: str) -> ApiModel:
    """Parse an OpenAPI JSON/YAML specification into an ApiModel."""
    if Path(filename).suffix.lower() not in (".json", ".yaml", ".yml"):
        raise DocumentParseError("Unsupported specification format. Use OpenAPI JSON or YAML.")
    return parse_openapi(data, filename)

