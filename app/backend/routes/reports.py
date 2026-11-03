"""Report export and report history endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.database.db import get_session_result, list_reports, record_report
from app.database.models import ReportMetadataRecord
from app.reports.report_generator import generate_report_bytes

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("", response_model=list[ReportMetadataRecord])
def list_reports_endpoint(session_id: Optional[str] = Query(None)) -> list[ReportMetadataRecord]:
    return list_reports(session_id=session_id)


@router.get("/{session_id}/{fmt}")
def download_report_endpoint(session_id: str, fmt: str) -> Response:
    result = get_session_result(session_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Validation session '{session_id}' not found.")
    try:
        data, media_type, filename = generate_report_bytes(result, fmt)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    record_report(
        session_id=session_id,
        fmt=fmt.lower().strip(),
        filename=filename,
        size_bytes=len(data),
    )
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

