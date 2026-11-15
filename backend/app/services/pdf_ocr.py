"""Optional OCR for image-only PDF pages.

Primary path: PyMuPDF + system Tesseract.
Fallback: RapidOCR (onnxruntime) when Tesseract is not installed — required so
scanned resumes still extract on developer Windows machines without apt packages.
"""

from __future__ import annotations

import shutil
from functools import lru_cache

from app.core.config import settings
from app.core.logging import logger


class OcrUnavailableError(RuntimeError):
    """A PDF has no readable text and OCR is not installed or is disabled."""

    def __init__(self, message: str, pages: list[int] | None = None) -> None:
        super().__init__(message)
        self.pages: list[int] = list(pages or [])


def format_page_refs(pages: list[int] | tuple[int, ...]) -> str:
    """1-based, recruiter-readable page references: 'page 2', 'pages 1-3 and 5'."""
    nums = sorted({int(p) for p in pages if int(p) > 0})
    if not nums:
        return ""
    runs: list[tuple[int, int]] = []
    for n in nums:
        if runs and n == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], n)
        else:
            runs.append((n, n))
    parts = [str(a) if a == b else f"{a}-{b}" for a, b in runs]
    if len(nums) == 1:
        return f"page {parts[0]}"
    joined = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + f" and {parts[-1]}"
    return f"pages {joined}"


def _tesseract_available() -> bool:
    if shutil.which("tesseract") is None:
        return False
    try:
        import pymupdf as fitz

        return bool(fitz.get_tessdata())
    except Exception:
        return False


@lru_cache(maxsize=1)
def _rapidocr_engine():
    try:
        from rapidocr_onnxruntime import RapidOCR

        return RapidOCR()
    except Exception as exc:  # noqa: BLE001
        logger.info("rapidocr_unavailable", error_type=type(exc).__name__)
        return None


def ocr_available() -> bool:
    if not settings.RESUME_OCR_ENABLED:
        return False
    return _tesseract_available() or _rapidocr_engine() is not None


def page_needs_ocr(page) -> bool:
    """True when a page's content is mostly an image or its text layer is unusable."""
    text = page.get_text("text") or ""
    letters = sum(c.isalpha() for c in text)
    printable = sum(c.isprintable() or c.isspace() for c in text) / max(1, len(text))
    garbage = text.count("(cid:") + text.count("\ufffd")
    area = abs(page.rect)
    image_area = 0.0
    for info in page.get_image_info():
        x0, y0, x1, y1 = info["bbox"]
        image_area += max(0.0, x1 - x0) * max(0.0, y1 - y0)
    image_cover = min(1.0, image_area / area) if area else 0.0
    if letters < 30 and image_cover > 0.3:
        return True
    if text.strip() and (garbage > 20 or printable < 0.85):
        return True
    return image_cover > 0.6 and letters < 200


def _ocr_page_rapidocr(page, dpi: int) -> str:
    import numpy as np
    import pymupdf as fitz

    engine = _rapidocr_engine()
    if engine is None:
        return ""
    zoom = max(1.0, float(dpi) / 72.0)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    # RapidOCR expects HWC uint8 BGR/RGB ndarray.
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:
        img = img[:, :, :3]
    result, _ = engine(img)
    if not result:
        return ""
    # Each item: [box, text, score]
    lines = [str(item[1]).strip() for item in result if item and len(item) > 1 and str(item[1]).strip()]
    return "\n".join(lines)


def ocr_page_text(page, dpi: int | None = None) -> str:
    """OCR a page; prefer Tesseract, fall back to RapidOCR."""
    dpi_i = int(dpi or settings.RESUME_OCR_DPI)
    if _tesseract_available():
        tp = page.get_textpage_ocr(
            language=settings.RESUME_OCR_LANG,
            dpi=dpi_i,
            full=False,
        )
        return page.get_text("text", textpage=tp) or ""
    return _ocr_page_rapidocr(page, dpi_i)
