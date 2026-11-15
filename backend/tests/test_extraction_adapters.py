"""Extraction adapters wrap existing PDF/DOCX/DOC paths behind one interface."""

from __future__ import annotations

from docx import Document

from app.services.extraction_adapters import ExtractionResult, extract_with_adapter


def test_docx_adapter_returns_text_and_optional_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("RESUME_SOURCE_LEDGER", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    path = tmp_path / "a.docx"
    doc = Document()
    doc.add_paragraph("Casey Example")
    doc.add_paragraph("• Built the billing API.")
    doc.save(path)

    result = extract_with_adapter(str(path))
    get_settings.cache_clear()
    assert isinstance(result, ExtractionResult)
    assert "Casey Example" in result.text
    assert result.method in {"docx_native", "docx"}
    assert result.limits_ok is True
    assert result.ledger is not None
    assert len(result.ledger.items) >= 1


def test_unsupported_extension_is_explicit_failure(tmp_path):
    path = tmp_path / "x.xyz"
    path.write_bytes(b"not a resume")
    result = extract_with_adapter(str(path))
    assert result.text == ""
    assert result.limits_ok is False or result.status in {"failed", "unsupported"}
    assert result.unsupported_elements or result.status == "unsupported"
