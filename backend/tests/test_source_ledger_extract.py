"""Extraction attaches a source ledger when RESUME_SOURCE_LEDGER is enabled."""

from __future__ import annotations

from docx import Document

from app.core.config import get_settings
from app.services.pdf_parser import extract_document


def test_docx_extract_includes_ledger_when_flag_on(tmp_path, monkeypatch):
    monkeypatch.setenv("RESUME_SOURCE_LEDGER", "true")
    get_settings.cache_clear()
    path = tmp_path / "sample.docx"
    doc = Document()
    doc.add_paragraph("Casey Example")
    doc.add_paragraph("Acme Corp — Engineer — 2020-2022")
    doc.add_paragraph("• Shipped the onboarding checklist for new analysts.")
    doc.save(path)

    text, meta = extract_document(str(path))
    get_settings.cache_clear()
    assert "Casey Example" in text
    assert "source_ledger" in meta
    items = meta["source_ledger"]["items"]
    assert len(items) >= 2
    assert items[0]["disposition"] == "unresolved"
    assert meta["source_revision"]


def test_docx_extract_omits_ledger_when_flag_off(tmp_path, monkeypatch):
    monkeypatch.setenv("RESUME_SOURCE_LEDGER", "false")
    get_settings.cache_clear()
    path = tmp_path / "sample.docx"
    doc = Document()
    doc.add_paragraph("Casey Example")
    doc.save(path)

    _text, meta = extract_document(str(path))
    get_settings.cache_clear()
    assert "source_ledger" not in meta
