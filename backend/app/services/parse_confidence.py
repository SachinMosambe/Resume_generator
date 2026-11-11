"""Parse confidence scored against independent source evidence (no resume text is logged)."""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.services.source_evidence import detect_employment_evidence

_TECH_NAMES = {"react native", "react native."}

_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_PRESENT = re.compile(r"(?i)\b(?:present|current|now|till date|to date|ongoing)\b")
_MONTH_YEAR = re.compile(r"(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*,?\s*((?:19|20)\d{2})\b")
_NUM_MONTH_YEAR = re.compile(r"\b(0?[1-9]|1[0-2])\s*/\s*((?:19|20)\d{2})\b")
_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")
# A company field that is only a date / date range is a misparsed header, not an employer.
_DATE_ONLY_COMPANY = re.compile(
    r"(?i)^[\s\W]*(?:(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*,?\s*)?(?:19|20)\d{2}|"
    r"\d{1,2}\s*/\s*(?:19|20)\d{2}|present|current|now)(?:[\s\W]+(?:to|and)?[\s\W]*"
    r"(?:(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*,?\s*)?(?:19|20)\d{2}|"
    r"\d{1,2}\s*/\s*(?:19|20)\d{2}|present|current|now))*[\s\W]*$"
)
# Concurrent employment shorter than this is common (handover, part-time) and not flagged.
_MIN_OVERLAP_MONTHS = 6


def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _month_index(year: int, month: int) -> int:
    return year * 12 + (month - 1)


def _points(text: str) -> list[int]:
    """Month indexes of the date tokens in ``text`` in reading order ('Present' = today)."""
    found: list[tuple[int, int]] = []
    for m in _MONTH_YEAR.finditer(text):
        found.append((m.start(), _month_index(int(m.group(2)), _MONTHS[m.group(1).lower()[:3]])))
    for m in _NUM_MONTH_YEAR.finditer(text):
        found.append((m.start(), _month_index(int(m.group(2)), int(m.group(1)))))
    covered = [(m.start(), m.end()) for m in _MONTH_YEAR.finditer(text)] + [
        (m.start(), m.end()) for m in _NUM_MONTH_YEAR.finditer(text)
    ]
    for m in _YEAR.finditer(text):
        if not any(s <= m.start() < e for s, e in covered):
            found.append((m.start(), _month_index(int(m.group(1)), 1)))
    for m in _PRESENT.finditer(text):
        today = date.today()
        found.append((m.start(), _month_index(today.year, today.month)))
    return [p for _pos, p in sorted(found)]


def _span(duration: Any) -> tuple[int, int] | None:
    pts = _points(str(duration or ""))
    if len(pts) < 2:
        return None
    start, end = pts[0], pts[1]
    return (start, end) if end >= start else None


def _has_contained_concurrent_roles(roles: list[dict[str, Any]]) -> bool:
    """True when a role's date range sits inside another employer's range for months."""
    spans = [
        (_norm(r.get("company")), s)
        for r in roles
        if (s := _span(r.get("duration") or r.get("dates"))) is not None
    ]
    for i, (comp_a, (a0, a1)) in enumerate(spans):
        for comp_b, (b0, b1) in spans[i + 1 :]:
            if not comp_a or not comp_b or comp_a == comp_b:
                continue
            contained = (a0 <= b0 and b1 <= a1) or (b0 <= a0 and a1 <= b1)
            if contained and min(a1, b1) - max(a0, b0) >= _MIN_OVERLAP_MONTHS:
                return True
    return False


def _garbled_role_identity(role: dict[str, Any]) -> bool:
    """Employer is a date, or just repeats the job title: the header was misread."""
    company = str(role.get("company") or "").strip()
    title = str(role.get("title") or "").strip()
    if not company:
        return False
    if _DATE_ONLY_COMPANY.match(company):
        return True
    return bool(title) and _norm(company) == _norm(title)


def score_parse(data: dict[str, Any], source_text: str) -> dict[str, Any]:
    evidence = detect_employment_evidence(source_text)
    roles = [r for r in (data.get("experience") or []) if isinstance(r, dict)]
    unassigned = data.get("unassigned_experience_bullets") or []
    reasons: list[str] = []
    empty_titles = sum(1 for r in roles if not (r.get("title") or "").strip())
    name = (data.get("name") or "").strip()
    confidence = 1.0
    if evidence.has_work_history and not roles and not unassigned:
        reasons.append("expected_experience_missing")
        confidence -= 0.5
    elif evidence.has_work_history and (not roles or unassigned):
        reasons.append("ambiguous_role_assignment")
        confidence -= 0.35 if not roles else 0.2
    if roles and empty_titles / max(1, len(roles)) >= 0.5:
        reasons.append("source_backed_titles_unresolved")
        confidence -= 0.25
    if not name or name.lower() in _TECH_NAMES:
        reasons.append("identity_ambiguous")
        confidence -= 0.2
    if any(_garbled_role_identity(r) for r in roles):
        reasons.append("role_identity_garbled")
        confidence -= 0.25
    if _has_contained_concurrent_roles(roles):
        reasons.append("overlapping_role_dates")
        confidence -= 0.15
    confidence = max(0.0, min(1.0, confidence))
    return {
        "confidence": confidence,
        "reasons": reasons,
        "llm_repaired": False,
        "employment_evidence": {
            "has_work_history": evidence.has_work_history,
            "reasons": evidence.reasons,
        },
    }
