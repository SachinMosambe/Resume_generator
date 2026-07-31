"""CRUD API for saved company format profiles (PDF/DOC/DOCX)."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.core.config import settings
from app.core.logging import logger
from app.services.format_profile_store import (
    ALLOWED_TEMPLATE_EXTENSIONS,
    FormatProfileError,
    delete_format_profile,
    get_format_profile,
    list_format_profiles,
    save_format_profile,
)
from pathlib import Path

router = APIRouter(prefix="/formats", tags=["formats"])


def _validate_template(file: UploadFile) -> None:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_TEMPLATE_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Format must be a PDF, DOC, or DOCX file",
        )
    if file.size and file.size > settings.max_file_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Format exceeds {settings.MAX_FILE_SIZE_MB} MB limit",
        )


@router.get("/")
async def list_formats() -> dict:
    return {"formats": list_format_profiles()}


@router.post("/")
async def create_format(
    template: UploadFile = File(..., description="Company format PDF/DOC/DOCX"),
    name: str = Form(""),
    client_name: str = Form(""),
):
    _validate_template(template)
    content = await template.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Format file is empty")
    try:
        profile = save_format_profile(
            name=name,
            filename=template.filename or "format.docx",
            content=content,
            client_id=client_name,
        )
    except FormatProfileError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("format_profile_create_failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save format: {exc}",
        ) from exc
    return profile


@router.get("/{format_id}")
async def get_format(format_id: str) -> dict:
    try:
        return get_format_profile(format_id)
    except FormatProfileError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{format_id}")
async def remove_format(format_id: str) -> dict:
    try:
        delete_format_profile(format_id)
    except FormatProfileError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"status": "deleted", "id": format_id}
