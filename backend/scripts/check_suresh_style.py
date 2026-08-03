"""Quick style/format regression check against Suresh Duvvada.docx."""
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
from app.models.format_schema import normalize_format_metadata, to_heading_title_case
from app.services.format_extraction_service import FormatExtractionService
from app.services.pdf_parser import extract_text_from_document
from app.services.resume_generation_service import ResumeGenerationService

rgs.upload_bytes_to_key = lambda **kwargs: None  # type: ignore[assignment]


def main() -> None:
    assert to_heading_title_case("PROFESSIONAL SUMMARY") == "Professional Summary"
    assert to_heading_title_case("skill set overview:") == "Skill Set Overview"
    assert to_heading_title_case("Work Experience") == "Work Experience"
    print("title_case_ok")

    test_root = ROOT.parent / "test"
    fmt = test_root / "format" / "Suresh Duvvada.docx"
    meta = FormatExtractionService().extract(fmt.name, fmt.read_bytes())
    meta = normalize_format_metadata(meta)
    labels = meta.get("section_labels") or {}
    order = [s for s in (meta.get("section_order") or []) if s != "header"]
    print("ORDER", order)
    print("LABELS", labels)
    print("STYLE", meta.get("styling"))
    assert all(v == to_heading_title_case(v) for v in labels.values()), labels
    assert not any(str(v).isupper() and len(str(v)) > 3 for v in labels.values()), labels
    print("extract_ok")

    resume = test_root / "resume" / "Sachin_Mosambe_ATS_CV.pdf"
    text = extract_text_from_document(str(resume))
    svc = ResumeGenerationService()
    candidate = Candidate(
        name="Sachin Mosambe",
        job_applied=None,
        client_name="TestClient",
        resume_path=str(resume),
        extracted_data={"raw_text": text, "resume_text": text},
        recruiter_id=uuid.uuid4(),
    )
    cf = ClientFormat(
        client_id="TestClient",
        format_template_path="upload://suresh.docx",
        format_metadata=meta,
        template_bytes_path=str(fmt),
    )
    docx = svc.generate(candidate, cf)
    out = test_root / "output_fixed"
    out.mkdir(exist_ok=True)
    out_path = out / "sachin__suresh_style_check.docx"
    out_path.write_bytes(docx)
    print("wrote", out_path, len(docx))

    from docx import Document

    d = Document(str(out_path))
    headings: list[str] = []
    issues: list[str] = []
    for p in d.paragraphs:
        t = p.text.strip()
        if not t:
            continue
        for r in p.runs:
            if r.italic:
                issues.append(f"italic text={t[:50]!r}")
            if r.underline:
                issues.append(f"underline text={t[:50]!r}")
            if r.font.size and abs(float(r.font.size.pt) - 10.0) > 0.15:
                issues.append(f"size={r.font.size.pt} text={t[:50]!r}")
        low = t.lower()
        if (
            any(
                k in low
                for k in (
                    "summary",
                    "skill",
                    "experience",
                    "education",
                    "certif",
                    "achievement",
                    "project",
                )
            )
            and len(t.split()) <= 5
            and p.runs
            and p.runs[0].bold
        ):
            headings.append(t)
            letters = "".join(ch for ch in t if ch.isalpha())
            if letters.isupper() and len(letters) >= 4:
                issues.append(f"ALLCAPS heading={t!r}")

    print("HEADINGS", headings)
    print("ISSUES_COUNT", len(issues))
    for i in issues[:15]:
        print(" ", i)
    joined = " | ".join(headings)
    assert "Professional Summary" in joined or "professional summary" in joined.lower(), headings
    assert not any(h.replace(" ", "").isupper() for h in headings), headings
    assert not any(i.startswith("italic") for i in issues), issues
    assert not any(i.startswith("ALLCAPS") for i in issues), issues
    print("render_style_ok")


if __name__ == "__main__":
    main()
