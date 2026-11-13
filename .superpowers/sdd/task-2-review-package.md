# Review package Task 2 (after title-only fix)
BASE: aeb8bd9b10157036c1f17146de535bae4b2a3c92
HEAD: 4855712a675ca628cce51174e2bd3ab70f9e500c
## Commits
4855712 fix: recover title-only experience roles under Experience heading 24d27dd feat: recover Dice, split-header, and bullet-only experience in faithful parse
## Diff stat
 backend/app/services/detailed_resume_parser.py  | 132 +++++++++++++++++++++++-  backend/app/services/parse_confidence.py        |  40 +++++++  backend/app/services/structured_resume_store.py |   7 ++  backend/tests/test_corpus_parse_recovery.py     | 114 ++++++++++++++++++++  backend/tests/test_parse_confidence.py          |  51 +++++++++  5 files changed, 341 insertions(+), 3 deletions(-)
diff --git a/backend/app/services/detailed_resume_parser.py b/backend/app/services/detailed_resume_parser.py
index 3b10712..74c5882 100644
--- a/backend/app/services/detailed_resume_parser.py
+++ b/backend/app/services/detailed_resume_parser.py
@@ -468,15 +468,33 @@ def _extract_portfolio(text: str) -> str:
 _NOT_A_PERSON_NAME = re.compile(
     r"(?i)\b(engineer|developer|manager|lead|architect|analyst|consultant|director|"
     r"designer|specialist|resume|curriculum|summary|skills|experience|objective)\b"
 )
 
 
+_TECH_NAME_TOKENS = {
+    "react", "native", "angular", "angularjs", "vue", "vuejs", "node", "nodejs", "js", "express",
+    "django", "flask", "spring", "boot", "hibernate", "kubernetes", "docker", "terraform", "jenkins",
+    "aws", "azure", "gcp", "sql", "nosql", "mysql", "postgresql", "mongodb", "javascript",
+    "typescript", "python", "java", "html", "css", "redux", "graphql", "kafka", "spark", "hadoop",
+    "tensorflow", "pytorch", "jquery", "android", "ios", "linux", "devops", "agile", "scrum",
+    "flutter", "dotnet", "net", "php", "kotlin", "golang", "scala", "tableau", "power", "bi",
+    "machine", "learning", "data", "science", "cloud", "api", "rest", "microservices",
+}
+
+
+def _looks_like_tech_label(text: str) -> bool:
+    """True for technology labels ("React Native.", "Spring Boot") that are not a person's name."""
+    words = [re.sub(r"[^a-z0-9]", "", w.lower()) for w in str(text or "").split()]
+    words = [w for w in words if w]
+    return bool(words) and all(w in _TECH_NAME_TOKENS for w in words)
+
+
 def _person_name_line(line: str) -> str:
     text = re.sub(r"\s+", " ", str(line or "")).strip()
-    if not text or "@" in text or _NOT_A_PERSON_NAME.search(text):
+    if not text or "@" in text or _NOT_A_PERSON_NAME.search(text) or _looks_like_tech_label(text):
         return ""
     if not re.fullmatch(r"[A-Za-z][A-Za-z .'-]*", text):
         return ""
     words = text.split()
     if not 1 <= len(words) <= 4:
         return ""
@@ -530,12 +548,14 @@ def _extract_name(text: str) -> str:
             ]
         ):
             continue
         if re.search(r"\d{4}", line):
             continue
         words = line.split()
+        if _looks_like_tech_label(line):
+            continue
         if 2 <= len(words) <= 5 and not re.search(r"[^a-zA-Z\s.\-']", line):
             title_case = sum(1 for w in words if w and w[0].isupper())
             if title_case >= len(words) // 2:
                 return line.title() if line.isupper() else line
     return ""
 
@@ -1310,12 +1330,25 @@ def _parse_job_header_line(line: str, date_match: re.Match) -> dict[str, str]:
     if " at " in before.lower() and not title:
         left, right = re.split(r"\s+at\s+", before, maxsplit=1, flags=re.IGNORECASE)
         if not _is_invalid_job_title(left):
             title = left.strip()
             company = right.strip()
 
+    # "Fabrikam Studio — Designer" before the date: employer, then a short role-word title.
+    if not title and company and "|" not in company:
+        company_title = re.match(r"^(?P<company>[^—–]{2,80}?)\s+[—–]\s+(?P<title>[^—–|,]{2,60})$", company)
+        if (
+            company_title
+            and _ROLE_WORD.search(company_title.group("title"))
+            and not _ROLE_WORD.search(company_title.group("company"))
+            and len(company_title.group("title").split()) <= 6
+            and not _is_invalid_job_title(company_title.group("title"))
+        ):
+            title = company_title.group("title").strip()
+            company = company_title.group("company").strip()
+
     # "Amazon — Seattle, WA" / "Heart and Profit — Remote": dash separates company and place.
     dash_place = re.match(r"^(?P<company>.+?)\s+[—–]\s+(?P<place>[^—–|]+)$", company)
     if dash_place and not location:
         place = dash_place.group("place").strip()
         if (
             re.fullmatch(r"(?i)remote|hybrid|on-?site", place)
@@ -1350,13 +1383,51 @@ def _parse_job_header_line(line: str, date_match: re.Match) -> dict[str, str]:
     }
     if project:
         parsed["project"] = _clean_text(project)
     return parsed
 
 
+# "(Platform Engineer) 03/19 - Present": title in parens, then the dates, below a company line.
+_PAREN_TITLE = re.compile(
+    r"^\(([^)]{2,80})\)\s*(\d{1,2}/\d{2,4}|\w+\.?\s+\d{4}|\d{4})\s*[-–—]\s*"
+    r"(Present|Current|\d{1,2}/\d{2,4}|\w+\.?\s+\d{4}|\d{4})$",
+    re.I,
+)
+
+
+def _is_title_only_header(line: str, lines: list[str], index: int) -> bool:
+    """True for a short job-title line (no dates/company) whose next non-blank line is a bullet."""
+    text = str(line or "").strip()
+    if not text or _is_bullet(text) or len(text) > 60 or len(text.split()) > 6:
+        return False
+    if text.endswith((".", ":", ";", ",")) or "@" in text or any(ch.isdigit() for ch in text):
+        return False
+    if not text[0].isupper() or _ACTION_VERB_START.match(text):
+        return False
+    if _DATE_PATTERN.search(text) or _is_section_heading_line(text) or _is_caps_section_label(text):
+        return False
+    if _is_invalid_job_title(text) or not _ROLE_WORD.search(text):
+        return False
+    nxt = index + 1
+    while nxt < len(lines) and not lines[nxt].strip():
+        nxt += 1
+    return nxt < len(lines) and _is_bullet(lines[nxt].strip())
+
+
 def _extract_experience(text: str) -> list[dict[str, Any]]:
+    roles, _orphans = _extract_experience_detailed(text)
+    return roles
+
+
+def _extract_experience_detailed(text: str) -> tuple[list[dict[str, Any]], list[str]]:
+    """Return (roles, orphan_bullets).
+
+    Orphan bullets are bullets inside an Experience section that precede any
+    recognised employer/title header. They are only meaningful when no role is found.
+    """
+    orphan_bullets: list[str] = []
     blocks = _section_blocks(text, _SECTION_HEADINGS["experience"])
     dated = [block for block in blocks if any(_DATE_PATTERN.search(line or "") for line in block)]
     chosen = dated or [block for block in blocks if any(line.strip() for line in block)]
     if chosen:
         lines = []
         for block in chosen:
@@ -1396,12 +1467,15 @@ def _extract_experience(text: str) -> list[dict[str, Any]]:
             ):
                 current_job = None
                 current_bullets = []
                 return
             # Keep Environment techs only — never invent tools from bullet keyword scans.
             experiences.append(current_job)
+        elif current_job and current_bullets:
+            # Date-only header with no employer/title: keep the bullets for review.
+            orphan_bullets.extend(b for b in current_bullets if b and not re.match(r"(?i)^environment\s*:", b))
         current_job = None
         current_bullets = []
 
     i = 0
     while i < len(lines):
         line = lines[i].strip()
@@ -1449,12 +1523,34 @@ def _extract_experience(text: str) -> list[dict[str, Any]]:
             current_bullets = []
             pending_company = ""
             i += step
             continue
         next_date = _DATE_PATTERN.search(next_line) if next_line and not _is_bullet(next_line) else None
 
+        # Split header: "Company" then "(Title) 03/19 - Present" (blank lines allowed between).
+        if not date_match and not _is_bullet(line) and not _PAREN_TITLE.match(line):
+            look_ahead = i + 1
+            while look_ahead < len(lines) and not lines[look_ahead].strip():
+                look_ahead += 1
+            paren_line = lines[look_ahead].strip() if look_ahead < len(lines) else ""
+            paren_next = _PAREN_TITLE.match(paren_line) if paren_line else None
+            if paren_next and len(line) <= 100 and not _is_cover_label_line(line):
+                _save_current()
+                pending_company = ""
+                current_job = {
+                    "title": _clean_text(paren_next.group(1)),
+                    "company": _clean_text(line),
+                    "location": "",
+                    "duration": _clean_text(paren_line[paren_line.index(")") + 1 :]),
+                    "description": [],
+                    "technologies": [],
+                }
+                current_bullets = []
+                i = look_ahead + 1
+                continue
+
         if date_match and not _is_bullet(line):
             _save_current()
             parsed = _parse_job_header_line(line, date_match)
             if _is_gap_period_entry(parsed.get("company") or "", parsed.get("title") or ""):
                 i += 1
                 continue
@@ -1640,12 +1736,27 @@ def _extract_experience(text: str) -> list[dict[str, Any]]:
                 clean_seed = _clean_bullet_text(line)
                 if clean_seed:
                     current_bullets.append(clean_seed)
             i += 2
             continue
 
+        # Title-only role: an explicit job-title line directly above bullets, with no
+        # employer or dates. The employer stays empty (never invented).
+        if chosen and not current_job and _is_title_only_header(line, lines, i):
+            current_job = {
+                "title": _clean_text(line),
+                "company": "",
+                "location": "",
+                "duration": "",
+                "description": [],
+                "technologies": [],
+            }
+            current_bullets = []
+            i += 1
+            continue
+
         # Collect bullets / detail lines for the current job.
         if current_job:
             if _is_section_heading_line(line):
                 i += 1
                 continue
             norm = _normalize_heading(line)
@@ -1679,22 +1790,27 @@ def _extract_experience(text: str) -> list[dict[str, Any]]:
                     and not current_bullets[-1].rstrip().endswith(":")
                 ):
                     current_bullets[-1] = f"{current_bullets[-1]} {clean}".strip()
                 else:
                     # Prefer discrete bullets over paragraph streams.
                     current_bullets.append(clean)
+        elif chosen and _is_bullet(line):
+            # Bullet inside an Experience section before any recognised role header.
+            orphan = _clean_bullet_text(line)
+            if orphan:
+                orphan_bullets.append(orphan)
         i += 1
 
     _save_current()
     roles = _dedupe_experience_roles(experiences)
     cleaned_roles = []
     for role in roles:
         role = _promote_title_from_first_bullet(role)
         role["company"] = _strip_engagement_duration(role.get("company"))
         cleaned_roles.append(role)
-    return cleaned_roles
+    return cleaned_roles, orphan_bullets
 
 
 def _strip_engagement_duration(company: Any) -> str:
     """Drop a source label such as '12 Month Duration' from the employer name."""
     text = str(company or "")
     text = re.sub(r"(?i)\s*[-–—]\s*\d+\s*month\s+duration\b", "", text)
@@ -2584,35 +2700,45 @@ def parse_resume_detailed(resume_path: str | None, resume_text: str | None = Non
     name = _extract_name(resume_text)
     summary, summary_from_section = _extract_summary(resume_text)
     languages = _extract_bullet_list(resume_text, "languages")
     # Spoken languages are short ("English (Native)"); a long item is a programming-language
     # list or a stray footer and is dropped on its own instead of wiping the whole list.
     languages = [item for item in languages if len(item) <= 40]
+    experience, orphan_bullets = _extract_experience_detailed(resume_text)
     result = {
         "name": name,
         "email": _extract_email(contact_text),
         "phone": _extract_phone(contact_text),
         "location": _extract_location(contact_text),
         "linkedin": _extract_linkedin(contact_text),
         "portfolio": _extract_portfolio(contact_text),
         "headline": _extract_headline(resume_text, name),
         "summary": summary,
         "summary_from_section": summary_from_section,
         "skills": _dedupe(skills),
         "skills_by_category": skills_by_category,
-        "experience": _extract_experience(resume_text),
+        "experience": experience,
         "education": _extract_education(resume_text),
         "projects": _extract_projects(resume_text),
         "certifications": _dedupe(
             [*_extract_bullet_list(resume_text, "certifications"), *_education_credentials(resume_text)]
         ),
         "achievements": _extract_bullet_list(resume_text, "achievements"),
         "languages": _dedupe([*inline_languages, *languages]),
         "additional_sections": _extract_additional_sections(resume_text),
     }
 
+    # Bullet-only layouts: keep source bullets for review instead of dropping them or
+    # inventing an employer. Only surfaced when the source shows work history.
+    from app.services.parse_confidence import score_parse
+    from app.services.source_evidence import detect_employment_evidence
+
+    if not result["experience"] and orphan_bullets and detect_employment_evidence(resume_text).has_work_history:
+        result["unassigned_experience_bullets"] = _dedupe(orphan_bullets)
+    result["parse_meta"] = score_parse(result, resume_text)
+
     logger.info(
         "deterministic_parse_complete",
         experience_count=len(result.get("experience", [])),
         education_count=len(result.get("education", [])),
         skills_count=len(result.get("skills", [])),
         skill_categories=len(result.get("skills_by_category") or {}),
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
diff --git a/backend/app/services/structured_resume_store.py b/backend/app/services/structured_resume_store.py
index e0435bf..3bfca27 100644
--- a/backend/app/services/structured_resume_store.py
+++ b/backend/app/services/structured_resume_store.py
@@ -71,12 +71,15 @@ def build_structured_resume(candidate_data: dict[str, Any]) -> dict[str, Any]:
         "achievements": [
             repair_collapsed_spaces(a) for a in _as_str_list(candidate_data.get("achievements"))
         ],
         "languages": _as_str_list(candidate_data.get("languages")),
         "additional_sections": _additional_sections(candidate_data.get("additional_sections")),
         "raw_resume_text": repair_collapsed_spaces(str(candidate_data.get("raw_resume_text") or "")),
+        # Review-only carriers: never rendered as a job. See parse_confidence.score_parse.
+        "parse_meta": dict(candidate_data.get("parse_meta") or {}),
+        "unassigned_experience_bullets": _as_str_list(candidate_data.get("unassigned_experience_bullets")),
         "stats": {
             "experience_count": len(experience),
             "experience_bullets": sum(len(e.get("description") or []) for e in experience),
             "education_count": len(education),
             "skills_count": sum(len(v) for v in (skills_by_category or {}).values())
             or len(_as_str_list(candidate_data.get("skills"))),
@@ -111,12 +114,16 @@ def apply_store_to_candidate_data(candidate_data: dict[str, Any], store: dict[st
     merged["education"] = normalize_education_entries(store.get("education") or [])
     merged["projects"] = store.get("projects") or []
     merged["certifications"] = store.get("certifications") or []
     merged["achievements"] = store.get("achievements") or []
     merged["languages"] = store.get("languages") or []
     merged["additional_sections"] = store.get("additional_sections") or []
+    if store.get("parse_meta"):
+        merged["parse_meta"] = store["parse_meta"]
+    if store.get("unassigned_experience_bullets"):
+        merged["unassigned_experience_bullets"] = store["unassigned_experience_bullets"]
     merged["structured_resume"] = store
     merged["structured_resume_json"] = store
     return merged
 
 
 def normalize_education_entries(entries: Any) -> list[dict[str, Any]]:
diff --git a/backend/tests/test_corpus_parse_recovery.py b/backend/tests/test_corpus_parse_recovery.py
new file mode 100644
index 0000000..7591d4e
--- /dev/null
+++ b/backend/tests/test_corpus_parse_recovery.py
@@ -0,0 +1,114 @@
+from pathlib import Path
+
+from app.services.detailed_resume_parser import parse_resume_detailed
+
+CASES = Path(__file__).parent / "fixtures" / "golden" / "cases"
+
+
+def _load(name: str) -> str:
+    return (CASES / name).read_text(encoding="utf-8")
+
+
+def test_dice_wrapper_recovers_roles_and_bullets():
+    data = parse_resume_detailed(None, _load("dice_wrapper.txt"))
+    assert len(data["experience"]) >= 1
+    companies = " ".join(r.get("company") or "" for r in data["experience"])
+    assert "amazon" in companies.lower()
+    bullets = " ".join(b for r in data["experience"] for b in (r.get("description") or []))
+    assert "onboarding" in bullets.lower()
+    assert data.get("parse_meta", {}).get("confidence", 0) >= 0.55
+
+
+def test_paren_title_split_header():
+    data = parse_resume_detailed(None, _load("paren_title.txt"))
+    assert len(data["experience"]) >= 1
+    role = data["experience"][0]
+    assert "Northwind" in (role.get("company") or "")
+    assert (role.get("title") or "") == "Platform Engineer"
+    assert "billing service" in " ".join(role.get("description") or [])
+    assert data["name"] == "Jordan Hale"
+
+
+def test_bullet_only_preserves_text():
+    data = parse_resume_detailed(None, _load("bullet_only.txt"))
+    assigned = [b for r in data["experience"] for b in (r.get("description") or [])]
+    unassigned = data.get("unassigned_experience_bullets") or []
+    assert assigned or unassigned
+    blob = " ".join(assigned + unassigned).lower()
+    assert "onboarding checklist" in blob and "weekly finance close" in blob
+    if not data["experience"]:
+        assert "expected_experience_missing" in (data.get("parse_meta") or {}).get("reasons", []) or (
+            "ambiguous_role_assignment" in (data.get("parse_meta") or {}).get("reasons", [])
+        )
+
+
+def test_education_only_ok_without_roles():
+    data = parse_resume_detailed(None, _load("education_only.txt"))
+    assert data["experience"] == []
+    assert data.get("education")
+    reasons = (data.get("parse_meta") or {}).get("reasons") or []
+    assert "expected_experience_missing" not in reasons
+
+
+def test_clean_conventional_control():
+    data = parse_resume_detailed(None, _load("clean_conventional.txt"))
+    assert len(data["experience"]) == 1
+    assert data["experience"][0].get("company")
+    assert data["name"] == "Alex Example"
+    assert data["parse_meta"]["confidence"] >= 0.9
+
+
+def test_tech_token_name_rejected():
+    text = "React Native.\nEXPERIENCE\nAcme Inc\nEngineer 2020 - Present\n• built apps\nSKILLS\nReact Native, Python\n"
+    data = parse_resume_detailed(None, text)
+    assert (data.get("name") or "").lower().strip(". ") != "react native"
+
+
+def test_emdash_company_title_dates_header():
+    data = parse_resume_detailed(None, _load("emdash_header.txt"))
+    assert len(data["experience"]) == 1
+    role = data["experience"][0]
+    assert role["company"] == "Fabrikam Studio"
+    assert role["title"] == "Designer"
+    assert "settings screens" in " ".join(role["description"])
+
+
+def test_date_only_headers_keep_bullets_for_review():
+    data = parse_resume_detailed(None, _load("bullet_only_dated.txt"))
+    assert data["experience"] == []
+    unassigned = " ".join(data.get("unassigned_experience_bullets") or []).lower()
+    assert "weekly sales report" in unassigned and "monthly books" in unassigned
+    assert "ambiguous_role_assignment" in data["parse_meta"]["reasons"]
+
+
+def test_bullet_only_flags_review_reason():
+    data = parse_resume_detailed(None, _load("bullet_only.txt"))
+    assert data["experience"] == []
+    assert len(data["unassigned_experience_bullets"]) == 3
+    assert "ambiguous_role_assignment" in data["parse_meta"]["reasons"]
+
+
+def test_title_only_experience_role_recovered():
+    data = parse_resume_detailed(None, _load("title_only.txt"))
+    assert len(data["experience"]) >= 1
+    role = data["experience"][0]
+    assert role["title"] == "Product Designer"
+    # No employer is stated in the source, so none may be invented.
+    assert (role.get("company") or "") == ""
+    assert "settings screens" in " ".join(role["description"])
+    assert not data.get("unassigned_experience_bullets")
+
+
+def test_title_only_requires_following_bullet():
+    text = "Casey Example\nEXPERIENCE\nProduct Designer\nSome free text without bullets here.\nEDUCATION\nB.A. Design\n"
+    data = parse_resume_detailed(None, text)
+    assert data["experience"] == []
+
+
+def test_sentence_line_before_bullets_is_not_a_title():
+    text = (
+        "Riley Quinn\nEXPERIENCE\nManaged a team of analysts and led the close process.\n"
+        "• Documented the weekly finance close.\nSKILLS\nExcel\n"
+    )
+    data = parse_resume_detailed(None, text)
+    assert data["experience"] == []
diff --git a/backend/tests/test_parse_confidence.py b/backend/tests/test_parse_confidence.py
new file mode 100644
index 0000000..24dc337
--- /dev/null
+++ b/backend/tests/test_parse_confidence.py
@@ -0,0 +1,51 @@
+from app.services.parse_confidence import score_parse
+
+
+def test_missing_experience_with_evidence_lowers_confidence():
+    src = "EXPERIENCE\nAcme Inc 2020 - Present\n• did things\n"
+    meta = score_parse({"name": "A B", "experience": []}, src)
+    assert "expected_experience_missing" in meta["reasons"]
+    assert meta["confidence"] <= 0.5
+    assert meta["llm_repaired"] is False
+
+
+def test_unassigned_bullets_flag_ambiguity_not_missing():
+    src = "EXPERIENCE\nAcme Inc 2020 - Present\n• did things\n"
+    meta = score_parse({"name": "A B", "experience": [], "unassigned_experience_bullets": ["did things"]}, src)
+    assert "ambiguous_role_assignment" in meta["reasons"]
+    assert "expected_experience_missing" not in meta["reasons"]
+
+
+def test_no_evidence_no_penalty():
+    meta = score_parse({"name": "A B", "experience": []}, "EDUCATION\nB.S. X\n")
+    assert meta["reasons"] == []
+    assert meta["confidence"] == 1.0
+
+
+def test_tech_name_flags_identity():
+    meta = score_parse({"name": "React Native.", "experience": []}, "SKILLS\nPython\n")
+    assert "identity_ambiguous" in meta["reasons"]
+
+
+def test_empty_titles_flagged():
+    data = {"name": "A B", "experience": [{"title": "", "company": "X"}, {"title": "", "company": "Y"}]}
+    meta = score_parse(data, "EXPERIENCE\nX 2020 - 2021\nY 2019 - 2020\n")
+    assert "source_backed_titles_unresolved" in meta["reasons"]
+
+
+def test_structured_store_carries_parse_meta_and_unassigned_bullets():
+    from app.services.structured_resume_store import apply_store_to_candidate_data, build_structured_resume
+
+    data = {
+        "name": "A B",
+        "experience": [],
+        "unassigned_experience_bullets": ["Shipped the checklist in 2021."],
+        "parse_meta": {"confidence": 0.65, "reasons": ["ambiguous_role_assignment"], "llm_repaired": False},
+    }
+    store = build_structured_resume(data)
+    assert store["experience"] == []
+    assert store["unassigned_experience_bullets"] == ["Shipped the checklist in 2021."]
+    assert store["parse_meta"]["reasons"] == ["ambiguous_role_assignment"]
+    merged = apply_store_to_candidate_data({}, store)
+    assert merged["parse_meta"]["confidence"] == 0.65
+    assert merged["unassigned_experience_bullets"] == ["Shipped the checklist in 2021."]
