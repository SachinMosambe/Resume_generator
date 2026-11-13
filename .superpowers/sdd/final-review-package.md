# Final whole-branch review package
MERGE_BASE: 9b6b1a75ed65142e3e645fb7f93075896eecc9a6
HEAD: ba76b0fb48a6473e1c6cd2a6138a42f647f2490e
## Commits
ba76b0f fix: require needs_review for unassigned-bullet golden fixtures 1a87c7f ci: enforce corpus golden quality gates on pull requests ed2e9a0 fix: keep Aptino/Suresh style tests when Capgemini template missing d210608 feat: assert Capgemini/Suresh style and hide empty projects d7d82fa fix: keep verified duration and location over cross-role LLM repairs 1fcaf3a fix: tighten LLM repair source checks for dates, survival, and role blocks 1356893 feat: add optional source-checked LLM parse repair fallback 324ed95 feat: harden intake for OCR, legacy DOC, and non-resume rejection 31ac2e8 fix: integrity review severity and additive warning headers 6900252 feat: make integrity review actionable with source-aware severity 4855712 fix: recover title-only experience roles under Experience heading 24d27dd feat: recover Dice, split-header, and bullet-only experience in faithful parse aeb8bd9 fix: ignore Employment Type metadata in employment evidence 441c08a feat: detect source employment evidence independent of parse 9ea9cfe fix: unscored golden fixtures until binary builders exist f924a4b test: pin corpus baseline case map and golden manifest skeleton
## Diff stat
 .github/workflows/ci.yml                           |   24 +  .superpowers/sdd/task-0-report.md                  |   87 ++  .superpowers/sdd/task-1-report.md                  |   36 +  .superpowers/sdd/task-3-report.md                  |   41 +  .superpowers/sdd/task-5-report.md                  |   45 +  .superpowers/sdd/task-6-report.md                  |   35 +  .superpowers/sdd/task-7-report.md                  |   82 ++  README.md                                          |    3 +-  backend/app/api/routes/generate.py                 |   29 +-  backend/app/core/config.py                         |    4 +  backend/app/main.py                                |    1 +  backend/app/services/detailed_resume_parser.py     |  136 +-  backend/app/services/doc_converter.py              |    5 +-  backend/app/services/docx_layout.py                |   12 +  backend/app/services/docx_skeleton_service.py      |    5 +  backend/app/services/intake_gate.py                |  147 ++  backend/app/services/llm_structure_repair.py       |  437 ++++++  backend/app/services/output_integrity.py           |  335 ++++-  backend/app/services/parse_confidence.py           |   40 +  backend/app/services/pdf_ocr.py                    |   22 +  backend/app/services/pdf_parser.py                 |   17 +-  backend/app/services/resume_generation_service.py  |   17 +  backend/app/services/source_evidence.py            |   47 +  backend/app/services/structured_resume_store.py    |    7 +  backend/eval_reports/baseline_case_map.md          |   63 +  backend/scripts/corpus_quality_eval.py             |  992 +++++++++++++  .../tests/fixtures/golden/build_golden_fixtures.py |  106 ++  .../fixtures/golden/cases/ambiguous_dates.txt      |    7 +  .../fixtures/golden/cases/ambiguous_headers.txt    |    8 +  .../tests/fixtures/golden/cases/ambiguous_name.txt |    7 +  .../tests/fixtures/golden/cases/ambiguous_swap.txt |    7 +  .../tests/fixtures/golden/cases/bullet_only.txt    |    8 +  .../fixtures/golden/cases/bullet_only_dated.txt    |    8 +  .../tests/fixtures/golden/cases/caps_sections.txt  |    9 +  .../tests/fixtures/golden/cases/certifications.txt |    9 +  .../fixtures/golden/cases/clean_conventional.txt   |   13 +  .../tests/fixtures/golden/cases/clean_one_role.txt |    9 +  .../fixtures/golden/cases/clean_with_projects.txt  |   14 +  .../golden/cases/clean_without_projects.txt        |   11 +  .../tests/fixtures/golden/cases/contact_header.txt |    8 +  .../tests/fixtures/golden/cases/current_role.txt   |    7 +  .../fixtures/golden/cases/dice_inside_resume.txt   |   12 +  .../fixtures/golden/cases/dice_labels_only.txt     |   16 +  .../tests/fixtures/golden/cases/dice_wrapper.txt   |   31 +  .../fixtures/golden/cases/education_one_role.txt   |    8 +  .../tests/fixtures/golden/cases/education_only.txt |    6 +  .../tests/fixtures/golden/cases/emdash_header.txt  |    7 +  .../tests/fixtures/golden/cases/empty_title.txt    |    5 +  backend/tests/fixtures/golden/cases/legacy_doc.txt |    7 +  .../fixtures/golden/cases/legacy_doc_contract.txt  |    7 +  .../fixtures/golden/cases/legacy_doc_multi.txt     |    7 +  .../tests/fixtures/golden/cases/long_bullets.txt   |   14 +  .../tests/fixtures/golden/cases/long_history.txt   |   33 +  .../fixtures/golden/cases/missing_optional.txt     |   11 +  .../fixtures/golden/cases/missing_summary.txt      |    9 +  .../fixtures/golden/cases/month_year_roles.txt     |    7 +  .../golden/cases/non_resume_certificate.txt        |    3 +  .../fixtures/golden/cases/non_resume_travel.txt    |    3 +  .../tests/fixtures/golden/cases/numeric_dates.txt  |   12 +  .../tests/fixtures/golden/cases/paren_title.txt    |    8 +  .../tests/fixtures/golden/cases/pipe_headers.txt   |    5 +  .../fixtures/golden/cases/promotion_ladder.txt     |   10 +  backend/tests/fixtures/golden/cases/references.txt |    7 +  .../fixtures/golden/cases/same_month_employers.txt |    7 +  .../tests/fixtures/golden/cases/scanned_mixed.txt  |    9 +  .../tests/fixtures/golden/cases/scanned_stub.txt   |    9 +  .../fixtures/golden/cases/scanned_three_page.txt   |   11 +  .../tests/fixtures/golden/cases/skills_only.txt    |    8 +  .../fixtures/golden/cases/sparse_profile_full.txt  |   18 +  .../tests/fixtures/golden/cases/sparse_valid.txt   |    7 +  .../fixtures/golden/cases/table_education.txt      |    8 +  .../fixtures/golden/cases/table_experience.txt     |    7 +  backend/tests/fixtures/golden/cases/title_only.txt |    7 +  backend/tests/fixtures/golden/cases/two_column.txt |   12 +  .../fixtures/golden/cases/two_column_sidebar.txt   |   12 +  .../fixtures/golden/cases/two_column_skills.txt    |   10 +  .../fixtures/golden/cases/unicode_bullets.txt      |    7 +  backend/tests/fixtures/golden/manifest.json        | 1461 ++++++++++++++++++++  backend/tests/fixtures/golden/style_checks.py      |  173 +++  backend/tests/fixtures/golden/synthetic_formats.py |   70 +  backend/tests/test_corpus_parse_recovery.py        |  114 ++  backend/tests/test_format_style_asserts.py         |  217 +++  backend/tests/test_golden_gate_regression.py       |  242 ++++  backend/tests/test_golden_manifest.py              |   76 +  backend/tests/test_intake_gate.py                  |  272 ++++  backend/tests/test_llm_structure_repair.py         |  407 ++++++  backend/tests/test_output_integrity.py             |  173 ++-  backend/tests/test_parse_confidence.py             |   51 +  backend/tests/test_source_evidence.py              |   36 +  frontend/src/app/page.tsx                          |   66 +-  90 files changed, 6546 insertions(+), 72 deletions(-)
.github/workflows/ci.yml
.superpowers/sdd/task-0-report.md
.superpowers/sdd/task-1-report.md
.superpowers/sdd/task-3-report.md
.superpowers/sdd/task-5-report.md
.superpowers/sdd/task-6-report.md
.superpowers/sdd/task-7-report.md
README.md
backend/app/api/routes/generate.py
backend/app/core/config.py
backend/app/main.py
backend/app/services/detailed_resume_parser.py
backend/app/services/doc_converter.py
backend/app/services/docx_layout.py
backend/app/services/docx_skeleton_service.py
backend/app/services/intake_gate.py
backend/app/services/llm_structure_repair.py
backend/app/services/output_integrity.py
backend/app/services/parse_confidence.py
backend/app/services/pdf_ocr.py
backend/app/services/pdf_parser.py
backend/app/services/resume_generation_service.py
backend/app/services/source_evidence.py
backend/app/services/structured_resume_store.py
backend/eval_reports/baseline_case_map.md
backend/scripts/corpus_quality_eval.py
backend/tests/fixtures/golden/build_golden_fixtures.py
backend/tests/fixtures/golden/cases/ambiguous_dates.txt
backend/tests/fixtures/golden/cases/ambiguous_headers.txt
backend/tests/fixtures/golden/cases/ambiguous_name.txt
backend/tests/fixtures/golden/cases/ambiguous_swap.txt
backend/tests/fixtures/golden/cases/bullet_only.txt
backend/tests/fixtures/golden/cases/bullet_only_dated.txt
backend/tests/fixtures/golden/cases/caps_sections.txt
backend/tests/fixtures/golden/cases/certifications.txt
backend/tests/fixtures/golden/cases/clean_conventional.txt
backend/tests/fixtures/golden/cases/clean_one_role.txt
backend/tests/fixtures/golden/cases/clean_with_projects.txt
backend/tests/fixtures/golden/cases/clean_without_projects.txt
backend/tests/fixtures/golden/cases/contact_header.txt
backend/tests/fixtures/golden/cases/current_role.txt
backend/tests/fixtures/golden/cases/dice_inside_resume.txt
backend/tests/fixtures/golden/cases/dice_labels_only.txt
backend/tests/fixtures/golden/cases/dice_wrapper.txt
backend/tests/fixtures/golden/cases/education_one_role.txt
backend/tests/fixtures/golden/cases/education_only.txt
backend/tests/fixtures/golden/cases/emdash_header.txt
backend/tests/fixtures/golden/cases/empty_title.txt
backend/tests/fixtures/golden/cases/legacy_doc.txt
backend/tests/fixtures/golden/cases/legacy_doc_contract.txt
backend/tests/fixtures/golden/cases/legacy_doc_multi.txt
backend/tests/fixtures/golden/cases/long_bullets.txt
backend/tests/fixtures/golden/cases/long_history.txt
backend/tests/fixtures/golden/cases/missing_optional.txt
backend/tests/fixtures/golden/cases/missing_summary.txt
backend/tests/fixtures/golden/cases/month_year_roles.txt
backend/tests/fixtures/golden/cases/non_resume_certificate.txt
backend/tests/fixtures/golden/cases/non_resume_travel.txt
backend/tests/fixtures/golden/cases/numeric_dates.txt
backend/tests/fixtures/golden/cases/paren_title.txt
backend/tests/fixtures/golden/cases/pipe_headers.txt
backend/tests/fixtures/golden/cases/promotion_ladder.txt
backend/tests/fixtures/golden/cases/references.txt
backend/tests/fixtures/golden/cases/same_month_employers.txt
backend/tests/fixtures/golden/cases/scanned_mixed.txt
backend/tests/fixtures/golden/cases/scanned_stub.txt
backend/tests/fixtures/golden/cases/scanned_three_page.txt
backend/tests/fixtures/golden/cases/skills_only.txt
backend/tests/fixtures/golden/cases/sparse_profile_full.txt
backend/tests/fixtures/golden/cases/sparse_valid.txt
backend/tests/fixtures/golden/cases/table_education.txt
backend/tests/fixtures/golden/cases/table_experience.txt
backend/tests/fixtures/golden/cases/title_only.txt
backend/tests/fixtures/golden/cases/two_column.txt
backend/tests/fixtures/golden/cases/two_column_sidebar.txt
backend/tests/fixtures/golden/cases/two_column_skills.txt
backend/tests/fixtures/golden/cases/unicode_bullets.txt
backend/tests/fixtures/golden/manifest.json
backend/tests/fixtures/golden/style_checks.py
backend/tests/fixtures/golden/synthetic_formats.py
backend/tests/test_corpus_parse_recovery.py
backend/tests/test_format_style_asserts.py
backend/tests/test_golden_gate_regression.py
backend/tests/test_golden_manifest.py
backend/tests/test_intake_gate.py
backend/tests/test_llm_structure_repair.py
backend/tests/test_output_integrity.py
backend/tests/test_parse_confidence.py
backend/tests/test_source_evidence.py
frontend/src/app/page.tsx
diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
index c463e64..dbaf585 100644
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -39,3 +39,27 @@ jobs:
       - run: pip install -r requirements.txt
       - run: python -m compileall app
       - run: python -c "from app.main import app; print(app.title)"
+
+  golden:
+    runs-on: ubuntu-latest
+    defaults:
+      run:
+        working-directory: backend
+    steps:
+      - uses: actions/checkout@v4
+      - uses: actions/setup-python@v5
+        with:
+          python-version: "3.11"
+          cache: pip
+          cache-dependency-path: backend/requirements.txt
+      - run: sudo apt-get update && sudo apt-get install -y tesseract-ocr libreoffice-writer
+      - run: pip install -r requirements.txt
+      # Fixtures only (tests/fixtures/golden); the private corpus is never needed.
+      # Capgemini style is checked against an anonymized synthetic template.
+      - run: python scripts/corpus_quality_eval.py --golden --formats aptino,capgemini,suresh
+        env:
+          RESUME_LLM_CONDENSE: "false"
+          RESUME_AGENT_PIPELINE: "false"
+          RESUME_LLM_POLISH: "false"
+          RESUME_LLM_PARSE_FALLBACK: "false"
+          RESUME_OCR_ENABLED: "true"
diff --git a/backend/app/core/config.py b/backend/app/core/config.py
index 5f4c1d7..7c9d910 100644
--- a/backend/app/core/config.py
+++ b/backend/app/core/config.py
@@ -31,6 +31,10 @@ class Settings(BaseSettings):
     APP_BUILD_ID: str = "dev"
     # When false (default), skip slow full-document LLM polish loops.
     RESUME_LLM_POLISH: bool = False
+    # Optional one-shot, source-checked LLM structure repair when the deterministic parse is
+    # weak. Default OFF (golden/scored CI stays deterministic). Rejected output is discarded.
+    RESUME_LLM_PARSE_FALLBACK: bool = False
+    RESUME_LLM_PARSE_TIMEOUT_SECONDS: float = 45.0
 
     # Multi-agent pipeline (extract -> plan -> write -> critique -> refine).
     # Runs inside the same service; enable per-deploy to compare against classic.
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
diff --git a/backend/app/services/llm_structure_repair.py b/backend/app/services/llm_structure_repair.py
new file mode 100644
index 0000000..241f4c6
--- /dev/null
+++ b/backend/app/services/llm_structure_repair.py
@@ -0,0 +1,437 @@
+"""Optional one-shot LLM structure repair for weak deterministic parses.
+
+The LLM may only *re-arrange* text that already exists in the source resume. Every
+company / title / location / date / bullet it returns must be found in the source, and
+every bullet must sit inside the source block of the employer it is assigned to.
+Anything else rejects the whole repair and the deterministic parse is returned unchanged.
+
+No resume text is logged.
+"""
+from __future__ import annotations
+
+import copy
+import json
+import re
+import threading
+from typing import Any, Callable
+
+from pydantic import BaseModel, Field, ValidationError
+
+from app.core.config import settings
+from app.core.logging import logger
+from app.services.parse_confidence import score_parse
+from app.services.source_evidence import detect_employment_evidence
+
+# client(system_prompt, user_prompt) -> parsed JSON dict (or raw JSON string)
+RepairClient = Callable[[str, str], Any]
+
+ELIGIBILITY_CONFIDENCE = 0.55
+MAX_SOURCE_CHARS = 48000
+_MIN_FACT_CHARS = 2
+
+
+class _RepairRole(BaseModel):
+    title: str = ""
+    company: str = ""
+    location: str = ""
+    duration: str = ""
+    description: list[str] = Field(default_factory=list)
+
+
+class _RepairPayload(BaseModel):
+    experience: list[_RepairRole] = Field(default_factory=list)
+
+
+# ---------------------------------------------------------------------------
+# Eligibility
+# ---------------------------------------------------------------------------
+
+def _roles(parsed: dict) -> list[dict]:
+    return [r for r in (parsed.get("experience") or []) if isinstance(r, dict)]
+
+
+def is_repair_eligible(source_text: str, parsed: dict) -> bool:
+    """True when the deterministic parse is weak AND the source shows work history."""
+    if not isinstance(parsed, dict) or not (source_text or "").strip():
+        return False
+    meta = parsed.get("parse_meta") or {}
+    if meta.get("llm_repaired"):
+        return False
+    evidence = detect_employment_evidence(source_text)
+    roles = _roles(parsed)
+    if not roles and evidence.has_work_history:
+        return True
+    if not evidence.has_work_history and not roles:
+        return False
+    confidence = meta.get("confidence")
+    if confidence is None:
+        confidence = score_parse(parsed, source_text)["confidence"]
+    if float(confidence) < ELIGIBILITY_CONFIDENCE:
+        return True
+    if roles:
+        empty = sum(1 for r in roles if not str(r.get("title") or "").strip())
+        reasons = meta.get("reasons")
+        if reasons is None:
+            reasons = score_parse(parsed, source_text)["reasons"]
+        if empty / len(roles) >= 0.5 and "source_backed_titles_unresolved" in reasons:
+            return True
+    return False
+
+
+# ---------------------------------------------------------------------------
+# Source matching
+# ---------------------------------------------------------------------------
+
+def _norm(text: Any) -> str:
+    """Casefold, drop everything that is not a letter/digit (survives reflow and bullets)."""
+    return re.sub(r"[^0-9a-z]+", "", str(text or "").casefold())
+
+
+def _positions(haystack: str, needle: str) -> list[int]:
+    out: list[int] = []
+    if not needle:
+        return out
+    start = 0
+    while True:
+        idx = haystack.find(needle, start)
+        if idx < 0:
+            return out
+        out.append(idx)
+        start = idx + 1
+
+
+def _words(text: Any) -> list[str]:
+    return re.findall(r"[0-9a-z]+", str(text or "").casefold())
+
+
+def _duration_in_source(duration: str, source_word_list: list[str]) -> bool:
+    """A duration must appear as one contiguous run of tokens (punctuation/spacing agnostic).
+
+    Tokens scattered across different roles ("2017" from one job, "Present" from another)
+    do not make a source-backed range.
+    """
+    if not duration.strip():
+        return True
+    words = _words(duration)
+    if not words:
+        return False
+    n = len(words)
+    return any(
+        source_word_list[i : i + n] == words for i in range(len(source_word_list) - n + 1)
+    )
+
+
+_BULLET_LINE_RE = re.compile(r"^\s*[•\u2022\u25cf\u25aa\u25e6\u2023\u00b7\-\*\u2013\u2014\u25a0]\s*")
+_DATE_HINT_RE = re.compile(
+    r"\b(?:19|20)\d{2}\b|\b(?:present|current|now|jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b",
+    re.IGNORECASE,
+)
+
+
+def _index_source(text: str) -> tuple[str, list[int]]:
+    """Return (``_norm(text)``, raw offset of every normalized character)."""
+    chars: list[str] = []
+    offsets: list[int] = []
+    for i, c in enumerate(text):
+        for ch in c.casefold():
+            if ch.isascii() and ch.isalnum():
+                chars.append(ch)
+                offsets.append(i)
+    return "".join(chars), offsets
+
+
+def _is_header_occurrence(raw: str, raw_idx: int) -> bool:
+    """True when the occurrence at ``raw_idx`` looks like a job header, not a mention.
+
+    A header line is not a bullet and either starts with the name or has a date on
+    the same / adjacent line.
+    """
+    line_start = raw.rfind("\n", 0, raw_idx) + 1
+    line_end = raw.find("\n", raw_idx)
+    if line_end < 0:
+        line_end = len(raw)
+    line = raw[line_start:line_end]
+    if _BULLET_LINE_RE.match(line):
+        return False
+    if not raw[line_start:raw_idx].strip():
+        return True
+    if _DATE_HINT_RE.search(line):
+        return True
+    prev_start = raw.rfind("\n", 0, max(line_start - 1, 0)) + 1
+    prev_line = raw[prev_start : max(line_start - 1, 0)] if line_start > 0 else ""
+    next_end = raw.find("\n", line_end + 1)
+    next_line = raw[line_end + 1 : next_end if next_end >= 0 else len(raw)]
+    return bool(_DATE_HINT_RE.search(prev_line) or _DATE_HINT_RE.search(next_line))
+
+
+def _header_positions(
+    raw: str, source_norm: str, offsets: list[int], key: str
+) -> list[int]:
+    """Normalized positions of ``key`` that sit in a job-header context.
+
+    Falls back to every occurrence when none looks like a header (plain layouts).
+    """
+    all_hits = _positions(source_norm, key)
+    headers = [p for p in all_hits if _is_header_occurrence(raw, offsets[p])]
+    return headers or all_hits
+
+
+# ---------------------------------------------------------------------------
+# Validation
+# ---------------------------------------------------------------------------
+
+def _parse_payload(raw: Any) -> _RepairPayload | None:
+    data = raw
+    if isinstance(raw, str):
+        try:
+            data = json.loads(re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip())
+        except (ValueError, TypeError):
+            return None
+    if not isinstance(data, dict) or not isinstance(data.get("experience"), list):
+        return None
+    for role in data["experience"]:
+        if not isinstance(role, dict):
+            return None
+        for key in ("title", "company", "location", "duration"):
+            if role.get(key) is not None and not isinstance(role.get(key), str):
+                return None
+        desc = role.get("description", [])
+        if desc is not None and (
+            not isinstance(desc, list) or any(not isinstance(b, str) for b in desc)
+        ):
+            return None
+    try:
+        return _RepairPayload.model_validate(data)
+    except ValidationError:
+        return None
+
+
+def _validate_repair(
+    payload: _RepairPayload, source_text: str, parsed: dict
+) -> tuple[list[dict[str, Any]] | None, str]:
+    """Return (normalized roles, "") when accepted, else (None, reason)."""
+    roles = payload.experience
+    if not roles:
+        return None, "empty_repair"
+
+    source_norm, offsets = _index_source(source_text)
+    source_word_list = _words(source_text)
+
+    anchors: list[tuple[int, int]] = []  # (position, role index)
+    role_positions: list[list[int]] = []
+    for i, role in enumerate(roles):
+        company = role.company.strip()
+        title = role.title.strip()
+        if not company and not title:
+            return None, "role_without_identity"
+        for label, value in (("company", company), ("title", title), ("location", role.location.strip())):
+            if not value:
+                continue
+            key = _norm(value)
+            if len(key) < _MIN_FACT_CHARS or key not in source_norm:
+                return None, f"{label}_not_in_source"
+        if not _duration_in_source(role.duration, source_word_list):
+            return None, "duration_not_in_source"
+        anchor_key = _norm(company or title)
+        # Prefer job-header occurrences so an employer mentioned inside another role's
+        # bullet neither starts a block nor truncates the real one.
+        positions = _header_positions(source_text, source_norm, offsets, anchor_key)
+        if not positions:
+            return None, "anchor_not_in_source"
+        role_positions.append(positions)
+        anchors.extend((p, i) for p in positions)
+
+    anchors.sort()
+    anchor_points = [p for p, _ in anchors]
+
+    def block_end(start: int) -> int:
+        for p in anchor_points:
+            if p > start:
+                return p
+        return len(source_norm) + 1
+
+    for i, role in enumerate(roles):
+        blocks = [(p, block_end(p)) for p in role_positions[i]]
+        for bullet in role.description:
+            key = _norm(bullet)
+            if not key:
+                continue
+            if len(key) < _MIN_FACT_CHARS:
+                return None, "bullet_not_in_source"
+            hits = _positions(source_norm, key)
+            if not hits:
+                return None, "bullet_not_in_source"
+            # The bullet text may legitimately start inside the header block; require
+            # it to sit under THIS role's employer, not another role's.
+            if not any(start <= h < end for h in hits for start, end in blocks):
+                return None, "bullet_wrong_employer"
+
+    # Existing verified facts must survive.
+    repaired_by_company: dict[str, list[_RepairRole]] = {}
+    for role in roles:
+        repaired_by_company.setdefault(_norm(role.company or role.title), []).append(role)
+    for old in _roles(parsed):
+        old_company = _norm(old.get("company"))
+        old_title = _norm(old.get("title"))
+        key = old_company or old_title
+        if not key:
+            continue
+        matches = repaired_by_company.get(key)
+        if not matches:
+            return None, "existing_role_dropped"
+        if old_title and old_company and not any(_norm(m.title) == old_title for m in matches):
+            return None, "existing_title_changed"
+        pool = {_norm(b) for m in matches for b in m.description}
+        for bullet in old.get("description") or []:
+            if _norm(bullet) and _norm(bullet) not in pool:
+                return None, "existing_bullet_dropped"
+
+    return _merge_roles(roles, _roles(parsed)), ""
+
+
+def _merge_roles(roles: list[_RepairRole], old_roles: list[dict]) -> list[dict[str, Any]]:
+    """Repair adds/fixes structure; verified deterministic fields are never dropped."""
+    unused = list(old_roles)
+    merged: list[dict[str, Any]] = []
+    for r in roles:
+        key = _norm(r.company or r.title)
+        title_key = _norm(r.title)
+        candidates = [o for o in unused if (_norm(o.get("company")) or _norm(o.get("title"))) == key]
+        old = next((o for o in candidates if title_key and _norm(o.get("title")) == title_key), None)
+        if old is None:
+            old = next((o for o in candidates if not _norm(o.get("title"))), None)
+        if old is not None:
+            unused.remove(old)
+        base: dict[str, Any] = copy.deepcopy(old) if old else {}
+        base["title"] = r.title.strip() or str(base.get("title") or "").strip()
+        base["company"] = r.company.strip() or str(base.get("company") or "").strip()
+        base["location"] = str(base.get("location") or "").strip() or r.location.strip()
+        base["duration"] = str(base.get("duration") or "").strip() or r.duration.strip()
+        base["description"] = [b.strip() for b in r.description if b.strip()]
+        technologies = base.get("technologies")
+        base["technologies"] = list(technologies) if isinstance(technologies, list) else []
+        merged.append(base)
+    return merged
+
+
+# ---------------------------------------------------------------------------
+# LLM call
+# ---------------------------------------------------------------------------
+
+_SYSTEM_PROMPT = (
+    "You repair the STRUCTURE of the work-experience section of a resume. "
+    "Copy text exactly as written in the source. Never invent, paraphrase, translate, "
+    "merge or summarize. Never add a company, title, date, location or bullet that is not "
+    "in the source. Put each bullet under the employer whose block it appears in. "
+    "If you are unsure of a field, return an empty string for it. "
+    "Return ONLY one JSON object: "
+    '{"experience":[{"title":"","company":"","location":"","duration":"","description":["..."]}]}'
+)
+
+
+def _build_user_prompt(source_text: str, parsed: dict) -> str:
+    current = [
+        {
+            "title": r.get("title") or "",
+            "company": r.get("company") or "",
+            "location": r.get("location") or "",
+            "duration": r.get("duration") or "",
+            "description": list(r.get("description") or []),
+        }
+        for r in _roles(parsed)
+    ]
+    unassigned = list(parsed.get("unassigned_experience_bullets") or [])
+    return (
+        "Current draft (may be incomplete or wrong; keep every correct role and bullet):\n"
+        f"{json.dumps({'experience': current, 'unassigned_bullets': unassigned}, ensure_ascii=False)}\n\n"
+        "SOURCE RESUME TEXT:\n"
+        f"{source_text}\n"
+    )
+
+
+def _default_client(system_prompt: str, user_prompt: str) -> Any:
+    """One Bedrock call, no JSON/validation retry loops, bounded by a wall-clock timeout."""
+    from app.agents.tools.llm_client import llm_call_json_with_metrics
+
+    box: dict[str, Any] = {}
+
+    def run() -> None:
+        try:
+            box["data"] = llm_call_json_with_metrics(
+                system_prompt,
+                user_prompt,
+                repair_attempts=0,
+                validation_attempts=0,
+                max_tokens=settings.RESUME_GENERATION_MAX_TOKENS,
+            ).data
+        except Exception as exc:  # noqa: BLE001 - surfaced to the caller as unavailable
+            box["error"] = exc
+
+    thread = threading.Thread(target=run, name="llm-structure-repair", daemon=True)
+    thread.start()
+    thread.join(timeout=float(settings.RESUME_LLM_PARSE_TIMEOUT_SECONDS))
+    if thread.is_alive():
+        raise TimeoutError("llm_structure_repair_timeout")
+    if "error" in box:
+        raise box["error"]
+    return box.get("data")
+
+
+# ---------------------------------------------------------------------------
+# Public API
+# ---------------------------------------------------------------------------
+
+def maybe_repair_parse(
+    source_text: str,
+    parsed: dict,
+    *,
+    client: RepairClient | None = None,
+) -> dict:
+    """Return a repaired parse dict, or ``parsed`` itself when ineligible / rejected.
+
+    ``parse_meta.llm_repaired`` is set to True only when a repair was accepted.
+    The caller is responsible for invoking this at most once per generation.
+    """
+    if not is_repair_eligible(source_text, parsed):
+        return parsed
+    if len(source_text) > MAX_SOURCE_CHARS:
+        logger.info("llm_structure_repair_skipped", reason="source_too_large")
+        return parsed
+
+    call = client or _default_client
+    try:
+        raw = call(_SYSTEM_PROMPT, _build_user_prompt(source_text, parsed))
+    except Exception as exc:  # noqa: BLE001 - never block generation
+        logger.warning("llm_structure_repair_unavailable", error_type=type(exc).__name__)
+        return parsed
+
+    payload = _parse_payload(raw)
+    if payload is None:
+        logger.warning("llm_structure_repair_rejected", reason="schema_invalid")
+        return parsed
+    roles, reason = _validate_repair(payload, source_text, parsed)
+    if roles is None:
+        logger.warning("llm_structure_repair_rejected", reason=reason)
+        return parsed
+
+    repaired = copy.deepcopy(parsed)
+    previous_meta = dict(parsed.get("parse_meta") or {})
+    repaired["experience"] = roles
+
+    # Bullets the deterministic parse could not place stay in review unless the repair used them.
+    placed = {_norm(b) for r in roles for b in r["description"]}
+    leftover = [
+        b for b in (parsed.get("unassigned_experience_bullets") or []) if _norm(b) not in placed
+    ]
+    if leftover:
+        repaired["unassigned_experience_bullets"] = leftover
+    else:
+        repaired.pop("unassigned_experience_bullets", None)
+
+    meta = score_parse(repaired, source_text)
+    meta["llm_repaired"] = True
+    if previous_meta.get("confidence") is not None:
+        meta["pre_repair_confidence"] = previous_meta["confidence"]
+    repaired["parse_meta"] = meta
+    logger.info("llm_structure_repair_accepted", roles=len(roles))
+    return repaired
diff --git a/backend/app/services/output_integrity.py b/backend/app/services/output_integrity.py
index 29d08b1..d5ce697 100644
--- a/backend/app/services/output_integrity.py
+++ b/backend/app/services/output_integrity.py
@@ -2,7 +2,14 @@
 
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
@@ -13,19 +20,54 @@ from dataclasses import dataclass, field
 from typing import Any
 
 from docx import Document
+from docx.table import Table
+from docx.text.paragraph import Paragraph
 
 from app.services.docx_layout import clean_education_title_dates
+from app.services.pdf_ocr import format_page_refs
 
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
@@ -35,10 +77,15 @@ def _norm(text: Any) -> str:
 
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
@@ -60,14 +107,20 @@ def _education_needle(value: Any, hay: str) -> Any:
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
@@ -79,30 +132,132 @@ _SKIP_SOURCE_LINE = re.compile(
 _SOURCE_DATE = re.compile(
     r"(?i)\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d{4}|\b\d{1,2}/\d{4}\b|\b(?:19|20)\d{2}\s*[-–—]"
 )
+# Metrics whose digits must survive verbatim: percentages and currency amounts.
+_METRIC = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?\s?[kmb]?\b|\b\d[\d,]*(?:\.\d+)?\s?%", re.IGNORECASE)
 
 
-def _source_lines_missing(source_text: str, hay: str, *, min_words: int = 6, min_share: float = 0.3) -> int:
-    """Count substantial source lines whose wording is mostly absent from the output.
+_BULLET_LINE = re.compile("^\\s*[\u2022\u25cf\u25e6\u25aa\u25a0\\-\\*]\\s*\\S")
+
+
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
+            # A bullet-marked line is resume content by construction, even when the parser
+            # never read it into a role (so no parsed fact points at it).
+            carries_fact = bool(metrics) or bool(_BULLET_LINE.match(raw)) or any(
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
@@ -114,14 +269,18 @@ def check_output_integrity(
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
 
@@ -132,6 +291,41 @@ def check_output_integrity(
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
@@ -146,10 +340,13 @@ def check_output_integrity(
     ):
         _check(key, store.get(key) or [], hay, checks, warnings, label)
 
-    suppressed = set(suppressed_sections or [])
+    suppressed = list(dict.fromkeys(suppressed_sections or []))
+    # Suppressed titles are heading-cased by the store builder ("References"), while the
+    # source title may be all-caps ("REFERENCES"); compare normalized.
+    suppressed_keys = {_norm(t) for t in suppressed}
     extras = [
         s for s in store.get("additional_sections") or []
-        if isinstance(s, dict) and s.get("title") not in suppressed
+        if isinstance(s, dict) and _norm(s.get("title")) not in suppressed_keys
     ]
     _check("additional_sections", [l for s in extras for l in s.get("lines") or []], hay, checks, warnings,
            "lines from other sections")
@@ -161,39 +358,99 @@ def check_output_integrity(
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
+                f"({format_page_refs(unread)}; OCR is not available); their content is missing.",
+            )
         )
     if ocr:
-        warnings.append(f"{len(ocr)} page(s) were read with OCR; check names, dates, and numbers.")
+        warnings.append(
+            _finding(
+                INFO,
+                "ocr_used",
+                f"{len(ocr)} page(s) were read with OCR ({format_page_refs(ocr)}); check names, dates, and numbers.",
+            )
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
diff --git a/backend/app/services/parse_confidence.py b/backend/app/services/parse_confidence.py
new file mode 100644
index 0000000..25578c9
--- /dev/null
+++ b/backend/app/services/parse_confidence.py
@@ -0,0 +1,40 @@
+"""Parse confidence scored against independent source evidence (no resume text is logged)."""
+from __future__ import annotations
+
+from typing import Any
+
+from app.services.source_evidence import detect_employment_evidence
+
+_TECH_NAMES = {"react native", "react native."}
+
+
+def score_parse(data: dict[str, Any], source_text: str) -> dict[str, Any]:
+    evidence = detect_employment_evidence(source_text)
+    roles = [r for r in (data.get("experience") or []) if isinstance(r, dict)]
+    unassigned = data.get("unassigned_experience_bullets") or []
+    reasons: list[str] = []
+    empty_titles = sum(1 for r in roles if not (r.get("title") or "").strip())
+    name = (data.get("name") or "").strip()
+    confidence = 1.0
+    if evidence.has_work_history and not roles and not unassigned:
+        reasons.append("expected_experience_missing")
+        confidence -= 0.5
+    elif evidence.has_work_history and not roles:
+        reasons.append("ambiguous_role_assignment")
+        confidence -= 0.35
+    if roles and empty_titles / max(1, len(roles)) >= 0.5:
+        reasons.append("source_backed_titles_unresolved")
+        confidence -= 0.25
+    if not name or name.lower() in _TECH_NAMES:
+        reasons.append("identity_ambiguous")
+        confidence -= 0.2
+    confidence = max(0.0, min(1.0, confidence))
+    return {
+        "confidence": confidence,
+        "reasons": reasons,
+        "llm_repaired": False,
+        "employment_evidence": {
+            "has_work_history": evidence.has_work_history,
+            "reasons": evidence.reasons,
+        },
+    }
diff --git a/backend/app/services/source_evidence.py b/backend/app/services/source_evidence.py
new file mode 100644
index 0000000..45ca2d7
--- /dev/null
+++ b/backend/app/services/source_evidence.py
@@ -0,0 +1,47 @@
+from __future__ import annotations
+
+from dataclasses import dataclass, field
+import re
+
+
+_EXP_HEAD = re.compile(
+    r"(?im)^(?:experience|work history|employment history|job history|professional experience)\s*$"
+)
+_JOBISH = re.compile(
+    r"(?i)\b(20\d{2}|present)\b|\([^)]{3,60}\)\s*\d{1,2}/\d{2,4}|\b(inc|llc|corp|ltd)\b"
+)
+
+
+@dataclass
+class EmploymentEvidence:
+    has_work_history: bool
+    reasons: list[str] = field(default_factory=list)
+    snippet_refs: list[str] = field(default_factory=list)
+
+
+def detect_employment_evidence(source_text: str) -> EmploymentEvidence:
+    lines = (source_text or "").splitlines()
+    refs: list[str] = []
+    reasons: list[str] = []
+    for i, raw in enumerate(lines):
+        line = raw.strip()
+        if not line:
+            continue
+        if _EXP_HEAD.match(line):
+            refs.append(f"line:{i}")
+            reasons.append("experience_heading")
+        elif line.startswith(("•", "-", "*")) and _JOBISH.search(line):
+            refs.append(f"line:{i}")
+            reasons.append("dated_or_employerish_bullet")
+        elif _JOBISH.search(line) and len(line) < 120:
+            refs.append(f"line:{i}")
+            reasons.append("jobish_line")
+
+    has = (
+        "experience_heading" in reasons and len(refs) >= 2
+    ) or reasons.count("dated_or_employerish_bullet") >= 3
+    return EmploymentEvidence(
+        has_work_history=has,
+        reasons=sorted(set(reasons)),
+        snippet_refs=refs[:20],
+    )
