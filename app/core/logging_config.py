"""Centralised logging setup."""

from __future__ import annotations

import logging

from app.core.config import settings

_CONFIGURED = False


def configure_logging() -> None:
    """Configure root logging once per process."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # Third-party libraries are noisy at INFO level
    for noisy in ("sentence_transformers", "httpx", "urllib3", "multipart", "fontTools"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)

