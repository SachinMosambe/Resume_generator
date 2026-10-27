"""Source blocks: ordered pieces of an extracted document with provenance.

The parser still consumes plain text (``blocks_to_text``), but extraction keeps
where each line came from (body, table, header, footer, text box, OCR) so later
checks can account for every block.
"""
from __future__ import annotations

from dataclasses import dataclass, field

_BULLET_PREFIXES = ("•", "-", "*", "▪", "●", "◦", "■")


@dataclass
class SourceBlock:
    id: str
    text: str
    origin: str  # body | table | header | footer | textbox | ocr | link
    page: int | None = None  # None where the format has no reliable pages (DOCX)
    bbox: tuple[float, float, float, float] | None = None
    style: str | None = None
    is_list: bool = False
    bold: bool = False
    font_size: float | None = None
    links: list[str] = field(default_factory=list)


def blocks_to_text(blocks: list[SourceBlock]) -> str:
    """Flatten blocks to the line-oriented text the resume parser expects."""
    lines: list[str] = []
    for block in blocks:
        text = block.text.strip()
        if not text:
            continue
        if block.is_list and not text.startswith(_BULLET_PREFIXES):
            text = f"• {text}"
        lines.append(text)
        for url in block.links:
            if url and url not in text:
                lines.append(url)
    return "\n".join(lines)
