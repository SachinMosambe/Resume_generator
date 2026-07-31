"""Canonical FormatSchema for company resume templates (PDF/DOC/DOCX)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


CANONICAL_BODY_SECTIONS = [
    "summary",
    "skills",
    "experience",
    "projects",
    "education",
    "certifications",
    "achievements",
    "languages",
]

DEFAULT_REQUIRED_SECTIONS = ["summary", "skills", "experience", "education"]


@dataclass
class FormatStyling:
    font_family: str = "Calibri"
    font_size_body: float = 11.0
    font_size_header: float = 12.0
    font_size_name: float = 20.0
    color_text: str = "#000000"
    color_muted: str = "#333333"
    margin_inches: float = 0.65
    line_spacing: float = 1.0
    space_after_para: float = 6.0
    layout: str = "single_column_ats"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FormatSource:
    filename: str = ""
    source_type: str = "unknown"  # pdf | doc | docx | aptino_builtin
    confidence: str = "high"  # high | medium | low
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FormatSchema:
    """Normalized company-format contract used by extraction, render, and validation."""

    template_id: str = ""
    template_name: str = ""
    sections: list[str] = field(default_factory=lambda: list(CANONICAL_BODY_SECTIONS))
    section_order: list[str] = field(default_factory=lambda: list(CANONICAL_BODY_SECTIONS))
    section_labels: dict[str, str] = field(default_factory=dict)
    field_mapping: dict[str, str] = field(default_factory=dict)
    styling: FormatStyling = field(default_factory=FormatStyling)
    layout: dict[str, Any] = field(default_factory=dict)
    company_header: dict[str, Any] | None = None
    company_footer: dict[str, Any] | None = None
    logos: list[dict[str, Any]] = field(default_factory=list)
    completeness_contract: list[str] = field(default_factory=lambda: list(DEFAULT_REQUIRED_SECTIONS))
    source: FormatSource = field(default_factory=FormatSource)
    preview_text: str = ""
    logo_count: int = 0
    # Extra passthrough keys (template_id aliases, etc.)
    extras: dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        """Dict shape consumed by existing generation / FormatSpec paths."""
        body_sections = [s for s in self.section_order if s != "header"]
        if not body_sections:
            body_sections = list(self.sections) or list(CANONICAL_BODY_SECTIONS)

        labels = dict(self.section_labels or {})
        mapping = dict(self.field_mapping or {})
        if not mapping and labels:
            mapping = dict(labels)
        if not labels and mapping:
            labels = dict(mapping)

        meta: dict[str, Any] = {
            "template_id": self.template_id,
            "template_name": self.template_name,
            "source_filename": self.source.filename,
            "source_type": self.source.source_type,
            "extraction_confidence": self.source.confidence,
            "extraction_notes": self.source.notes,
            "sections": body_sections,
            "section_order": list(self.section_order) or body_sections,
            "section_labels": labels,
            "field_mapping": mapping,
            "styling": self.styling.to_dict(),
            "layout": dict(self.layout or {}),
            "company_header": self.company_header,
            "company_footer": self.company_footer,
            "logos": list(self.logos or []),
            "logo_count": int(self.logo_count or len(self.logos or [])),
            "completeness_contract": list(self.completeness_contract or DEFAULT_REQUIRED_SECTIONS),
            "preview_text": self.preview_text,
            "header_text": "",
            "footer_text": "",
        }
        for key, value in (self.extras or {}).items():
            if key not in meta or meta[key] in (None, "", [], {}):
                meta[key] = value
        return meta


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_hex_color(value: Any, default: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return default
    if not raw.startswith("#"):
        raw = f"#{raw}"
    if len(raw) == 4:  # #RGB
        raw = f"#{raw[1]*2}{raw[2]*2}{raw[3]*2}"
    if len(raw) != 7:
        return default
    try:
        int(raw[1:], 16)
    except ValueError:
        return default
    return raw.upper()


def _normalize_section_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        # Reject legacy index-only section_order (0, 1, 2, ...)
        if isinstance(item, int):
            continue
        name = str(item or "").strip().lower()
        if not name or name.isdigit() or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def normalize_format_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize arbitrary extraction/Aptino metadata into FormatSchema dict form."""
    raw = dict(metadata or {})
    sections = _normalize_section_list(raw.get("sections"))
    order = _normalize_section_list(raw.get("section_order"))
    if not order:
        order = list(sections) if sections else list(CANONICAL_BODY_SECTIONS)
    if not sections:
        sections = [s for s in order if s != "header"] or list(CANONICAL_BODY_SECTIONS)

    styling_raw = dict(raw.get("styling") or {})
    styling = FormatStyling(
        font_family=str(styling_raw.get("font_family") or "Calibri"),
        font_size_body=_as_float(styling_raw.get("font_size_body"), 11.0),
        font_size_header=_as_float(styling_raw.get("font_size_header"), 12.0),
        font_size_name=_as_float(styling_raw.get("font_size_name"), 20.0),
        color_text=_normalize_hex_color(styling_raw.get("color_text"), "#000000"),
        color_muted=_normalize_hex_color(styling_raw.get("color_muted"), "#333333"),
        margin_inches=_as_float(styling_raw.get("margin_inches"), 0.65),
        line_spacing=_as_float(styling_raw.get("line_spacing"), 1.0),
        space_after_para=_as_float(styling_raw.get("space_after_para"), 6.0),
        layout=str(styling_raw.get("layout") or "single_column_ats"),
    )

    labels = raw.get("section_labels") if isinstance(raw.get("section_labels"), dict) else {}
    mapping = raw.get("field_mapping") if isinstance(raw.get("field_mapping"), dict) else {}
    labels = {str(k).lower(): str(v) for k, v in labels.items() if str(k).strip()}
    mapping = {str(k).lower(): str(v) for k, v in mapping.items() if str(k).strip()}

    contract = _normalize_section_list(raw.get("completeness_contract"))
    if not contract:
        contract = [s for s in DEFAULT_REQUIRED_SECTIONS if s in sections or s in order]
        if not contract:
            contract = list(DEFAULT_REQUIRED_SECTIONS)

    source_type = str(raw.get("source_type") or "").strip().lower() or "unknown"
    confidence = str(raw.get("extraction_confidence") or "").strip().lower()
    if not confidence:
        if source_type in {"docx", "doc", "aptino_builtin"}:
            confidence = "high"
        elif source_type == "pdf":
            confidence = "medium"
        else:
            confidence = "low"

    layout = dict(raw.get("layout") or {})
    if not layout.get("type"):
        layout["type"] = "single_column"

    schema = FormatSchema(
        template_id=str(raw.get("template_id") or ""),
        template_name=str(raw.get("template_name") or ""),
        sections=sections,
        section_order=order,
        section_labels=labels,
        field_mapping=mapping,
        styling=styling,
        layout=layout,
        company_header=raw.get("company_header") if isinstance(raw.get("company_header"), dict) else None,
        company_footer=raw.get("company_footer") if isinstance(raw.get("company_footer"), dict) else None,
        logos=list(raw.get("logos") or []) if isinstance(raw.get("logos"), list) else [],
        completeness_contract=contract,
        source=FormatSource(
            filename=str(raw.get("source_filename") or ""),
            source_type=source_type,
            confidence=confidence,
            notes=str(raw.get("extraction_notes") or ""),
        ),
        preview_text=str(raw.get("preview_text") or ""),
        logo_count=int(raw.get("logo_count") or len(raw.get("logos") or []) or 0),
        extras={
            k: v
            for k, v in raw.items()
            if k
            not in {
                "template_id",
                "template_name",
                "source_filename",
                "source_type",
                "extraction_confidence",
                "extraction_notes",
                "sections",
                "section_order",
                "section_labels",
                "field_mapping",
                "styling",
                "layout",
                "company_header",
                "company_footer",
                "logos",
                "logo_count",
                "completeness_contract",
                "preview_text",
                "header_text",
                "footer_text",
            }
        },
    )
    return schema.to_metadata()


def parse_hex_rgb(color: str) -> tuple[int, int, int]:
    """Return (r, g, b) for a #RRGGBB color; falls back to black."""
    normalized = _normalize_hex_color(color, "#000000")
    return (
        int(normalized[1:3], 16),
        int(normalized[3:5], 16),
        int(normalized[5:7], 16),
    )
