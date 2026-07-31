"""Deterministic format + completeness gates for generated resumes."""

from __future__ import annotations

from typing import Any

from app.agent_pipeline.state import FormatSpec, ResumeKB, norm_text
from app.models.format_schema import normalize_format_metadata


def _section_type(section: dict[str, Any]) -> str:
    stype = str(section.get("type") or "").strip().lower()
    title = str(section.get("title") or "").strip().lower()
    # Composed docs often use type "text" for summary — prefer title cues.
    for key in (
        "summary",
        "skills",
        "experience",
        "projects",
        "education",
        "certifications",
        "achievements",
        "languages",
    ):
        if key in title or key in stype:
            return key
    if stype and stype not in {"text", "bullets", "list"}:
        return stype
    return title or stype


def document_section_types(document: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for section in document.get("sections") or []:
        if not isinstance(section, dict):
            continue
        stype = _section_type(section)
        if stype:
            out.append(stype)
    return out


def validate_format_document(
    document: dict[str, Any],
    spec: FormatSpec | dict[str, Any] | None,
    kb: ResumeKB | None = None,
) -> list[dict[str, str]]:
    """
    Return findings with severity critical|warn.

    Checks: section order, required sections, labels, styling bounds, header completeness,
    and role-identity presence when kb is provided.
    """
    findings: list[dict[str, str]] = []
    if isinstance(spec, FormatSpec):
        metadata = normalize_format_metadata(spec.metadata)
        expected_order = [s for s in spec.section_order if s != "header"]
        labels = dict(spec.labels or {})
    else:
        metadata = normalize_format_metadata(spec if isinstance(spec, dict) else {})
        expected_order = [
            s
            for s in (metadata.get("section_order") or metadata.get("sections") or [])
            if str(s).lower() != "header"
        ]
        labels = dict(metadata.get("section_labels") or metadata.get("field_mapping") or {})

    actual = document_section_types(document)
    actual_set = set(actual)

    # Section order: relative order of overlapping sections must match expected.
    expected_present = [s for s in expected_order if s in actual_set]
    actual_in_expected = [s for s in actual if s in set(expected_order)]
    if expected_present and actual_in_expected != expected_present:
        findings.append(
            {
                "section": "structure",
                "severity": "critical",
                "issue": (
                    f"Section order mismatch. expected={expected_present} "
                    f"actual={actual_in_expected}"
                )[:200],
            }
        )

    required = [
        s
        for s in (metadata.get("completeness_contract") or ["summary", "skills", "experience", "education"])
        if str(s).strip()
    ]
    for req in required:
        if req not in actual_set:
            findings.append(
                {
                    "section": req,
                    "severity": "critical",
                    "issue": f"Required section '{req}' missing from composed resume",
                }
            )

    # Labels: when provided, titles should match (case-insensitive, ignoring trailing colon).
    if labels:
        for section in document.get("sections") or []:
            if not isinstance(section, dict):
                continue
            stype = _section_type(section)
            expected_label = labels.get(stype)
            if not expected_label:
                continue
            title = str(section.get("title") or "").strip().rstrip(":").strip()
            exp = str(expected_label).strip().rstrip(":").strip()
            if title and exp and norm_text(title) != norm_text(exp):
                findings.append(
                    {
                        "section": stype,
                        "severity": "warn",
                        "issue": f"Section label '{title}' differs from format '{exp}'",
                    }
                )

    styling = metadata.get("styling") or {}
    for key, lo, hi in (
        ("font_size_body", 8, 16),
        ("font_size_header", 9, 24),
        ("font_size_name", 12, 36),
    ):
        try:
            size = float(styling.get(key) or 0)
        except (TypeError, ValueError):
            size = 0
        if size and (size < lo or size > hi):
            findings.append(
                {
                    "section": "styling",
                    "severity": "warn",
                    "issue": f"{key}={size} outside sane range {lo}-{hi}",
                }
            )
    if not styling.get("font_family"):
        findings.append(
            {
                "section": "styling",
                "severity": "warn",
                "issue": "font_family missing from format styling",
            }
        )

    header = document.get("header") if isinstance(document.get("header"), dict) else {}
    name = str(header.get("name") or "").strip()
    if not name or name.lower() in {"candidate", "unknown"}:
        findings.append(
            {
                "section": "header",
                "severity": "critical",
                "issue": "Candidate name missing from composed resume header",
            }
        )
    contact = header.get("contact") or []
    if any(str(c).strip() for c in contact):
        findings.append(
            {
                "section": "header",
                "severity": "warn",
                "issue": "Personal contact details should not appear on client resume (name only)",
            }
        )

    if kb is not None:
        findings.extend(_check_role_identities(document, kb))

    return findings


def _check_role_identities(document: dict[str, Any], kb: ResumeKB) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    expected = kb.role_identities()
    if not expected:
        return findings

    found: list[tuple[str, str, str]] = []
    for section in document.get("sections") or []:
        if not isinstance(section, dict):
            continue
        if _section_type(section) != "experience":
            continue
        for role in section.get("content") or []:
            if not isinstance(role, dict):
                continue
            found.append(
                (
                    str(role.get("company") or ""),
                    str(role.get("title") or ""),
                    str(role.get("duration") or role.get("dates") or ""),
                )
            )

    found_blob = " ".join(norm_text(f"{c} {t} {d}") for c, t, d in found)
    missing = 0
    for company, title, duration in expected:
        key = norm_text(f"{company} {title}")
        if key and key not in found_blob and norm_text(company) not in found_blob:
            missing += 1
    if missing:
        findings.append(
            {
                "section": "experience",
                "severity": "critical",
                "issue": f"{missing} role identities from source missing in composed resume",
            }
        )
    return findings


def has_critical_findings(findings: list[dict[str, str]]) -> bool:
    return any(str(f.get("severity")) == "critical" for f in findings)


def format_findings_message(findings: list[dict[str, str]]) -> str:
    criticals = [f for f in findings if str(f.get("severity")) == "critical"]
    if not criticals:
        return ""
    parts = [str(f.get("issue") or "format validation failed") for f in criticals[:5]]
    return "; ".join(parts)
