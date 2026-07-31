"""Persist named company format profiles under UPLOAD_DIR/formats."""

from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import logger
from app.models.client_format import ClientFormat
from app.models.format_schema import normalize_format_metadata
from app.services.format_extraction_service import FormatExtractionError, FormatExtractionService
from app.services.s3_service import sanitize_filename


ALLOWED_TEMPLATE_EXTENSIONS = {".pdf", ".doc", ".docx"}


class FormatProfileError(ValueError):
    pass


def _formats_root() -> Path:
    root = Path(settings.UPLOAD_DIR) / "formats"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _profile_dir(format_id: str) -> Path:
    return _formats_root() / sanitize_filename(format_id)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_logos(profile_dir: Path, logos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Persist logo binaries beside schema; keep data URLs in schema for generation."""
    logo_dir = profile_dir / "logos"
    logo_dir.mkdir(parents=True, exist_ok=True)
    out: list[dict[str, Any]] = []
    for idx, logo in enumerate(logos or []):
        if not isinstance(logo, dict):
            continue
        item = dict(logo)
        data = str(item.get("data") or "")
        if data.startswith("data:image") and "," in data:
            try:
                import base64

                header, encoded = data.split(",", 1)
                ext = "png"
                if "jpeg" in header or "jpg" in header:
                    ext = "jpg"
                elif "gif" in header:
                    ext = "gif"
                raw = base64.b64decode(encoded)
                path = logo_dir / f"logo_{idx}.{ext}"
                path.write_bytes(raw)
                item["file"] = f"logos/{path.name}"
            except Exception as exc:
                logger.debug("logo_persist_failed", error=str(exc))
        out.append(item)
    return out


def save_format_profile(
    *,
    name: str,
    filename: str,
    content: bytes,
    client_id: str = "",
) -> dict[str, Any]:
    """Extract schema from PDF/DOC/DOCX, persist original + schema, return summary."""
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_TEMPLATE_EXTENSIONS:
        raise FormatProfileError("Format must be a PDF, DOC, or DOCX file")
    if not content:
        raise FormatProfileError("Format file is empty")

    try:
        schema = FormatExtractionService().extract(filename or f"format{ext}", content)
    except FormatExtractionError as exc:
        raise FormatProfileError(str(exc)) from exc

    schema = normalize_format_metadata(schema)
    format_id = uuid.uuid4().hex
    profile_dir = _profile_dir(format_id)
    if profile_dir.exists():
        shutil.rmtree(profile_dir, ignore_errors=True)
    profile_dir.mkdir(parents=True, exist_ok=True)

    template_name = f"template{ext}"
    (profile_dir / template_name).write_bytes(content)

    # Cache converted DOCX for .doc inputs when possible.
    converted_docx_path = ""
    if ext == ".doc":
        try:
            from app.services.doc_converter import convert_doc_to_docx

            converted = convert_doc_to_docx(profile_dir / template_name, output_dir=profile_dir)
            if converted.exists():
                dest = profile_dir / "template_converted.docx"
                if converted != dest:
                    shutil.copy2(converted, dest)
                    if converted.name != "template_converted.docx":
                        try:
                            if converted.parent == profile_dir and converted.name != template_name:
                                converted.unlink(missing_ok=True)
                        except Exception:
                            pass
                converted_docx_path = "template_converted.docx"
        except Exception as exc:
            logger.warning("doc_convert_cache_failed", error=str(exc))

    logos = _write_logos(profile_dir, list(schema.get("logos") or []))
    schema["logos"] = logos
    schema["logo_count"] = len(logos)
    display_name = (name or "").strip() or Path(filename or "format").stem.replace("_", " ")
    schema["template_name"] = display_name
    schema["template_id"] = format_id

    meta = {
        "id": format_id,
        "name": display_name,
        "client_id": (client_id or "").strip() or "Client",
        "source_type": schema.get("source_type") or ext.replace(".", ""),
        "source_filename": filename,
        "template_file": template_name,
        "converted_docx": converted_docx_path,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "section_count": len(schema.get("sections") or []),
        "logo_count": schema.get("logo_count") or 0,
        "extraction_confidence": schema.get("extraction_confidence"),
        "preview_text": schema.get("preview_text") or "",
    }
    (profile_dir / "schema.json").write_text(json.dumps(schema, indent=2), encoding="utf-8")
    (profile_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    logger.info("format_profile_saved", format_id=format_id, name=display_name, source_type=meta["source_type"])
    return {
        **meta,
        "schema_preview": {
            "sections": schema.get("sections"),
            "section_order": schema.get("section_order"),
            "styling": schema.get("styling"),
            "logo_count": schema.get("logo_count"),
            "extraction_notes": schema.get("extraction_notes"),
        },
    }


def list_format_profiles() -> list[dict[str, Any]]:
    root = _formats_root()
    items: list[dict[str, Any]] = []
    for path in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not path.is_dir():
            continue
        meta_path = path / "meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            items.append(
                {
                    "id": meta.get("id") or path.name,
                    "name": meta.get("name") or path.name,
                    "client_id": meta.get("client_id") or "",
                    "source_type": meta.get("source_type") or "",
                    "source_filename": meta.get("source_filename") or "",
                    "created_at": meta.get("created_at") or "",
                    "section_count": meta.get("section_count") or 0,
                    "logo_count": meta.get("logo_count") or 0,
                    "extraction_confidence": meta.get("extraction_confidence") or "",
                    "preview_text": (meta.get("preview_text") or "")[:240],
                }
            )
        except Exception as exc:
            logger.warning("format_profile_list_skip", path=str(path), error=str(exc))
    return items


def get_format_profile(format_id: str) -> dict[str, Any]:
    profile_dir = _profile_dir(format_id)
    meta_path = profile_dir / "meta.json"
    schema_path = profile_dir / "schema.json"
    if not meta_path.exists() or not schema_path.exists():
        raise FormatProfileError(f"Format profile not found: {format_id}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    schema = normalize_format_metadata(json.loads(schema_path.read_text(encoding="utf-8")))
    return {
        **meta,
        "schema": schema,
        "schema_preview": {
            "sections": schema.get("sections"),
            "section_order": schema.get("section_order"),
            "styling": schema.get("styling"),
            "logo_count": schema.get("logo_count"),
            "extraction_notes": schema.get("extraction_notes"),
        },
    }


def delete_format_profile(format_id: str) -> None:
    profile_dir = _profile_dir(format_id)
    if not profile_dir.exists():
        raise FormatProfileError(f"Format profile not found: {format_id}")
    shutil.rmtree(profile_dir)
    logger.info("format_profile_deleted", format_id=format_id)


def load_client_format(format_id: str, client_id: str = "") -> ClientFormat:
    """Build a ClientFormat from a saved profile, including template path for skeleton fill."""
    profile = get_format_profile(format_id)
    profile_dir = _profile_dir(format_id)
    meta = {k: v for k, v in profile.items() if k not in {"schema", "schema_preview"}}
    schema = normalize_format_metadata(profile.get("schema") or {})

    template_file = str(meta.get("template_file") or "")
    converted = str(meta.get("converted_docx") or "")
    source_type = str(meta.get("source_type") or schema.get("source_type") or "").lower()

    template_path = ""
    if source_type == "doc" and converted and (profile_dir / converted).exists():
        template_path = str(profile_dir / converted)
        schema["source_type"] = "docx"  # skeleton uses converted docx
        schema["extraction_notes"] = (
            str(schema.get("extraction_notes") or "") + " Using cached DOCX conversion from DOC."
        ).strip()
    elif template_file and (profile_dir / template_file).exists():
        template_path = str(profile_dir / template_file)

    try:
        profile_uuid = uuid.UUID(hex=format_id) if len(format_id) == 32 else uuid.uuid5(uuid.NAMESPACE_URL, format_id)
    except Exception:
        profile_uuid = uuid.uuid4()

    return ClientFormat(
        id=profile_uuid,
        client_id=(client_id or meta.get("client_id") or "Client"),
        format_metadata=schema,
        format_template_path=f"formats/{format_id}/{template_file}",
        template_bytes_path=template_path,
        format_profile_id=format_id,
        is_active=True,
    )


def slugify_name(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", (name or "").strip()).strip("-").lower()
    return slug or "format"
