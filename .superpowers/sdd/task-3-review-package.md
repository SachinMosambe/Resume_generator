# Review package Task 3 (after Important fixes)
BASE: 4855712a675ca628cce51174e2bd3ab70f9e500c
HEAD: 31ac2e81b5f72eb4b78386e3b728758e27570c83
## Commits
31ac2e8 fix: integrity review severity and additive warning headers 6900252 feat: make integrity review actionable with source-aware severity
## Diff stat
 .superpowers/sdd/task-3-report.md                 |  41 ++  README.md                                         |   3 +-  backend/app/api/routes/generate.py                |   5 +-  backend/app/main.py                               |   1 +  backend/app/services/output_integrity.py          | 318 +++++++++--  backend/app/services/resume_generation_service.py |   1 +  backend/scripts/corpus_quality_eval.py            | 627 ++++++++++++++++++++++  backend/tests/test_output_integrity.py            | 173 +++++-  frontend/src/app/page.tsx                         |  66 ++-  9 files changed, 1177 insertions(+), 58 deletions(-)
diff --git a/backend/app/api/routes/generate.py b/backend/app/api/routes/generate.py
index c4e738b..ae70ace 100644
--- a/backend/app/api/routes/generate.py
+++ b/backend/app/api/routes/generate.py
@@ -19,10 +19,11 @@ from app.models.candidate import Candidate
 from app.models.client_format import ClientFormat
 from app.services.aptino_template import build_aptino_client_format
 from app.services.format_extraction_service import FormatExtractionError, FormatExtractionService
 from app.services.format_profile_store import FormatProfileError, load_client_format, save_format_profile
 from app.services.docx_reader import DocxLimitError
+from app.services.output_integrity import warning_messages, warning_payload
 from app.services.pdf_ocr import OcrUnavailableError
 from app.services.pdf_parser import extract_document
 from app.services.resume_generation_service import ResumeGenerationError, ResumeGenerationService
 from app.services.s3_service import sanitize_filename
 
@@ -245,11 +246,13 @@ async def generate_resume(
         headers["X-Saved-Format-Id"] = str(saved_format_info["id"])
         headers["X-Saved-Format-Name"] = sanitize_filename(str(saved_format_info.get("name") or ""))
     report = getattr(service, "last_report", None)
     if report is not None:
         headers["X-Review-Status"] = report.status
-        headers["X-Review-Warnings"] = quote(json.dumps(report.warnings[:10]))
+        # Legacy readers: JSON list of message strings. Details: additive {severity, code, message} objects.
+        headers["X-Review-Warnings"] = quote(json.dumps(warning_messages(report)))
+        headers["X-Review-Warning-Details"] = quote(json.dumps(warning_payload(report)))
     return Response(
         content=docx_bytes,
         media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
         headers=headers,
     )
diff --git a/backend/app/main.py b/backend/app/main.py
index a03f85e..04e5d8a 100644
--- a/backend/app/main.py
+++ b/backend/app/main.py
@@ -21,10 +21,11 @@ app.add_middleware(
         'Content-Disposition',
         'X-Saved-Format-Id',
         'X-Saved-Format-Name',
         'X-Review-Status',
         'X-Review-Warnings',
+        'X-Review-Warning-Details',
     ],
 )
 
 app.include_router(generate_router, prefix='/api')
 app.include_router(formats_router, prefix='/api')
diff --git a/backend/app/services/output_integrity.py b/backend/app/services/output_integrity.py
index 29d08b1..8dd257f 100644
--- a/backend/app/services/output_integrity.py
+++ b/backend/app/services/output_integrity.py
@@ -1,46 +1,92 @@
 """Mechanical source-vs-output check for generated resumes.
 
 Compares normalized text presence only. A "passed" status means every checked source
 field was found in the document, not that the document is semantically verified.
-Warnings are recruiter-facing and never contain resume content.
+
+Warnings are structured ``{severity, code, message}`` dicts and recruiter-facing: they
+carry counts and codes, never resume content.
+
+* ``blocking`` findings (missing required facts, wrong-job bullets, missing experience)
+  move the status to ``needs_review`` (or ``failed`` for core-field loss / wrong jobs).
+* ``info`` findings (reflowed source lines, OCR used, policy omissions) are shown to the
+  recruiter but never change the status on their own.
 """
 
 from __future__ import annotations
 
 import io
 import re
 from dataclasses import dataclass, field
 from typing import Any
 
 from docx import Document
+from docx.table import Table
+from docx.text.paragraph import Paragraph
 
 from app.services.docx_layout import clean_education_title_dates
 
 # Below this share of a core field found in the output, the document is marked failed.
 _FAIL_RATIO = 0.5
 _CORE_CHECKS = ("companies", "titles", "dates", "bullets")
 
+BLOCKING = "blocking"
+INFO = "info"
+
+# Heading anchors (company + title) must sit this close together, in normalized chars.
+_HEADING_WINDOW = 200
+_MIN_ROLE_BULLET_WORDS = 4
+
 
 @dataclass
 class IntegrityReport:
     status: str
     checks: dict[str, dict] = field(default_factory=dict)
-    warnings: list[str] = field(default_factory=list)
+    warnings: list[dict[str, str]] = field(default_factory=list)
+
+
+def _finding(severity: str, code: str, message: str) -> dict[str, str]:
+    return {"severity": severity, "code": code, "message": message}
+
+
+def warning_payload(report: IntegrityReport, limit: int = 10) -> list[dict[str, str]]:
+    """Header-safe warnings; legacy strings are wrapped as objects.
+
+    Blocking findings are ordered first (stable otherwise) so that truncation to
+    ``limit`` can never drop a blocking finding in favour of an info one.
+    """
+    normalized: list[dict[str, str]] = []
+    for w in report.warnings:
+        if isinstance(w, dict):
+            normalized.append(w)
+        else:
+            normalized.append(_finding(BLOCKING if report.status != "passed" else INFO, "legacy", str(w)))
+    normalized.sort(key=lambda w: 0 if w.get("severity") == BLOCKING else 1)
+    return normalized[:limit]
+
+
+def warning_messages(report: IntegrityReport, limit: int = 10) -> list[str]:
+    """Plain message strings (legacy ``X-Review-Warnings`` format), blocking first."""
+    return [w["message"] for w in warning_payload(report, limit)]
 
 
 def _norm(text: Any) -> str:
     text = re.sub(r"[\u2010-\u2015]", "-", str(text or "")).lower()
     return re.sub(r"[^a-z0-9]+", " ", text).strip()
 
 
 def _docx_text(data: bytes) -> str:
     doc = Document(io.BytesIO(data))
-    parts = [p.text for p in doc.paragraphs]
-    for table in doc.tables:
-        for row in table.rows:
-            parts.extend(c.text for c in row.cells)
+    parts: list[str] = []
+    # Body order (paragraphs and tables interleaved) so positions reflect the page layout.
+    for child in doc.element.body.iterchildren():
+        tag = child.tag.rsplit("}", 1)[-1]
+        if tag == "p":
+            parts.append(Paragraph(child, doc).text)
+        elif tag == "tbl":
+            for row in Table(child, doc).rows:
+                parts.extend(c.text for c in row.cells)
     for section in doc.sections:
         for part in (section.header, section.footer):
             parts.extend(p.text for p in part.paragraphs)
             for table in part.tables:
                 for row in table.rows:
@@ -58,18 +104,24 @@ def _education_needle(value: Any, hay: str) -> Any:
         if _norm(alt) and _norm(alt) in hay:
             return alt
     return value
 
 
-def _check(name: str, expected: list[Any], hay: str, checks: dict, warnings: list[str], label: str) -> None:
+def _check(name: str, expected: list[Any], hay: str, checks: dict, warnings: list[dict], label: str) -> None:
     items = list(dict.fromkeys(n for n in (_norm(x) for x in expected) if n))
     if not items:
         return
     missing = [x for x in items if x not in hay]
     checks[name] = {"ok": not missing, "expected": len(items), "found": len(items) - len(missing)}
     if missing:
-        warnings.append(f"{len(missing)} of {len(items)} {label} from the source were not found in the output.")
+        warnings.append(
+            _finding(
+                BLOCKING,
+                f"{name}_missing",
+                f"{len(missing)} of {len(items)} {label} from the source were not found in the output.",
+            )
+        )
 
 
 _SKIP_SOURCE_LINE = re.compile(
     r"(?i)(@|https?://|www\.|linkedin|\d{3}[-.\s)]+\d{3}[-.\s]\d{4}|references available|"
     r"preferred|desired work|willing to relocate|work authorization|employment type|profile source|"
@@ -77,34 +129,131 @@ _SKIP_SOURCE_LINE = re.compile(
     r"gap\s*period|on-site or hybrid|contract to hire)"
 )
 _SOURCE_DATE = re.compile(
     r"(?i)\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d{4}|\b\d{1,2}/\d{4}\b|\b(?:19|20)\d{2}\s*[-–—]"
 )
+# Metrics whose digits must survive verbatim: percentages and currency amounts.
+_METRIC = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?\s?[kmb]?\b|\b\d[\d,]*(?:\.\d+)?\s?%", re.IGNORECASE)
 
 
-def _source_lines_missing(source_text: str, hay: str, *, min_words: int = 6, min_share: float = 0.3) -> int:
-    """Count substantial source lines whose wording is mostly absent from the output.
+def _contains(padded: str, needle: str) -> bool:
+    return bool(needle) and f" {needle} " in padded
 
-    The field checks above compare parsed data with the document, so a line the parser
-    never read cannot fail them. This compares the source text itself. Lines that are
-    expected to change shape (contact details, dated role headers, profile-sheet labels)
-    are skipped.
+
+def _classify_source_lines(
+    source_text: str,
+    hay: str,
+    facts: list[str],
+    *,
+    min_words: int = 6,
+    min_share: float = 0.3,
+) -> dict[str, int]:
+    """Classify substantial source lines that are mostly absent from the output.
+
+    The field checks compare parsed data with the document, so a line the parser never
+    read cannot fail them. This compares the source text itself. Lines expected to change
+    shape (contact details, dated role headers, profile-sheet labels) are skipped.
+
+    * ``hard``: missing line that carries a required fact (employer, title, bullet text,
+      or a metric number).
+    * ``soft``: missing line with no required fact (wrapped/reworded prose, headings).
+    * ``changed``: line is present but a percentage/currency figure from it is not.
     """
     padded = f" {hay} "
-    missing = 0
+    hard = soft = changed = 0
     for raw in (source_text or "").splitlines():
         line = raw.strip()
         if not line or _SKIP_SOURCE_LINE.search(line) or _SOURCE_DATE.search(line):
             continue
-        words = _norm(line).split()
+        norm_line = _norm(line)
+        words = norm_line.split()
         if len(words) < min_words:
             continue
+        metrics = [m for m in (_norm(x) for x in _METRIC.findall(line)) if m]
         grams = [" ".join(words[i : i + 4]) for i in range(len(words) - 3)]
         found = sum(1 for g in grams if f" {g} " in padded)
         if found < min_share * len(grams):
-            missing += 1
-    return missing
+            line_padded = f" {norm_line} "
+            carries_fact = bool(metrics) or any(
+                _contains(line_padded, f) or (len(f.split()) >= _MIN_ROLE_BULLET_WORDS and _contains(f" {f} ", norm_line))
+                for f in facts
+            )
+            if carries_fact:
+                hard += 1
+            else:
+                soft += 1
+        elif any(not _contains(padded, m) for m in metrics):
+            changed += 1
+    return {"hard": hard, "soft": soft, "changed": changed}
+
+
+def _source_lines_missing(source_text: str, hay: str, *, min_words: int = 6, min_share: float = 0.3) -> int:
+    """Count substantial source lines whose wording is mostly absent from the output."""
+    r = _classify_source_lines(source_text, hay, [], min_words=min_words, min_share=min_share)
+    return r["hard"] + r["soft"]
+
+
+def _find_all(padded: str, needle: str) -> list[int]:
+    if not needle:
+        return []
+    token = f" {needle} "
+    out, start = [], 0
+    while (i := padded.find(token, start)) != -1:
+        out.append(i)
+        start = i + 1
+    return out
+
+
+def _heading_position(company: str, title: str, padded: str) -> int | None:
+    """Position of the role's heading: company and title found close together."""
+    comp_hits, title_hits = _find_all(padded, company), _find_all(padded, title)
+    if comp_hits and title_hits:
+        pairs = [(abs(c - t), min(c, t)) for c in comp_hits for t in title_hits if abs(c - t) <= _HEADING_WINDOW]
+        if pairs:
+            return min(pairs)[1]
+        return None
+    if comp_hits and not title:
+        return comp_hits[0]
+    return None
+
+
+def _misassigned_bullets(roles: list[dict], hay: str) -> int:
+    """Count bullets found only under a different role's heading than the store assigns."""
+    padded = f" {hay} "
+    located: list[tuple[int, dict]] = []
+    for role in roles:
+        pos = _heading_position(_norm(role.get("company")), _norm(role.get("title")), padded)
+        if pos is not None:
+            located.append((pos, role))
+    if len(located) < 2:
+        return 0
+    located.sort(key=lambda x: x[0])
+    starts = [p for p, _ in located]
+    if len(set(starts)) != len(starts):
+        return 0
+    wrong = 0
+    for idx, (start, role) in enumerate(located):
+        end = starts[idx + 1] if idx + 1 < len(starts) else len(padded) + 1
+        for bullet in role.get("description") or []:
+            needle = _norm(bullet) if isinstance(bullet, str) else ""
+            if len(needle.split()) < _MIN_ROLE_BULLET_WORDS:
+                continue
+            hits = _find_all(padded, needle)
+            if not hits or any(start <= h < end for h in hits):
+                continue
+            if any(h >= starts[0] for h in hits):
+                wrong += 1
+    return wrong
+
+
+def _experience_gap(store: dict, parse_meta: dict, roles: list[dict], hay: str) -> bool:
+    """True when source work history exists but no roles (or preserved bullets) reach the output."""
+    evidence = parse_meta.get("employment_evidence") or {}
+    if roles or not evidence.get("has_work_history"):
+        return False
+    unassigned = [n for n in (_norm(b) for b in store.get("unassigned_experience_bullets") or []) if n]
+    return not (unassigned and all(n in hay for n in unassigned))
 
 
 def check_output_integrity(
     store: dict,
     docx_bytes: bytes,
@@ -112,28 +261,67 @@ def check_output_integrity(
     template_sample_text: str = "",
     allowed_text: str = "",
     suppressed_sections: list[str] | None = None,
     extraction_meta: dict | None = None,
     source_text: str = "",
+    parse_meta: dict | None = None,
+    verify_role_assignment: bool = True,
 ) -> IntegrityReport:
     try:
         hay = _docx_text(docx_bytes)
     except Exception:
-        return IntegrityReport("failed", {}, ["The generated document could not be opened."])
+        return IntegrityReport(
+            "failed", {}, [_finding(BLOCKING, "document_unreadable", "The generated document could not be opened.")]
+        )
 
     checks: dict[str, dict] = {}
-    warnings: list[str] = []
+    warnings: list[dict[str, str]] = []
     name = (store.get("header") or {}).get("name")
     _check("name", [name] if name else [], hay, checks, warnings, "candidate name")
 
     roles = [r for r in store.get("experience") or [] if isinstance(r, dict)]
     _check("companies", [r.get("company") for r in roles], hay, checks, warnings, "employers")
     _check("titles", [r.get("title") for r in roles], hay, checks, warnings, "job titles")
     _check("dates", [r.get("duration") for r in roles], hay, checks, warnings, "employment dates")
     bullets = [b for r in roles for b in (r.get("description") or []) if isinstance(b, str)]
     _check("bullets", bullets, hay, checks, warnings, "experience bullets")
 
+    wrong_assignment = 0
+    if verify_role_assignment and len(roles) >= 2:
+        wrong_assignment = _misassigned_bullets(roles, hay)
+        checks["role_assignment"] = {"ok": not wrong_assignment, "expected": 0, "found": wrong_assignment}
+        if wrong_assignment:
+            warnings.append(
+                _finding(
+                    BLOCKING,
+                    "bullet_wrong_role",
+                    f"{wrong_assignment} experience bullet(s) appear under a different employer "
+                    "than the source assigns.",
+                )
+            )
+
+    meta = parse_meta if parse_meta is not None else (store.get("parse_meta") or {})
+    if _experience_gap(store, meta, roles, hay):
+        checks["experience_roles"] = {"ok": False, "expected": 1, "found": 0}
+        warnings.append(
+            _finding(
+                BLOCKING,
+                "expected_experience_missing",
+                "The source shows work history, but no experience roles were extracted; "
+                "the Experience section is missing or incomplete.",
+            )
+        )
+    elif not roles and (meta.get("employment_evidence") or {}).get("has_work_history"):
+        warnings.append(
+            _finding(
+                BLOCKING,
+                "experience_roles_unassigned",
+                "Work history bullets were kept but could not be assigned to employers; "
+                "the Experience section needs manual review.",
+            )
+        )
+
     edu = [e for e in store.get("education") or [] if isinstance(e, dict)]
     edu_fields = [_education_needle(e.get(k), hay) for e in edu for k in ("degree", "institution", "school", "year")]
     _check("education", edu_fields, hay, checks, warnings, "education fields")
 
     grouped = store.get("skills_by_category") or {}
@@ -159,41 +347,97 @@ def check_output_integrity(
         n for n in (_norm(l) for l in (template_sample_text or "").splitlines())
         if len(n) >= 8 and n in hay and n not in allowed
     ]
     checks["template_leak"] = {"ok": not leaks, "expected": 0, "found": len(leaks)}
     if leaks:
-        warnings.append(f"{len(leaks)} line(s) from the client template's sample content appear in the output.")
+        warnings.append(
+            _finding(
+                BLOCKING,
+                "template_leak",
+                f"{len(leaks)} line(s) from the client template's sample content appear in the output.",
+            )
+        )
 
-    meta = extraction_meta or {}
-    unread = list(meta.get("ocr_missing_pages") or [])
-    ocr = list(meta.get("ocr_pages") or [])
-    checks["source_pages"] = {"ok": not unread and not ocr, "expected": len(unread) + len(ocr), "found": len(ocr)}
+    ext = extraction_meta or {}
+    unread = list(ext.get("ocr_missing_pages") or [])
+    ocr = list(ext.get("ocr_pages") or [])
+    # OCR-read pages are informational; only pages that could not be read lose content.
+    checks["source_pages"] = {"ok": not unread, "expected": len(unread) + len(ocr), "found": len(ocr)}
     if unread:
         warnings.append(
-            f"{len(unread)} page(s) of the source look like scanned images and could not be read "
-            "(OCR is not available); their content is missing."
+            _finding(
+                BLOCKING,
+                "source_pages_unread",
+                f"{len(unread)} page(s) of the source look like scanned images and could not be read "
+                "(OCR is not available); their content is missing.",
+            )
         )
     if ocr:
-        warnings.append(f"{len(ocr)} page(s) were read with OCR; check names, dates, and numbers.")
+        warnings.append(
+            _finding(INFO, "ocr_used", f"{len(ocr)} page(s) were read with OCR; check names, dates, and numbers.")
+        )
 
     if source_text:
-        lost = _source_lines_missing(source_text, hay)
-        checks["source_lines"] = {"ok": not lost, "expected": 0, "found": lost}
-        if lost:
+        facts = list(
+            dict.fromkeys(
+                n
+                for n in (
+                    *(_norm(r.get("company")) for r in roles),
+                    *(_norm(r.get("title")) for r in roles),
+                    *(_norm(b) for b in bullets),
+                )
+                if len(n) >= 4
+            )
+        )
+        res = _classify_source_lines(source_text, hay, facts)
+        hard, soft, changed = res["hard"], res["soft"], res["changed"]
+        checks["source_lines"] = {
+            "ok": not (hard or changed),
+            "expected": 0,
+            "found": hard + soft + changed,
+            "hard": hard,
+            "soft": soft,
+            "changed_numbers": changed,
+        }
+        if hard:
+            warnings.append(
+                _finding(
+                    BLOCKING,
+                    "source_lines",
+                    f"{hard} line(s) of the source resume that carry employers, titles, bullets, or figures "
+                    "were not found in the output; compare before sending.",
+                )
+            )
+        if changed:
             warnings.append(
-                f"{lost} line(s) of the source resume were not found in the output; compare before sending."
+                _finding(
+                    BLOCKING,
+                    "source_numbers",
+                    f"{changed} source line(s) have percentage or currency figures that do not match the output; "
+                    "compare before sending.",
+                )
+            )
+        if soft:
+            warnings.append(
+                _finding(
+                    INFO,
+                    "source_lines_soft",
+                    f"{soft} source line(s) were reworded or reflowed; no employer, title, bullet, or figure "
+                    "was affected.",
+                )
             )
 
     for title in suppressed:
-        warnings.append(f"Section '{title}' was omitted by client policy.")
+        warnings.append(_finding(INFO, "section_suppressed", f"Section '{title}' was omitted by client policy."))
 
-    if all(c["ok"] for c in checks.values()):
-        status = "passed"
-    elif any(
+    has_blocking = any(w["severity"] == BLOCKING for w in warnings)
+    if wrong_assignment or any(
         checks[k]["expected"] >= 2 and checks[k]["found"] < _FAIL_RATIO * checks[k]["expected"]
         for k in _CORE_CHECKS
         if k in checks
     ):
         status = "failed"
-    else:
+    elif has_blocking:
         status = "needs_review"
+    else:
+        status = "passed"
     return IntegrityReport(status, checks, warnings)
diff --git a/backend/tests/test_output_integrity.py b/backend/tests/test_output_integrity.py
index dd77894..4ef1ada 100644
--- a/backend/tests/test_output_integrity.py
+++ b/backend/tests/test_output_integrity.py
@@ -1,10 +1,14 @@
 import io
 
 from docx import Document
 
-from app.services.output_integrity import check_output_integrity
+from app.services.output_integrity import check_output_integrity, warning_messages, warning_payload
+
+
+def _msgs(report):
+    return [w["message"] if isinstance(w, dict) else str(w) for w in report.warnings]
 
 STORE = {
     "header": {"name": "Jordan Rivera"},
     "experience": [
         {
@@ -60,12 +64,12 @@ def test_all_present_passes():
 
 def test_missing_bullet_needs_review_without_leaking_content():
     lines = [l for l in FULL if not l.startswith("Led migration")]
     report = check_output_integrity(STORE, _docx(*lines))
     assert report.status == "needs_review"
-    assert any("bullet" in w.lower() for w in report.warnings)
-    assert all("migration" not in w.lower() for w in report.warnings)
+    assert any("bullet" in m.lower() for m in _msgs(report))
+    assert all("migration" not in m.lower() for m in _msgs(report))
 
 
 def test_most_roles_missing_fails():
     store = {
         **STORE,
@@ -94,17 +98,18 @@ def test_template_sample_leak_detected_but_branding_allowed():
 def test_suppressed_section_reported_not_failed():
     store = {**STORE, "additional_sections": STORE["additional_sections"] + [
         {"title": "References", "lines": ["Pat Manager, pat.manager@example.org"]}]}
     report = check_output_integrity(store, _docx(*FULL), suppressed_sections=["References"])
     assert report.status == "passed"
-    assert any("References" in w and "omitted" in w for w in report.warnings)
+    assert any("References" in m and "omitted" in m for m in _msgs(report))
+    assert all(w["severity"] == "info" for w in report.warnings)
 
 
 def test_unread_scanned_pages_need_review():
     report = check_output_integrity(STORE, _docx(*FULL), extraction_meta={"ocr_missing_pages": [2], "ocr_pages": []})
     assert report.status == "needs_review"
-    assert any("scanned" in w for w in report.warnings)
+    assert any("scanned" in m for m in _msgs(report))
 
 
 def test_api_returns_review_headers_visible_to_browser(fixtures, tmp_path, monkeypatch):
     import json
     from urllib.parse import unquote
@@ -128,11 +133,165 @@ def test_api_returns_review_headers_visible_to_browser(fixtures, tmp_path, monke
 
 def test_unreadable_docx_fails():
     assert check_output_integrity(STORE, b"not a docx").status == "failed"
 
 
-def test_source_line_missing_from_output_needs_review():
+def test_source_lines_alone_do_not_force_needs_review():
+    # A reworded/reflowed source line carrying no employer, title, bullet, or metric is informational.
     source = "\n".join([*FULL, "Led migration of the ledger platform to a new event-driven architecture design"])
     report = check_output_integrity(STORE, _docx(*FULL), source_text=source)
-    assert report.status == "needs_review"
+    assert report.status == "passed", report.warnings
+    assert report.checks["source_lines"]["ok"] is True
     assert report.checks["source_lines"]["found"] == 1
+    assert any(w["severity"] == "info" and w["code"] == "source_lines_soft" for w in report.warnings)
     assert check_output_integrity(STORE, _docx(*FULL), source_text="\n".join(FULL)).status == "passed"
+
+
+def test_source_line_with_required_fact_missing_needs_review():
+    # The line names the employer, so a dropped line is a likely dropped bullet.
+    source = "\n".join([*FULL, "Acme Corp rebuilt the ledger platform around a new event-driven architecture design"])
+    report = check_output_integrity(STORE, _docx(*FULL), source_text=source)
+    assert report.status == "needs_review"
+    assert any(w["severity"] == "blocking" and w["code"] == "source_lines" for w in report.warnings)
+    assert all("ledger" not in m.lower() for m in _msgs(report))
+
+
+def test_changed_factual_number_needs_review():
+    source = "\n".join([*FULL, "Reduced payment settlement latency by 35% across the entire merchant platform estate"])
+    out = [*FULL, "Reduced payment settlement latency by 53% across the entire merchant platform estate"]
+    report = check_output_integrity(STORE, _docx(*out), source_text=source)
+    assert report.status == "needs_review"
+    assert any(w["code"] == "source_numbers" for w in report.warnings)
+    assert all("35" not in m and "53" not in m for m in _msgs(report))
+
+
+def test_ocr_used_is_info_only():
+    report = check_output_integrity(STORE, _docx(*FULL), extraction_meta={"ocr_pages": [1], "ocr_missing_pages": []})
+    assert report.status == "passed"
+    assert any(w["severity"] == "info" and "OCR" in w["message"] for w in report.warnings)
+
+
+EMPTY_EXP_STORE = {**STORE, "experience": []}
+EVIDENCE_META = {
+    "employment_evidence": {"has_work_history": True, "reasons": ["experience_heading"]},
+    "reasons": ["expected_experience_missing"],
+}
+NO_EXP_LINES = ["Jordan Rivera", "B.S. Physics", "Tech University", "2014", "Languages: Python, Go",
+                "Publications", "Streaming joins. 2022."]
+
+
+def test_zero_roles_with_employment_evidence_needs_review():
+    report = check_output_integrity(
+        EMPTY_EXP_STORE, _docx(*NO_EXP_LINES), source_text="\n".join(FULL), parse_meta=EVIDENCE_META
+    )
+    assert report.status == "needs_review"
+    blocking = [w for w in report.warnings if w["severity"] == "blocking"]
+    assert any(w["code"] == "expected_experience_missing" and "experience" in w["message"].lower() for w in blocking)
+
+
+def test_zero_roles_without_evidence_has_no_experience_warning():
+    report = check_output_integrity(
+        EMPTY_EXP_STORE, _docx(*NO_EXP_LINES), parse_meta={"employment_evidence": {"has_work_history": False}}
+    )
+    assert report.status == "passed"
+    assert not any(w["code"] == "expected_experience_missing" for w in report.warnings)
+
+
+def test_zero_roles_with_preserved_unassigned_bullets_needs_review():
+    store = {**EMPTY_EXP_STORE, "unassigned_experience_bullets": ["Led migration to event-driven payments."]}
+    report = check_output_integrity(
+        store, _docx(*NO_EXP_LINES, "Led migration to event-driven payments."), parse_meta=EVIDENCE_META
+    )
+    assert not any(w["code"] == "expected_experience_missing" for w in report.warnings)
+    assert report.status == "needs_review"
+    assert any(w["severity"] == "blocking" and w["code"] == "experience_roles_unassigned" for w in report.warnings)
+
+
+def test_zero_roles_with_unpreserved_unassigned_bullets_is_blocking():
+    store = {**EMPTY_EXP_STORE, "unassigned_experience_bullets": ["Led migration to event-driven payments."]}
+    report = check_output_integrity(store, _docx(*NO_EXP_LINES), parse_meta=EVIDENCE_META)
+    assert report.status == "needs_review"
+    assert any(w["code"] == "expected_experience_missing" for w in report.warnings)
+
+
+TWO_ROLES = {
+    **STORE,
+    "experience": [
+        {"company": "Acme Corp", "title": "Staff Engineer", "duration": "Jul 2021 - Present",
+         "description": ["Led migration to event-driven payments."]},
+        {"company": "Globex Inc", "title": "Developer", "duration": "Jan 2015 - Jun 2021",
+         "description": ["Built nightly reconciliation jobs for treasury."]},
+    ],
+}
+TWO_ROLE_TAIL = ["B.S. Physics", "Tech University", "2014", "Languages: Python, Go", "Publications", "Streaming joins. 2022."]
+
+
+def _two_role_docx(bullet_a, bullet_b):
+    return _docx(
+        "Jordan Rivera",
+        "Staff Engineer", "Acme Corp", "Jul. 2021 – Present", bullet_a,
+        "Developer", "Globex Inc", "Jan. 2015 – Jun. 2021", bullet_b,
+        *TWO_ROLE_TAIL,
+    )
+
+
+def test_bullet_under_wrong_employer_fails():
+    docx = _two_role_docx("Built nightly reconciliation jobs for treasury.", "Led migration to event-driven payments.")
+    report = check_output_integrity(TWO_ROLES, docx)
+    assert report.status == "failed"
+    assert any(w["code"] == "bullet_wrong_role" for w in report.warnings)
+    assert all("reconciliation" not in m.lower() and "Globex" not in m for m in _msgs(report))
+
+
+def test_bullets_under_correct_employers_pass():
+    docx = _two_role_docx("Led migration to event-driven payments.", "Built nightly reconciliation jobs for treasury.")
+    assert check_output_integrity(TWO_ROLES, docx).status == "passed"
+
+
+def test_wrong_assignment_check_can_be_disabled():
+    docx = _two_role_docx("Built nightly reconciliation jobs for treasury.", "Led migration to event-driven payments.")
+    assert check_output_integrity(TWO_ROLES, docx, verify_role_assignment=False).status == "passed"
+
+
+def test_warning_payload_wraps_legacy_strings_and_caps():
+    report = check_output_integrity(STORE, _docx(*FULL))
+    report.warnings = [f"legacy {i}" for i in range(12)]
+    report.status = "needs_review"
+    payload = warning_payload(report)
+    assert len(payload) == 10
+    assert payload[0] == {"severity": "blocking", "code": "legacy", "message": "legacy 0"}
+
+
+def test_warning_payload_keeps_blocking_when_truncating():
+    report = check_output_integrity(STORE, _docx(*FULL))
+    info = [{"severity": "info", "code": "i", "message": f"info {i}"} for i in range(12)]
+    blocking = {"severity": "blocking", "code": "b", "message": "blocking last"}
+    report.warnings = [*info, blocking]
+    report.status = "needs_review"
+    payload = warning_payload(report)
+    assert len(payload) == 10
+    assert payload[0] == blocking
+    assert warning_messages(report)[0] == "blocking last"
+
+
+def test_api_review_headers_legacy_strings_and_additive_details(fixtures, tmp_path, monkeypatch):
+    import json
+    from urllib.parse import unquote
+
+    from fastapi.testclient import TestClient
+
+    from app.main import app
+
+    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
+    with open(fixtures["single_column_pdf"], "rb") as fh:
+        resp = TestClient(app).post(
+            "/api/generate",
+            files={"resume": ("cv.pdf", fh, "application/pdf")},
+            headers={"Origin": "http://localhost:3000"},
+        )
+    assert resp.status_code == 200
+    legacy = json.loads(unquote(resp.headers["X-Review-Warnings"]))
+    details = json.loads(unquote(resp.headers["X-Review-Warning-Details"]))
+    assert all(isinstance(w, str) for w in legacy)
+    assert all(set(w) == {"severity", "code", "message"} for w in details)
+    assert legacy == [w["message"] for w in details]
+    assert "x-review-warning-details" in resp.headers.get("access-control-expose-headers", "").lower()
diff --git a/frontend/src/app/page.tsx b/frontend/src/app/page.tsx
index 0d9694c..17f88d4 100644
--- a/frontend/src/app/page.tsx
+++ b/frontend/src/app/page.tsx
@@ -23,15 +23,38 @@ import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
 
 type TemplateMode = "aptino_default" | "client_format" | "saved_format";
 
 type ReviewStatus = "passed" | "needs_review" | "failed";
 
+type ReviewWarning = {
+  severity: "blocking" | "info";
+  code: string;
+  message: string;
+};
+
 type Review = {
   status: ReviewStatus;
-  warnings: string[];
+  warnings: ReviewWarning[];
 };
 
+// Header warnings may be legacy strings or {severity, code, message} objects.
+function normalizeWarning(raw: unknown, status: ReviewStatus): ReviewWarning | null {
+  if (typeof raw === "string") {
+    return { severity: status === "passed" ? "info" : "blocking", code: "legacy", message: raw };
+  }
+  if (raw && typeof raw === "object") {
+    const w = raw as Record<string, unknown>;
+    if (typeof w.message !== "string") return null;
+    return {
+      severity: w.severity === "info" ? "info" : "blocking",
+      code: typeof w.code === "string" ? w.code : "unknown",
+      message: w.message,
+    };
+  }
+  return null;
+}
+
 const REVIEW_STYLES: Record<ReviewStatus, { box: string; title: string; body: string }> = {
   passed: {
     box: "border-emerald-200 bg-emerald-50",
     title: "Automated check passed",
     body: "Every employer, title, date, bullet, and section found in the source also appears in the document. This is a text-presence check, not a full proofread — skim before sending.",
@@ -49,30 +72,49 @@ const REVIEW_STYLES: Record<ReviewStatus, { box: string; title: string; body: st
 };
 
 function parseReview(response: Response): Review | null {
   const status = response.headers.get("X-Review-Status") as ReviewStatus | null;
   if (!status || !(status in REVIEW_STYLES)) return null;
-  let warnings: string[] = [];
-  try {
-    const parsed = JSON.parse(decodeURIComponent(response.headers.get("X-Review-Warnings") || "[]"));
-    if (Array.isArray(parsed)) warnings = parsed.map(String);
-  } catch {
-    /* ignore malformed header */
-  }
+  const readList = (name: string): ReviewWarning[] | null => {
+    const raw = response.headers.get(name);
+    if (!raw) return null;
+    try {
+      const parsed = JSON.parse(decodeURIComponent(raw));
+      if (!Array.isArray(parsed)) return null;
+      return parsed
+        .map((w) => normalizeWarning(w, status))
+        .filter((w): w is ReviewWarning => w !== null);
+    } catch {
+      return null; /* ignore malformed header */
+    }
+  };
+  // Prefer structured details; fall back to the legacy list of message strings.
+  const warnings = readList("X-Review-Warning-Details") ?? readList("X-Review-Warnings") ?? [];
   return { status, warnings };
 }
 
 function ReviewPanel({ review }: { review: Review }) {
   const style = REVIEW_STYLES[review.status];
+  const blocking = review.warnings.filter((w) => w.severity === "blocking");
+  const info = review.warnings.filter((w) => w.severity === "info");
   return (
     <section role="status" className={`mt-6 rounded-2xl border p-5 ${style.box}`}>
       <p className="text-sm font-semibold text-gray-900">{style.title}</p>
       <p className="mt-1 text-sm text-gray-700">{style.body}</p>
-      {review.warnings.length > 0 && (
-        <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-gray-700">
-          {review.warnings.map((w) => (
-            <li key={w}>{w}</li>
+      {blocking.length > 0 && (
+        <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-gray-800">
+          {blocking.map((w, i) => (
+            <li key={`${w.code}-${i}`} className="font-medium">
+              {w.message}
+            </li>
+          ))}
+        </ul>
+      )}
+      {info.length > 0 && (
+        <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-gray-500">
+          {info.map((w, i) => (
+            <li key={`${w.code}-${i}`}>Note: {w.message}</li>
           ))}
         </ul>
       )}
     </section>
   );
