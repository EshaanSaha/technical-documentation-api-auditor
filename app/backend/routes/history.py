"""Session history and retrieval endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.backend.schemas.api_schemas import DeleteSessionResponse
from app.core.models import ValidationResult
from app.database.db import delete_session, get_session_result, list_sessions
from app.database.models import SessionSummaryRecord

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionSummaryRecord])
def list_sessions_endpoint(limit: int = Query(100, ge=1, le=500)) -> list[SessionSummaryRecord]:
    return list_sessions(limit=limit)


@router.get("/{session_id}", response_model=ValidationResult)
def get_session_endpoint(session_id: str) -> ValidationResult:
    result = get_session_result(session_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Validation session '{session_id}' not found.")
    return result


@router.delete("/{session_id}", response_model=DeleteSessionResponse)
def delete_session_endpoint(session_id: str) -> DeleteSessionResponse:
    deleted = delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Validation session '{session_id}' not found.")
    return DeleteSessionResponse(deleted=True, session_id=session_id)

