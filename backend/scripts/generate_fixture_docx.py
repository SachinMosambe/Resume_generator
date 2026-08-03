"""Generate DOCX from test fixtures without Bedrock / S3 (for local Docker runs)."""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

os.environ.setdefault("RESUME_LLM_CONDENSE", "false")
os.environ.setdefault("RESUME_LLM_POLISH", "false")
os.environ.setdefault("RESUME_AGENT_PIPELINE", "false")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app.services.resume_generation_service as rgs
from app.models.candidate import Candidate
from app.models.client_format import ClientFormat
from app.services.aptino_template import build_aptino_client_format
from app.services.format_extraction_service import FormatExtractionService
from app.services.pdf_parser import extract_text_from_document
from app.services.resume_generation_service import ResumeGenerationService
from app.services.s3_service import sanitize_filename

rgs.upload_bytes_to_key = lambda **kwargs: None  # type: ignore[assignment]


def main() -> None:
    test_root = Path("/test") if Path("/test/resume").is_dir() else ROOT.parent / "test"
    out = test_root / "output_fixed"
    out.mkdir(parents=True, exist_ok=True)
    svc = ResumeGenerationService()

    resumes = sorted((test_root / "resume").glob("*.pdf"))
    formats = {
        "aptino_default": None,
        "juhi_aptino": test_root / "format" / "Juhi Patil - Aptino format.docx",
        "suresh": test_root / "format" / "Suresh Duvvada.docx",
    }

    for resume in resumes:
        text = extract_text_from_document(str(resume))
        name = resume.stem.replace("_", " ")
        for fmt_name, fmt_path in formats.items():
            if resume.name.lower().startswith("aditya") and fmt_name == "suresh":
                continue
            print("GEN", resume.name, fmt_name)
            candidate = Candidate(
                name=name,
                job_applied=None,
                client_name="TestClient",
                resume_path=str(resume),
                extracted_data={"raw_text": text, "resume_text": text},
                recruiter_id=uuid.uuid4(),
            )
            if fmt_path is None:
                client_format = build_aptino_client_format("TestClient")
            else:
                meta = FormatExtractionService().extract(fmt_path.name, fmt_path.read_bytes())
                client_format = ClientFormat(
                    client_id="TestClient",
                    format_template_path=f"upload://{sanitize_filename(fmt_path.name)}",
                    format_metadata=meta,
                    template_bytes_path=str(fmt_path),
                )
            docx = svc.generate(candidate, client_format)
            out_path = out / f"{resume.stem}__{fmt_name}.docx"
            out_path.write_bytes(docx)
            print("  wrote", out_path.name, len(docx))
    print("fixture_generate_ok")


if __name__ == "__main__":
    main()
