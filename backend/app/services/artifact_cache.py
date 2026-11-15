"""Phase 6: tenant-scoped idempotency / artifact cache.

Identical accepted requests return the same stored artifact bytes and verification
report. Never share cached candidate artifacts across tenants.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.canonical_resume import re_sub_safe

RENDERER_VERSION = "docx_render@1"
CACHE_SCHEMA_VERSION = 1


@dataclass
class CachedArtifact:
    key: str
    tenant_id: str
    docx_sha256: str
    report: dict[str, Any]
    meta: dict[str, Any]
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_idempotency_key(
    *,
    tenant_id: str,
    source_file_hash: str,
    canonical_revision: str,
    extraction_version: str,
    schema_version: str,
    parser_version: str,
    model_id: str,
    prompt_version: str,
    template_version: str,
    renderer_version: str = RENDERER_VERSION,
    formatting_options: dict[str, Any] | None = None,
) -> str:
    payload = {
        "tenant_id": tenant_id,
        "source_file_hash": source_file_hash,
        "canonical_revision": canonical_revision,
        "extraction_version": extraction_version,
        "schema_version": schema_version,
        "parser_version": parser_version,
        "model_id": model_id,
        "prompt_version": prompt_version,
        "template_version": template_version,
        "renderer_version": renderer_version,
        "options": formatting_options or {},
        "cache_schema": CACHE_SCHEMA_VERSION,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()
    return digest


def _paths(tenant_id: str, key: str) -> tuple[Path, Path, Path]:
    settings = get_settings()
    root = Path(settings.UPLOAD_DIR) / "artifact_cache" / re_sub_safe(tenant_id) / key[:2] / key
    return root, root / "artifact.docx", root / "report.json"


def get_cached_artifact(tenant_id: str, key: str) -> tuple[bytes, CachedArtifact] | None:
    root, docx_path, report_path = _paths(tenant_id, key)
    lock = root / ".lock"
    if lock.exists():
        # Concurrent writer in progress — do not return partial.
        return None
    if not docx_path.is_file() or not report_path.is_file():
        return None
    meta = json.loads(report_path.read_text(encoding="utf-8"))
    if meta.get("tenant_id") != tenant_id:
        return None  # hard tenant isolation
    data = docx_path.read_bytes()
    expected = meta.get("docx_sha256")
    if expected and hashlib.sha256(data).hexdigest() != expected:
        return None
    return data, CachedArtifact(
        key=key,
        tenant_id=tenant_id,
        docx_sha256=str(expected or ""),
        report=dict(meta.get("report") or {}),
        meta=dict(meta.get("meta") or {}),
        created_at=float(meta.get("created_at") or 0.0),
    )


def publish_artifact(
    *,
    tenant_id: str,
    key: str,
    docx_bytes: bytes,
    report: dict[str, Any],
    meta: dict[str, Any] | None = None,
) -> CachedArtifact:
    """Atomic publish: write to temp then replace. Holds a lock during write."""
    root, docx_path, report_path = _paths(tenant_id, key)
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".lock"
    lock.write_text(str(time.time()), encoding="utf-8")
    try:
        tmp_docx = root / "artifact.docx.partial"
        tmp_report = root / "report.json.partial"
        digest = hashlib.sha256(docx_bytes).hexdigest()
        tmp_docx.write_bytes(docx_bytes)
        payload = {
            "key": key,
            "tenant_id": tenant_id,
            "docx_sha256": digest,
            "report": report,
            "meta": {
                **(meta or {}),
                # timings / versions only — never raw candidate text
                "published_at": time.time(),
            },
            "created_at": time.time(),
            "cache_schema": CACHE_SCHEMA_VERSION,
        }
        # Strip accidental raw text fields if a caller passed them.
        for banned in ("raw_text", "resume_text", "source_text", "catalog"):
            payload["meta"].pop(banned, None)
            payload["report"].pop(banned, None)
        tmp_report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_docx.replace(docx_path)
        tmp_report.replace(report_path)
        return CachedArtifact(
            key=key,
            tenant_id=tenant_id,
            docx_sha256=digest,
            report=report,
            meta=payload["meta"],
            created_at=payload["created_at"],
        )
    finally:
        lock.unlink(missing_ok=True)


def invalidate_tenant_key(tenant_id: str, key: str) -> None:
    root, docx_path, report_path = _paths(tenant_id, key)
    docx_path.unlink(missing_ok=True)
    report_path.unlink(missing_ok=True)
