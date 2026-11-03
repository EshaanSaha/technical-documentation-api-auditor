"""Text preprocessing and spaCy pipeline management."""

from __future__ import annotations

import re
from functools import lru_cache

import spacy
from spacy.language import Language

from app.core.config import settings
from app.core.logging_config import get_logger
from app.nlp.text_normalization import normalize_whitespace

logger = get_logger(__name__)

# Underscores are deliberately NOT stripped: they are part of snake_case identifiers.
_MARKDOWN_INLINE = re.compile(r"(\*\*|\*|~~)")
_BULLET = re.compile(r"^\s*(?:[-*\u2022\u25cf\u25aa]|\d+[.)])\s+")


@lru_cache(maxsize=1)
def get_nlp() -> Language:
    """Load the spaCy pipeline once per process.

    Falls back to a blank English pipeline with a rule-based sentencizer when
    the statistical model is not installed, so parsing still works (with
    reduced linguistic features) instead of crashing.
    """
    try:
        nlp = spacy.load(settings.spacy_model, exclude=["ner"])
        logger.info("Loaded spaCy model '%s'", settings.spacy_model)
    except OSError:
        logger.warning(
            "spaCy model '%s' not found; using blank English pipeline. "
            "Run: python -m spacy download %s",
            settings.spacy_model,
            settings.spacy_model,
        )
        nlp = spacy.blank("en")
    if "parser" not in nlp.pipe_names and "sentencizer" not in nlp.pipe_names:
        nlp.add_pipe("sentencizer")
    return nlp


def spacy_model_loaded() -> bool:
    return get_nlp().meta.get("name", "") not in ("", "pipeline")


def clean_inline_markup(text: str) -> str:
    """Remove bullet markers and Markdown emphasis while keeping code spans' content."""
    text = _BULLET.sub("", text or "")
    text = _MARKDOWN_INLINE.sub("", text)
    return normalize_whitespace(text)


def split_sentences(text: str) -> list[str]:
    """Sentence segmentation using the spaCy pipeline."""
    text = normalize_whitespace(text)
    if not text:
        return []
    return [s.text.strip() for s in get_nlp()(text).sents if s.text.strip()]
