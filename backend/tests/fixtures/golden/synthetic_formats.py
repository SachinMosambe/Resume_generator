"""Synthetic, anonymized client-format templates for CI.

The real ``Capgemini-Format.docx`` carries a real candidate's resume and is never
committed. ``build_synthetic_capgemini_docx`` rebuilds only the *style contract* of that
format with placeholder text: right-aligned name, ``Avenir 45`` font family on every run,
and the heading order Professional Summary / Skills Profile / Professional Experience /
Summary of Projects / Education.

Font note: ``Avenir 45`` is a font family *name* written into the run properties. The font
does not need to be installed for the style assertions (they read the DOCX XML), so CI on
plain Ubuntu behaves identically; a viewer without the font falls back to its default.
"""

from __future__ import annotations

import io

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt

CAPGEMINI_FONT = "Avenir 45"
CAPGEMINI_SECTIONS = [
    "Professional Summary",
    "Skills Profile",
    "Professional Experience",
    "Summary of Projects",
    "Education",
]


def _run(paragraph, text: str, *, size: float, bold: bool = False):
    run = paragraph.add_run(text)
    run.font.name = CAPGEMINI_FONT
    run.font.size = Pt(size)
    run.bold = bold
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), CAPGEMINI_FONT)
    return run


def build_synthetic_capgemini_docx() -> bytes:
    """Return a minimal Capgemini-style ClientFormat DOCX (no real candidate text)."""
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = CAPGEMINI_FONT
    normal.font.size = Pt(10.5)

    name = doc.add_paragraph()
    name.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _run(name, "Sample Candidate", size=14, bold=True)

    for heading in CAPGEMINI_SECTIONS:
        para = doc.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        _run(para, heading, size=12, bold=True)
        if heading == "Professional Experience":
            body = doc.add_paragraph()
            _run(body, "Sample Company\t2020 - 2022", size=10.5, bold=True)
            title = doc.add_paragraph()
            _run(title, "Sample Role", size=10.5)
            bullet = doc.add_paragraph()
            _run(bullet, "Placeholder responsibility text.", size=10.5)
        else:
            body = doc.add_paragraph()
            _run(body, "Placeholder text.", size=10.5)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
