"""End-to-end validation pipeline, database persistence, reporting and FastAPI tests."""

from __future__ import annotations

from pathlib import Path

from app.backend.main import app, health_check
from app.backend.routes.history import (
    delete_session_endpoint,
    get_session_endpoint,
    list_sessions_endpoint,
)
from app.backend.routes.reports import download_report_endpoint
from app.backend.routes.settings_routes import (
    get_thresholds_endpoint,
    reset_thresholds_endpoint,
    update_thresholds_endpoint,
)
from app.backend.routes.validation import validate_sample_endpoint
from app.backend.schemas.api_schemas import (
    SampleValidationRequest,
    ThresholdsPayload,
)
from app.core.config import settings
from app.database.db import (
    delete_session,
    get_session_result,
    list_sessions,
    record_document,
    save_validation_session,
)
from app.engine.validation_engine import run_validation
from app.parsers.loader import parse_documentation, parse_specification
from app.reports.report_generator import generate_report_bytes


def test_clean_documentation_scores_high() -> None:
    spec_path = settings.sample_dir / "shopwave_openapi.yaml"
    clean_path = settings.sample_dir / "shopwave_api_docs_clean.md"

    spec_model = parse_specification(spec_path.read_bytes(), spec_path.name)
    doc_model = parse_documentation(clean_path.read_bytes(), clean_path.name)
    result = run_validation(spec_model, doc_model, session_name="Clean Reference Audit")

    assert result.summary["total_spec_endpoints"] == 10
    assert result.summary["exact_matched_endpoints"] == 10
    assert result.summary["missing_endpoints"] == 0
    assert result.summary["unexpected_endpoints"] == 0
    assert result.summary["parameter_mismatches"] == 0
    assert result.completeness_score >= 95.0


def test_inconsistent_sample_detects_all_seeded_error_categories() -> None:
    spec_path = settings.sample_dir / "shopwave_openapi.yaml"
    doc_path = settings.sample_dir / "shopwave_api_docs.md"

    spec_model = parse_specification(spec_path.read_bytes(), spec_path.name)
    doc_model = parse_documentation(doc_path.read_bytes(), doc_path.name)
    result = run_validation(spec_model, doc_model, session_name="Inconsistent Sample Audit")

    s = result.summary
    assert s["total_spec_endpoints"] == 10
    assert s["total_doc_endpoints"] == 10
    assert s["exact_matched_endpoints"] == 8
    assert s["likely_matched_endpoints"] == 1  # GET /v1/products/{product_id} vs /products/{product_id}
    assert s["missing_endpoints"] == 1  # PATCH /customers/{customer_id}
    assert s["unexpected_endpoints"] == 1  # GET /customers/{customer_id}/rewards
    assert s["parameter_mismatches"] >= 4
    assert s["schema_inconsistencies"] >= 4
    assert s["description_inconsistencies"] >= 2
    assert s["authentication_issues"] >= 1
    assert 40.0 <= result.completeness_score <= 85.0

    # Verify CSV, Excel and PDF report generation
    csv_bytes, _, _ = generate_report_bytes(result, "csv")
    xlsx_bytes, _, _ = generate_report_bytes(result, "xlsx")
    pdf_bytes, _, _ = generate_report_bytes(result, "pdf")

    assert b"ShopWave Commerce API" in csv_bytes
    assert xlsx_bytes[:2] == b"PK"
    assert pdf_bytes[:4] == b"%PDF"


def test_sqlite_persistence_lifecycle(tmp_path: Path) -> None:
    db_file = tmp_path / "test_auditor.db"
    spec_path = settings.sample_dir / "shopwave_openapi.yaml"
    doc_path = settings.sample_dir / "shopwave_api_docs.md"

    spec_model = parse_specification(spec_path.read_bytes(), spec_path.name)
    doc_model = parse_documentation(doc_path.read_bytes(), doc_path.name)
    result = run_validation(spec_model, doc_model, session_name="DB Lifecycle Test")

    record_document("doc_hash_1", doc_path.name, "documentation", "md", 100, "data/uploads/doc_hash_1.md", db_path=db_file)
    record_document("spec_hash_1", spec_path.name, "specification", "yaml", 100, "data/uploads/spec_hash_1.yaml", db_path=db_file)
    saved = save_validation_session(result, "doc_hash_1", "spec_hash_1", db_path=db_file)

    sessions = list_sessions(db_path=db_file)
    assert len(sessions) == 1
    assert sessions[0].session_id == saved.session_id

    loaded = get_session_result(saved.session_id, db_path=db_file)
    assert loaded is not None
    assert loaded.completeness_score == saved.completeness_score
    assert len(loaded.issues) == len(saved.issues)

    assert delete_session(saved.session_id, db_path=db_file) is True
    assert list_sessions(db_path=db_file) == []


def test_fastapi_endpoints_end_to_end() -> None:
    route_paths = set(app.openapi().get("paths", {}).keys())
    assert "/api/health" in route_paths
    assert "/api/validate" in route_paths
    assert "/api/validate/sample" in route_paths
    assert "/api/sessions" in route_paths
    assert "/api/reports/{session_id}/{fmt}" in route_paths

    h_json = health_check()
    assert h_json.status == "ok"
    assert h_json.embedding_model_downloaded is True
    assert h_json.spacy_model_loaded is True

    result = validate_sample_endpoint(
        SampleValidationRequest(
            doc_variant="shopwave_api_docs.md",
            spec_variant="shopwave_openapi.yaml",
            session_name="API Test Session",
        )
    )
    session_id = result.session_id
    assert session_id
    assert result.summary["missing_endpoints"] == 1

    sessions = list_sessions_endpoint(limit=50)
    assert any(s.session_id == session_id for s in sessions)

    fetched = get_session_endpoint(session_id)
    assert fetched.session_id == session_id

    pdf_resp = download_report_endpoint(session_id, "pdf")
    assert pdf_resp.status_code == 200
    assert pdf_resp.body.startswith(b"%PDF")

    t_cur = get_thresholds_endpoint()
    assert 0.5 < t_cur.description_high < 1.0
    t_upd = update_thresholds_endpoint(ThresholdsPayload(description_high=0.88))
    assert t_upd.description_high == 0.88
    t_rst = reset_thresholds_endpoint()
    assert t_rst.description_high == 0.85

    del_resp = delete_session_endpoint(session_id)
    assert del_resp.deleted is True
