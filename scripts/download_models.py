"""One-time setup script to download local NLP models into data/models/.

Usage (from project root with .venv activated):
    python scripts/download_models.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Allow network access during this explicit setup script
os.environ.pop("HF_HUB_OFFLINE", None)
os.environ.pop("TRANSFORMERS_OFFLINE", None)

from app.core.config import settings  # noqa: E402


def download_embedding_model() -> None:
    target = settings.embedding_model_dir
    if (target / "config.json").is_file() or (target / "modules.json").is_file():
        print(f"[OK] Embedding model already present at: {target}")
        return
    print(f"[INFO] Downloading '{settings.embedding_model_name}' to {target} ...")
    target.mkdir(parents=True, exist_ok=True)
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(settings.embedding_model_name, device="cpu")
    model.save(str(target))
    print(f"[OK] Saved embedding model to: {target}")


def verify_spacy_model() -> None:
    import spacy

    try:
        spacy.load(settings.spacy_model)
        print(f"[OK] spaCy model '{settings.spacy_model}' is installed.")
    except OSError:
        print(f"[INFO] Downloading spaCy model '{settings.spacy_model}' ...")
        from spacy.cli import download

        download(settings.spacy_model)
        print(f"[OK] Installed spaCy model '{settings.spacy_model}'.")


if __name__ == "__main__":
    verify_spacy_model()
    download_embedding_model()

