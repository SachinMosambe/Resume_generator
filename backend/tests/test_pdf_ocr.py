import pymupdf as fitz
import pytest

from app.services import pdf_ocr
from app.services.pdf_ocr import OcrUnavailableError, ocr_available, page_needs_ocr
from app.services.pdf_parser import extract_document, extract_text_from_document


def test_scanned_page_needs_ocr(fixtures):
    with fitz.open(fixtures["scanned_pdf"]) as doc:
        assert page_needs_ocr(doc[0]) is True


def test_native_page_does_not_need_ocr(fixtures):
    with fitz.open(fixtures["single_column_pdf"]) as doc:
        assert page_needs_ocr(doc[0]) is False


def test_mixed_pdf_flags_only_the_scanned_page(fixtures):
    with fitz.open(fixtures["mixed_pdf"]) as doc:
        assert [page_needs_ocr(p) for p in doc] == [False, True]


def test_scanned_pdf_without_ocr_raises(fixtures, monkeypatch):
    monkeypatch.setattr(pdf_ocr, "ocr_available", lambda: False)
    with pytest.raises(OcrUnavailableError):
        extract_text_from_document(str(fixtures["scanned_pdf"]))


def test_mixed_pdf_without_ocr_keeps_native_text_and_reports_gap(fixtures, monkeypatch):
    monkeypatch.setattr(pdf_ocr, "ocr_available", lambda: False)
    text, meta = extract_document(str(fixtures["mixed_pdf"]))
    assert "Globex" in text
    assert meta["ocr_missing_pages"] == [2]
    assert meta["ocr_pages"] == []


def test_native_pdf_meta_is_clean(fixtures):
    _, meta = extract_document(str(fixtures["single_column_pdf"]))
    assert meta["ocr_missing_pages"] == [] and meta["ocr_pages"] == []


def test_api_explains_scanned_pdf_without_ocr(fixtures, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr(pdf_ocr, "ocr_available", lambda: False)
    with open(fixtures["scanned_pdf"], "rb") as fh:
        resp = TestClient(app).post(
            "/api/generate", files={"resume": ("scan.pdf", fh, "application/pdf")}
        )
    assert resp.status_code == 422
    assert "scanned" in resp.json()["detail"]


@pytest.mark.skipif(not ocr_available(), reason="tesseract not installed")
def test_scanned_pdf_text_recovered(fixtures):
    text, meta = extract_document(str(fixtures["scanned_pdf"]))
    assert "Acme" in text and "EXPERIENCE" in text.upper()
    assert meta["ocr_pages"] == [1]
