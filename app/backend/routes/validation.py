"""Validation & document parsing endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.backend.schemas.api_schemas import SampleValidationRequest
from app.core.config import ValidationThresholds, settings
from app.core.logging_config import get_logger
from app.core.models import ApiModel, ValidationResult
from app.database.db import (
    load_thresholds,
    record_document,
    save_validation_session,
)
from app.engine.validation_engine import run_validation
from app.parsers.blocks import DocumentParseError
from app.parsers.loader import parse_documentation, parse_specification
from app.utils.file_validation import (
    UploadValidationError,
    safe_filename,
    store_upload,
    validate_upload,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["validation"])


def _persist_and_record(data: bytes, filename: str, role: str) -> str:
    clean_name = validate_upload(data, filename, role)
    digest = store_upload(data, clean_name)
    ext = Path(clean_name).suffix.lower().lstrip(".")
    rel_path = f"data/uploads/{digest}.{ext}"
    record_document(
        sha256=digest,
        original_name=clean_name,
        role=role,
        fmt=ext,
        size_bytes=len(data),
        stored_rel_path=rel_path,
    )
    return digest


@router.post("/parse-preview", response_model=ApiModel)
async def parse_preview_endpoint(
    file: UploadFile = File(...),
    role: str = Form("documentation"),
) -> ApiModel:
    """Parse a single uploaded file and return its extracted structure for preview."""
    if role not in ("documentation", "specification"):
        raise HTTPException(status_code=400, detail="Role must be 'documentation' or 'specification'.")
    raw = await file.read()
    fname = safe_filename(file.filename or "upload")
    try:
        clean_name = validate_upload(raw, fname, role)
        if role == "documentation":
            return parse_documentation(raw, clean_name)
        return parse_specification(raw, clean_name)
    except (UploadValidationError, DocumentParseError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/validate", response_model=ValidationResult)
async def validate_uploads_endpoint(
    documentation: UploadFile = File(...),
    specification: UploadFile = File(...),
    session_name: Optional[str] = Form(None),
    thresholds_json: Optional[str] = Form(None),
) -> ValidationResult:
    """Validate uploaded API documentation against an uploaded OpenAPI specification."""
    doc_bytes = await documentation.read()
    spec_bytes = await specification.read()
    doc_name = safe_filename(documentation.filename or "documentation.md")
    spec_name = safe_filename(specification.filename or "openapi.yaml")

    try:
        doc_sha = _persist_and_record(doc_bytes, doc_name, "documentation")
        spec_sha = _persist_and_record(spec_bytes, spec_name, "specification")
        doc_model = parse_documentation(doc_bytes, doc_name)
        spec_model = parse_specification(spec_bytes, spec_name)
    except (UploadValidationError, DocumentParseError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    active_thresholds = load_thresholds()
    if thresholds_json:
        try:
            active_thresholds = ValidationThresholds.from_dict(json.loads(thresholds_json))
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid thresholds payload: {exc}") from exc

    result = run_validation(
        spec_model=spec_model,
        doc_model=doc_model,
        thresholds=active_thresholds,
        session_name=(session_name or "").strip(),
    )
    return save_validation_session(result, doc_sha256=doc_sha, spec_sha256=spec_sha)


@router.post("/validate/sample", response_model=ValidationResult)
def validate_sample_endpoint(req: SampleValidationRequest) -> ValidationResult:
    """Run the validation pipeline on built-in sample files in ``data/sample_data/``."""
    doc_file = safe_filename(req.doc_variant)
    spec_file = safe_filename(req.spec_variant)
    doc_path = settings.sample_dir / doc_file
    spec_path = settings.sample_dir / spec_file

    if not doc_path.is_file():
        raise HTTPException(status_code=404, detail=f"Sample documentation '{doc_file}' not found.")
    if not spec_path.is_file():
        raise HTTPException(status_code=404, detail=f"Sample specification '{spec_file}' not found.")

    doc_bytes = doc_path.read_bytes()
    spec_bytes = spec_path.read_bytes()

    try:
        doc_sha = _persist_and_record(doc_bytes, doc_file, "documentation")
        spec_sha = _persist_and_record(spec_bytes, spec_file, "specification")
        doc_model = parse_documentation(doc_bytes, doc_file)
        spec_model = parse_specification(spec_bytes, spec_file)
    except (UploadValidationError, DocumentParseError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    thresholds = ValidationThresholds.from_dict(req.thresholds) if req.thresholds else load_thresholds()
    default_name = f"Sample Audit ({doc_file} vs {spec_file})"
    result = run_validation(
        spec_model=spec_model,
        doc_model=doc_model,
        thresholds=thresholds,
        session_name=(req.session_name or default_name).strip(),
    )
    return save_validation_session(result, doc_sha256=doc_sha, spec_sha256=spec_sha)

