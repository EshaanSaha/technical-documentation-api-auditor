"""FastAPI application entrypoint for Technical Documentation & API Consistency Auditor."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.backend.routes.history import router as history_router
from app.backend.routes.reports import router as reports_router
from app.backend.routes.settings_routes import router as settings_router
from app.backend.routes.validation import router as validation_router
from app.backend.schemas.api_schemas import HealthResponse
from app.core.config import settings
from app.core.logging_config import configure_logging, get_logger
from app.database.db import init_db
from app.nlp.preprocessing import spacy_model_loaded
from app.nlp.semantic_matching import get_semantic_matcher

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Backend initialized (SQLite DB at %s)", settings.db_path)
    yield


app = FastAPI(
    title="Technical Documentation & API Consistency Auditor API",
    description=(
        "Local NLP-powered validation engine that compares technical API documentation "
        "(PDF, DOCX, Markdown) against OpenAPI 3.x / Swagger 2.0 specifications."
    ),
    version=__version__,
    lifespan=lifespan,
)

app.include_router(validation_router)
app.include_router(history_router)
app.include_router(reports_router)
app.include_router(settings_router)


@app.get("/api/health", response_model=HealthResponse, tags=["system"])
def health_check() -> HealthResponse:
    init_db()
    sample_files = (
        sorted(p.name for p in settings.sample_dir.iterdir() if p.is_file())
        if settings.sample_dir.is_dir()
        else []
    )
    matcher = get_semantic_matcher()
    return HealthResponse(
        status="ok",
        version=__version__,
        spacy_model_loaded=spacy_model_loaded(),
        spacy_model_name=settings.spacy_model,
        embedding_model_downloaded=matcher.is_downloaded(),
        embedding_model_name=settings.embedding_model_name,
        database_ready=settings.db_path.exists(),
        sample_files=sample_files,
    )

