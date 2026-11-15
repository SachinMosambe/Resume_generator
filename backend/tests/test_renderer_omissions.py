"""Regression: required store content must appear in rendered Aptino DOCX."""

from __future__ import annotations

from io import BytesIO

from docx import Document

from app.services.aptino_template import get_aptino_default_metadata
from app.services.docx_skeleton_service import render_from_docx_skeleton
from app.services.structured_resume_store import attach_unassigned_experience, document_from_store


def _paras(docx_bytes: bytes) -> str:
    doc = Document(BytesIO(docx_bytes))
    return "\n".join(p.text for p in doc.paragraphs if p.text and p.text.strip())


def test_additional_section_lines_are_rendered():
    store = {
        "header": {"name": "Casey Example", "role": "Engineer"},
        "summary": "",
        "skills": [],
        "skills_by_category": {},
        "experience": [
            {
                "company": "Acme Corp",
                "title": "Engineer",
                "duration": "2020-2022",
                "description": ["Shipped the onboarding checklist for new analysts."],
            }
        ],
        "education": [],
        "projects": [],
        "certifications": ["AWS Solutions Architect"],
        "achievements": [],
        "languages": [],
        "additional_sections": [
            {"title": "Publications", "lines": ["Wrote the ledger migration case study in 2021."]}
        ],
    }
    metadata = get_aptino_default_metadata()
    document = document_from_store(store, metadata)
    assert any(
        isinstance(s, dict) and "Publications" in str(s.get("title") or "") for s in document["sections"]
    )
    # Schema-path render via skeleton needs a template file; use in-memory schema by
    # building a minimal blank docx as skeleton.
    from docx import Document as DocxDocument
    from pathlib import Path
    import tempfile

    blank = DocxDocument()
    blank.add_paragraph("Sample")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "blank.docx"
        blank.save(path)
        docx_bytes = render_from_docx_skeleton(path, document, metadata, source_type="docx")
    assert docx_bytes
    text = _paras(docx_bytes)
    assert "AWS Solutions Architect" in text
    assert "ledger migration case study" in text
    assert "onboarding checklist" in text


def test_duplicate_bullet_under_two_roles_both_rendered():
    store = {
        "header": {"name": "Casey Example", "role": "Engineer"},
        "summary": "",
        "skills": [],
        "skills_by_category": {},
        "experience": [
            {
                "company": "Acme Corp",
                "title": "Engineer",
                "duration": "2018-2020",
                "description": ["Owned the ledger service."],
            },
            {
                "company": "Globex Inc",
                "title": "Lead",
                "duration": "2020-2022",
                "description": ["Owned the ledger service."],
            },
        ],
        "education": [],
        "projects": [],
        "certifications": [],
        "achievements": [],
        "languages": [],
        "additional_sections": [],
    }
    metadata = get_aptino_default_metadata()
    document = document_from_store(store, metadata)
    from docx import Document as DocxDocument
    from pathlib import Path
    import tempfile

    blank = DocxDocument()
    blank.add_paragraph("Sample")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "blank.docx"
        blank.save(path)
        docx_bytes = render_from_docx_skeleton(path, document, metadata, source_type="docx")
    assert docx_bytes
    text = _paras(docx_bytes)
    assert text.count("Owned the ledger service.") >= 2
    assert "Acme Corp" in text and "Globex Inc" in text


def test_unassigned_bullets_remain_visible():
    store = {
        "header": {"name": "Casey Example", "role": ""},
        "summary": "",
        "skills": [],
        "skills_by_category": {},
        "experience": [
            {
                "company": "Acme Corp",
                "title": "Engineer",
                "duration": "2020-2022",
                "description": ["Shipped features."],
            }
        ],
        "education": [],
        "projects": [],
        "certifications": [],
        "achievements": [],
        "languages": [],
        "additional_sections": [],
        "unassigned_experience_bullets": ["Supported the quarterly board packet in 2019."],
    }
    metadata = get_aptino_default_metadata()
    document = document_from_store(store, metadata)
    document = attach_unassigned_experience(document, store, metadata)
    from docx import Document as DocxDocument
    from pathlib import Path
    import tempfile

    blank = DocxDocument()
    blank.add_paragraph("Sample")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "blank.docx"
        blank.save(path)
        docx_bytes = render_from_docx_skeleton(path, document, metadata, source_type="docx")
    assert docx_bytes
    text = _paras(docx_bytes)
    assert "Supported the quarterly board packet" in text
    assert "Role details need review" in text
