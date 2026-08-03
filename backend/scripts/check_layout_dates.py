"""Quick checks for right-aligned dates and bullet summary."""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("RESUME_LLM_CONDENSE", "false")
os.environ.setdefault("RESUME_LLM_POLISH", "false")
os.environ.setdefault("RESUME_AGENT_PIPELINE", "false")

import app.services.resume_generation_service as rgs
from app.models.candidate import Candidate
from app.models.client_format import ClientFormat
from app.models.format_schema import normalize_format_metadata
from app.services.docx_layout import split_left_right_meta, summary_to_bullets
from app.services.format_extraction_service import FormatExtractionService
from app.services.pdf_parser import extract_text_from_document
from app.services.resume_generation_service import ResumeGenerationService

rgs.upload_bytes_to_key = lambda **kwargs: None  # type: ignore[assignment]


def main() -> None:
    left, right = split_left_right_meta(
        "Adnig Technologies - Rai-Power, Gurugram  June 2013 to September 2014"
    )
    assert "Adnig" in left and "June 2013" in right, (left, right)
    left2, right2 = split_left_right_meta("Company https://example.com/job")
    assert "Company" in left2 and right2.startswith("https://"), (left2, right2)
    bullets = summary_to_bullets(
        "Built APIs. Led migrations. Improved latency by 40%."
    )
    assert len(bullets) >= 2, bullets
    print("helpers_ok", left, "|", right)

    test_root = ROOT.parent / "test"
    fmt = test_root / "format" / "Suresh Duvvada.docx"
    meta = normalize_format_metadata(
        FormatExtractionService().extract(fmt.name, fmt.read_bytes())
    )
    resume = test_root / "resume" / "Sachin_Mosambe_ATS_CV.pdf"
    text = extract_text_from_document(str(resume))
    svc = ResumeGenerationService()
    candidate = Candidate(
        name="Sachin Mosambe",
        client_name="TestClient",
        resume_path=str(resume),
        extracted_data={"raw_text": text, "resume_text": text},
        recruiter_id=uuid.uuid4(),
    )
    # Inject an experience row that previously mashed date onto the company line.
    data = candidate.extracted_data or {}
    # Generation will parse the PDF; also render a tiny synthetic doc via skeleton.
    from app.services.docx_skeleton_service import render_from_docx_skeleton

    synthetic = {
        "header": {"name": "Test Candidate", "role": "", "contact": []},
        "sections": [
            {
                "type": "bullets",
                "title": "Professional Summary",
                "content": [
                    "First summary point about backend systems.",
                    "Second summary point about cloud and GenAI.",
                ],
            },
            {
                "type": "experience",
                "title": "Work Experience",
                "content": [
                    {
                        "company": "Adnig Technologies - Rai-Power, Gurugram",
                        "title": "Software Engineer",
                        "duration": "June 2013 to September 2014",
                        "description": ["Built internal tools."],
                    },
                    {
                        "company": "Adnig Technologies - Rai-Power, Gurugram  June 2013 to September 2014",
                        "title": "Software Engineer",
                        "duration": "",
                        "description": ["Handled mashed date in company field."],
                    },
                ],
            },
            {
                "type": "education",
                "title": "Educational Details",
                "content": [
                    {
                        "degree": "B.Tech Computer Engineering",
                        "institution": "Test Institute",
                        "year": "2018 - 2021",
                    }
                ],
            },
        ],
    }
    docx = render_from_docx_skeleton(fmt, synthetic, meta, source_type="docx")
    assert docx, "skeleton render failed"
    out = test_root / "output_fixed"
    out.mkdir(exist_ok=True)
    path = out / "layout_date_summary_check.docx"
    path.write_bytes(docx)
    print("wrote", path)

    from docx import Document

    d = Document(str(path))
    summary_bullets = 0
    date_tabs = 0
    mashed = []
    after_summary = False
    for p in d.paragraphs:
        t = p.text.strip()
        if not t:
            continue
        if t.lower() == "professional summary":
            after_summary = True
            continue
        if after_summary and t.lower() in {
            "work experience",
            "educational details",
            "skill set overview",
        }:
            after_summary = False
        if after_summary and p.style and "list" in (p.style.name or "").lower():
            summary_bullets += 1
        if "\t" in p.text and any(ch.isdigit() for ch in t):
            date_tabs += 1
        if "Gurugram  June" in t or "Gurugram June" in t:
            mashed.append(t)
    print("summary_bullets", summary_bullets, "date_tabs", date_tabs, "mashed", mashed)
    assert summary_bullets >= 2, summary_bullets
    assert date_tabs >= 2, date_tabs
    assert not mashed, mashed
    print("layout_ok")

    # Full generate path smoke
    cf = ClientFormat(
        client_id="TestClient",
        format_metadata=meta,
        template_bytes_path=str(fmt),
    )
    full = svc.generate(candidate, cf)
    full_path = out / "sachin__layout_full.docx"
    full_path.write_bytes(full)
    print("full_ok", full_path, len(full))


if __name__ == "__main__":
    main()
