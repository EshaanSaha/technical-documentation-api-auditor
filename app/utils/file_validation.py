"""Upload validation: file type, size, content signature and safe filenames.

Uploaded content is only ever *read* by parsers (no rendering of HTML, no
macro execution, YAML via ``safe_load``), and stored under a content hash name
so a user-supplied filename can never be used for path traversal.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from pathlib import Path

from app.core.config import DOCUMENTATION_EXTENSIONS, SPECIFICATION_EXTENSIONS, settings


class UploadValidationError(ValueError):
    """User-facing upload validation failure."""


def safe_filename(name: str) -> str:
    base = Path(name or "upload").name
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base).strip(" .")
    return base[:120] or "upload"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_upload(data: bytes, filename: str, role: str) -> str:
    """Validate an upload for a given role ('documentation' or 'specification').

    Returns the sanitized filename. Raises :class:`UploadValidationError`.
    """
    name = safe_filename(filename)
    ext = Path(name).suffix.lower()
    allowed = DOCUMENTATION_EXTENSIONS if role == "documentation" else SPECIFICATION_EXTENSIONS
    if ext not in allowed:
        raise UploadValidationError(
            f"'{name}' has an unsupported extension for {role}. Allowed: {', '.join(sorted(allowed))}."
        )
    if not data:
        raise UploadValidationError(f"'{name}' is empty.")
    if len(data) > settings.max_upload_bytes:
        raise UploadValidationError(f"'{name}' exceeds the {settings.max_upload_mb} MB upload limit.")

    # Content signature checks: the extension must agree with the actual bytes.
    if ext == ".pdf" and not data.lstrip()[:5].startswith(b"%PDF"):
        raise UploadValidationError(f"'{name}' does not look like a PDF file.")
    if ext == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                if "word/document.xml" not in zf.namelist():
                    raise UploadValidationError(f"'{name}' is not a Word document.")
                if any(n.lower().endswith("vbaproject.bin") for n in zf.namelist()):
                    raise UploadValidationError(f"'{name}' contains macros; macro-enabled documents are rejected.")
        except zipfile.BadZipFile as exc:
            raise UploadValidationError(f"'{name}' is not a valid DOCX archive.") from exc
    if ext in {".md", ".markdown", ".json", ".yaml", ".yml"} and b"\x00" in data[:4096] and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise UploadValidationError(f"'{name}' appears to be a binary file, not text.")
    return name


def store_upload(data: bytes, filename: str) -> str:
    """Store content once, addressed by hash (identical uploads are not duplicated)."""
    digest = sha256_hex(data)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    target = settings.upload_dir / f"{digest}{Path(filename).suffix.lower()}"
    if not target.exists():
        target.write_bytes(data)
    return digest

