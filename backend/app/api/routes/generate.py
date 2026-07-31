"""Generate resume from uploaded source file + optional client template."""

from __future__ import annotations

import re
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response

from app.core.config import settings
from app.core.logging import logger
from app.models.candidate import Candidate
from app.models.client_format import ClientFormat
from app.services.aptino_template import build_aptino_client_format
from app.services.format_extraction_service import FormatExtractionError, FormatExtractionService
from app.services.format_profile_store import FormatProfileError, load_client_format, save_format_profile
from app.services.pdf_parser import extract_text_from_document
from app.services.resume_generation_service import ResumeGenerationError, ResumeGenerationService
from app.services.s3_service import sanitize_filename

router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc"}


def _suffix(filename: str | None) -> str:
    return Path(filename or "").suffix.lower()


def _validate_upload(file: UploadFile, label: str) -> None:
    ext = _suffix(file.filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"{label} must be a PDF, DOC, or DOCX file",
        )
    if file.size and file.size > settings.max_file_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"{label} exceeds {settings.MAX_FILE_SIZE_MB} MB limit",
        )


def _guess_name_from_text(text: str) -> str | None:
    for line in (text or "").splitlines()[:12]:
        cleaned = re.sub(r"\s+", " ", line).strip()
        if not cleaned or len(cleaned) > 60:
            continue
        if "@" in cleaned or "http" in cleaned.lower():
            continue
        if re.search(r"\d{3}", cleaned):
            continue
        if re.match(r"^[A-Za-z][A-Za-z.'\- ]+$", cleaned) and " " in cleaned:
            return cleaned
    return None


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/generate")
async def generate_resume(
    resume: UploadFile = File(..., description="Source candidate resume (PDF/DOC/DOCX)"),
    template_source: str = Form("aptino_default"),
    client_name: str = Form(""),
    job_role: str = Form(""),
    format_id: str = Form(""),
    save_format: str = Form(""),
    format_name: str = Form(""),
    template: UploadFile | None = File(None, description="Optional client format PDF/DOC/DOCX"),
):
    _validate_upload(resume, "Resume")
    if template_source not in {"aptino_default", "client_format", "saved_format"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="template_source must be aptino_default, client_format, or saved_format",
        )

    resume_bytes = await resume.read()
    if not resume_bytes:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Resume file is empty")

    resume_ext = _suffix(resume.filename) or ".pdf"
    tmp_dir = Path(tempfile.mkdtemp(prefix="resume_gen_"))
    resume_path = tmp_dir / f"source_{uuid.uuid4().hex}{resume_ext}"
    resume_path.write_bytes(resume_bytes)
    template_tmp_path: Path | None = None

    try:
        resume_text = extract_text_from_document(str(resume_path)) or ""
    except Exception as exc:
        logger.warning("resume_text_extract_failed", error=str(exc))
        resume_text = ""

    client_id = (client_name or "").strip() or "Client"
    role = (job_role or "").strip() or None
    guessed_name = _guess_name_from_text(resume_text)

    candidate = Candidate(
        name=guessed_name or Path(resume.filename or "Candidate").stem.replace("_", " "),
        job_applied=role,
        job_role=role,
        job_title=role,
        client_name=client_id,
        resume_path=str(resume_path),
        extracted_data={"raw_text": resume_text, "resume_text": resume_text},
        recruiter_id=uuid.uuid4(),
    )

    saved_format_info: dict | None = None

    if template_source == "aptino_default":
        client_format = build_aptino_client_format(client_id)
    elif template_source == "saved_format":
        fid = (format_id or "").strip()
        if not fid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="format_id is required when template_source=saved_format",
            )
        try:
            client_format = load_client_format(fid, client_id=client_id)
        except FormatProfileError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    else:
        if template is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Upload a client format template when template_source=client_format",
            )
        _validate_upload(template, "Client format")
        template_bytes = await template.read()
        if not template_bytes:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Client format file is empty",
            )

        should_save = str(save_format or "").strip().lower() in {"1", "true", "yes", "on"}
        if should_save:
            try:
                saved_format_info = save_format_profile(
                    name=format_name or (template.filename or "Client Format"),
                    filename=template.filename or "format.docx",
                    content=template_bytes,
                    client_id=client_id,
                )
                client_format = load_client_format(saved_format_info["id"], client_id=client_id)
            except FormatProfileError as exc:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        else:
            try:
                metadata = FormatExtractionService().extract(template.filename or "format.docx", template_bytes)
            except FormatExtractionError as exc:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

            # Persist upload temporarily so DOCX/DOC skeleton fill can use original bytes.
            template_ext = _suffix(template.filename) or ".docx"
            template_tmp_path = tmp_dir / f"template_{uuid.uuid4().hex}{template_ext}"
            template_tmp_path.write_bytes(template_bytes)
            client_format = ClientFormat(
                client_id=client_id,
                format_template_path=f"upload://{sanitize_filename(template.filename or 'format')}",
                format_metadata=metadata,
                template_bytes_path=str(template_tmp_path),
            )

    if settings.RESUME_AGENT_PIPELINE:
        from app.agent_pipeline import AgentResumeGenerationService

        service: ResumeGenerationService = AgentResumeGenerationService()
    else:
        service = ResumeGenerationService()

    try:
        docx_bytes = service.generate(candidate, client_format)
    except ResumeGenerationError as exc:
        logger.exception("resume_generation_failed")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("resume_generation_unexpected")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate resume: {exc}",
        ) from exc
    finally:
        try:
            resume_path.unlink(missing_ok=True)
            if template_tmp_path is not None:
                template_tmp_path.unlink(missing_ok=True)
            tmp_dir.rmdir()
        except OSError:
            pass

    safe_name = sanitize_filename(candidate.name or "resume")
    filename = f"{safe_name}_generated.docx"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if saved_format_info and saved_format_info.get("id"):
        headers["X-Saved-Format-Id"] = str(saved_format_info["id"])
        headers["X-Saved-Format-Name"] = sanitize_filename(str(saved_format_info.get("name") or ""))
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=headers,
    )
