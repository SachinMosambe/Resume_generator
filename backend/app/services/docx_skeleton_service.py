"""Fill a cloned DOCX company template with composed candidate content."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from app.core.logging import logger
from app.models.format_schema import normalize_format_metadata
from app.services.doc_converter import DocConversionError, convert_doc_to_docx


def render_from_docx_skeleton(
    template_path: Path,
    document: dict[str, Any],
    metadata: dict[str, Any] | None,
    *,
    source_type: str = "docx",
) -> bytes | None:
    """
    Clone a DOCX (or converted DOC) skeleton: keep headers/footers/styles,
    clear body sample content, inject composed resume content.
    Returns None to signal caller should fall back to schema renderer.
    """
    try:
        from docx import Document
        from docx.shared import Pt, RGBColor
        from docx.oxml.ns import qn
        from io import BytesIO
    except ImportError:
        return None

    path = Path(template_path)
    if not path.exists():
        return None

    work_path = path
    tmp_converted: Path | None = None
    if source_type == "doc" or path.suffix.lower() == ".doc":
        try:
            tmp_converted = convert_doc_to_docx(path, output_dir=path.parent)
            work_path = tmp_converted
        except DocConversionError as exc:
            logger.warning("skeleton_doc_convert_failed", error=str(exc))
            return None

    if work_path.suffix.lower() != ".docx":
        return None

    metadata = normalize_format_metadata(metadata)
    styling = metadata.get("styling") or {}
    font_family = str(styling.get("font_family") or "Calibri")
    body_size = float(styling.get("font_size_body") or 11)
    header_size = float(styling.get("font_size_header") or 12)
    name_size = float(styling.get("font_size_name") or 20)
    color_text = _rgb(styling.get("color_text"), (0, 0, 0))
    color_muted = _rgb(styling.get("color_muted"), (0x33, 0x33, 0x33))
    space_after = float(styling.get("space_after_para") or 6)

    try:
        doc = Document(str(work_path))
    except Exception as exc:
        logger.warning("skeleton_open_failed", error=str(exc))
        return None

    # Clear body paragraphs/tables but keep section properties + headers/footers.
    _clear_body(doc)

    try:
        normal = doc.styles["Normal"]
        normal.font.name = font_family
        normal.font.size = Pt(body_size)
        normal._element.rPr.rFonts.set(qn("w:eastAsia"), font_family)
    except Exception:
        pass

    header = document.get("header") or {}
    name = str(header.get("name") or "Candidate").strip() or "Candidate"
    name_para = doc.add_paragraph()
    name_para.paragraph_format.space_after = Pt(2)
    name_run = name_para.add_run(name)
    name_run.bold = True
    name_run.font.name = font_family
    name_run.font.size = Pt(name_size)
    name_run.font.color.rgb = color_text

    contact = [str(c).strip() for c in (header.get("contact") or []) if str(c).strip()]
    if contact:
        contact_para = doc.add_paragraph()
        contact_para.paragraph_format.space_after = Pt(space_after)
        contact_run = contact_para.add_run("  |  ".join(contact))
        contact_run.font.name = font_family
        contact_run.font.size = Pt(max(9.5, body_size - 0.5))
        contact_run.font.color.rgb = color_muted

    for section in document.get("sections") or []:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "").strip()
        if title:
            title_para = doc.add_paragraph()
            title_run = title_para.add_run(title.upper().rstrip(":"))
            title_run.bold = True
            title_run.font.name = font_family
            title_run.font.size = Pt(header_size)
            title_run.font.color.rgb = color_text
            title_para.paragraph_format.space_before = Pt(12)
            title_para.paragraph_format.space_after = Pt(space_after)
            _apply_bottom_border(title_para)

        content = section.get("content")
        stype = str(section.get("type") or "").lower()
        if not content:
            continue
        if stype == "text":
            p = doc.add_paragraph()
            run = p.add_run(str(content))
            run.font.name = font_family
            run.font.size = Pt(body_size)
            run.font.color.rgb = color_text
            p.paragraph_format.space_after = Pt(space_after)
        elif stype == "skills":
            _add_skills(doc, content, font_family, body_size, color_text)
        elif stype in {"experience", "projects", "education"}:
            for item in content if isinstance(content, list) else [content]:
                _add_record(doc, item, font_family, body_size, color_text, color_muted, space_after)
        else:
            items = content if isinstance(content, list) else [content]
            for item in items:
                text = str(item or "").strip()
                if not text:
                    continue
                p = doc.add_paragraph(style="List Bullet")
                run = p.add_run(text)
                run.font.name = font_family
                run.font.size = Pt(body_size)
                run.font.color.rgb = color_text

    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    result = buffer.read()

    if tmp_converted and tmp_converted.exists() and tmp_converted != path:
        try:
            # Only delete temp conversions created in a temp dir pattern.
            if "tmp" in str(tmp_converted).lower() or tempfile.gettempdir() in str(tmp_converted):
                tmp_converted.unlink(missing_ok=True)
        except Exception:
            pass

    return result if result else None


def _rgb(value: Any, default: tuple[int, int, int]) -> Any:
    from docx.shared import RGBColor
    from app.models.format_schema import parse_hex_rgb

    try:
        return RGBColor(*parse_hex_rgb(str(value or "")))
    except Exception:
        return RGBColor(*default)


def _clear_body(doc: Any) -> None:
    from docx.oxml.ns import qn

    body = doc.element.body
    # Remove paragraphs and tables; keep sectPr at the end.
    for child in list(body):
        if child.tag == qn("w:sectPr"):
            continue
        body.remove(child)


def _apply_bottom_border(paragraph: Any) -> None:
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    p = paragraph._p
    p_pr = p.get_or_add_pPr()
    existing = p_pr.find(qn("w:pBdr"))
    if existing is not None:
        p_pr.remove(existing)
    p_bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "000000")
    p_bdr.append(bottom)
    p_pr.append(p_bdr)


def _add_skills(doc: Any, content: Any, font_family: str, body_size: float, color: Any) -> None:
    from docx.shared import Pt

    if isinstance(content, dict):
        for category, skill_list in content.items():
            skills = [str(s).strip() for s in (skill_list or []) if str(s).strip()]
            if not skills:
                continue
            p = doc.add_paragraph()
            cat = p.add_run(f"{category}: ")
            cat.bold = True
            cat.font.name = font_family
            cat.font.size = Pt(body_size)
            cat.font.color.rgb = color
            rest = p.add_run(", ".join(skills))
            rest.font.name = font_family
            rest.font.size = Pt(body_size)
            rest.font.color.rgb = color
        return
    skills = [str(s).strip() for s in (content if isinstance(content, list) else [content]) if str(s).strip()]
    if skills:
        p = doc.add_paragraph()
        run = p.add_run(", ".join(skills))
        run.font.name = font_family
        run.font.size = Pt(body_size)
        run.font.color.rgb = color


def _add_record(
    doc: Any,
    item: Any,
    font_family: str,
    body_size: float,
    color_text: Any,
    color_muted: Any,
    space_after: float,
) -> None:
    from docx.shared import Pt

    if not isinstance(item, dict):
        text = str(item or "").strip()
        if text:
            p = doc.add_paragraph()
            run = p.add_run(text)
            run.font.name = font_family
            run.font.size = Pt(body_size)
            run.font.color.rgb = color_text
        return

    title = str(
        item.get("title")
        or item.get("role")
        or item.get("degree")
        or item.get("name")
        or ""
    ).strip()
    company = str(
        item.get("company")
        or item.get("institution")
        or item.get("organization")
        or ""
    ).strip()
    dates = str(item.get("duration") or item.get("dates") or item.get("year") or "").strip()
    bullets = item.get("description") or item.get("bullets") or item.get("achievements") or []

    if company or title:
        line = doc.add_paragraph()
        line.paragraph_format.space_before = Pt(6)
        line.paragraph_format.space_after = Pt(0)
        primary = company or title
        run = line.add_run(primary)
        run.bold = True
        run.font.name = font_family
        run.font.size = Pt(body_size)
        run.font.color.rgb = color_text
        if dates:
            date_run = line.add_run(f"  {dates}")
            date_run.font.name = font_family
            date_run.font.size = Pt(body_size)
            date_run.font.color.rgb = color_muted
    if company and title and company != title:
        role = doc.add_paragraph()
        role.paragraph_format.space_after = Pt(2)
        role_run = role.add_run(title)
        role_run.italic = True
        role_run.font.name = font_family
        role_run.font.size = Pt(body_size)
        role_run.font.color.rgb = color_text

    if isinstance(bullets, str):
        bullets = [bullets]
    for bullet in bullets or []:
        text = str(bullet or "").strip()
        if not text:
            continue
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.space_after = Pt(2)
        run = p.add_run(text)
        run.font.name = font_family
        run.font.size = Pt(body_size)
        run.font.color.rgb = color_text
