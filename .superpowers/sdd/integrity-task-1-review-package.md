diff --git a/backend/app/services/output_integrity.py b/backend/app/services/output_integrity.py
index 0b75412..dada493 100644
--- a/backend/app/services/output_integrity.py
+++ b/backend/app/services/output_integrity.py
@@ -140,67 +140,111 @@ _SOURCE_DATE = re.compile(
 _METRIC = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?\s?[kmb]?\b|\b\d[\d,]*(?:\.\d+)?\s?%", re.IGNORECASE)
 
 
 _BULLET_LINE = re.compile("^\\s*[\u2022\u25cf\u25e6\u25aa\u25a0\\-\\*]\\s*\\S")
 
 
 def _contains(padded: str, needle: str) -> bool:
     return bool(needle) and f" {needle} " in padded
 
 
-def _classify_source_lines(
+def _source_line_classifications(
     source_text: str,
     hay: str,
     facts: list[str],
     *,
     min_words: int = 6,
     min_share: float = 0.3,
-) -> dict[str, int]:
-    """Classify substantial source lines that are mostly absent from the output.
+) -> list[tuple[str, str]]:
+    """Return raw substantial source lines paired with their integrity classification.
 
     The field checks compare parsed data with the document, so a line the parser never
     read cannot fail them. This compares the source text itself. Lines expected to change
     shape (contact details, dated role headers, profile-sheet labels) are skipped.
 
     * ``hard``: missing line that carries a required fact (employer, title, bullet text,
       or a metric number).
     * ``soft``: missing line with no required fact (wrapped/reworded prose, headings).
     * ``changed``: line is present but a percentage/currency figure from it is not.
     """
     padded = f" {hay} "
-    hard = soft = changed = 0
+    classified: list[tuple[str, str]] = []
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
             # A bullet-marked line is resume content by construction, even when the parser
             # never read it into a role (so no parsed fact points at it).
             carries_fact = bool(metrics) or bool(_BULLET_LINE.match(raw)) or any(
                 _contains(line_padded, f) or (len(f.split()) >= _MIN_ROLE_BULLET_WORDS and _contains(f" {f} ", norm_line))
                 for f in facts
             )
-            if carries_fact:
-                hard += 1
-            else:
-                soft += 1
+            classified.append((line, "hard" if carries_fact else "soft"))
         elif any(not _contains(padded, m) for m in metrics):
-            changed += 1
-    return {"hard": hard, "soft": soft, "changed": changed}
+            classified.append((line, "changed"))
+    return classified
+
+
+def _classify_source_lines(
+    source_text: str,
+    hay: str,
+    facts: list[str],
+    *,
+    min_words: int = 6,
+    min_share: float = 0.3,
+) -> dict[str, int]:
+    """Count substantial source lines by integrity classification."""
+    counts = {"hard": 0, "soft": 0, "changed": 0}
+    for _, classification in _source_line_classifications(
+        source_text, hay, facts, min_words=min_words, min_share=min_share
+    ):
+        counts[classification] += 1
+    return counts
+
+
+def _source_line_facts(store: dict[str, Any]) -> list[str]:
+    roles = [r for r in store.get("experience") or [] if isinstance(r, dict)]
+    bullets = [b for r in roles for b in (r.get("description") or []) if isinstance(b, str)]
+    return list(
+        dict.fromkeys(
+            n
+            for n in (
+                *(_norm(r.get("company")) for r in roles),
+                *(_norm(r.get("title")) for r in roles),
+                *(_norm(b) for b in bullets),
+            )
+            if len(n) >= 4
+        )
+    )
+
+
+def list_missing_hard_source_lines(
+    source_text: str, output_text: str, store: dict[str, Any]
+) -> list[str]:
+    """Return raw source lines that count as integrity hard misses (fact-bearing, absent)."""
+    missing = (
+        line
+        for line, classification in _source_line_classifications(
+            source_text, _norm(output_text), _source_line_facts(store)
+        )
+        if classification == "hard"
+    )
+    return list(dict.fromkeys(missing))
 
 
 def _source_lines_missing(source_text: str, hay: str, *, min_words: int = 6, min_share: float = 0.3) -> int:
     """Count substantial source lines whose wording is mostly absent from the output."""
     r = _classify_source_lines(source_text, hay, [], min_words=min_words, min_share=min_share)
     return r["hard"] + r["soft"]
 
 
 def _find_all(padded: str, needle: str) -> list[int]:
     if not needle:
@@ -488,31 +532,21 @@ def check_output_integrity(
     if ocr:
         warnings.append(
             _finding(
                 INFO,
                 "ocr_used",
                 f"{len(ocr)} page(s) were read with OCR ({format_page_refs(ocr)}); check names, dates, and numbers.",
             )
         )
 
     if source_text:
-        facts = list(
-            dict.fromkeys(
-                n
-                for n in (
-                    *(_norm(r.get("company")) for r in roles),
-                    *(_norm(r.get("title")) for r in roles),
-                    *(_norm(b) for b in bullets),
-                )
-                if len(n) >= 4
-            )
-        )
+        facts = _source_line_facts(store)
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
diff --git a/backend/tests/test_output_integrity.py b/backend/tests/test_output_integrity.py
index 384d752..04cb6d6 100644
--- a/backend/tests/test_output_integrity.py
+++ b/backend/tests/test_output_integrity.py
@@ -148,20 +148,50 @@ def test_source_lines_alone_do_not_force_needs_review():
 
 def test_source_line_with_required_fact_missing_needs_review():
     # The line names the employer, so a dropped line is a likely dropped bullet.
     source = "\n".join([*FULL, "Acme Corp rebuilt the ledger platform around a new event-driven architecture design"])
     report = check_output_integrity(STORE, _docx(*FULL), source_text=source)
     assert report.status == "needs_review"
     assert any(w["severity"] == "blocking" and w["code"] == "source_lines" for w in report.warnings)
     assert all("ledger" not in m.lower() for m in _msgs(report))
 
 
+def test_list_missing_hard_source_lines_finds_absent_bullet():
+    source = (
+        "Casey Example\n"
+        "Experience\n"
+        "Acme Corp — Engineer — 2020-2022\n"
+        "• Shipped the onboarding checklist for new analysts in 2021.\n"
+        "• Closed the monthly books for a small team in 2022.\n"
+    )
+    # Output has name + employer but drops the onboarding bullet line content
+    output = "Casey Example\nAcme Corp\nEngineer\nClosed the monthly books for a small team in 2022.\n"
+    store = {
+        "name": "Casey Example",
+        "experience": [
+            {
+                "company": "Acme Corp",
+                "title": "Engineer",
+                "duration": "2020-2022",
+                "description": [
+                    "Shipped the onboarding checklist for new analysts in 2021.",
+                    "Closed the monthly books for a small team in 2022.",
+                ],
+            }
+        ],
+    }
+    from app.services.output_integrity import list_missing_hard_source_lines
+
+    missing = list_missing_hard_source_lines(source, output, store)
+    assert any("onboarding checklist" in m.lower() for m in missing)
+
+
 def test_changed_factual_number_needs_review():
     source = "\n".join([*FULL, "Reduced payment settlement latency by 35% across the entire merchant platform estate"])
     out = [*FULL, "Reduced payment settlement latency by 53% across the entire merchant platform estate"]
     report = check_output_integrity(STORE, _docx(*out), source_text=source)
     assert report.status == "needs_review"
     assert any(w["code"] == "source_numbers" for w in report.warnings)
     assert all("35" not in m and "53" not in m for m in _msgs(report))
 
 
 def test_ocr_used_is_info_only():

---
LOG:
7ad222f feat: list integrity hard-missing source lines for recovery
STAT:
 backend/app/services/output_integrity.py | 76 +++++++++++++++++++++++---------  backend/tests/test_output_integrity.py   | 30 +++++++++++++  2 files changed, 85 insertions(+), 21 deletions(-)
