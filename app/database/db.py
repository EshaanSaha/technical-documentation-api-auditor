"""SQLite database operations with automatic initialization and error handling."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from app.core.config import ValidationThresholds, settings
from app.core.logging_config import get_logger
from app.core.models import ValidationResult
from app.database.models import (
    SCHEMA_SQL,
    ReportMetadataRecord,
    SessionSummaryRecord,
)

logger = get_logger(__name__)


class DatabaseError(RuntimeError):
    """Raised when a database operation fails."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


@contextmanager
def get_connection(db_path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    target = db_path or settings.db_path
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        logger.exception("SQLite operation failed")
        raise DatabaseError(f"Database operation failed: {exc}") from exc
    finally:
        conn.close()


def init_db(db_path: Optional[Path] = None) -> None:
    """Create database tables and indexes if they do not exist."""
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA_SQL)


def record_document(
    sha256: str,
    original_name: str,
    role: str,
    fmt: str,
    size_bytes: int,
    stored_rel_path: str,
    db_path: Optional[Path] = None,
) -> None:
    """Insert document metadata, deduplicated by SHA-256 content digest."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO documents (sha256, original_name, role, format, size_bytes, stored_path, uploaded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sha256) DO UPDATE SET
                original_name = excluded.original_name,
                uploaded_at = excluded.uploaded_at
            """,
            (sha256, original_name, role, fmt, size_bytes, stored_rel_path, _utc_now()),
        )


def save_validation_session(
    result: ValidationResult,
    doc_sha256: str,
    spec_sha256: str,
    db_path: Optional[Path] = None,
) -> ValidationResult:
    """Persist a validation session, its normalized issues and full result payload."""
    init_db(db_path)
    if not result.session_id:
        result.session_id = uuid.uuid4().hex[:12]
    if not result.created_at:
        result.created_at = _utc_now()

    summary = result.summary or {}
    sev_counts = summary.get("severity_counts") or {}
    payload_json = result.model_dump_json()

    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO validation_sessions (
                session_id, session_name, created_at, doc_sha256, spec_sha256,
                documentation_file, specification_file, api_title, api_version,
                completeness_score, total_spec_endpoints, total_doc_endpoints,
                matched_endpoints, missing_endpoints, total_issues,
                critical_issues, high_issues, medium_issues, low_issues, result_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.session_id,
                result.session_name,
                result.created_at,
                doc_sha256,
                spec_sha256,
                result.documentation_file,
                result.specification_file,
                result.api_title,
                result.api_version,
                result.completeness_score,
                int(summary.get("total_spec_endpoints", 0)),
                int(summary.get("total_doc_endpoints", 0)),
                int(summary.get("matched_endpoints", 0)),
                int(summary.get("missing_endpoints", 0)),
                int(summary.get("total_issues", len(result.issues))),
                int(sev_counts.get("Critical", 0)),
                int(sev_counts.get("High", 0)),
                int(sev_counts.get("Medium", 0)),
                int(sev_counts.get("Low", 0)),
                payload_json,
            ),
        )
        conn.executemany(
            """
            INSERT INTO validation_issues (
                session_id, issue_id, endpoint, method, category, issue_type,
                severity, expected, actual, evidence, explanation, suggestion
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    result.session_id,
                    issue.issue_id,
                    issue.endpoint,
                    issue.method,
                    issue.category.value,
                    issue.issue_type,
                    issue.severity.value,
                    issue.expected,
                    issue.actual,
                    issue.evidence,
                    issue.explanation,
                    issue.suggestion,
                )
                for issue in result.issues
            ],
        )

    logger.info("Saved validation session %s (%d issues)", result.session_id, len(result.issues))
    return result


def list_sessions(limit: int = 100, db_path: Optional[Path] = None) -> list[SessionSummaryRecord]:
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT session_id, session_name, created_at, documentation_file, specification_file,
                   api_title, api_version, completeness_score, total_spec_endpoints,
                   total_doc_endpoints, matched_endpoints, missing_endpoints, total_issues,
                   critical_issues, high_issues, medium_issues, low_issues
            FROM validation_sessions
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [SessionSummaryRecord(**dict(row)) for row in rows]


def get_session_result(session_id: str, db_path: Optional[Path] = None) -> Optional[ValidationResult]:
    init_db(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT result_json FROM validation_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    if row is None:
        return None
    return ValidationResult.model_validate_json(row["result_json"])


def delete_session(session_id: str, db_path: Optional[Path] = None) -> bool:
    init_db(db_path)
    with get_connection(db_path) as conn:
        cur = conn.execute("DELETE FROM validation_sessions WHERE session_id = ?", (session_id,))
        return cur.rowcount > 0


def record_report(
    session_id: str,
    fmt: str,
    filename: str,
    size_bytes: int,
    db_path: Optional[Path] = None,
) -> ReportMetadataRecord:
    init_db(db_path)
    rec = ReportMetadataRecord(
        report_id=uuid.uuid4().hex[:10],
        session_id=session_id,
        format=fmt,
        filename=filename,
        size_bytes=size_bytes,
        generated_at=_utc_now(),
    )
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO reports (report_id, session_id, format, filename, size_bytes, generated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (rec.report_id, rec.session_id, rec.format, rec.filename, rec.size_bytes, rec.generated_at),
        )
    return rec


def list_reports(session_id: Optional[str] = None, db_path: Optional[Path] = None) -> list[ReportMetadataRecord]:
    init_db(db_path)
    with get_connection(db_path) as conn:
        if session_id:
            rows = conn.execute(
                "SELECT * FROM reports WHERE session_id = ? ORDER BY generated_at DESC",
                (session_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM reports ORDER BY generated_at DESC LIMIT 100").fetchall()
    return [ReportMetadataRecord(**dict(r)) for r in rows]


def load_thresholds(db_path: Optional[Path] = None) -> ValidationThresholds:
    init_db(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT value_json FROM app_settings WHERE key = 'thresholds'").fetchone()
    if row is None:
        return ValidationThresholds()
    try:
        return ValidationThresholds.from_dict(json.loads(row["value_json"]))
    except (json.JSONDecodeError, ValueError, TypeError):
        return ValidationThresholds()


def save_thresholds(thresholds: ValidationThresholds, db_path: Optional[Path] = None) -> ValidationThresholds:
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value_json, updated_at)
            VALUES ('thresholds', ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value_json = excluded.value_json,
                updated_at = excluded.updated_at
            """,
            (json.dumps(thresholds.to_dict()), _utc_now()),
        )
    return thresholds

