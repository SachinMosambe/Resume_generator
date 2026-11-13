# Review package Task 4
BASE: 31ac2e81b5f72eb4b78386e3b728758e27570c83
HEAD: 324ed95429acd6bcdfd90f101a3d0c4dce36d7cb
## Commits
324ed95 feat: harden intake for OCR, legacy DOC, and non-resume rejection
## Diff stat
 backend/app/api/routes/generate.py       |  24 ++-  backend/app/services/doc_converter.py    |   5 +-  backend/app/services/intake_gate.py      | 147 +++++++++++++++++  backend/app/services/output_integrity.py |   9 +-  backend/app/services/pdf_ocr.py          |  22 +++  backend/app/services/pdf_parser.py       |  17 +-  backend/tests/test_intake_gate.py        | 272 +++++++++++++++++++++++++++++++  7 files changed, 486 insertions(+), 10 deletions(-)
diff --git a/backend/app/api/routes/generate.py b/backend/app/api/routes/generate.py
index ae70ace..b1f963a 100644
--- a/backend/app/api/routes/generate.py
+++ b/backend/app/api/routes/generate.py
@@ -19,13 +19,15 @@ from app.models.candidate import Candidate
 from app.models.client_format import ClientFormat
 from app.services.aptino_template import build_aptino_client_format
 from app.services.format_extraction_service import FormatExtractionError, FormatExtractionService
 from app.services.format_profile_store import FormatProfileError, load_client_format, save_format_profile
 from app.services.docx_reader import DocxLimitError
 from app.services.output_integrity import warning_messages, warning_payload
-from app.services.pdf_ocr import OcrUnavailableError
+from app.services.doc_converter import DocConversionError
+from app.services.intake_gate import assess_resume_intake
+from app.services.pdf_ocr import OcrUnavailableError, format_page_refs
 from app.services.pdf_parser import extract_document
 from app.services.resume_generation_service import ResumeGenerationError, ResumeGenerationService
 from app.services.s3_service import sanitize_filename
 
 router = APIRouter()
 
@@ -112,16 +114,23 @@ async def generate_resume(
         resume_path.unlink(missing_ok=True)
         try:
             tmp_dir.rmdir()
         except OSError:
             pass
         if isinstance(exc, OcrUnavailableError):
+            where = format_page_refs(exc.pages)
             detail = (
-                "This PDF is scanned (image only) and OCR is not installed on this server. "
+                f"This PDF is scanned (image only{f'; {where}' if where else ''}) and OCR is not "
+                "available on this server, so no text could be read. "
                 "Upload the original DOCX or a text-based PDF, or enable OCR (see README)."
             )
+        elif isinstance(exc, DocConversionError):
+            detail = (
+                "This legacy .doc file could not be converted on this server. "
+                "Re-save it as .docx (or PDF) in Word and upload it again."
+            )
         elif isinstance(exc, DocxLimitError):
             detail = "This DOCX is too large or complex to process safely. Save a simpler copy and retry."
         else:
             detail = "Could not read this resume. Upload a text-based PDF, DOC, or DOCX."
         raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail) from exc
     if not resume_text.strip():
@@ -132,12 +141,23 @@ async def generate_resume(
             pass
         raise HTTPException(
             status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
             detail="No readable text was found in this resume. Upload a text-based PDF, DOC, or DOCX.",
         )
 
+    assessment = assess_resume_intake(resume_text)
+    if not assessment.is_resume:
+        extraction_meta["quarantine_reason"] = assessment.reason_code
+        logger.warning("resume_quarantined", reason=assessment.reason_code, signals=assessment.resume_signals)
+        resume_path.unlink(missing_ok=True)
+        try:
+            tmp_dir.rmdir()
+        except OSError:
+            pass
+        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=assessment.message)
+
     client_id = (client_name or "").strip() or "Client"
     role = (job_role or "").strip() or None
     guessed_name = _guess_name_from_text(resume_text)
 
     candidate = Candidate(
         name=guessed_name or Path(resume.filename or "Candidate").stem.replace("_", " "),
diff --git a/backend/app/services/doc_converter.py b/backend/app/services/doc_converter.py
index c5ca2eb..daf0316 100644
--- a/backend/app/services/doc_converter.py
+++ b/backend/app/services/doc_converter.py
@@ -218,15 +218,14 @@ def convert_doc_to_docx(source: Path, output_dir: Path | None = None) -> Path:
     finally:
         shutil.rmtree(work_root, ignore_errors=True)
 
     detail = " | ".join(logs)[:500] if logs else "no converter output"
     logger.error("doc_conversion_failed soffice=%s detail=%s", soffice, detail)
     raise DocConversionError(
-        "Could not convert .doc to .docx. "
-        "Re-save the file as .docx in Word and upload again, or install full LibreOffice writer. "
-        f"Details: {detail[:240]}"
+        "Could not convert this .doc file to .docx. "
+        "Re-save the file as .docx in Word and upload it again."
     )
 
 
 def _convert_with_word(source: Path, output_dir: Path) -> Path | None:
     """Convert .doc with Microsoft Word on Windows when LibreOffice is absent."""
     if os.name != "nt":
diff --git a/backend/app/services/intake_gate.py b/backend/app/services/intake_gate.py
new file mode 100644
index 0000000..0a0e4ad
--- /dev/null
+++ b/backend/app/services/intake_gate.py
@@ -0,0 +1,147 @@
+"""Intake gate: reject uploads that are clearly not a resume, with an actionable reason.
+
+The gate is deliberately conservative. A file is quarantined only when it carries
+explicit non-resume document markers (certificate, I-94 / travel record, invoice...)
+AND it lacks the structure of a resume. A sparse or education-only resume has resume
+structure (section headings, dated roles, contact lines) and is never quarantined,
+and text with no markers at all is always let through.
+"""
+
+from __future__ import annotations
+
+import re
+from dataclasses import dataclass
+
+# Kind -> patterns that identify the document type. Matched case-insensitively.
+_MARKERS: dict[str, tuple[str, ...]] = {
+    "certificate": (
+        r"certificate\s+of\s+(?:completion|achievement|participation|attendance|appreciation|excellence"
+        r"|training|registration|incorporation|merit)",
+        r"this\s+(?:is\s+to\s+)?certif(?:ies|y)\s+that",
+        r"is\s+hereby\s+awarded",
+        r"has\s+successfully\s+completed\s+the\s+(?:course|program|training)",
+    ),
+    "travel_record": (
+        r"\bi[-\s]?94\b",
+        r"\bi[-\s]?797[a-z]?\b",
+        r"travel\s+history",
+        r"(?:arrival|departure)\s*(?:/|and)?\s*(?:arrival|departure)?\s+record",
+        r"admit\s+until\s+date",
+        r"class\s+of\s+admission",
+        r"customs\s+and\s+border\s+protection",
+        r"department\s+of\s+homeland\s+security",
+        r"boarding\s+pass",
+        r"passport\s+(?:number|no\.?)\b",
+    ),
+    "financial": (
+        r"\binvoice\s*(?:#|no\.?|number)",
+        r"\bbank\s+statement\b",
+        r"\bpay\s*(?:stub|slip)\b",
+        r"\bpayslip\b",
+        r"\bamount\s+due\b",
+        r"\bw-?2\s+wage\s+and\s+tax\b",
+    ),
+}
+
+_KIND_LABEL = {
+    "certificate": "a certificate",
+    "travel_record": "an immigration or travel record (for example an I-94)",
+    "financial": "a financial document",
+}
+
+# A heading is a short line that is (almost) only the section name.
+_HEADING_GROUPS: dict[str, tuple[str, ...]] = {
+    "experience": (
+        "experience", "work experience", "professional experience", "employment",
+        "employment history", "work history", "career history", "relevant experience",
+    ),
+    "education": ("education", "academic background", "education and training", "academics"),
+    "skills": ("skills", "technical skills", "core skills", "core competencies", "key skills", "skills and tools"),
+    "summary": ("summary", "professional summary", "profile", "objective", "career objective", "about me"),
+    "projects": ("projects", "key projects", "selected projects", "personal projects"),
+    "certifications": ("certifications", "licenses and certifications", "licenses"),
+}
+_HEADING_LOOKUP = {name: group for group, names in _HEADING_GROUPS.items() for name in names}
+
+_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
+_DATE_RANGE = re.compile(
+    rf"(?i)\b(?:{_MONTH}\s+)?(?:19|20)\d{{2}}\s*(?:-|–|—|to)\s*(?:(?:{_MONTH}\s+)?(?:19|20)\d{{2}}|present|current|now)\b"
+)
+_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
+_PHONE = re.compile(r"(?<!\d)(?:\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)")
+_BULLET = re.compile(r"^\s*[•\u2022\u25cf\u25aa\u25ba*\-–]\s+\S")
+
+_TITLE_LINES = 8  # a document-type marker this close to the top names the document
+
+
+@dataclass(frozen=True)
+class IntakeAssessment:
+    is_resume: bool
+    reason_code: str | None = None  # certificate | travel_record | financial
+    message: str | None = None
+    resume_signals: int = 0
+
+
+def _normalize_heading(line: str) -> str:
+    lowered = (line or "").lower().replace("&", " and ")
+    return " ".join(re.sub(r"[^a-z ]+", " ", lowered).split())
+
+
+def _resume_signals(text: str) -> int:
+    """Count independent resume-structure signals (0..N)."""
+    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
+    headings = {
+        _HEADING_LOOKUP[norm]
+        for ln in lines
+        if len(ln) <= 40 and (norm := _normalize_heading(ln)) in _HEADING_LOOKUP
+    }
+    signals = len(headings)
+    if len(_DATE_RANGE.findall(text or "")) >= 1:
+        signals += 1
+    if _EMAIL.search(text or "") or _PHONE.search(text or ""):
+        signals += 1
+    if sum(1 for ln in lines if _BULLET.match(ln)) >= 2:
+        signals += 1
+    return signals
+
+
+def _marker_hits(text: str) -> tuple[dict[str, int], dict[str, bool]]:
+    """Per-kind marker counts, and whether a kind's marker appears near the top."""
+    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
+    top = "\n".join(lines[:_TITLE_LINES])
+    counts: dict[str, int] = {}
+    in_title: dict[str, bool] = {}
+    for kind, patterns in _MARKERS.items():
+        total = 0
+        near_top = False
+        for pat in patterns:
+            rx = re.compile(pat, re.IGNORECASE)
+            total += len(rx.findall(text or ""))
+            near_top = near_top or bool(rx.search(top))
+        if total:
+            counts[kind] = total
+            in_title[kind] = near_top
+    return counts, in_title
+
+
+def assess_resume_intake(text: str) -> IntakeAssessment:
+    """Decide whether extracted text may proceed to resume generation.
+
+    Quarantine requires BOTH: a non-resume marker (near the top of the document, or at
+    least two marker hits) and weak resume structure (fewer than two resume signals).
+    """
+    counts, in_title = _marker_hits(text)
+    signals = _resume_signals(text)
+    if not counts:
+        return IntakeAssessment(True, resume_signals=signals)
+
+    kind = max(counts, key=lambda k: (in_title.get(k, False), counts[k]))
+    marker_strong = in_title.get(kind, False) or counts[kind] >= 2
+    # A real resume that merely mentions "I-94" or lists a certificate still has structure.
+    if marker_strong and signals < 2:
+        message = (
+            f"This file looks like {_KIND_LABEL[kind]}, not a resume, so no document was generated. "
+            "Upload the candidate's resume (PDF, DOC, or DOCX) instead."
+        )
+        return IntakeAssessment(False, reason_code=kind, message=message, resume_signals=signals)
+    return IntakeAssessment(True, resume_signals=signals)
diff --git a/backend/app/services/output_integrity.py b/backend/app/services/output_integrity.py
index 8dd257f..065b0b4 100644
--- a/backend/app/services/output_integrity.py
+++ b/backend/app/services/output_integrity.py
@@ -21,12 +21,13 @@ from typing import Any
 
 from docx import Document
 from docx.table import Table
 from docx.text.paragraph import Paragraph
 
 from app.services.docx_layout import clean_education_title_dates
+from app.services.pdf_ocr import format_page_refs
 
 # Below this share of a core field found in the output, the document is marked failed.
 _FAIL_RATIO = 0.5
 _CORE_CHECKS = ("companies", "titles", "dates", "bullets")
 
 BLOCKING = "blocking"
@@ -365,18 +366,22 @@ def check_output_integrity(
     if unread:
         warnings.append(
             _finding(
                 BLOCKING,
                 "source_pages_unread",
                 f"{len(unread)} page(s) of the source look like scanned images and could not be read "
-                "(OCR is not available); their content is missing.",
+                f"({format_page_refs(unread)}; OCR is not available); their content is missing.",
             )
         )
     if ocr:
         warnings.append(
-            _finding(INFO, "ocr_used", f"{len(ocr)} page(s) were read with OCR; check names, dates, and numbers.")
+            _finding(
+                INFO,
+                "ocr_used",
+                f"{len(ocr)} page(s) were read with OCR ({format_page_refs(ocr)}); check names, dates, and numbers.",
+            )
         )
 
     if source_text:
         facts = list(
             dict.fromkeys(
                 n
diff --git a/backend/app/services/pdf_ocr.py b/backend/app/services/pdf_ocr.py
index bbf0750..14915b2 100644
--- a/backend/app/services/pdf_ocr.py
+++ b/backend/app/services/pdf_ocr.py
@@ -11,12 +11,34 @@ import shutil
 from app.core.config import settings
 
 
 class OcrUnavailableError(RuntimeError):
     """A PDF has no readable text and OCR is not installed or is disabled."""
 
+    def __init__(self, message: str, pages: list[int] | None = None) -> None:
+        super().__init__(message)
+        self.pages: list[int] = list(pages or [])
+
+
+def format_page_refs(pages: list[int] | tuple[int, ...]) -> str:
+    """1-based, recruiter-readable page references: 'page 2', 'pages 1-3 and 5'."""
+    nums = sorted({int(p) for p in pages if int(p) > 0})
+    if not nums:
+        return ""
+    runs: list[tuple[int, int]] = []
+    for n in nums:
+        if runs and n == runs[-1][1] + 1:
+            runs[-1] = (runs[-1][0], n)
+        else:
+            runs.append((n, n))
+    parts = [str(a) if a == b else f"{a}-{b}" for a, b in runs]
+    if len(nums) == 1:
+        return f"page {parts[0]}"
+    joined = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + f" and {parts[-1]}"
+    return f"pages {joined}"
+
 
 def ocr_available() -> bool:
     if not settings.RESUME_OCR_ENABLED or shutil.which("tesseract") is None:
         return False
     try:
         import pymupdf as fitz
diff --git a/backend/app/services/pdf_parser.py b/backend/app/services/pdf_parser.py
index c482810..5a6f162 100644
--- a/backend/app/services/pdf_parser.py
+++ b/backend/app/services/pdf_parser.py
@@ -1,9 +1,10 @@
 """Utility service for extracting raw text from PDF and Word documents."""
 import html as html_lib
 import re
+import shutil
 from contextvars import ContextVar
 from html.parser import HTMLParser
 from pathlib import Path
 
 import pdfplumber
 
@@ -218,13 +219,13 @@ def finalize_pdf_text(text: str) -> str:
     # Drop lines that are a lone icon-font glyph (e.g. a private-use or Latin-1 symbol).
     output = [ln for ln in output if not re.fullmatch(r"\s*[À-ÿ-]\s*", ln)]
     return "\n".join(output)
 
 
 def _new_meta() -> dict:
-    return {"ocr_pages": [], "ocr_missing_pages": []}
+    return {"ocr_pages": [], "ocr_missing_pages": [], "doc_converted": False}
 
 
 _LAST_META: ContextVar[dict] = ContextVar("document_extraction_meta", default=_new_meta())
 
 
 def last_extraction_meta() -> dict:
@@ -262,12 +263,13 @@ def extract_text_from_document(
                 text = _extract_pdf(path, meta).strip()
             text = finalize_pdf_text(text)
         elif ext == ".docx":
             text = _extract_docx(path, max_chars=max_chars if lightweight else None).strip()
         elif ext == ".doc":
             text = _extract_doc(path, max_chars=max_chars if lightweight else None).strip()
+            meta["doc_converted"] = True
         elif ext in (".html", ".htm"):
             text = _extract_html(path).strip()
         else:
             return ""
     except Exception as exc:
         from app.services.doc_converter import DocConversionError
@@ -441,21 +443,25 @@ def extract_text_from_pdf(path: str) -> str:
 
 
 def _extract_doc(path: str, *, max_chars: int | None = None) -> str:
     """Extract text from legacy .doc by converting to .docx first."""
     from app.services.doc_converter import DocConversionError, convert_doc_to_docx
 
+    converted: Path | None = None
     try:
         converted = convert_doc_to_docx(Path(path))
         return _extract_docx(str(converted), max_chars=max_chars).strip()
     except DocConversionError as exc:
         logger.error("doc_conversion_failed", path=path, error=str(exc))
         raise
     except Exception as exc:
         logger.error("doc_extraction_unexpected", path=path, error=str(exc))
         raise DocConversionError(f"Unexpected .doc extraction failure: {exc}") from exc
+    finally:
+        if converted is not None and converted.parent.name.startswith("doc_convert_"):
+            shutil.rmtree(converted.parent, ignore_errors=True)
 
 
 _ICON_TOKEN = re.compile(r"^\(cid:\d+\)$")
 _DATE_ONLY_TEXT = re.compile(
     r"(?i)^(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{4}\s*[-–—/]\s*"
     r"(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{4}|present|current|\d{4})$"
@@ -1062,14 +1068,19 @@ def _extract_pdf_with_ocr(path: str, need: list[int], meta: dict) -> str:
                 meta["ocr_pages"].append(i + 1)
             else:
                 meta["ocr_missing_pages"].append(i + 1)
                 text = page.get_text("text") or ""
             pages.append(text)
     combined = "\n\n".join(_strip_repeated_header_footer([p for p in pages if p.strip()])).strip()
-    if meta["ocr_missing_pages"] and sum(c.isalpha() for c in combined) < 100:
-        raise pdf_ocr.OcrUnavailableError("PDF has no readable text layer and OCR is unavailable")
+    # Nothing readable at all: fail loudly. If OCR recovered any page, the draft proceeds and
+    # the unread pages are reported through ocr_missing_pages (blocking integrity finding).
+    if meta["ocr_missing_pages"] and not meta["ocr_pages"] and sum(c.isalpha() for c in combined) < 100:
+        raise pdf_ocr.OcrUnavailableError(
+            "PDF has no readable text layer and OCR is unavailable",
+            pages=list(meta["ocr_missing_pages"]),
+        )
     logger.info(
         "pdf_ocr_used",
         ocr_pages=len(meta["ocr_pages"]),
         missing_pages=len(meta["ocr_missing_pages"]),
     )
     return combined
diff --git a/backend/tests/test_intake_gate.py b/backend/tests/test_intake_gate.py
new file mode 100644
index 0000000..542de82
--- /dev/null
+++ b/backend/tests/test_intake_gate.py
@@ -0,0 +1,272 @@
+"""Intake hardening: OCR paths, legacy .doc conversion, and non-resume quarantine.
+
+Tesseract and LibreOffice are not required: OCR and conversion are monkeypatched.
+"""
+
+from __future__ import annotations
+
+import json
+from pathlib import Path
+
+import pymupdf as fitz
+import pytest
+from docx import Document
+from fastapi.testclient import TestClient
+
+from app.api.routes import generate as generate_route
+from app.main import app
+from app.services import doc_converter, pdf_ocr
+from app.services.intake_gate import assess_resume_intake
+from app.services.output_integrity import check_output_integrity
+from app.services.pdf_ocr import OcrUnavailableError, format_page_refs
+from app.services.pdf_parser import extract_document
+from tests.test_output_integrity import FULL, STORE, _docx
+
+GOLDEN = Path(__file__).parent / "fixtures" / "golden"
+OCR_TEXT = "OCR RECOVERED: Casey Example\nEXPERIENCE\nSenior Engineer | ExampleCorp - 2020 - Present"
+
+
+def _case(name: str) -> str:
+    return (GOLDEN / "cases" / f"{name}.txt").read_text(encoding="utf-8")
+
+
+def _post(filename: str, payload: bytes, mime: str = "application/pdf"):
+    return TestClient(app).post("/api/generate", files={"resume": (filename, payload, mime)})
+
+
+def _ocr_on(monkeypatch, text: str = OCR_TEXT):
+    monkeypatch.setattr(pdf_ocr, "ocr_available", lambda: True)
+    monkeypatch.setattr(pdf_ocr, "ocr_page_text", lambda page, dpi=None: text)
+
+
+def _ocr_off(monkeypatch):
+    monkeypatch.setattr(pdf_ocr, "ocr_available", lambda: False)
+
+
+# --- OCR ---------------------------------------------------------------------------------------
+
+
+def test_ocr_unavailable_whole_scan_returns_clear_error(fixtures, monkeypatch):
+    _ocr_off(monkeypatch)
+    with pytest.raises(OcrUnavailableError) as info:
+        extract_document(str(fixtures["scanned_pdf"]))
+    assert info.value.pages == [1]
+
+    resp = _post("scan.pdf", Path(fixtures["scanned_pdf"]).read_bytes())
+    assert resp.status_code == 422
+    detail = resp.json()["detail"]
+    assert "scanned" in detail and "page 1" in detail
+    assert "Traceback" not in detail and "Error" not in detail
+
+
+def test_image_only_pdf_with_ocr_recovers_text_and_meta(fixtures, monkeypatch):
+    _ocr_on(monkeypatch)
+    text, meta = extract_document(str(fixtures["scanned_pdf"]))
+    assert "Casey Example" in text
+    assert meta["ocr_pages"] == [1]
+    assert meta["ocr_missing_pages"] == []
+    assert meta["doc_converted"] is False
+
+
+def test_ocr_text_merges_in_source_page_order(fixtures, monkeypatch):
+    _ocr_on(monkeypatch)
+    text, meta = extract_document(str(fixtures["mixed_pdf"]))
+    assert meta["ocr_pages"] == [2] and meta["ocr_missing_pages"] == []
+    assert text.index("Globex") < text.index("OCR RECOVERED")
+
+
+def test_mixed_pdf_without_ocr_marks_missing_pages(fixtures, monkeypatch):
+    _ocr_off(monkeypatch)
+    text, meta = extract_document(str(fixtures["mixed_pdf"]))
+    assert "Globex" in text
+    assert meta["ocr_missing_pages"] == [2] and meta["ocr_pages"] == []
+
+
+def test_mixed_pdf_partial_draft_marks_missing_pages():
+    meta = {"ocr_pages": [1], "ocr_missing_pages": [2]}
+    report = check_output_integrity(STORE, _docx(*FULL), extraction_meta=meta)
+    assert report.status == "needs_review"
+    blocking = [w for w in report.warnings if w["severity"] == "blocking" and w["code"] == "source_pages_unread"]
+    assert blocking and "page 2" in blocking[0]["message"]
+    info = [w for w in report.warnings if w["code"] == "ocr_used"]
+    assert info and info[0]["severity"] == "info" and "page 1" in info[0]["message"]
+
+
+def test_recovered_and_unreadable_pages_are_tracked_separately(fixtures, monkeypatch):
+    # OCR yields text only for the first call; the second flagged page stays unreadable.
+    calls = {"n": 0}
+
+    def flaky(page, dpi=None):
+        calls["n"] += 1
+        return OCR_TEXT if calls["n"] == 1 else ""
+
+    monkeypatch.setattr(pdf_ocr, "ocr_available", lambda: True)
+    monkeypatch.setattr(pdf_ocr, "ocr_page_text", flaky)
+    path = Path(fixtures["scanned_pdf"]).parent / "two_scans.pdf"
+    with fitz.open(fixtures["scanned_pdf"]) as a, fitz.open() as out:
+        out.insert_pdf(a)
+        out.insert_pdf(a)
+        out.save(path)
+    text, meta = extract_document(str(path))
+    assert "OCR RECOVERED" in text
+    assert meta["ocr_pages"] == [1] and meta["ocr_missing_pages"] == [2]
+
+
+def test_page_refs_are_one_based_and_readable():
+    assert format_page_refs([]) == ""
+    assert format_page_refs([2]) == "page 2"
+    assert format_page_refs([1, 2, 3]) == "pages 1-3"
+    assert format_page_refs([5, 1, 2]) == "pages 1-2 and 5"
+    assert format_page_refs([1, 3, 5]) == "pages 1, 3 and 5"
+
+
+# --- Legacy .doc -------------------------------------------------------------------------------
+
+OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64
+
+
+def test_doc_converts_and_reports_doc_converted(tmp_path, monkeypatch):
+    source = tmp_path / "legacy.doc"
+    source.write_bytes(OLE_MAGIC)
+    converted = tmp_path / "converted" / "legacy.docx"
+    converted.parent.mkdir()
+    doc = Document()
+    for line in _case("legacy_doc").splitlines():
+        doc.add_paragraph(line)
+    doc.save(converted)
+
+    monkeypatch.setattr(doc_converter, "convert_doc_to_docx", lambda p, output_dir=None: converted)
+    text, meta = extract_document(str(source))
+    assert "Litware" in text and "Casey Example" in text
+    assert meta["doc_converted"] is True
+
+
+def test_doc_missing_libreoffice_422(tmp_path, monkeypatch):
+    monkeypatch.setattr(doc_converter, "find_libreoffice", lambda: None)
+    monkeypatch.setattr(doc_converter, "_convert_with_word", lambda source, out: None)
+
+    with pytest.raises(doc_converter.DocConversionError):
+        doc_converter.convert_doc_to_docx(_write(tmp_path / "a.doc", OLE_MAGIC))
+
+    resp = _post("resume.doc", OLE_MAGIC, "application/msword")
+    assert resp.status_code == 422
+    detail = resp.json()["detail"]
+    assert ".docx" in detail
+    assert "soffice" not in detail.lower() and "libreoffice" not in detail.lower()
+
+
+def test_doc_conversion_failure_422_hides_converter_internals(tmp_path, monkeypatch):
+    class _Result:
+        returncode = 1
+        stdout = ""
+        stderr = "SECRET /usr/lib/libreoffice crash"
+
+    monkeypatch.setattr(doc_converter, "find_libreoffice", lambda: "soffice")
+    monkeypatch.setattr(doc_converter.subprocess, "run", lambda *a, **k: _Result())
+    monkeypatch.setattr(doc_converter, "_poll_docx", lambda *a, **k: None)
+
+    with pytest.raises(doc_converter.DocConversionError) as info:
+        doc_converter.convert_doc_to_docx(_write(tmp_path / "b.doc", OLE_MAGIC))
+    assert "SECRET" not in str(info.value) and ".docx" in str(info.value)
+
+    resp = _post("resume.doc", OLE_MAGIC, "application/msword")
+    assert resp.status_code == 422
+    assert ".docx" in resp.json()["detail"] and "SECRET" not in resp.json()["detail"]
+
+
+def _write(path: Path, payload: bytes) -> Path:
+    path.write_bytes(payload)
+    return path
+
+
+# --- Non-resume quarantine ---------------------------------------------------------------------
+
+REALISTIC_CERTIFICATE = """CERTIFICATE OF COMPLETION
+This is to certify that Casey Example
+has successfully completed the course Project Management Fundamentals
+Issued March 14, 2024
+Signature
+"""
+
+REALISTIC_I94 = """U.S. Department of Homeland Security
+U.S. Customs and Border Protection
+Departure/Arrival Record - Form I-94
+Admit Until Date: 08/14/2027
+Class of Admission: H-1B
+Most Recent I-94
+"""
+
+TRAVEL_HISTORY = """Travel History
+Casey Example
+Entry 03/02/2023 - Dallas, TX
+Exit 04/11/2023 - Dallas, TX
+"""
+
+
+@pytest.mark.parametrize("name", ["non_resume_certificate", "non_resume_travel"])
+def test_golden_non_resume_stubs_are_quarantined(name):
+    result = assess_resume_intake(_case(name))
+    assert result.is_resume is False and result.reason_code
+
+
+@pytest.mark.parametrize(
+    "text,reason",
+    [
+        (REALISTIC_CERTIFICATE, "certificate"),
+        (REALISTIC_I94, "travel_record"),
+        (TRAVEL_HISTORY, "travel_record"),
+        ("INVOICE #4411\nBill to: Litware\nAmount due: $1,200.00\nInvoice number 4411", "financial"),
+    ],
+)
+def test_non_resume_quarantine_reasons(text, reason):
+    result = assess_resume_intake(text)
+    assert result.is_resume is False
+    assert result.reason_code == reason
+    assert "not a resume" in result.message and "Upload" in result.message
+
+
+def test_non_resume_quarantine_422(monkeypatch):
+    monkeypatch.setattr(generate_route, "extract_document", lambda path, **kw: (REALISTIC_I94, {}))
+    resp = _post("i94.pdf", b"%PDF-1.4 stub")
+    assert resp.status_code == 422
+    detail = resp.json()["detail"]
+    assert "not a resume" in detail and "I-94" in detail
+
+
+def test_non_resume_certificate_422_via_api(monkeypatch):
+    monkeypatch.setattr(generate_route, "extract_document", lambda path, **kw: (REALISTIC_CERTIFICATE, {}))
+    resp = _post("cert.pdf", b"%PDF-1.4 stub")
+    assert resp.status_code == 422 and "certificate" in resp.json()["detail"]
+
+
+@pytest.mark.parametrize(
+    "name",
+    ["sparse_valid", "education_only", "skills_only", "title_only", "sparse_profile_full", "scanned_stub", "legacy_doc"],
+)
+def test_sparse_valid_resume_not_quarantined(name):
+    assert assess_resume_intake(_case(name)).is_resume is True
+
+
+def test_every_golden_resume_case_passes_the_gate():
+    manifest = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
+    checked = 0
+    for fixture in manifest["fixtures"]:
+        quarantined = fixture.get("expected_status") == "quarantine"
+        result = assess_resume_intake((GOLDEN / fixture["source"]).read_text(encoding="utf-8"))
+        assert result.is_resume is (not quarantined), fixture["id"]
+        checked += 1
+    assert checked >= 40
+
+
+def test_resume_mentioning_i94_or_certificate_is_not_quarantined():
+    text = (
+        "Casey Example\ncasey@example.com\nSUMMARY\nAnalyst on an H-1B (I-94 valid to 2027).\n"
+        "EXPERIENCE\nAnalyst | Litware - 2021 - Present\n- Closed the books.\n- Built reports.\n"
+        "CERTIFICATIONS\nCertificate of Completion, Project Management Fundamentals\n"
+    )
+    assert assess_resume_intake(text).is_resume is True
+
+
+def test_minimal_resume_without_markers_is_never_quarantined():
+    assert assess_resume_intake("Casey Example\nAnalyst at Litware since 2021").is_resume is True
+    assert assess_resume_intake("").is_resume is True
