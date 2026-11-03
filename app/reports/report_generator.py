"""Downloadable validation report generator (Module H).

Supports:
* CSV (``.csv``)
* Excel workbook (``.xlsx``, multi-sheet with formatted headers)
* PDF document (``.pdf``, enterprise engineering report via ReportLab)

Every report includes:
1. Project summary
2. Files analyzed
3. Total endpoints (specification vs documentation)
4. Matched endpoints (exact & likely)
5. Missing endpoints
6. Parameter mismatches
7. Schema mismatches
8. Description inconsistencies
9. Overall completeness score & weighted breakdown
10. Recommended corrections with reproducible evidence
"""

from __future__ import annotations

import csv
import io
from xml.sax.saxutils import escape as xml_escape

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.core.models import ValidationResult


def _summary_rows(result: ValidationResult) -> list[tuple[str, str]]:
    s = result.summary or {}
    sev = s.get("severity_counts") or {}
    return [
        ("Session ID", result.session_id or "N/A"),
        ("Session Name", result.session_name or "Validation Audit"),
        ("Created At", result.created_at),
        ("API Title", result.api_title or "N/A"),
        ("API Version", result.api_version or "N/A"),
        ("Documentation File", result.documentation_file),
        ("OpenAPI Specification File", result.specification_file),
        ("Overall Completeness Score", f"{result.completeness_score:.1f} / 100.0"),
        ("Total Endpoints in Specification", str(s.get("total_spec_endpoints", 0))),
        ("Total Endpoints in Documentation", str(s.get("total_doc_endpoints", 0))),
        ("Successfully Matched Endpoints", str(s.get("matched_endpoints", 0))),
        ("  - Exact Matches", str(s.get("exact_matched_endpoints", 0))),
        ("  - Likely Matches", str(s.get("likely_matched_endpoints", 0))),
        ("Missing Endpoints", str(s.get("missing_endpoints", 0))),
        ("Unexpected Documented Endpoints", str(s.get("unexpected_endpoints", 0))),
        ("Parameter Mismatches", str(s.get("parameter_mismatches", 0))),
        ("Schema & Status Inconsistencies", str(s.get("schema_inconsistencies", 0))),
        ("Description Inconsistencies", str(s.get("description_inconsistencies", 0))),
        ("Authentication Issues", str(s.get("authentication_issues", 0))),
        (
            "Total Findings (Critical / High / Medium / Low)",
            f"{s.get('total_issues', len(result.issues))} "
            f"({sev.get('Critical', 0)} / {sev.get('High', 0)} / {sev.get('Medium', 0)} / {sev.get('Low', 0)})",
        ),
    ]


# --------------------------------------------------------------------------- #
# CSV Export
# --------------------------------------------------------------------------- #
def generate_csv_report(result: ValidationResult) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)

    writer.writerow(["# TECHNICAL DOCUMENTATION & API CONSISTENCY AUDIT REPORT"])
    for key, val in _summary_rows(result):
        writer.writerow([key, val])

    writer.writerow([])
    writer.writerow(["# COMPLETENESS SCORE BREAKDOWN"])
    writer.writerow(["Dimension", "Weight", "Score (%)", "Details"])
    for comp in result.score_breakdown:
        writer.writerow([comp.name, f"{comp.weight:.2f}", f"{comp.score * 100:.1f}", comp.detail])

    writer.writerow([])
    writer.writerow(["# ENDPOINT MATCHING"])
    writer.writerow(["Status", "Spec Method", "Spec Path", "Doc Method", "Doc Path", "Confidence", "Explanation"])
    for m in result.matches:
        writer.writerow([
            m.status.value,
            m.spec_method or "",
            m.spec_path or "",
            m.doc_method or "",
            m.doc_path or "",
            f"{m.confidence:.2f}",
            m.explanation,
        ])

    writer.writerow([])
    writer.writerow(["# VALIDATION FINDINGS & RECOMMENDED CORRECTIONS"])
    writer.writerow([
        "Issue ID",
        "Severity",
        "Category",
        "Method",
        "Endpoint",
        "Issue Type",
        "Expected (OpenAPI Spec)",
        "Actual (Documentation)",
        "Evidence",
        "Explanation",
        "Recommended Correction",
    ])
    for issue in result.issues:
        writer.writerow([
            issue.issue_id,
            issue.severity.value,
            issue.category.value,
            issue.method,
            issue.endpoint,
            issue.issue_type,
            issue.expected,
            issue.actual,
            issue.evidence,
            issue.explanation,
            issue.suggestion,
        ])

    return buf.getvalue().encode("utf-8-sig")


# --------------------------------------------------------------------------- #
# Excel (.xlsx) Export
# --------------------------------------------------------------------------- #
def _style_sheet_header(ws, col_count: int) -> None:
    header_fill = PatternFill(start_color="315B8A", end_color="315B8A", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, size=10)
    for col in range(1, col_count + 1):
        cell = ws.cell(row=1, column=col)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"


def _autosize_columns(ws, max_width: int = 52) -> None:
    for col_cells in ws.columns:
        col_letter = col_cells[0].column_letter
        length = max(len(str(c.value or "")) for c in col_cells[:80])
        ws.column_dimensions[col_letter].width = max(12, min(max_width, length + 3))


def generate_excel_report(result: ValidationResult) -> bytes:
    wb = Workbook()

    # 1. Summary sheet
    ws_sum = wb.active
    ws_sum.title = "Summary"
    ws_sum.append(["Metric", "Value"])
    _style_sheet_header(ws_sum, 2)
    for k, v in _summary_rows(result):
        ws_sum.append([k, v])
    ws_sum.append([])
    ws_sum.append(["Score Component", "Weight", "Component Score (%)", "Evidence / Detail"])
    for comp in result.score_breakdown:
        ws_sum.append([comp.name, round(comp.weight, 3), round(comp.score * 100, 1), comp.detail])
    _autosize_columns(ws_sum, 65)

    # 2. Findings sheet
    ws_iss = wb.create_sheet("Findings")
    headers_iss = [
        "Issue ID",
        "Severity",
        "Category",
        "Method",
        "Endpoint",
        "Issue Type",
        "Expected (Spec)",
        "Actual (Documented)",
        "Evidence",
        "Explanation",
        "Recommended Correction",
    ]
    ws_iss.append(headers_iss)
    _style_sheet_header(ws_iss, len(headers_iss))
    for i in result.issues:
        ws_iss.append([
            i.issue_id,
            i.severity.value,
            i.category.value,
            i.method,
            i.endpoint,
            i.issue_type,
            i.expected,
            i.actual,
            i.evidence,
            i.explanation,
            i.suggestion,
        ])
    _autosize_columns(ws_iss)

    # 3. Endpoint Matching sheet
    ws_ep = wb.create_sheet("Endpoint Matching")
    headers_ep = ["Match Status", "Spec Method", "Spec Path", "Doc Method", "Doc Path", "Confidence", "Explanation"]
    ws_ep.append(headers_ep)
    _style_sheet_header(ws_ep, len(headers_ep))
    for m in result.matches:
        ws_ep.append([
            m.status.value,
            m.spec_method or "",
            m.spec_path or "",
            m.doc_method or "",
            m.doc_path or "",
            round(m.confidence, 2),
            m.explanation,
        ])
    _autosize_columns(ws_ep)

    # 4. Parameter & Schema Comparison sheet
    ws_cmp = wb.create_sheet("Parameters & Schemas")
    headers_cmp = [
        "Method",
        "Endpoint",
        "Scope",
        "Spec Name",
        "Documented Name",
        "Expected Type",
        "Documented Type",
        "Expected Required",
        "Documented Required",
        "Expected Location",
        "Documented Location",
        "Status",
    ]
    ws_cmp.append(headers_cmp)
    _style_sheet_header(ws_cmp, len(headers_cmp))
    for row in result.comparisons:
        ws_cmp.append([
            row.method,
            row.endpoint,
            row.scope,
            row.name,
            row.documented_name,
            row.expected_type,
            row.documented_type,
            row.expected_required,
            row.documented_required,
            row.expected_location,
            row.documented_location,
            row.status,
        ])
    _autosize_columns(ws_cmp)

    # 5. Description Consistency sheet
    ws_desc = wb.create_sheet("Descriptions")
    headers_desc = ["Method", "Endpoint", "Element", "Cosine Similarity", "Classification", "Specification Text", "Documentation Text"]
    ws_desc.append(headers_desc)
    _style_sheet_header(ws_desc, len(headers_desc))
    for d in result.descriptions:
        ws_desc.append([
            d.method,
            d.endpoint,
            d.element,
            round(d.similarity, 3) if d.similarity is not None else "N/A",
            d.band,
            d.spec_text,
            d.doc_text,
        ])
    _autosize_columns(ws_desc, 60)

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# --------------------------------------------------------------------------- #
# PDF Export (ReportLab)
# --------------------------------------------------------------------------- #
def _p(text: str, style: ParagraphStyle) -> Paragraph:
    safe = xml_escape(str(text or "")).replace("\n", "<br/>")
    return Paragraph(safe, style)


def generate_pdf_report(result: ValidationResult) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"API Consistency Audit - {result.session_name}",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "AuditTitle",
        parent=styles["Heading1"],
        fontSize=16,
        leading=20,
        textColor=colors.HexColor("#202B3C"),
        spaceAfter=4,
    )
    h2_style = ParagraphStyle(
        "AuditH2",
        parent=styles["Heading2"],
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#315B8A"),
        spaceBefore=10,
        spaceAfter=4,
    )
    cell_style = ParagraphStyle(
        "AuditCell",
        parent=styles["Normal"],
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#202B3C"),
    )
    header_cell_style = ParagraphStyle(
        "AuditHeaderCell",
        parent=cell_style,
        textColor=colors.white,
        fontName="Helvetica-Bold",
    )

    base_table_style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#315B8A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ])

    story = [
        Paragraph("Technical Documentation &amp; API Consistency Audit Report", title_style),
        Paragraph(
            xml_escape(
                f"Session: {result.session_name} ({result.session_id or 'local'})  |  "
                f"Generated: {result.created_at}  |  "
                f"Completeness Score: {result.completeness_score:.1f}%"
            ),
            cell_style,
        ),
        Spacer(1, 4 * mm),
    ]

    # 1. Executive Summary & Completeness Breakdown side-by-side / stacked
    story.append(Paragraph("1. Project Summary &amp; Audit Metrics", h2_style))
    summary_pairs = _summary_rows(result)
    half = (len(summary_pairs) + 1) // 2
    left_rows = summary_pairs[:half]
    right_rows = summary_pairs[half:]
    combined_summary = [
        [
            _p("Metric", header_cell_style),
            _p("Value", header_cell_style),
            _p("Metric", header_cell_style),
            _p("Value", header_cell_style),
        ]
    ]
    for idx in range(half):
        lk, lv = left_rows[idx]
        rk, rv = right_rows[idx] if idx < len(right_rows) else ("", "")
        combined_summary.append([_p(lk, cell_style), _p(lv, cell_style), _p(rk, cell_style), _p(rv, cell_style)])

    t_sum = Table(combined_summary, colWidths=[65 * mm, 68 * mm, 65 * mm, 68 * mm], repeatRows=1)
    t_sum.setStyle(base_table_style)
    story.append(t_sum)

    # 2. Score Breakdown
    story.append(Paragraph("2. Completeness Score Methodology &amp; Breakdown", h2_style))
    score_rows = [[
        _p("Validation Dimension", header_cell_style),
        _p("Weight", header_cell_style),
        _p("Component Score", header_cell_style),
        _p("Breakdown Evidence", header_cell_style),
    ]]
    for comp in result.score_breakdown:
        score_rows.append([
            _p(comp.name, cell_style),
            _p(f"{comp.weight * 100:.0f}%", cell_style),
            _p(f"{comp.score * 100:.1f}%", cell_style),
            _p(comp.detail, cell_style),
        ])
    t_score = Table(score_rows, colWidths=[65 * mm, 25 * mm, 32 * mm, 144 * mm], repeatRows=1)
    t_score.setStyle(base_table_style)
    story.append(t_score)

    # 3. Endpoint Matching Summary
    story.append(Paragraph("3. Endpoint Matching Analysis", h2_style))
    ep_rows = [[
        _p("Match Status", header_cell_style),
        _p("Spec Endpoint", header_cell_style),
        _p("Documented Endpoint", header_cell_style),
        _p("Confidence", header_cell_style),
        _p("Explanation", header_cell_style),
    ]]
    for m in result.matches:
        spec_label = f"{m.spec_method} {m.spec_path}" if m.spec_path else "—"
        doc_label = f"{m.doc_method} {m.doc_path}" if m.doc_path else "—"
        ep_rows.append([
            _p(m.status.value, cell_style),
            _p(spec_label, cell_style),
            _p(doc_label, cell_style),
            _p(f"{m.confidence:.2f}", cell_style),
            _p(m.explanation, cell_style),
        ])
    t_ep = Table(ep_rows, colWidths=[38 * mm, 52 * mm, 52 * mm, 20 * mm, 104 * mm], repeatRows=1)
    t_ep.setStyle(base_table_style)
    story.append(t_ep)

    # 4. Detailed Findings & Recommended Corrections
    story.append(Paragraph("4. Validation Findings, Evidence &amp; Recommended Corrections", h2_style))
    issue_rows = [[
        _p("ID", header_cell_style),
        _p("Severity", header_cell_style),
        _p("Category", header_cell_style),
        _p("Endpoint", header_cell_style),
        _p("Expected vs Actual", header_cell_style),
        _p("Evidence &amp; Explanation", header_cell_style),
        _p("Recommended Correction", header_cell_style),
    ]]
    for iss in result.issues:
        exp_act = f"Expected: {iss.expected}\nDocumented: {iss.actual}"
        ev_exp = f"{iss.explanation}\n[Evidence: {iss.evidence}]"
        issue_rows.append([
            _p(iss.issue_id, cell_style),
            _p(iss.severity.value, cell_style),
            _p(iss.category.value, cell_style),
            _p(f"{iss.method} {iss.endpoint}", cell_style),
            _p(exp_act, cell_style),
            _p(ev_exp, cell_style),
            _p(iss.suggestion, cell_style),
        ])
    t_iss = Table(
        issue_rows,
        colWidths=[16 * mm, 18 * mm, 25 * mm, 38 * mm, 52 * mm, 65 * mm, 52 * mm],
        repeatRows=1,
    )
    t_iss.setStyle(base_table_style)
    story.append(t_iss)

    doc.build(story)
    return buf.getvalue()


def generate_report_bytes(result: ValidationResult, fmt: str) -> tuple[bytes, str, str]:
    """Return ``(bytes, media_type, filename)`` for ``fmt`` in {'csv', 'xlsx', 'pdf'}."""
    fmt_clean = fmt.lower().strip()
    slug = (result.session_id or "audit")[:12]
    if fmt_clean == "csv":
        return generate_csv_report(result), "text/csv; charset=utf-8", f"audit_report_{slug}.csv"
    if fmt_clean in ("xlsx", "excel"):
        return (
            generate_excel_report(result),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            f"audit_report_{slug}.xlsx",
        )
    if fmt_clean == "pdf":
        return generate_pdf_report(result), "application/pdf", f"audit_report_{slug}.pdf"
    raise ValueError(f"Unsupported report format '{fmt}'. Expected csv, xlsx or pdf.")

