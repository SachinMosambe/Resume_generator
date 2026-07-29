"""Utility service for extracting raw text from PDF and Word documents."""
from pathlib import Path

import pdfplumber

try:
    import docx
except ImportError:  # pragma: no cover
    docx = None


def _normalize_line(line: str) -> str:
    return " ".join((line or "").strip().split()).casefold()


def _strip_repeated_header_footer(
    page_texts: list[str], *, top_n: int = 3, bottom_n: int = 3, min_repeats: int = 2
) -> list[str]:
    """Remove repeated header/footer lines that appear on most pages.

    Many resumes repeat the same name/contact line at the top and a footer/page
    marker at the bottom of each page; keeping these confuses parsers by
    duplicating content.
    """
    if not page_texts or len(page_texts) < min_repeats:
        return page_texts

    # Collect top/bottom line candidates across pages.
    top_counts: dict[str, int] = {}
    bottom_counts: dict[str, int] = {}
    top_raw: dict[str, str] = {}
    bottom_raw: dict[str, str] = {}

    for text in page_texts:
        lines = [ln for ln in (text or "").splitlines() if ln.strip()]
        if not lines:
            continue
        for ln in lines[:top_n]:
            key = _normalize_line(ln)
            if not key:
                continue
            top_counts[key] = top_counts.get(key, 0) + 1
            top_raw.setdefault(key, ln)
        for ln in lines[-bottom_n:]:
            key = _normalize_line(ln)
            if not key:
                continue
            bottom_counts[key] = bottom_counts.get(key, 0) + 1
            bottom_raw.setdefault(key, ln)

    # Mark as header/footer if repeated on a majority of pages.
    page_count = max(1, len(page_texts))
    threshold = max(min_repeats, int(page_count * 0.6))

    header_keys = {k for k, c in top_counts.items() if c >= threshold}
    footer_keys = {k for k, c in bottom_counts.items() if c >= threshold}

    if not header_keys and not footer_keys:
        return page_texts

    cleaned_pages: list[str] = []
    for text in page_texts:
        raw_lines = (text or "").splitlines()
        kept: list[str] = []
        for ln in raw_lines:
            key = _normalize_line(ln)
            if key and (key in header_keys or key in footer_keys):
                continue
            kept.append(ln)
        cleaned_pages.append("\n".join(kept).strip())

    return cleaned_pages


def extract_text_from_document(path: str) -> str:
    """Extract text from a supported document type."""
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return _extract_pdf(path).strip()
    if ext == ".docx":
        return _extract_docx(path).strip()
    if ext == ".doc":
        return _extract_doc(path).strip()
    return ""


def extract_text_from_pdf(path: str) -> str:
    """Backward-compatible alias for PDF text extraction."""
    return extract_text_from_document(path)


def _extract_doc(path: str) -> str:
    """Extract text from legacy .doc by converting to .docx first."""
    try:
        from app.services.doc_converter import DocConversionError, convert_doc_to_docx
    except Exception:
        return ""
    try:
        converted = convert_doc_to_docx(Path(path), output_dir=Path(path).parent)
        return _extract_docx(str(converted)).strip()
    except DocConversionError:
        return ""
    except Exception:
        return ""


def _extract_pdf(path: str) -> str:
    text = _extract_pdfplumber(path)
    if not text.strip():
        text = _extract_pymupdf(path)
    return text


def _extract_pdfplumber(path: str) -> str:
    try:
        with pdfplumber.open(path) as pdf:
            pages: list[str] = []
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    pages.append(page_text)
            pages = _strip_repeated_header_footer(pages)
            return "\n\n".join(pages)
    except Exception:
        return ""


def _extract_pymupdf(path: str) -> str:
    try:
        import fitz  # pymupdf
        doc = fitz.open(path)
        pages = [page.get_text() for page in doc]
        doc.close()
        pages = _strip_repeated_header_footer(pages)
        return "\n\n".join(pages)
    except Exception:
        return ""


def _extract_docx(path: str) -> str:
    if docx is None:
        return ""
    try:
        document = docx.Document(path)
        # DOCX headers/footers are not included in `document.paragraphs`, but
        # many resumes repeat name/contact at the top of each page inside body
        # content. Apply a light de-duplication of repeated leading/trailing lines.
        parts: list[str] = [p.text for p in document.paragraphs if p.text and str(p.text).strip()]
        # Many client/candidate resumes store experience/skills in tables — include them.
        for table in getattr(document, "tables", []) or []:
            for row in table.rows:
                cells = []
                for cell in row.cells:
                    cell_text = " ".join(
                        p.text.strip() for p in cell.paragraphs if p.text and p.text.strip()
                    ).strip()
                    if cell_text:
                        cells.append(cell_text)
                if cells:
                    parts.append(" | ".join(cells))
        text = "\n".join(parts)
        pages = [text]
        pages = _strip_repeated_header_footer(pages, min_repeats=999)  # no-op for single "page"
        return pages[0] if pages else text
    except Exception:
        return ""
