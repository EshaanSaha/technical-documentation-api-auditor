"""Semantic and lexical similarity.

* Semantic similarity uses the locally stored ``all-MiniLM-L6-v2`` Sentence
  Transformers model. The model is loaded **only** from the project's
  ``data/models`` directory with Hugging Face offline mode enforced, so no
  network request is ever made at runtime.
* Lexical similarity of identifiers uses RapidFuzz on normalized names.
"""

from __future__ import annotations

import os
import threading
from functools import lru_cache
from typing import Optional, Sequence

from rapidfuzz import fuzz

from app.core.config import settings
from app.core.logging_config import get_logger
from app.nlp.text_normalization import normalize_identifier, normalize_whitespace

# Enforce offline operation for transformers / huggingface_hub before they are imported.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

logger = get_logger(__name__)


class SemanticModelUnavailable(RuntimeError):
    """Raised when the local embedding model has not been downloaded."""


class SemanticMatcher:
    """Thread-safe lazy wrapper around the local Sentence Transformers model."""

    def __init__(self, model_dir: str) -> None:
        self._model_dir = model_dir
        self._model = None
        self._lock = threading.Lock()
        self._error: Optional[str] = None

    @property
    def model_dir(self) -> str:
        return self._model_dir

    def is_downloaded(self) -> bool:
        return os.path.isfile(os.path.join(self._model_dir, "config.json")) or os.path.isfile(
            os.path.join(self._model_dir, "modules.json")
        )

    def _load(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            if not self.is_downloaded():
                self._error = (
                    f"Embedding model not found in '{os.path.relpath(self._model_dir, os.getcwd())}'. "
                    "Run: python scripts/download_models.py"
                )
                raise SemanticModelUnavailable(self._error)
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(self._model_dir, device="cpu")
                logger.info("Loaded embedding model from %s", self._model_dir)
            except Exception as exc:  # noqa: BLE001 - surface any load failure as unavailability
                self._error = f"Failed to load embedding model: {exc}"
                logger.exception("Embedding model load failed")
                raise SemanticModelUnavailable(self._error) from exc
        return self._model

    def available(self) -> bool:
        try:
            self._load()
            return True
        except SemanticModelUnavailable:
            return False

    @property
    def last_error(self) -> Optional[str]:
        return self._error

    def similarity_pairs(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        """Cosine similarity for each (a, b) pair, computed in one batch."""
        if not pairs:
            return []
        model = self._load()
        texts = [normalize_whitespace(t) for pair in pairs for t in pair]
        vectors = model.encode(texts, batch_size=32, convert_to_numpy=True, normalize_embeddings=True,
                               show_progress_bar=False)
        scores = []
        for i in range(len(pairs)):
            a, b = vectors[2 * i], vectors[2 * i + 1]
            scores.append(float(max(0.0, min(1.0, (a * b).sum()))))
        return scores

    def similarity(self, a: str, b: str) -> float:
        return self.similarity_pairs([(a, b)])[0]


@lru_cache(maxsize=1)
def get_semantic_matcher() -> SemanticMatcher:
    return SemanticMatcher(str(settings.embedding_model_dir))


# --------------------------------------------------------------------------- #
# Lexical similarity
# --------------------------------------------------------------------------- #
def name_similarity(a: str, b: str) -> float:
    """Similarity of two identifiers on the RapidFuzz 0..100 scale (normalized forms)."""
    na, nb = normalize_identifier(a), normalize_identifier(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 100.0
    ratio = fuzz.ratio(na, nb)
    # token_set_ratio rewards "email" vs "email_address"; dampen it so that
    # partial overlaps never outrank a close full-string match.
    tokens = fuzz.token_set_ratio(na.replace("_", " "), nb.replace("_", " ")) * 0.9
    return float(max(ratio, tokens))


def path_similarity(a: str, b: str) -> float:
    """Similarity of two path templates on a 0..1 scale."""
    if a == b:
        return 1.0
    seg_a = [s for s in a.split("/") if s]
    seg_b = [s for s in b.split("/") if s]
    seq = fuzz.ratio(a, b) / 100.0
    if not seg_a or not seg_b:
        return seq
    # Segment-wise alignment penalises structural differences (different depth).
    aligned = sum(fuzz.ratio(x, y) / 100.0 for x, y in zip(seg_a, seg_b))
    structural = aligned / max(len(seg_a), len(seg_b))
    return round(0.5 * seq + 0.5 * structural, 4)

