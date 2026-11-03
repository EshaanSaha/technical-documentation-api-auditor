"""Generate DOCX, PDF and JSON sample files from the Markdown/YAML sources.

Ensures ``data/sample_data/`` contains ready-to-upload files across 3 realistic
enterprise API suites in all 5 supported formats (Markdown, DOCX, PDF, OpenAPI
YAML, OpenAPI JSON):

1. **ShopWave Commerce API v2.3** (10 endpoints — Customers, Orders, Products)
   - ``shopwave_openapi.yaml`` / ``shopwave_openapi.json``
   - ``shopwave_api_docs.md`` / ``.docx`` / ``.pdf`` (inconsistent)
   - ``shopwave_api_docs_clean.md`` (100% consistent reference)
2. **FinLedger Enterprise Banking & Payments API v3.4** (18 endpoints — Accounts,
   ACH/Wire Transfers, Corporate Cards, FX Quotes, Compliance KYC, Webhooks)
   - ``finledger_openapi.yaml`` / ``finledger_openapi.json``
   - ``finledger_api_docs.md`` / ``.docx`` / ``.pdf``
3. **MedCore Clinical EHR & Patient Portal API v4.1** (15 endpoints — Patient
   Charts, Appointments, e-Prescriptions, Diagnostic Labs, Insurance Claims)
   - ``medcore_openapi.yaml`` / ``medcore_openapi.json``
   - ``medcore_api_docs.md`` / ``.docx`` / ``.pdf``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import yaml
from docx import Document
from docx.shared import Pt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings  # noqa: E402
from app.parsers.blocks import BlockType  # noqa: E402
from app.parsers.markdown_parser import parse_markdown  # noqa: E402

SAMPLE_SUITES: tuple[tuple[str, str], ...] = (
    ("shopwave_openapi.yaml", "shopwave_api_docs.md"),
    ("finledger_openapi.yaml", "finledger_api_docs.md"),
    ("medcore_openapi.yaml", "medcore_api_docs.md"),
)


def build_openapi_json(yaml_path: Path, json_path: Path) -> None:
    spec_obj = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    json_path.write_text(json.dumps(spec_obj, indent=2), encoding="utf-8")


def build_docx_from_markdown(md_path: Path, docx_path: Path) -> None:
    parsed = parse_markdown(md_path.read_bytes(), md_path.name)
    doc = Document()

    for block in parsed.blocks:
        if block.type == BlockType.HEADING:
            doc.add_heading(block.text, level=min(block.level, 4))
        elif block.type == BlockType.PARAGRAPH:
            doc.add_paragraph(block.text)
        elif block.type == BlockType.LIST_ITEM:
            doc.add_paragraph(block.text, style="List Bullet")
        elif block.type == BlockType.CODE:
            p = doc.add_paragraph()
            run = p.add_run(block.text)
            run.font.name = "Consolas"
            run.font.size = Pt(9.5)
        elif block.type == BlockType.TABLE and block.rows:
            cols = max(len(r) for r in block.rows)
            table = doc.add_table(rows=len(block.rows), cols=cols)
            for r_idx, row in enumerate(block.rows):
                for c_idx, val in enumerate(row):
                    table.cell(r_idx, c_idx).text = val

    doc.save(str(docx_path))


def build_pdf_from_markdown(md_path: Path, pdf_path: Path) -> None:
    parsed = parse_markdown(md_path.read_bytes(), md_path.name)
    pdf = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=md_path.stem,
    )
    styles = getSampleStyleSheet()
    h_styles = {
        1: ParagraphStyle("H1", parent=styles["Heading1"], fontSize=18, leading=22, spaceBefore=10, spaceAfter=6),
        2: ParagraphStyle("H2", parent=styles["Heading2"], fontSize=14, leading=18, spaceBefore=8, spaceAfter=4),
        3: ParagraphStyle("H3", parent=styles["Heading3"], fontSize=12, leading=15, spaceBefore=6, spaceAfter=3),
    }
    body_style = ParagraphStyle("Body", parent=styles["Normal"], fontSize=10, leading=13, spaceAfter=4)
    code_style = ParagraphStyle("Code", fontName="Courier", fontSize=8.5, leading=10.5, spaceBefore=3, spaceAfter=5)

    tbl_style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ])

    story = []
    for block in parsed.blocks:
        if block.type == BlockType.HEADING:
            st = h_styles.get(block.level, h_styles[3])
            story.append(Paragraph(xml_escape(block.text), st))
        elif block.type == BlockType.PARAGRAPH:
            story.append(Paragraph(xml_escape(block.text), body_style))
        elif block.type == BlockType.LIST_ITEM:
            story.append(Paragraph("- " + xml_escape(block.text), body_style))
        elif block.type == BlockType.CODE:
            story.append(Preformatted(block.text, code_style))
        elif block.type == BlockType.TABLE and block.rows:
            t = Table(block.rows, repeatRows=1)
            t.setStyle(tbl_style)
            story.append(t)
            story.append(Spacer(1, 3 * mm))

    pdf.build(story)


def ensure_sample_files() -> None:
    sample_dir = settings.sample_dir
    sample_dir.mkdir(parents=True, exist_ok=True)
    for spec_yaml_name, doc_md_name in SAMPLE_SUITES:
        yaml_path = sample_dir / spec_yaml_name
        md_path = sample_dir / doc_md_name
        if yaml_path.is_file():
            json_path = sample_dir / f"{yaml_path.stem}.json"
            build_openapi_json(yaml_path, json_path)
        if md_path.is_file():
            build_docx_from_markdown(md_path, sample_dir / f"{md_path.stem}.docx")
            build_pdf_from_markdown(md_path, sample_dir / f"{md_path.stem}.pdf")


if __name__ == "__main__":
    ensure_sample_files()
    print("[OK] Generated all enterprise sample suites in data/sample_data/")
