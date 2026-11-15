"""Small adapter interface over existing extractors (PDF / DOCX / DOC / OCR).

Keeps successful paths; does not replace them. Docling comparison is opt-in and
report-only until evaluation justifies a switch (see Wave 2 plan Phase 2).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.source_ledger import SourceLedger


@dataclass
class ExtractionResult:
    text: str
    method: str
    meta: dict[str, Any] = field(default_factory=dict)
    ledger: SourceLedger | None = None
    unsupported_elements: list[dict[str, Any]] = field(default_factory=list)
    limits_ok: bool = True
    status: str = "ok"  # ok | failed | unsupported | needs_review
    diagnostics: dict[str, Any] = field(default_factory=dict)


_SUPPORTED = {".pdf", ".docx", ".doc", ".html", ".htm"}


def _file_size_mb(path: str) -> float:
    try:
        return Path(path).stat().st_size / (1024 * 1024)
    except OSError:
        return 0.0


def _pdf_page_count(path: str) -> int | None:
    try:
        import fitz

        doc = fitz.open(path)
        try:
            return len(doc)
        finally:
            doc.close()
    except Exception:
        try:
            import pdfplumber

            with pdfplumber.open(path) as pdf:
                return len(pdf.pages)
        except Exception:
            return None


def probe_docling_available() -> dict[str, Any]:
    """Integration boundary for Docling — do not call on candidate data without decision."""
    try:
        import importlib

        importlib.import_module("docling")
        return {"available": True, "used": False, "note": "Installed but not selected without eval."}
    except Exception:
        return {
            "available": False,
            "used": False,
            "note": "Docling not installed; keep existing PDF extractor. Eval before switching.",
        }


def extract_with_adapter(path: str, **kwargs: Any) -> ExtractionResult:
    """Extract via existing ``pdf_parser.extract_document``; enforce hard limits."""
    settings = get_settings()
    ext = Path(path).suffix.lower()
    started = time.perf_counter()
    if ext not in _SUPPORTED:
        return ExtractionResult(
            text="",
            method="none",
            limits_ok=False,
            status="unsupported",
            unsupported_elements=[{"kind": "extension", "value": ext or "(none)"}],
            diagnostics={"reason": "unsupported_extension"},
        )

    max_mb = float(getattr(settings, "MAX_FILE_SIZE_MB", 10) or 10)
    size_mb = _file_size_mb(path)
    if size_mb > max_mb:
        return ExtractionResult(
            text="",
            method=ext.lstrip(".") or "unknown",
            limits_ok=False,
            status="failed",
            diagnostics={"reason": "file_size_limit", "size_mb": round(size_mb, 3), "max_mb": max_mb},
        )

    if ext == ".pdf":
        pages = _pdf_page_count(path)
        max_pages = int(getattr(settings, "RESUME_EXTRACT_MAX_PAGES", 40) or 40)
        if pages is not None and pages > max_pages:
            return ExtractionResult(
                text="",
                method="pdf_native",
                limits_ok=False,
                status="failed",
                diagnostics={
                    "reason": "page_limit",
                    "pages": pages,
                    "max_pages": max_pages,
                },
            )

    from app.services.docx_reader import DocxLimitError
    from app.services.doc_converter import DocConversionError
    from app.services.pdf_ocr import OcrUnavailableError
    from app.services.pdf_parser import extract_document

    timeout = float(getattr(settings, "RESUME_EXTRACT_TIMEOUT_SECONDS", 120.0) or 120.0)
    try:
        text, meta = extract_document(path, **kwargs)
    except DocxLimitError as exc:
        return ExtractionResult(
            text="",
            method="docx_native",
            limits_ok=False,
            status="failed",
            diagnostics={"reason": "docx_limit", "error": type(exc).__name__},
        )
    except DocConversionError as exc:
        return ExtractionResult(
            text="",
            method="doc_converted",
            limits_ok=False,
            status="failed",
            diagnostics={
                "reason": "doc_conversion",
                "error": type(exc).__name__,
                "retain_original": True,
            },
        )
    except OcrUnavailableError as exc:
        return ExtractionResult(
            text="",
            method="ocr",
            limits_ok=True,
            status="needs_review",
            diagnostics={
                "reason": "ocr_unavailable",
                "pages": list(getattr(exc, "pages", []) or []),
            },
        )
    except Exception as exc:  # noqa: BLE001
        return ExtractionResult(
            text="",
            method=ext.lstrip(".") or "unknown",
            limits_ok=False,
            status="failed",
            diagnostics={"reason": "extract_error", "error": type(exc).__name__},
        )

    elapsed = time.perf_counter() - started
    if elapsed > timeout:
        # Extraction finished but exceeded budget — do not claim clean success.
        meta = dict(meta or {})
        meta["extract_timeout"] = True
        return ExtractionResult(
            text=text or "",
            method=ext.lstrip("."),
            meta=meta,
            limits_ok=False,
            status="needs_review",
            diagnostics={"reason": "time_limit", "elapsed_seconds": round(elapsed, 2), "limit": timeout},
        )

    method = {
        ".docx": "docx_native",
        ".doc": "doc_converted",
        ".pdf": "pdf_native",
        ".html": "html",
        ".htm": "html",
    }.get(ext, ext.lstrip("."))
    if meta.get("ocr_pages"):
        method = "pdf_ocr_mixed" if text.strip() else "ocr"
    if meta.get("doc_converted"):
        method = "doc_converted"

    ledger = None
    ledger_data = meta.get("source_ledger")
    if isinstance(ledger_data, dict):
        try:
            ledger = SourceLedger.from_dict(ledger_data)
        except Exception:  # noqa: BLE001
            ledger = None

    unsupported = list((ledger.unsupported_elements if ledger else None) or [])
    # Inventory known incomplete surfaces rather than silently claiming full coverage.
    if ext == ".docx":
        unsupported.append({"kind": "note", "value": "embedded_objects_not_fully_inventoried"})
    if ext == ".pdf":
        unsupported.append({"kind": "note", "value": "annotations_and_xobject_forms_not_fully_inventoried"})
        meta = dict(meta or {})
        meta["docling_probe"] = probe_docling_available()

    truncated = bool(meta.get("truncated"))
    status = "ok"
    if truncated or meta.get("ocr_missing_pages"):
        status = "needs_review"
    if not (text or "").strip():
        status = "failed"

    meta = dict(meta or {})
    # Wave 3: Docling only as layout fallback for hard PDFs (not the default path).
    if (
        ext == ".pdf"
        and bool(getattr(settings, "RESUME_DOCLING_FALLBACK", True))
        and _should_try_docling(meta, text or "")
    ):
        alt = _try_docling_extract(path)
        meta["docling_fallback"] = {
            "attempted": True,
            "used": bool(alt.get("used")),
            "available": bool(alt.get("available")),
            "reason": alt.get("reason"),
            "chars": alt.get("chars"),
        }
        if alt.get("used") and alt.get("text"):
            text = str(alt["text"])
            method = "pdf_docling_fallback"
            # Rebuild ledger from the improved reading order when Wave-2 ledger is on.
            if bool(getattr(settings, "RESUME_SOURCE_LEDGER", False)):
                try:
                    from app.services.source_blocks import SourceBlock
                    from app.services.source_ledger import build_ledger_from_blocks

                    blocks = [
                        SourceBlock(
                            id=f"b{i:05d}",
                            text=ln,
                            origin="docling",
                            is_list=ln.lstrip().startswith(("•", "-", "*", "●")),
                        )
                        for i, ln in enumerate(
                            (x.strip() for x in text.splitlines() if x.strip()), start=1
                        )
                    ]
                    ledger = build_ledger_from_blocks(
                        blocks,
                        file_hash=str(meta.get("file_hash") or Path(path).name),
                        extractor_version="docling_fallback@1",
                        extraction_method="pdf_docling_fallback",
                    )
                    meta["source_ledger"] = ledger.to_dict()
                    meta["source_revision"] = ledger.source_revision
                except Exception:  # noqa: BLE001
                    pass
            if (text or "").strip():
                status = "needs_review" if (truncated or meta.get("ocr_missing_pages")) else "ok"

    return ExtractionResult(
        text=text or "",
        method=method,
        meta=meta,
        ledger=ledger,
        unsupported_elements=unsupported,
        limits_ok=not truncated,
        status=status,
        diagnostics={
            "truncated": truncated,
            "elapsed_seconds": round(elapsed, 3),
            "size_mb": round(size_mb, 3),
            "docling_fallback": meta.get("docling_fallback"),
        },
    )


def _should_try_docling(meta: dict[str, Any], text: str) -> bool:
    """True when native extract looks layout-hard or incomplete."""
    settings = get_settings()
    min_cols = int(getattr(settings, "RESUME_DOCLING_MIN_COLUMN_PAGES", 2) or 2)
    column_pages = int(meta.get("column_pages") or 0)
    unread = list(meta.get("ocr_missing_pages") or [])
    if unread:
        return True
    if column_pages >= min_cols:
        return True
    # Empty or near-empty extract — always try Docling before declaring no_text.
    if len((text or "").split()) < 40:
        return True
    # Very short extract on a multi-page PDF often means reading-order collapse.
    pages = meta.get("page_count") or meta.get("pages")
    try:
        page_n = int(pages) if pages is not None else 0
    except (TypeError, ValueError):
        page_n = 0
    if page_n >= 2 and len((text or "").split()) < 80:
        return True
    return not (text or "").strip()


def _try_docling_extract(path: str) -> dict[str, Any]:
    """Best-effort Docling conversion. Never raises into the adapter."""
    probe = probe_docling_available()
    if not probe.get("available"):
        return {"available": False, "used": False, "reason": "not_installed"}
    try:
        from docling.document_converter import DocumentConverter

        converter = DocumentConverter()
        converted = converter.convert(path)
        doc = getattr(converted, "document", None)
        text = ""
        if doc is not None and hasattr(doc, "export_to_markdown"):
            text = str(doc.export_to_markdown() or "")
        elif doc is not None and hasattr(doc, "export_to_text"):
            text = str(doc.export_to_text() or "")
        text = text.strip()
        if len(text.split()) < 40:
            return {
                "available": True,
                "used": False,
                "reason": "too_short",
                "chars": len(text),
            }
        return {
            "available": True,
            "used": True,
            "reason": "layout_fallback",
            "chars": len(text),
            "text": text,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "available": True,
            "used": False,
            "reason": type(exc).__name__,
        }
