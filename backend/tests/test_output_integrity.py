import io

from docx import Document

from app.services.output_integrity import check_output_integrity, warning_messages, warning_payload


def _msgs(report):
    return [w["message"] if isinstance(w, dict) else str(w) for w in report.warnings]

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
    assert any("bullet" in m.lower() for m in _msgs(report))
    assert all("migration" not in m.lower() for m in _msgs(report))


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
    assert any("References" in m and "omitted" in m for m in _msgs(report))
    assert all(w["severity"] == "info" for w in report.warnings)


def test_unread_scanned_pages_need_review():
    report = check_output_integrity(STORE, _docx(*FULL), extraction_meta={"ocr_missing_pages": [2], "ocr_pages": []})
    assert report.status == "needs_review"
    assert any("scanned" in m for m in _msgs(report))


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


def test_source_lines_alone_do_not_force_needs_review():
    # A reworded/reflowed source line carrying no employer, title, bullet, or metric is informational.
    source = "\n".join([*FULL, "Led migration of the ledger platform to a new event-driven architecture design"])
    report = check_output_integrity(STORE, _docx(*FULL), source_text=source)
    assert report.status == "passed", report.warnings
    assert report.checks["source_lines"]["ok"] is True
    assert report.checks["source_lines"]["found"] == 1
    assert any(w["severity"] == "info" and w["code"] == "source_lines_soft" for w in report.warnings)
    assert check_output_integrity(STORE, _docx(*FULL), source_text="\n".join(FULL)).status == "passed"


def test_source_line_with_required_fact_missing_needs_review():
    # The line names the employer, so a dropped line is a likely dropped bullet.
    source = "\n".join([*FULL, "Acme Corp rebuilt the ledger platform around a new event-driven architecture design"])
    report = check_output_integrity(STORE, _docx(*FULL), source_text=source)
    assert report.status == "needs_review"
    assert any(w["severity"] == "blocking" and w["code"] == "source_lines" for w in report.warnings)
    assert all("ledger" not in m.lower() for m in _msgs(report))


def test_changed_factual_number_needs_review():
    source = "\n".join([*FULL, "Reduced payment settlement latency by 35% across the entire merchant platform estate"])
    out = [*FULL, "Reduced payment settlement latency by 53% across the entire merchant platform estate"]
    report = check_output_integrity(STORE, _docx(*out), source_text=source)
    assert report.status == "needs_review"
    assert any(w["code"] == "source_numbers" for w in report.warnings)
    assert all("35" not in m and "53" not in m for m in _msgs(report))


def test_ocr_used_is_info_only():
    report = check_output_integrity(STORE, _docx(*FULL), extraction_meta={"ocr_pages": [1], "ocr_missing_pages": []})
    assert report.status == "passed"
    assert any(w["severity"] == "info" and "OCR" in w["message"] for w in report.warnings)


EMPTY_EXP_STORE = {**STORE, "experience": []}
EVIDENCE_META = {
    "employment_evidence": {"has_work_history": True, "reasons": ["experience_heading"]},
    "reasons": ["expected_experience_missing"],
}
NO_EXP_LINES = ["Jordan Rivera", "B.S. Physics", "Tech University", "2014", "Languages: Python, Go",
                "Publications", "Streaming joins. 2022."]


def test_zero_roles_with_employment_evidence_needs_review():
    report = check_output_integrity(
        EMPTY_EXP_STORE, _docx(*NO_EXP_LINES), source_text="\n".join(FULL), parse_meta=EVIDENCE_META
    )
    assert report.status == "needs_review"
    blocking = [w for w in report.warnings if w["severity"] == "blocking"]
    assert any(w["code"] == "expected_experience_missing" and "experience" in w["message"].lower() for w in blocking)


def test_zero_roles_without_evidence_has_no_experience_warning():
    report = check_output_integrity(
        EMPTY_EXP_STORE, _docx(*NO_EXP_LINES), parse_meta={"employment_evidence": {"has_work_history": False}}
    )
    assert report.status == "passed"
    assert not any(w["code"] == "expected_experience_missing" for w in report.warnings)


def test_zero_roles_with_preserved_unassigned_bullets_needs_review():
    store = {**EMPTY_EXP_STORE, "unassigned_experience_bullets": ["Led migration to event-driven payments."]}
    report = check_output_integrity(
        store, _docx(*NO_EXP_LINES, "Led migration to event-driven payments."), parse_meta=EVIDENCE_META
    )
    assert not any(w["code"] == "expected_experience_missing" for w in report.warnings)
    assert report.status == "needs_review"
    assert any(w["severity"] == "blocking" and w["code"] == "experience_roles_unassigned" for w in report.warnings)


def test_zero_roles_with_unpreserved_unassigned_bullets_is_blocking():
    store = {**EMPTY_EXP_STORE, "unassigned_experience_bullets": ["Led migration to event-driven payments."]}
    report = check_output_integrity(store, _docx(*NO_EXP_LINES), parse_meta=EVIDENCE_META)
    assert report.status == "needs_review"
    assert any(w["code"] == "expected_experience_missing" for w in report.warnings)


TWO_ROLES = {
    **STORE,
    "experience": [
        {"company": "Acme Corp", "title": "Staff Engineer", "duration": "Jul 2021 - Present",
         "description": ["Led migration to event-driven payments."]},
        {"company": "Globex Inc", "title": "Developer", "duration": "Jan 2015 - Jun 2021",
         "description": ["Built nightly reconciliation jobs for treasury."]},
    ],
}
TWO_ROLE_TAIL = ["B.S. Physics", "Tech University", "2014", "Languages: Python, Go", "Publications", "Streaming joins. 2022."]


def _two_role_docx(bullet_a, bullet_b):
    return _docx(
        "Jordan Rivera",
        "Staff Engineer", "Acme Corp", "Jul. 2021 – Present", bullet_a,
        "Developer", "Globex Inc", "Jan. 2015 – Jun. 2021", bullet_b,
        *TWO_ROLE_TAIL,
    )


def test_bullet_under_wrong_employer_fails():
    docx = _two_role_docx("Built nightly reconciliation jobs for treasury.", "Led migration to event-driven payments.")
    report = check_output_integrity(TWO_ROLES, docx)
    assert report.status == "failed"
    assert any(w["code"] == "bullet_wrong_role" for w in report.warnings)
    assert all("reconciliation" not in m.lower() and "Globex" not in m for m in _msgs(report))


def test_bullets_under_correct_employers_pass():
    docx = _two_role_docx("Led migration to event-driven payments.", "Built nightly reconciliation jobs for treasury.")
    assert check_output_integrity(TWO_ROLES, docx).status == "passed"


def test_wrong_assignment_check_can_be_disabled():
    docx = _two_role_docx("Built nightly reconciliation jobs for treasury.", "Led migration to event-driven payments.")
    assert check_output_integrity(TWO_ROLES, docx, verify_role_assignment=False).status == "passed"


def test_warning_payload_wraps_legacy_strings_and_caps():
    report = check_output_integrity(STORE, _docx(*FULL))
    report.warnings = [f"legacy {i}" for i in range(12)]
    report.status = "needs_review"
    payload = warning_payload(report)
    assert len(payload) == 10
    assert payload[0] == {"severity": "blocking", "code": "legacy", "message": "legacy 0"}


def test_warning_payload_keeps_blocking_when_truncating():
    report = check_output_integrity(STORE, _docx(*FULL))
    info = [{"severity": "info", "code": "i", "message": f"info {i}"} for i in range(12)]
    blocking = {"severity": "blocking", "code": "b", "message": "blocking last"}
    report.warnings = [*info, blocking]
    report.status = "needs_review"
    payload = warning_payload(report)
    assert len(payload) == 10
    assert payload[0] == blocking
    assert warning_messages(report)[0] == "blocking last"


def test_api_review_headers_legacy_strings_and_additive_details(fixtures, tmp_path, monkeypatch):
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
    legacy = json.loads(unquote(resp.headers["X-Review-Warnings"]))
    details = json.loads(unquote(resp.headers["X-Review-Warning-Details"]))
    assert all(isinstance(w, str) for w in legacy)
    assert all(set(w) == {"severity", "code", "message"} for w in details)
    assert legacy == [w["message"] for w in details]
    assert "x-review-warning-details" in resp.headers.get("access-control-expose-headers", "").lower()


def _meta(*reasons, history=True):
    return {"reasons": list(reasons), "employment_evidence": {"has_work_history": history}}


def test_identity_ambiguous_blocks_when_name_is_not_source_backed():
    store = {**STORE, "header": {"name": "Candidate"}}
    report = check_output_integrity(
        store, _docx("Candidate", *FULL[1:]), parse_meta=_meta("identity_ambiguous"), source_text="Skills\nReact Native"
    )
    assert report.status == "needs_review"
    assert any(w["code"] == "identity_ambiguous" and w["severity"] == "blocking" for w in report.warnings)


def test_identity_ambiguous_ignored_when_name_confirmed_by_source():
    report = check_output_integrity(
        STORE, _docx(*FULL), parse_meta=_meta("identity_ambiguous"), source_text="Jordan Rivera\nExperience"
    )
    assert not any(w["code"] == "identity_ambiguous" for w in report.warnings)


def test_unresolved_titles_block_only_with_employment_evidence():
    store = {**STORE, "experience": [{**STORE["experience"][0], "title": ""}]}
    lines = [x for x in FULL if x != "Staff Engineer"]
    blocked = check_output_integrity(store, _docx(*lines), parse_meta=_meta("source_backed_titles_unresolved"))
    assert any(w["code"] == "source_backed_titles_unresolved" and w["severity"] == "blocking" for w in blocked.warnings)
    quiet = check_output_integrity(
        store, _docx(*lines), parse_meta=_meta("source_backed_titles_unresolved", history=False)
    )
    assert not any(w["code"] == "source_backed_titles_unresolved" for w in quiet.warnings)


def test_garbled_role_and_overlap_reasons_block_without_leaking_content():
    report = check_output_integrity(
        STORE, _docx(*FULL), parse_meta=_meta("role_identity_garbled", "overlapping_role_dates")
    )
    codes = {w["code"] for w in report.warnings if w["severity"] == "blocking"}
    assert {"role_identity_garbled", "overlapping_role_dates"} <= codes
    assert report.status == "needs_review"
    assert all("Acme" not in m and "Jordan" not in m for m in _msgs(report))


def test_unassigned_bullets_with_roles_need_review_and_must_be_rendered():
    store = {**STORE, "unassigned_experience_bullets": ["Trained two analysts on the close checklist."]}
    shown = check_output_integrity(store, _docx(*FULL, "Trained two analysts on the close checklist."))
    assert shown.status == "needs_review"
    assert any(w["code"] == "experience_bullets_unassigned" for w in shown.warnings)
    assert not any(w["code"] == "unassigned_bullets_missing" for w in shown.warnings)
    hidden = check_output_integrity(store, _docx(*FULL))
    assert any(w["code"] == "unassigned_bullets_missing" for w in hidden.warnings)
