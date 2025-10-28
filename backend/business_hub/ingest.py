"""Document ingestion utilities."""
from __future__ import annotations

import hashlib
import mimetypes
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Tuple

from .models import Document, DocumentSource, DocumentType
from .storage import upsert_document

SUPPORTED_IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".heic"}
SUPPORTED_DOC_TYPES = {".pdf", ".eml", ".msg", ".txt"}
SUPPORTED_EXTENSIONS = SUPPORTED_IMAGE_TYPES | SUPPORTED_DOC_TYPES


class IngestionError(RuntimeError):
    """Raised when an ingestion operation fails."""


def detect_type(file_path: Path) -> DocumentType:
    ext = file_path.suffix.lower()
    if ext in {".pdf", ".eml", ".msg"}:
        return DocumentType.INVOICE
    if ext in SUPPORTED_IMAGE_TYPES:
        return DocumentType.RECEIPT
    return DocumentType.OTHER


def compute_hash(file_path: Path) -> str:
    sha = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()


def ingest_file(source_path: Path, dest_root: Path = Path("storage")) -> Tuple[Document, Path]:
    if not source_path.exists():
        raise IngestionError(f"File not found: {source_path}")
    ext = source_path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise IngestionError(f"Unsupported file type: {ext}")

    dest_root.mkdir(parents=True, exist_ok=True)
    doc_id = f"doc_{uuid.uuid4().hex[:12]}"
    dest_path = dest_root / f"{doc_id}{ext}"
    shutil.copy2(source_path, dest_path)

    mime = mimetypes.guess_type(dest_path)[0] or "application/octet-stream"
    doc_type = detect_type(dest_path)
    document = Document(
        id=doc_id,
        type=doc_type,
        mime=mime,
        source=DocumentSource.UPLOAD,
        created_at=datetime.utcnow(),
        pages=1,
        storage_path=str(dest_path),
        ocr_text_indexed=False,
        hash_sha256=compute_hash(dest_path),
    )
    upsert_document(document)
    return document, dest_path


__all__ = [name for name in globals() if not name.startswith("_")]
