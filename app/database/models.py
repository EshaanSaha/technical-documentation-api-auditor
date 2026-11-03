"""SQLite DDL schema definitions and lightweight row models."""

from __future__ import annotations

from pydantic import BaseModel

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
    sha256          TEXT PRIMARY KEY,
    original_name   TEXT NOT NULL,
    role            TEXT NOT NULL,
    format          TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL,
    stored_path     TEXT NOT NULL,
    uploaded_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS validation_sessions (
    session_id          TEXT PRIMARY KEY,
    session_name        TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    doc_sha256          TEXT NOT NULL,
    spec_sha256         TEXT NOT NULL,
    documentation_file  TEXT NOT NULL,
    specification_file  TEXT NOT NULL,
    api_title           TEXT NOT NULL,
    api_version         TEXT NOT NULL,
    completeness_score  REAL NOT NULL,
    total_spec_endpoints INTEGER NOT NULL,
    total_doc_endpoints  INTEGER NOT NULL,
    matched_endpoints   INTEGER NOT NULL,
    missing_endpoints   INTEGER NOT NULL,
    total_issues        INTEGER NOT NULL,
    critical_issues     INTEGER NOT NULL,
    high_issues         INTEGER NOT NULL,
    medium_issues       INTEGER NOT NULL,
    low_issues          INTEGER NOT NULL,
    result_json         TEXT NOT NULL,
    FOREIGN KEY (doc_sha256) REFERENCES documents(sha256),
    FOREIGN KEY (spec_sha256) REFERENCES documents(sha256)
);

CREATE TABLE IF NOT EXISTS validation_issues (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    issue_id        TEXT NOT NULL,
    endpoint        TEXT NOT NULL,
    method          TEXT NOT NULL,
    category        TEXT NOT NULL,
    issue_type      TEXT NOT NULL,
    severity        TEXT NOT NULL,
    expected        TEXT NOT NULL,
    actual          TEXT NOT NULL,
    evidence        TEXT NOT NULL,
    explanation     TEXT NOT NULL,
    suggestion      TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES validation_sessions(session_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reports (
    report_id       TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    format          TEXT NOT NULL,
    filename        TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL,
    generated_at    TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES validation_sessions(session_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS app_settings (
    key             TEXT PRIMARY KEY,
    value_json      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON validation_sessions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_issues_session_id ON validation_issues(session_id);
CREATE INDEX IF NOT EXISTS idx_reports_session_id ON reports(session_id);
"""


class SessionSummaryRecord(BaseModel):
    session_id: str
    session_name: str
    created_at: str
    documentation_file: str
    specification_file: str
    api_title: str
    api_version: str
    completeness_score: float
    total_spec_endpoints: int
    total_doc_endpoints: int
    matched_endpoints: int
    missing_endpoints: int
    total_issues: int
    critical_issues: int
    high_issues: int
    medium_issues: int
    low_issues: int


class ReportMetadataRecord(BaseModel):
    report_id: str
    session_id: str
    format: str
    filename: str
    size_bytes: int
    generated_at: str

