"""Local filesystem stand-in for ATS S3 helpers (no AWS S3)."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from app.core.config import settings
from app.core.logging import logger


def sanitize_filename(name: str) -> str:
    name = name.encode("utf-8", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9._-]", "_", name)


def _storage_root() -> Path:
    root = Path(settings.UPLOAD_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root


def upload_bytes_to_key(
    recruiter_id: str,
    object_key: str,
    content: bytes,
    content_type: str = "application/octet-stream",
) -> str:
    """Write bytes under UPLOAD_DIR and return the absolute filesystem path."""
    del content_type  # unused locally
    safe_key = object_key.replace("\\", "/").lstrip("/")
    dest = _storage_root() / safe_key
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    logger.info(
        "file_saved_locally",
        recruiter_id=recruiter_id,
        path=str(dest),
        size=len(content),
    )
    return str(dest)


def download_to_local_path(
    recruiter_id: str,
    object_key: str,
    dest_path: Path | None = None,
) -> str:
    """Resolve a local path. If object_key is already a file, use it; else look under UPLOAD_DIR."""
    del recruiter_id
    source = Path(object_key)
    if source.exists():
        return str(source)

    candidate = _storage_root() / object_key.replace("\\", "/").lstrip("/")
    if candidate.exists():
        if dest_path is None:
            return str(candidate)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(candidate.read_bytes())
        return str(dest_path)

    if dest_path is None:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(object_key).suffix)
        dest_path = Path(tmp.name)
        tmp.close()

    raise FileNotFoundError(f"Local file not found for key={object_key}")
