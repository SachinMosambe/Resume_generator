"""Intake gate: reject uploads that are clearly not a resume, with an actionable reason.

The gate is deliberately conservative. A file is quarantined only when it carries
explicit non-resume document markers (certificate, I-94 / travel record, invoice...)
AND it lacks the structure of a resume. A sparse or education-only resume has resume
structure (section headings, dated roles, contact lines) and is never quarantined,
and text with no markers at all is always let through.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Kind -> patterns that identify the document type. Matched case-insensitively.
_MARKERS: dict[str, tuple[str, ...]] = {
    "certificate": (
        r"certificate\s+of\s+(?:completion|achievement|participation|attendance|appreciation|excellence"
        r"|training|registration|incorporation|merit)",
        r"this\s+(?:is\s+to\s+)?certif(?:ies|y)\s+that",
        r"is\s+hereby\s+awarded",
        r"has\s+successfully\s+completed\s+the\s+(?:course|program|training)",
    ),
    "travel_record": (
        r"\bi[-\s]?94\b",
        r"\bi[-\s]?797[a-z]?\b",
        r"travel\s+history",
        r"(?:arrival|departure)\s*(?:/|and)?\s*(?:arrival|departure)?\s+record",
        r"admit\s+until\s+date",
        r"class\s+of\s+admission",
        r"customs\s+and\s+border\s+protection",
        r"department\s+of\s+homeland\s+security",
        r"boarding\s+pass",
        r"passport\s+(?:number|no\.?)\b",
    ),
    "financial": (
        r"\binvoice\s*(?:#|no\.?|number)",
        r"\bbank\s+statement\b",
        r"\bpay\s*(?:stub|slip)\b",
        r"\bpayslip\b",
        r"\bamount\s+due\b",
        r"\bw-?2\s+wage\s+and\s+tax\b",
    ),
}

_KIND_LABEL = {
    "certificate": "a certificate",
    "travel_record": "an immigration or travel record (for example an I-94)",
    "financial": "a financial document",
}

# A heading is a short line that is (almost) only the section name.
_HEADING_GROUPS: dict[str, tuple[str, ...]] = {
    "experience": (
        "experience", "work experience", "professional experience", "employment",
        "employment history", "work history", "career history", "relevant experience",
    ),
    "education": ("education", "academic background", "education and training", "academics"),
    "skills": ("skills", "technical skills", "core skills", "core competencies", "key skills", "skills and tools"),
    "summary": ("summary", "professional summary", "profile", "objective", "career objective", "about me"),
    "projects": ("projects", "key projects", "selected projects", "personal projects"),
    "certifications": ("certifications", "licenses and certifications", "licenses"),
}
_HEADING_LOOKUP = {name: group for group, names in _HEADING_GROUPS.items() for name in names}

_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATE_RANGE = re.compile(
    rf"(?i)\b(?:{_MONTH}\s+)?(?:19|20)\d{{2}}\s*(?:-|–|—|to)\s*(?:(?:{_MONTH}\s+)?(?:19|20)\d{{2}}|present|current|now)\b"
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)")
_BULLET = re.compile(r"^\s*[•\u2022\u25cf\u25aa\u25ba*\-–]\s+\S")

_TITLE_LINES = 8  # a document-type marker this close to the top names the document


@dataclass(frozen=True)
class IntakeAssessment:
    is_resume: bool
    reason_code: str | None = None  # certificate | travel_record | financial
    message: str | None = None
    resume_signals: int = 0


def _normalize_heading(line: str) -> str:
    lowered = (line or "").lower().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z ]+", " ", lowered).split())


def _resume_signals(text: str) -> int:
    """Count independent resume-structure signals (0..N)."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    headings = {
        _HEADING_LOOKUP[norm]
        for ln in lines
        if len(ln) <= 40 and (norm := _normalize_heading(ln)) in _HEADING_LOOKUP
    }
    signals = len(headings)
    if len(_DATE_RANGE.findall(text or "")) >= 1:
        signals += 1
    if _EMAIL.search(text or "") or _PHONE.search(text or ""):
        signals += 1
    if sum(1 for ln in lines if _BULLET.match(ln)) >= 2:
        signals += 1
    return signals


def _marker_hits(text: str) -> tuple[dict[str, int], dict[str, bool]]:
    """Per-kind marker counts, and whether a kind's marker appears near the top."""
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    top = "\n".join(lines[:_TITLE_LINES])
    counts: dict[str, int] = {}
    in_title: dict[str, bool] = {}
    for kind, patterns in _MARKERS.items():
        total = 0
        near_top = False
        for pat in patterns:
            rx = re.compile(pat, re.IGNORECASE)
            total += len(rx.findall(text or ""))
            near_top = near_top or bool(rx.search(top))
        if total:
            counts[kind] = total
            in_title[kind] = near_top
    return counts, in_title


def assess_resume_intake(text: str) -> IntakeAssessment:
    """Decide whether extracted text may proceed to resume generation.

    Quarantine requires BOTH: a non-resume marker (near the top of the document, or at
    least two marker hits) and weak resume structure (fewer than two resume signals).
    """
    counts, in_title = _marker_hits(text)
    signals = _resume_signals(text)
    if not counts:
        return IntakeAssessment(True, resume_signals=signals)

    kind = max(counts, key=lambda k: (in_title.get(k, False), counts[k]))
    marker_strong = in_title.get(kind, False) or counts[kind] >= 2
    # A real resume that merely mentions "I-94" or lists a certificate still has structure.
    if marker_strong and signals < 2:
        message = (
            f"This file looks like {_KIND_LABEL[kind]}, not a resume, so no document was generated. "
            "Upload the candidate's resume (PDF, DOC, or DOCX) instead."
        )
        return IntakeAssessment(False, reason_code=kind, message=message, resume_signals=signals)
    return IntakeAssessment(True, resume_signals=signals)
