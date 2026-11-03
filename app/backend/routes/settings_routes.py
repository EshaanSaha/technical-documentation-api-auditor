"""Application settings and threshold configuration endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.backend.schemas.api_schemas import ThresholdsPayload
from app.core.config import ValidationThresholds
from app.database.db import load_thresholds, save_thresholds

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/thresholds", response_model=ThresholdsPayload)
def get_thresholds_endpoint() -> ThresholdsPayload:
    current = load_thresholds()
    return ThresholdsPayload(**current.to_dict())


@router.put("/thresholds", response_model=ThresholdsPayload)
def update_thresholds_endpoint(payload: ThresholdsPayload) -> ThresholdsPayload:
    updated = save_thresholds(ValidationThresholds.from_dict(payload.model_dump()))
    return ThresholdsPayload(**updated.to_dict())


@router.post("/thresholds/reset", response_model=ThresholdsPayload)
def reset_thresholds_endpoint() -> ThresholdsPayload:
    defaults = save_thresholds(ValidationThresholds())
    return ThresholdsPayload(**defaults.to_dict())

