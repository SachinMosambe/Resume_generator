"""Intake hardening: OCR paths, legacy .doc conversion, and non-resume quarantine.

Tesseract and LibreOffice are not required: OCR and conversion are monkeypatched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pymupdf as fitz
import pytest
from docx import Document
from fastapi.testclient import TestClient

from app.api.routes import generate as generate_route
from app.main import app
from app.services import doc_converter, pdf_ocr
from app.services.intake_gate import assess_resume_filename, assess_resume_intake
from app.services.output_integrity import check_output_integrity
from app.services.pdf_ocr import OcrUnavailableError, format_page_refs
from app.services.pdf_parser import extract_document
from tests.test_output_integrity import FULL, STORE, _docx

GOLDEN = Path(__file__).parent / "fixtures" / "golden"
OCR_TEXT = "OCR RECOVERED: Casey Example\nEXPERIENCE\nSenior Engineer | ExampleCorp - 2020 - Present"


def _case(name: str) -> str:
    return (GOLDEN / "cases" / f"{name}.txt").read_text(encoding="utf-8")


def _post(filename: str, payload: bytes, mime: str = "application/pdf"):
    return TestClient(app).post("/api/generate", files={"resume": (filename, payload, mime)})


def _ocr_on(monkeypatch, text: str = OCR_TEXT):
    monkeypatch.setattr(pdf_ocr, "ocr_available", lambda: True)
    monkeypatch.setattr(pdf_ocr, "ocr_page_text", lambda page, dpi=None: text)


def _ocr_off(monkeypatch):
    monkeypatch.setattr(pdf_ocr, "ocr_available", lambda: False)


# --- OCR ---------------------------------------------------------------------------------------


def test_ocr_unavailable_whole_scan_returns_clear_error(fixtures, monkeypatch):
    _ocr_off(monkeypatch)
    with pytest.raises(OcrUnavailableError) as info:
        extract_document(str(fixtures["scanned_pdf"]))
    assert info.value.pages == [1]

    resp = _post("scan.pdf", Path(fixtures["scanned_pdf"]).read_bytes())
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "scanned" in detail and "page 1" in detail
    assert "Traceback" not in detail and "Error" not in detail


def test_image_only_pdf_with_ocr_recovers_text_and_meta(fixtures, monkeypatch):
    _ocr_on(monkeypatch)
    text, meta = extract_document(str(fixtures["scanned_pdf"]))
    assert "Casey Example" in text
    assert meta["ocr_pages"] == [1]
    assert meta["ocr_missing_pages"] == []
    assert meta["doc_converted"] is False


def test_ocr_text_merges_in_source_page_order(fixtures, monkeypatch):
    _ocr_on(monkeypatch)
    text, meta = extract_document(str(fixtures["mixed_pdf"]))
    assert meta["ocr_pages"] == [2] and meta["ocr_missing_pages"] == []
    assert text.index("Globex") < text.index("OCR RECOVERED")


def test_mixed_pdf_without_ocr_marks_missing_pages(fixtures, monkeypatch):
    _ocr_off(monkeypatch)
    text, meta = extract_document(str(fixtures["mixed_pdf"]))
    assert "Globex" in text
    assert meta["ocr_missing_pages"] == [2] and meta["ocr_pages"] == []


def test_mixed_pdf_partial_draft_marks_missing_pages():
    meta = {"ocr_pages": [1], "ocr_missing_pages": [2]}
    report = check_output_integrity(STORE, _docx(*FULL), extraction_meta=meta)
    assert report.status == "needs_review"
    blocking = [w for w in report.warnings if w["severity"] == "blocking" and w["code"] == "source_pages_unread"]
    assert blocking and "page 2" in blocking[0]["message"]
    info = [w for w in report.warnings if w["code"] == "ocr_used"]
    assert info and info[0]["severity"] == "info" and "page 1" in info[0]["message"]


def test_recovered_and_unreadable_pages_are_tracked_separately(fixtures, monkeypatch):
    # OCR yields text only for the first call; the second flagged page stays unreadable.
    calls = {"n": 0}

    def flaky(page, dpi=None):
        calls["n"] += 1
        return OCR_TEXT if calls["n"] == 1 else ""

    monkeypatch.setattr(pdf_ocr, "ocr_available", lambda: True)
    monkeypatch.setattr(pdf_ocr, "ocr_page_text", flaky)
    path = Path(fixtures["scanned_pdf"]).parent / "two_scans.pdf"
    with fitz.open(fixtures["scanned_pdf"]) as a, fitz.open() as out:
        out.insert_pdf(a)
        out.insert_pdf(a)
        out.save(path)
    text, meta = extract_document(str(path))
    assert "OCR RECOVERED" in text
    assert meta["ocr_pages"] == [1] and meta["ocr_missing_pages"] == [2]


def test_page_refs_are_one_based_and_readable():
    assert format_page_refs([]) == ""
    assert format_page_refs([2]) == "page 2"
    assert format_page_refs([1, 2, 3]) == "pages 1-3"
    assert format_page_refs([5, 1, 2]) == "pages 1-2 and 5"
    assert format_page_refs([1, 3, 5]) == "pages 1, 3 and 5"


# --- Legacy .doc -------------------------------------------------------------------------------

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64


def test_doc_converts_and_reports_doc_converted(tmp_path, monkeypatch):
    source = tmp_path / "legacy.doc"
    source.write_bytes(OLE_MAGIC)
    converted = tmp_path / "converted" / "legacy.docx"
    converted.parent.mkdir()
    doc = Document()
    for line in _case("legacy_doc").splitlines():
        doc.add_paragraph(line)
    doc.save(converted)

    monkeypatch.setattr(doc_converter, "convert_doc_to_docx", lambda p, output_dir=None: converted)
    text, meta = extract_document(str(source))
    assert "Litware" in text and "Casey Example" in text
    assert meta["doc_converted"] is True


def test_doc_missing_libreoffice_422(tmp_path, monkeypatch):
    monkeypatch.setattr(doc_converter, "find_libreoffice", lambda: None)
    monkeypatch.setattr(doc_converter, "_convert_with_word", lambda source, out: None)

    with pytest.raises(doc_converter.DocConversionError):
        doc_converter.convert_doc_to_docx(_write(tmp_path / "a.doc", OLE_MAGIC))

    resp = _post("resume.doc", OLE_MAGIC, "application/msword")
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert ".docx" in detail
    assert "soffice" not in detail.lower() and "libreoffice" not in detail.lower()


def test_doc_conversion_failure_422_hides_converter_internals(tmp_path, monkeypatch):
    class _Result:
        returncode = 1
        stdout = ""
        stderr = "SECRET /usr/lib/libreoffice crash"

    monkeypatch.setattr(doc_converter, "find_libreoffice", lambda: "soffice")
    monkeypatch.setattr(doc_converter.subprocess, "run", lambda *a, **k: _Result())
    monkeypatch.setattr(doc_converter, "_poll_docx", lambda *a, **k: None)

    with pytest.raises(doc_converter.DocConversionError) as info:
        doc_converter.convert_doc_to_docx(_write(tmp_path / "b.doc", OLE_MAGIC))
    assert "SECRET" not in str(info.value) and ".docx" in str(info.value)

    resp = _post("resume.doc", OLE_MAGIC, "application/msword")
    assert resp.status_code == 422
    assert ".docx" in resp.json()["detail"] and "SECRET" not in resp.json()["detail"]


def _write(path: Path, payload: bytes) -> Path:
    path.write_bytes(payload)
    return path


# --- Non-resume quarantine ---------------------------------------------------------------------

REALISTIC_CERTIFICATE = """CERTIFICATE OF COMPLETION
This is to certify that Casey Example
has successfully completed the course Project Management Fundamentals
Issued March 14, 2024
Signature
"""

REALISTIC_I94 = """U.S. Department of Homeland Security
U.S. Customs and Border Protection
Departure/Arrival Record - Form I-94
Admit Until Date: 08/14/2027
Class of Admission: H-1B
Most Recent I-94
"""

TRAVEL_HISTORY = """Travel History
Casey Example
Entry 03/02/2023 - Dallas, TX
Exit 04/11/2023 - Dallas, TX
"""


@pytest.mark.parametrize("name", ["non_resume_certificate", "non_resume_travel"])
def test_golden_non_resume_stubs_are_quarantined(name):
    result = assess_resume_intake(_case(name))
    assert result.is_resume is False and result.reason_code


@pytest.mark.parametrize(
    "text,reason",
    [
        (REALISTIC_CERTIFICATE, "certificate"),
        (REALISTIC_I94, "travel_record"),
        (TRAVEL_HISTORY, "travel_record"),
        ("INVOICE #4411\nBill to: Litware\nAmount due: $1,200.00\nInvoice number 4411", "financial"),
    ],
)
def test_non_resume_quarantine_reasons(text, reason):
    result = assess_resume_intake(text)
    assert result.is_resume is False
    assert result.reason_code == reason
    assert "not a resume" in result.message and "Upload" in result.message


def test_non_resume_quarantine_422(monkeypatch):
    from app.services.extraction_adapters import ExtractionResult

    monkeypatch.setattr(
        generate_route,
        "extract_with_adapter",
        lambda path, **kw: ExtractionResult(text=REALISTIC_I94, method="pdf_native", meta={}, status="ok"),
    )
    resp = _post("i94.pdf", b"%PDF-1.4 stub")
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "not a resume" in detail and "I-94" in detail


def test_non_resume_certificate_422_via_api(monkeypatch):
    from app.services.extraction_adapters import ExtractionResult

    monkeypatch.setattr(
        generate_route,
        "extract_with_adapter",
        lambda path, **kw: ExtractionResult(text=REALISTIC_CERTIFICATE, method="pdf_native", meta={}, status="ok"),
    )
    resp = _post("cert.pdf", b"%PDF-1.4 stub")
    assert resp.status_code == 422 and "certificate" in resp.json()["detail"]


@pytest.mark.parametrize(
    "name",
    ["sparse_valid", "education_only", "skills_only", "title_only", "sparse_profile_full", "scanned_stub", "legacy_doc"],
)
def test_sparse_valid_resume_not_quarantined(name):
    assert assess_resume_intake(_case(name)).is_resume is True


def test_every_golden_resume_case_passes_the_gate():
    manifest = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
    checked = 0
    for fixture in manifest["fixtures"]:
        quarantined = fixture.get("expected_status") == "quarantine"
        result = assess_resume_intake((GOLDEN / fixture["source"]).read_text(encoding="utf-8"))
        assert result.is_resume is (not quarantined), fixture["id"]
        checked += 1
    assert checked >= 40


def test_resume_mentioning_i94_or_certificate_is_not_quarantined():
    text = (
        "Casey Example\ncasey@example.com\nSUMMARY\nAnalyst on an H-1B (I-94 valid to 2027).\n"
        "EXPERIENCE\nAnalyst | Litware - 2021 - Present\n- Closed the books.\n- Built reports.\n"
        "CERTIFICATIONS\nCertificate of Completion, Project Management Fundamentals\n"
    )
    assert assess_resume_intake(text).is_resume is True


def test_minimal_resume_without_markers_is_never_quarantined():
    assert assess_resume_intake("Casey Example\nAnalyst at Litware since 2021").is_resume is True
    assert assess_resume_intake("").is_resume is True


def test_i797_filename_quarantined_even_without_text():
    """Scanned I-797 notices have empty text layers; filename must still quarantine."""
    named = assess_resume_filename("I797 A_INFINITY GRP_MANAV KAPOOR_Exp 04182026.pdf")
    assert named is not None and named.is_resume is False
    assert named.reason_code == "travel_record"
    gated = assess_resume_intake("", filename="I797_notice.pdf")
    assert gated.is_resume is False and gated.reason_code == "travel_record"


def test_i797_filename_api_422_before_ocr(monkeypatch):
    # Must not reach extract — immigration scans are not OCR failures.
    monkeypatch.setattr(
        generate_route,
        "extract_with_adapter",
        lambda path, **kw: (_ for _ in ()).throw(AssertionError("extract should not run")),
    )
    resp = _post("I797 A_INFINITY GRP_MANAV KAPOOR.pdf", b"%PDF-1.4 stub")
    assert resp.status_code == 422
    assert "not a resume" in resp.json()["detail"]
    assert "I-797" in resp.json()["detail"] or "immigration" in resp.json()["detail"]
