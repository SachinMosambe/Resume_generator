"""Mechanical source-vs-output check for generated resumes.

Compares normalized text presence only. A "passed" status means every checked source
field was found in the document, not that the document is semantically verified.

Warnings are structured ``{severity, code, message}`` dicts and recruiter-facing: they
carry counts and codes, never resume content.

* ``blocking`` findings (missing required facts, wrong-job bullets, missing experience)
  move the status to ``needs_review`` (or ``failed`` for core-field loss / wrong jobs).
* ``info`` findings (reflowed source lines, OCR used, policy omissions) are shown to the
  recruiter but never change the status on their own.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.services.docx_layout import clean_education_title_dates

# Below this share of a core field found in the output, the document is marked failed.
_FAIL_RATIO = 0.5
_CORE_CHECKS = ("companies", "titles", "dates", "bullets")

BLOCKING = "blocking"
INFO = "info"

# Heading anchors (company + title) must sit this close together, in normalized chars.
_HEADING_WINDOW = 200
_MIN_ROLE_BULLET_WORDS = 4


@dataclass
class IntegrityReport:
    status: str
    checks: dict[str, dict] = field(default_factory=dict)
    warnings: list[dict[str, str]] = field(default_factory=list)


def _finding(severity: str, code: str, message: str) -> dict[str, str]:
    return {"severity": severity, "code": code, "message": message}


def warning_payload(report: IntegrityReport, limit: int = 10) -> list[dict[str, str]]:
    """Header-safe warnings; legacy string warnings are wrapped as objects."""
    out: list[dict[str, str]] = []
    for w in report.warnings[:limit]:
        if isinstance(w, dict):
            out.append(w)
        else:
            out.append(
                _finding(BLOCKING if report.status != "passed" else INFO, "legacy", str(w))
            )
    return out


def _norm(text: Any) -> str:
    text = re.sub(r"[\u2010-\u2015]", "-", str(text or "")).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _docx_text(data: bytes) -> str:
    doc = Document(io.BytesIO(data))
    parts: list[str] = []
    # Body order (paragraphs and tables interleaved) so positions reflect the page layout.
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            parts.append(Paragraph(child, doc).text)
        elif tag == "tbl":
            for row in Table(child, doc).rows:
                parts.extend(c.text for c in row.cells)
    for section in doc.sections:
        for part in (section.header, section.footer):
            parts.extend(p.text for p in part.paragraphs)
            for table in part.tables:
                for row in table.rows:
                    parts.extend(c.text for c in row.cells)
    return _norm("\n".join(parts))


def _education_needle(value: Any, hay: str) -> Any:
    """Use the rendered form when a heading crumb or month prefix was removed."""
    raw = _norm(value)
    if not raw or raw in hay:
        return value
    title, dates = clean_education_title_dates(str(value or ""), str(value or ""))
    for alt in (title, dates):
        if _norm(alt) and _norm(alt) in hay:
            return alt
    return value


def _check(name: str, expected: list[Any], hay: str, checks: dict, warnings: list[dict], label: str) -> None:
    items = list(dict.fromkeys(n for n in (_norm(x) for x in expected) if n))
    if not items:
        return
    missing = [x for x in items if x not in hay]
    checks[name] = {"ok": not missing, "expected": len(items), "found": len(items) - len(missing)}
    if missing:
        warnings.append(
            _finding(
                BLOCKING,
                f"{name}_missing",
                f"{len(missing)} of {len(items)} {label} from the source were not found in the output.",
            )
        )


_SKIP_SOURCE_LINE = re.compile(
    r"(?i)(@|https?://|www\.|linkedin|\d{3}[-.\s)]+\d{3}[-.\s]\d{4}|references available|"
    r"preferred|desired work|willing to relocate|work authorization|employment type|profile source|"
    r"profile downloaded|total experience|visa sponsorship|authorized to work|contract\s*-\s*corp|"
    r"gap\s*period|on-site or hybrid|contract to hire)"
)
_SOURCE_DATE = re.compile(
    r"(?i)\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d{4}|\b\d{1,2}/\d{4}\b|\b(?:19|20)\d{2}\s*[-–—]"
)
# Metrics whose digits must survive verbatim: percentages and currency amounts.
_METRIC = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?\s?[kmb]?\b|\b\d[\d,]*(?:\.\d+)?\s?%", re.IGNORECASE)


def _contains(padded: str, needle: str) -> bool:
    return bool(needle) and f" {needle} " in padded


def _classify_source_lines(
    source_text: str,
    hay: str,
    facts: list[str],
    *,
    min_words: int = 6,
    min_share: float = 0.3,
) -> dict[str, int]:
    """Classify substantial source lines that are mostly absent from the output.

    The field checks compare parsed data with the document, so a line the parser never
    read cannot fail them. This compares the source text itself. Lines expected to change
    shape (contact details, dated role headers, profile-sheet labels) are skipped.

    * ``hard``: missing line that carries a required fact (employer, title, bullet text,
      or a metric number).
    * ``soft``: missing line with no required fact (wrapped/reworded prose, headings).
    * ``changed``: line is present but a percentage/currency figure from it is not.
    """
    padded = f" {hay} "
    hard = soft = changed = 0
    for raw in (source_text or "").splitlines():
        line = raw.strip()
        if not line or _SKIP_SOURCE_LINE.search(line) or _SOURCE_DATE.search(line):
            continue
        norm_line = _norm(line)
        words = norm_line.split()
        if len(words) < min_words:
            continue
        metrics = [m for m in (_norm(x) for x in _METRIC.findall(line)) if m]
        grams = [" ".join(words[i : i + 4]) for i in range(len(words) - 3)]
        found = sum(1 for g in grams if f" {g} " in padded)
        if found < min_share * len(grams):
            line_padded = f" {norm_line} "
            carries_fact = bool(metrics) or any(
                _contains(line_padded, f) or (len(f.split()) >= _MIN_ROLE_BULLET_WORDS and _contains(f" {f} ", norm_line))
                for f in facts
            )
            if carries_fact:
                hard += 1
            else:
                soft += 1
        elif any(not _contains(padded, m) for m in metrics):
            changed += 1
    return {"hard": hard, "soft": soft, "changed": changed}


def _source_lines_missing(source_text: str, hay: str, *, min_words: int = 6, min_share: float = 0.3) -> int:
    """Count substantial source lines whose wording is mostly absent from the output."""
    r = _classify_source_lines(source_text, hay, [], min_words=min_words, min_share=min_share)
    return r["hard"] + r["soft"]


def _find_all(padded: str, needle: str) -> list[int]:
    if not needle:
        return []
    token = f" {needle} "
    out, start = [], 0
    while (i := padded.find(token, start)) != -1:
        out.append(i)
        start = i + 1
    return out


def _heading_position(company: str, title: str, padded: str) -> int | None:
    """Position of the role's heading: company and title found close together."""
    comp_hits, title_hits = _find_all(padded, company), _find_all(padded, title)
    if comp_hits and title_hits:
        pairs = [(abs(c - t), min(c, t)) for c in comp_hits for t in title_hits if abs(c - t) <= _HEADING_WINDOW]
        if pairs:
            return min(pairs)[1]
        return None
    if comp_hits and not title:
        return comp_hits[0]
    return None


def _misassigned_bullets(roles: list[dict], hay: str) -> int:
    """Count bullets found only under a different role's heading than the store assigns."""
    padded = f" {hay} "
    located: list[tuple[int, dict]] = []
    for role in roles:
        pos = _heading_position(_norm(role.get("company")), _norm(role.get("title")), padded)
        if pos is not None:
            located.append((pos, role))
    if len(located) < 2:
        return 0
    located.sort(key=lambda x: x[0])
    starts = [p for p, _ in located]
    if len(set(starts)) != len(starts):
        return 0
    wrong = 0
    for idx, (start, role) in enumerate(located):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(padded) + 1
        for bullet in role.get("description") or []:
            needle = _norm(bullet) if isinstance(bullet, str) else ""
            if len(needle.split()) < _MIN_ROLE_BULLET_WORDS:
                continue
            hits = _find_all(padded, needle)
            if not hits or any(start <= h < end for h in hits):
                continue
            if any(h >= starts[0] for h in hits):
                wrong += 1
    return wrong


def _experience_gap(store: dict, parse_meta: dict, roles: list[dict], hay: str) -> bool:
    """True when source work history exists but no roles (or preserved bullets) reach the output."""
    evidence = parse_meta.get("employment_evidence") or {}
    if roles or not evidence.get("has_work_history"):
        return False
    unassigned = [n for n in (_norm(b) for b in store.get("unassigned_experience_bullets") or []) if n]
    return not (unassigned and all(n in hay for n in unassigned))


def check_output_integrity(
    store: dict,
    docx_bytes: bytes,
    *,
    template_sample_text: str = "",
    allowed_text: str = "",
    suppressed_sections: list[str] | None = None,
    extraction_meta: dict | None = None,
    source_text: str = "",
    parse_meta: dict | None = None,
    verify_role_assignment: bool = True,
) -> IntegrityReport:
    try:
        hay = _docx_text(docx_bytes)
    except Exception:
        return IntegrityReport(
            "failed", {}, [_finding(BLOCKING, "document_unreadable", "The generated document could not be opened.")]
        )

    checks: dict[str, dict] = {}
    warnings: list[dict[str, str]] = []
    name = (store.get("header") or {}).get("name")
    _check("name", [name] if name else [], hay, checks, warnings, "candidate name")

    roles = [r for r in store.get("experience") or [] if isinstance(r, dict)]
    _check("companies", [r.get("company") for r in roles], hay, checks, warnings, "employers")
    _check("titles", [r.get("title") for r in roles], hay, checks, warnings, "job titles")
    _check("dates", [r.get("duration") for r in roles], hay, checks, warnings, "employment dates")
    bullets = [b for r in roles for b in (r.get("description") or []) if isinstance(b, str)]
    _check("bullets", bullets, hay, checks, warnings, "experience bullets")

    wrong_assignment = 0
    if verify_role_assignment and len(roles) >= 2:
        wrong_assignment = _misassigned_bullets(roles, hay)
        checks["role_assignment"] = {"ok": not wrong_assignment, "expected": 0, "found": wrong_assignment}
        if wrong_assignment:
            warnings.append(
                _finding(
                    BLOCKING,
                    "bullet_wrong_role",
                    f"{wrong_assignment} experience bullet(s) appear under a different employer "
                    "than the source assigns.",
                )
            )

    meta = parse_meta if parse_meta is not None else (store.get("parse_meta") or {})
    if _experience_gap(store, meta, roles, hay):
        checks["experience_roles"] = {"ok": False, "expected": 1, "found": 0}
        warnings.append(
            _finding(
                BLOCKING,
                "expected_experience_missing",
                "The source shows work history, but no experience roles were extracted; "
                "the Experience section is missing or incomplete.",
            )
        )
    elif not roles and (meta.get("employment_evidence") or {}).get("has_work_history"):
        warnings.append(
            _finding(
                INFO,
                "experience_roles_unassigned",
                "Work history bullets were kept but could not be assigned to employers.",
            )
        )

    edu = [e for e in store.get("education") or [] if isinstance(e, dict)]
    edu_fields = [_education_needle(e.get(k), hay) for e in edu for k in ("degree", "institution", "school", "year")]
    _check("education", edu_fields, hay, checks, warnings, "education fields")

    grouped = store.get("skills_by_category") or {}
    skills = [s for vals in grouped.values() for s in (vals or [])] if isinstance(grouped, dict) else []
    _check("skills", skills or store.get("skills") or [], hay, checks, warnings, "skills")
    for key, label in (
        ("certifications", "certifications"),
        ("achievements", "achievements"),
        ("languages", "languages"),
    ):
        _check(key, store.get(key) or [], hay, checks, warnings, label)

    suppressed = set(suppressed_sections or [])
    extras = [
        s for s in store.get("additional_sections") or []
        if isinstance(s, dict) and s.get("title") not in suppressed
    ]
    _check("additional_sections", [l for s in extras for l in s.get("lines") or []], hay, checks, warnings,
           "lines from other sections")

    allowed = _norm(allowed_text)
    leaks = [
        n for n in (_norm(l) for l in (template_sample_text or "").splitlines())
        if len(n) >= 8 and n in hay and n not in allowed
    ]
    checks["template_leak"] = {"ok": not leaks, "expected": 0, "found": len(leaks)}
    if leaks:
        warnings.append(
            _finding(
                BLOCKING,
                "template_leak",
                f"{len(leaks)} line(s) from the client template's sample content appear in the output.",
            )
        )

    ext = extraction_meta or {}
    unread = list(ext.get("ocr_missing_pages") or [])
    ocr = list(ext.get("ocr_pages") or [])
    # OCR-read pages are informational; only pages that could not be read lose content.
    checks["source_pages"] = {"ok": not unread, "expected": len(unread) + len(ocr), "found": len(ocr)}
    if unread:
        warnings.append(
            _finding(
                BLOCKING,
                "source_pages_unread",
                f"{len(unread)} page(s) of the source look like scanned images and could not be read "
                "(OCR is not available); their content is missing.",
            )
        )
    if ocr:
        warnings.append(
            _finding(INFO, "ocr_used", f"{len(ocr)} page(s) were read with OCR; check names, dates, and numbers.")
        )

    if source_text:
        facts = list(
            dict.fromkeys(
                n
                for n in (
                    *(_norm(r.get("company")) for r in roles),
                    *(_norm(r.get("title")) for r in roles),
                    *(_norm(b) for b in bullets),
                )
                if len(n) >= 4
            )
        )
        res = _classify_source_lines(source_text, hay, facts)
        hard, soft, changed = res["hard"], res["soft"], res["changed"]
        checks["source_lines"] = {
            "ok": not (hard or changed),
            "expected": 0,
            "found": hard + soft + changed,
            "hard": hard,
            "soft": soft,
            "changed_numbers": changed,
        }
        if hard:
            warnings.append(
                _finding(
                    BLOCKING,
                    "source_lines",
                    f"{hard} line(s) of the source resume that carry employers, titles, bullets, or figures "
                    "were not found in the output; compare before sending.",
                )
            )
        if changed:
            warnings.append(
                _finding(
                    BLOCKING,
                    "source_numbers",
                    f"{changed} source line(s) have percentage or currency figures that do not match the output; "
                    "compare before sending.",
                )
            )
        if soft:
            warnings.append(
                _finding(
                    INFO,
                    "source_lines_soft",
                    f"{soft} source line(s) were reworded or reflowed; no employer, title, bullet, or figure "
                    "was affected.",
                )
            )

    for title in suppressed:
        warnings.append(_finding(INFO, "section_suppressed", f"Section '{title}' was omitted by client policy."))

    has_blocking = any(w["severity"] == BLOCKING for w in warnings)
    if wrong_assignment or any(
        checks[k]["expected"] >= 2 and checks[k]["found"] < _FAIL_RATIO * checks[k]["expected"]
        for k in _CORE_CHECKS
        if k in checks
    ):
        status = "failed"
    elif has_blocking:
        status = "needs_review"
    else:
        status = "passed"
    return IntegrityReport(status, checks, warnings)
