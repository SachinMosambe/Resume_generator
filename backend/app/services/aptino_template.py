"""Built-in Aptino default resume template (logo header + company footer + layout)."""

from __future__ import annotations

import base64
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

# Stable id used when generating with the built-in Aptino template (no DB row required).
APTINO_DEFAULT_FORMAT_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
APTINO_TEMPLATE_ID = "aptino_default"

APTINO_COMPANY_NAME = "Aptino Inc."
APTINO_COMPANY_ADDRESS = "222 West Las Colinas Blvd, Suite 1651 Irving, TX 75039."
APTINO_COMPANY_CONTACT = "Email: info@aptino.com  www.aptino.com"

APTINO_SECTION_ORDER = [
    "header",
    "summary",
    "skills",
    "experience",
    "projects",
    "education",
    "certifications",
    "achievements",
    "languages",
]

_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
_LOGO_CANDIDATES = (
    _ASSETS_DIR / "aptino_logo_transparent.png",
    _ASSETS_DIR / "aptino_logo.png",
)


@lru_cache(maxsize=1)
def _load_aptino_logo_data_url() -> str | None:
    for path in _LOGO_CANDIDATES:
        if not path.exists():
            continue
        raw = path.read_bytes()
        if len(raw) < 300:
            continue
        b64 = base64.b64encode(raw).decode("ascii")
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        return f"data:{mime};base64,{b64}"
    return None


def get_aptino_company_footer_lines() -> list[str]:
    """Company sign shown in the DOCX footer on every page."""
    return [APTINO_COMPANY_NAME, APTINO_COMPANY_ADDRESS, APTINO_COMPANY_CONTACT]


# Backward-compatible alias (older code referred to these as "company header").
def get_aptino_company_header_lines() -> list[str]:
    return get_aptino_company_footer_lines()


def get_aptino_default_metadata() -> dict[str, Any]:
    """Return format metadata used as the default Aptino resume template."""
    from app.models.format_schema import normalize_format_metadata

    logos: list[dict[str, Any]] = []
    logo_data = _load_aptino_logo_data_url()
    if logo_data:
        logos.append(
            {
                "data": logo_data,
                "position": "top_right",
                "source": "aptino_default_header",
            }
        )

    company_sign = {
        "name": APTINO_COMPANY_NAME,
        "address": APTINO_COMPANY_ADDRESS,
        "contact": APTINO_COMPANY_CONTACT,
        "lines": get_aptino_company_footer_lines(),
    }

    field_mapping = {
        "summary": "PROFESSIONAL SUMMARY",
        "skills": "TECHNICAL SKILLS",
        "experience": "PROFESSIONAL EXPERIENCE",
        "projects": "PROJECTS",
        "education": "EDUCATION",
        "certifications": "CERTIFICATIONS",
        "achievements": "ACHIEVEMENTS",
        "languages": "LANGUAGES",
    }

    return normalize_format_metadata(
        {
            "template_id": APTINO_TEMPLATE_ID,
            "template_name": "Aptino Default",
            "source_type": "aptino_builtin",
            "source_filename": "aptino_default",
            "extraction_confidence": "high",
            "extraction_notes": "Built-in Aptino ATS template",
            "sections": [s for s in APTINO_SECTION_ORDER if s != "header"],
            "section_order": list(APTINO_SECTION_ORDER),
            "styling": {
                "font_family": "Calibri",
                "font_size_body": 11,
                "font_size_header": 12,
                "font_size_name": 20,
                "color_text": "#000000",
                "color_muted": "#333333",
                "margin_inches": 0.7,
                "line_spacing": 1.0,
                "space_after_para": 6.0,
                "layout": "single_column_ats",
            },
            "layout": {
                "type": "single_column",
                "name_position": "top_left",
                "logo_position": "top_right",
                "company_footer": "center",
                "dates": "right_aligned",
                "section_dividers": True,
            },
            "company_footer": company_sign,
            "company_header": company_sign,
            "field_mapping": field_mapping,
            "section_labels": dict(field_mapping),
            "completeness_contract": ["summary", "skills", "experience", "education"],
            "logo_count": len(logos),
            "logos": logos,
            "preview_text": (
                "Section order: PROFESSIONAL SUMMARY → TECHNICAL SKILLS → PROFESSIONAL EXPERIENCE → "
                "PROJECTS → EDUCATION → CERTIFICATIONS → ACHIEVEMENTS → LANGUAGES || "
                "Template headings: PROFESSIONAL SUMMARY | TECHNICAL SKILLS | PROFESSIONAL EXPERIENCE | "
                "PROJECTS | EDUCATION | CERTIFICATIONS"
            ),
        }
    )


def build_aptino_client_format(client_id: str) -> Any:
    """Lightweight ClientFormat stand-in for the built-in Aptino template."""
    from types import SimpleNamespace

    return SimpleNamespace(
        id=APTINO_DEFAULT_FORMAT_ID,
        client_id=client_id or "Aptino",
        format_template_path="builtin://aptino_default",
        format_metadata=get_aptino_default_metadata(),
        is_active=True,
    )


def is_aptino_template(metadata: dict[str, Any] | None) -> bool:
    if not metadata:
        return False
    return (
        str(metadata.get("template_id") or "").lower() == APTINO_TEMPLATE_ID
        or str(metadata.get("source_type") or "").lower() == "aptino_builtin"
    )
