import io

from docx import Document

from app.services.output_integrity import check_output_integrity

STORE = {
    "header": {"name": "Jordan Rivera"},
    "experience": [
        {
            "company": "Acme Corp",
            "title": "Staff Engineer",
            "duration": "Jul 2021 - Present",
            "description": ["Led migration to event-driven payments."],
        }
    ],
    "education": [{"degree": "B.S. Physics", "institution": "Tech University", "year": "2014"}],
    "skills_by_category": {"Languages": ["Python", "Go"]},
    "additional_sections": [{"title": "Publications", "lines": ["Streaming joins. 2022."]}],
}

FULL = [
    "Jordan Rivera", "Staff Engineer", "Acme Corp", "Jul. 2021 – Present",
    "Led migration to event-driven payments.", "B.S. Physics", "Tech University", "2014",
    "Languages: Python, Go", "Publications", "Streaming joins. 2022.",
]


def _docx(*lines):
    d = Document()
    for line in lines:
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_shortened_education_date_still_passes():
    store = {
        **STORE,
        "education": [
            {"degree": "Bachelor of Science, Computer Science", "institution": "State University", "year": "06/1994"}
        ],
    }
    lines = [
        "Jordan Rivera", "Staff Engineer", "Acme Corp", "Jul. 2021 – Present",
        "Led migration to event-driven payments.",
        "Bachelor of Science, Computer Science", "State University", "1994",
        "Languages: Python, Go", "Publications", "Streaming joins. 2022.",
    ]
    report = check_output_integrity(store, _docx(*lines))
    assert report.status == "passed", report.warnings


def test_all_present_passes():
    report = check_output_integrity(STORE, _docx(*FULL))
    assert report.status == "passed", report.warnings
    assert report.warnings == []


def test_missing_bullet_needs_review_without_leaking_content():
    lines = [l for l in FULL if not l.startswith("Led migration")]
    report = check_output_integrity(STORE, _docx(*lines))
    assert report.status == "needs_review"
    assert any("bullet" in w.lower() for w in report.warnings)
    assert all("migration" not in w.lower() for w in report.warnings)


def test_most_roles_missing_fails():
    store = {
        **STORE,
        "experience": [
            {"company": f"Company{i}", "title": "Engineer", "duration": f"Jan 20{10 + i} - Dec 20{10 + i}",
             "description": [f"Delivered outcome number {i} for the team."]}
            for i in range(4)
        ],
    }
    report = check_output_integrity(store, _docx(*FULL))
    assert report.status == "failed"


def test_template_sample_leak_detected_but_branding_allowed():
    lines = FULL + ["Sample Candidate Name", "Client Staffing Ltd | Confidential"]
    report = check_output_integrity(
        STORE,
        _docx(*lines),
        template_sample_text="Sample Candidate Name\nSampleCo Industries\nClient Staffing Ltd | Confidential",
        allowed_text="Client Staffing Ltd | Confidential",
    )
    assert report.status == "needs_review"
    assert report.checks["template_leak"]["found"] == 1


def test_suppressed_section_reported_not_failed():
    store = {**STORE, "additional_sections": STORE["additional_sections"] + [
        {"title": "References", "lines": ["Pat Manager, pat.manager@example.org"]}]}
    report = check_output_integrity(store, _docx(*FULL), suppressed_sections=["References"])
    assert report.status == "passed"
    assert any("References" in w and "omitted" in w for w in report.warnings)


def test_unread_scanned_pages_need_review():
    report = check_output_integrity(STORE, _docx(*FULL), extraction_meta={"ocr_missing_pages": [2], "ocr_pages": []})
    assert report.status == "needs_review"
    assert any("scanned" in w for w in report.warnings)


def test_api_returns_review_headers_visible_to_browser(fixtures, tmp_path, monkeypatch):
    import json
    from urllib.parse import unquote

    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    with open(fixtures["single_column_pdf"], "rb") as fh:
        resp = TestClient(app).post(
            "/api/generate",
            files={"resume": ("cv.pdf", fh, "application/pdf")},
            headers={"Origin": "http://localhost:3000"},
        )
    assert resp.status_code == 200
    assert resp.headers["X-Review-Status"] in {"passed", "needs_review", "failed"}
    assert isinstance(json.loads(unquote(resp.headers["X-Review-Warnings"])), list)
    assert "x-review-status" in resp.headers.get("access-control-expose-headers", "").lower()


def test_unreadable_docx_fails():
    assert check_output_integrity(STORE, b"not a docx").status == "failed"
