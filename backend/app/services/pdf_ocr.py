"""Optional OCR for image-only PDF pages via PyMuPDF's Tesseract bridge.

Tesseract (Apache-2.0) is a system package, not a Python dependency. When it is
missing, callers keep native text and report which pages could not be read.
"""

from __future__ import annotations

import shutil

from app.core.config import settings


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


def ocr_available() -> bool:
    if not settings.RESUME_OCR_ENABLED or shutil.which("tesseract") is None:
        return False
    try:
        import pymupdf as fitz

        return bool(fitz.get_tessdata())
    except Exception:
        return False


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


def ocr_page_text(page, dpi: int | None = None) -> str:
    """OCR only the image regions; native text on the page is kept as-is."""
    tp = page.get_textpage_ocr(
        language=settings.RESUME_OCR_LANG,
        dpi=int(dpi or settings.RESUME_OCR_DPI),
        full=False,
    )
    return page.get_text("text", textpage=tp) or ""
