"""API request and response schemas."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    spacy_model_loaded: bool
    spacy_model_name: str
    embedding_model_downloaded: bool
    embedding_model_name: str
    database_ready: bool
    sample_files: list[str] = Field(default_factory=list)


class SampleValidationRequest(BaseModel):
    doc_variant: str = Field(
        default="shopwave_api_docs.md",
        description="Filename in data/sample_data/ for the documentation file.",
    )
    spec_variant: str = Field(
        default="shopwave_openapi.yaml",
        description="Filename in data/sample_data/ for the OpenAPI specification.",
    )
    session_name: Optional[str] = None
    thresholds: Optional[dict[str, float]] = None


class ThresholdsPayload(BaseModel):
    description_high: float = Field(default=0.85, ge=0.50, le=0.99)
    description_moderate: float = Field(default=0.65, ge=0.35, le=0.95)
    description_unrelated: float = Field(default=0.30, ge=0.05, le=0.70)
    endpoint_likely_match: float = Field(default=0.62, ge=0.40, le=0.95)
    name_fuzzy_match: float = Field(default=80.0, ge=60.0, le=98.0)


class DeleteSessionResponse(BaseModel):
    deleted: bool
    session_id: str

