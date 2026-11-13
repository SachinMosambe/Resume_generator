# Review package Task 1 (after fix)
BASE: 9ea9cfefb3d659106d8992fd91548759b6471a0d
HEAD: aeb8bd9b10157036c1f17146de535bae4b2a3c92
## Commits
aeb8bd9 fix: ignore Employment Type metadata in employment evidence 441c08a feat: detect source employment evidence independent of parse
## Diff stat
 .superpowers/sdd/task-1-report.md       | 36 +++++++++++++++++++++++++  backend/app/services/source_evidence.py | 47 +++++++++++++++++++++++++++++++++  backend/tests/test_source_evidence.py   | 36 +++++++++++++++++++++++++  3 files changed, 119 insertions(+)
diff --git a/.superpowers/sdd/task-1-report.md b/.superpowers/sdd/task-1-report.md
new file mode 100644
index 0000000..b129264
--- /dev/null
+++ b/.superpowers/sdd/task-1-report.md
@@ -0,0 +1,36 @@
+# Task 1 Report: Source employment evidence
+
+## Status
+
+Completed Steps 1–5 using test-driven development.
+
+Commit: `441c08a feat: detect source employment evidence independent of parse`
+
+## Changes
+
+- Added `backend/tests/test_source_evidence.py` using the three existing synthetic golden text fixtures.
+- Added `backend/app/services/source_evidence.py`.
+- Implemented `EmploymentEvidence` and `detect_employment_evidence(source_text)`.
+- Evidence references contain only opaque zero-based line indexes, capped at 20.
+- The implementation does not log resume text or evidence content.
+
+## TDD evidence
+
+1. Added the requested tests before production code.
+2. Initial test execution failed during test setup because repository dependencies were missing.
+3. Installed the declared backend requirements and implemented the minimal detector from the brief.
+4. Final command:
+   `PYTHONPATH=backend py -3.12 -m pytest backend/tests/test_source_evidence.py -v`
+5. Result: `2 passed in 0.02s`.
+
+## Concerns
+
+- The exact brief command requires `backend` on `PYTHONPATH` in this Windows environment.
+- The initial red run was blocked by missing test-environment dependencies before collection reached the expected missing detector module.
+
+## Important quality finding fix
+
+- Tightened `_EXP_HEAD` to accept only complete headings: Experience, Work History, Employment History, Job History, and Professional Experience.
+- Added a regression test proving Dice-style `Employment Type` metadata plus an education year does not imply work history.
+- Red: `1 failed, 2 passed` before the regex fix.
+- Green: `3 passed in 0.02s` after the fix; existing Dice, bullet-only, and education-only coverage remains green.
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
diff --git a/backend/tests/test_source_evidence.py b/backend/tests/test_source_evidence.py
new file mode 100644
index 0000000..8e8d5bd
--- /dev/null
+++ b/backend/tests/test_source_evidence.py
@@ -0,0 +1,36 @@
+from app.services.source_evidence import detect_employment_evidence
+
+
+DICE = open(
+    __file__.replace(
+        "test_source_evidence.py", "fixtures/golden/cases/dice_wrapper.txt"
+    ),
+    encoding="utf-8",
+).read()
+EDU = open(
+    __file__.replace(
+        "test_source_evidence.py", "fixtures/golden/cases/education_only.txt"
+    ),
+    encoding="utf-8",
+).read()
+BULLET = open(
+    __file__.replace(
+        "test_source_evidence.py", "fixtures/golden/cases/bullet_only.txt"
+    ),
+    encoding="utf-8",
+).read()
+
+
+def test_dice_and_bullet_sources_flag_work_history():
+    assert detect_employment_evidence(DICE).has_work_history is True
+    assert detect_employment_evidence(BULLET).has_work_history is True
+
+
+def test_education_only_has_no_work_history():
+    assert detect_employment_evidence(EDU).has_work_history is False
+
+
+def test_employment_type_metadata_has_no_work_history():
+    source = "Employment Type\nFull-time\nEducation\nBS Computer Science 2018\n"
+
+    assert detect_employment_evidence(source).has_work_history is False
