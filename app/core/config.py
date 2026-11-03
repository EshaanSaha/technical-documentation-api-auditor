"""Application configuration.

All configuration is read from environment variables (optionally loaded from a
``.env`` file in the project root). Business logic never reads ``os.environ``
directly; it imports :data:`settings` from here instead.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _env(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def _resolve(path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else PROJECT_ROOT / path


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings."""

    api_host: str = field(default_factory=lambda: _env("AUDITOR_API_HOST", "127.0.0.1"))
    api_port: int = field(default_factory=lambda: int(_env("AUDITOR_API_PORT", "8000")))
    ui_port: int = field(default_factory=lambda: int(_env("AUDITOR_UI_PORT", "8501")))
    api_url: str = field(default_factory=lambda: _env("AUDITOR_API_URL", "http://127.0.0.1:8000"))

    db_path: Path = field(default_factory=lambda: _resolve(_env("AUDITOR_DB_PATH", "data/auditor.db")))
    upload_dir: Path = field(default_factory=lambda: _resolve(_env("AUDITOR_UPLOAD_DIR", "data/uploads")))
    sample_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "sample_data")
    max_upload_mb: int = field(default_factory=lambda: int(_env("AUDITOR_MAX_UPLOAD_MB", "20")))

    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_model_dir: Path = field(
        default_factory=lambda: _resolve(_env("AUDITOR_EMBEDDING_MODEL_DIR", "data/models/all-MiniLM-L6-v2"))
    )
    spacy_model: str = field(default_factory=lambda: _env("AUDITOR_SPACY_MODEL", "en_core_web_sm"))

    log_level: str = field(default_factory=lambda: _env("AUDITOR_LOG_LEVEL", "INFO"))

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


settings = Settings()


@dataclass(frozen=True)
class ValidationThresholds:
    """Tunable heuristics used by the validation engine.

    These are *heuristics*, not correctness standards. They can be overridden
    per validation run from the Settings page.
    """

    # Description semantic similarity bands (cosine similarity, 0..1)
    description_high: float = 0.85
    description_moderate: float = 0.65
    description_unrelated: float = 0.30
    # Endpoint candidate matching: minimum combined score to report a "likely match"
    endpoint_likely_match: float = 0.62
    # Identifier fuzzy similarity (0..100, RapidFuzz scale) to consider two names the same entity
    name_fuzzy_match: float = 80.0

    @classmethod
    def from_dict(cls, data: dict | None) -> "ValidationThresholds":
        if not data:
            return cls()
        known = {k: float(v) for k, v in data.items() if k in cls.__dataclass_fields__ and v is not None}
        return cls(**known)

    def to_dict(self) -> dict[str, float]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


# File types accepted per upload role
DOCUMENTATION_EXTENSIONS: frozenset[str] = frozenset({".pdf", ".docx", ".md", ".markdown"})
SPECIFICATION_EXTENSIONS: frozenset[str] = frozenset({".json", ".yaml", ".yml"})

