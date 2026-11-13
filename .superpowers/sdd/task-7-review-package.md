# Review package Task 7
BASE: ed2e9a08eeced78df90ef7946271cd72ccf7603b
HEAD: 1a87c7fe19722a2765f22a782611a4ad8622e28a
## Commits
1a87c7f ci: enforce corpus golden quality gates on pull requests
## Diff stat
 .github/workflows/ci.yml                           |  24 ++  backend/app/services/detailed_resume_parser.py     |   4 +-  backend/app/services/output_integrity.py           |  14 +-  backend/scripts/corpus_quality_eval.py             | 371 ++++++++++++++++++++-  backend/tests/fixtures/golden/manifest.json        |   4 +-  backend/tests/fixtures/golden/style_checks.py      | 173 ++++++++++  backend/tests/fixtures/golden/synthetic_formats.py |  70 ++++  backend/tests/test_format_style_asserts.py         | 162 ++-------  backend/tests/test_golden_gate_regression.py       | 182 ++++++++++  9 files changed, 857 insertions(+), 147 deletions(-)
diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
index c463e64..dbaf585 100644
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -38,4 +38,28 @@ jobs:
           cache-dependency-path: backend/requirements.txt
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
diff --git a/backend/app/services/detailed_resume_parser.py b/backend/app/services/detailed_resume_parser.py
index 74c5882..c982188 100644
--- a/backend/app/services/detailed_resume_parser.py
+++ b/backend/app/services/detailed_resume_parser.py
@@ -1318,9 +1318,11 @@ def _parse_job_header_line(line: str, date_match: re.Match) -> dict[str, str]:
     if not title and before and not re.search(r"\s[–—]\s", before):
         role_then_company = re.match(
             r"^(?P<title>.{0,90}?\b(?:Engineer|Developer|Manager|Architect|Analyst|Consultant|"
             r"Director|Designer|Scientist|Specialist|Coordinator|Administrator|Intern|Officer|"
-            r"Researcher|Programmer|Lead)\b(?:\s*\([^)]{1,40}\))?)\s+(?P<company>[A-Z0-9].{1,90})$",
+            # Optional level suffix ("Engineer II", "Analyst 3") belongs to the title.
+            r"Researcher|Programmer|Lead)\b(?:\s+(?:[IVX]{1,4}|[1-9])\b)?(?:\s*\([^)]{1,40}\))?)"
+            r"\s+(?P<company>(?![IVX]{1,4}$|[1-9]$)[A-Z0-9].{1,90})$",
             before,
         )
         if role_then_company and not _is_invalid_job_title(role_then_company.group("title")):
             title = role_then_company.group("title").strip()
diff --git a/backend/app/services/output_integrity.py b/backend/app/services/output_integrity.py
index 065b0b4..d5ce697 100644
--- a/backend/app/services/output_integrity.py
+++ b/backend/app/services/output_integrity.py
@@ -135,8 +135,11 @@ _SOURCE_DATE = re.compile(
 # Metrics whose digits must survive verbatim: percentages and currency amounts.
 _METRIC = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?\s?[kmb]?\b|\b\d[\d,]*(?:\.\d+)?\s?%", re.IGNORECASE)
 
 
+_BULLET_LINE = re.compile("^\\s*[\u2022\u25cf\u25e6\u25aa\u25a0\\-\\*]\\s*\\S")
+
+
 def _contains(padded: str, needle: str) -> bool:
     return bool(needle) and f" {needle} " in padded
 
 
@@ -173,9 +176,11 @@ def _classify_source_lines(
         grams = [" ".join(words[i : i + 4]) for i in range(len(words) - 3)]
         found = sum(1 for g in grams if f" {g} " in padded)
         if found < min_share * len(grams):
             line_padded = f" {norm_line} "
-            carries_fact = bool(metrics) or any(
+            # A bullet-marked line is resume content by construction, even when the parser
+            # never read it into a role (so no parsed fact points at it).
+            carries_fact = bool(metrics) or bool(_BULLET_LINE.match(raw)) or any(
                 _contains(line_padded, f) or (len(f.split()) >= _MIN_ROLE_BULLET_WORDS and _contains(f" {f} ", norm_line))
                 for f in facts
             )
             if carries_fact:
@@ -334,12 +339,15 @@ def check_output_integrity(
         ("languages", "languages"),
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
 
diff --git a/backend/scripts/corpus_quality_eval.py b/backend/scripts/corpus_quality_eval.py
index c69a134..63decab 100644
--- a/backend/scripts/corpus_quality_eval.py
+++ b/backend/scripts/corpus_quality_eval.py
@@ -3,15 +3,21 @@
 Usage (from backend/):
   python scripts/corpus_quality_eval.py
   python scripts/corpus_quality_eval.py --limit 120
   python scripts/corpus_quality_eval.py --limit 40 --formats aptino,capgemini
+  python scripts/corpus_quality_eval.py --golden --formats aptino,capgemini,suresh
+
+``--golden`` is the CI quality gate: it uses only the anonymized fixtures under
+``tests/fixtures/golden`` (never the private corpus), prints numerator / denominator /
+failing IDs per gate, and exits nonzero if any gate misses its manifest threshold.
 
 Outputs JSON + Markdown under backend/eval_reports/.
 """
 from __future__ import annotations
 
 import argparse
 import hashlib
+import importlib.util
 import io
 import json
 import logging
 import os
@@ -27,8 +33,11 @@ _TMP = Path(tempfile.mkdtemp(prefix="corpus_eval_"))
 os.environ["RESUME_LLM_CONDENSE"] = "false"
 os.environ["RESUME_AGENT_PIPELINE"] = "false"
 os.environ["RESUME_LLM_POLISH"] = "false"
 os.environ["UPLOAD_DIR"] = str(_TMP / "uploads")
+if "--golden" in sys.argv:
+    # Golden gates measure deterministic parsing only: no LLM repair, ever.
+    os.environ["RESUME_LLM_PARSE_FALLBACK"] = "false"
 os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)
 
 ROOT = Path(__file__).resolve().parents[1]
 REPO = ROOT.parent
@@ -537,14 +546,369 @@ def to_markdown(summary: dict, rows: list[dict], format_names: list[str]) -> str
     lines.append("")
     return "\n".join(lines)
 
 
-def main() -> None:
+# ---------------------------------------------------------------------------
+# Golden CI gate (--golden): anonymized fixtures only, never the private corpus.
+# ---------------------------------------------------------------------------
+
+GOLDEN_DIR = ROOT / "tests" / "fixtures" / "golden"
+# A fixture whose manifest status is ``needs_review`` is deliberately ambiguous: flagging it
+# is the desired outcome and a clean pass is acceptable only if every expected fact is intact
+# (the expectation check below enforces that). ``failed`` / ``error`` is never acceptable.
+GOLDEN_STATUS_OK = {"passed": {"passed"}, "needs_review": {"needs_review", "passed"}}
+
+
+def _golden_module(name: str):
+    """Load a helper module from tests/fixtures/golden by path (no pytest needed)."""
+    spec = importlib.util.spec_from_file_location(f"golden_{name}", GOLDEN_DIR / f"{name}.py")
+    module = importlib.util.module_from_spec(spec)
+    sys.modules[spec.name] = module
+    spec.loader.exec_module(module)  # type: ignore[union-attr]
+    return module
+
+
+def load_golden_formats(wanted: set[str]) -> tuple[dict[str, ClientFormat], list[str]]:
+    """Client formats for the golden run.
+
+    Capgemini is always the anonymized synthetic template (the real one holds a real
+    candidate's resume and is not committed). Suresh / Juhi come from the committed
+    ``test/format`` files. A requested format that cannot be loaded is a hard error
+    (returned in the second element), never a silent skip.
+    """
+    formats: dict[str, ClientFormat] = {}
+    problems: list[str] = []
+    extractor = FormatExtractionService()
+
+    def add(key: str, path: Path) -> None:
+        meta = normalize_format_metadata(extractor.extract(path.name, path.read_bytes()))
+        formats[key] = ClientFormat(
+            client_id=key.title(),
+            format_template_path=f"upload://{path.name}",
+            format_metadata=meta,
+            template_bytes_path=str(path),
+        )
+
+    if "aptino" in wanted:
+        formats["aptino"] = build_aptino_client_format("Aptino")
+    if "capgemini" in wanted:
+        synthetic = _golden_module("synthetic_formats")
+        path = _TMP / "synthetic_formats" / "Capgemini-Format.docx"
+        path.parent.mkdir(parents=True, exist_ok=True)
+        path.write_bytes(synthetic.build_synthetic_capgemini_docx())
+        add("capgemini", path)
+    for key, filename in (("suresh", "Suresh Duvvada.docx"), ("juhi", "Juhi Patil - Aptino format.docx")):
+        if key not in wanted:
+            continue
+        path = FORMAT_DIR / filename
+        if path.exists():
+            add(key, path)
+        else:
+            problems.append(f"format '{key}' requested but template missing: {path}")
+    for key in sorted(wanted - set(formats) - {"capgemini", "aptino", "suresh", "juhi"}):
+        problems.append(f"unknown format '{key}'")
+    return formats, problems
+
+
+def _contains(haystack: str, needle: str) -> bool:
+    return norm(needle) in haystack
+
+
+def golden_expectation_failures(fixture: dict, out_txt: str, preserved: list[str] | None = None) -> list[str]:
+    """Material content the manifest says must survive into the rendered resume.
+
+    ``preserved`` is parser-kept text that is deliberately not rendered as a job (unassigned
+    bullets). It only counts for fixtures that declare ``allow_unassigned_bullets``.
+    """
+    hay = norm(out_txt)
+    if fixture.get("allow_unassigned_bullets") and preserved:
+        hay = f"{hay} {norm(' '.join(preserved))}"
+    missing: list[str] = []
+    for role in fixture.get("expected_roles") or []:
+        company = role.get("company") or ""
+        if company and not _contains(hay, company):
+            missing.append(f"company:{company}")
+        if role.get("title") and not _contains(hay, role["title"]):
+            missing.append(f"title:{role['title']}")
+        for token in role.get("dates_contains") or []:
+            if not _contains(hay, token):
+                missing.append(f"date:{token}")
+        for bullet in role.get("bullet_substrings") or []:
+            if not _contains(hay, bullet):
+                missing.append(f"bullet:{bullet}")
+    for key, label in (
+        ("expected_bullet_substrings", "bullet"),
+        ("expected_education_substrings", "education"),
+        ("expected_summary_substrings", "summary"),
+        ("expected_skill_substrings", "skill"),
+        ("expected_certification_substrings", "certification"),
+    ):
+        for needle in fixture.get(key) or []:
+            if not _contains(hay, needle):
+                missing.append(f"{label}:{needle}")
+    return missing
+
+
+def _find_parsed_role(parsed_roles: list[dict], company: str) -> dict | None:
+    want = norm(company)
+    for role in parsed_roles:
+        got = norm(role.get("company") or "")
+        if want and got and (want in got or got in want):
+            return role
+    return None
+
+
+def golden_parse_facts(fixture: dict, text: str) -> dict:
+    """Format-independent parse observations for the fixture-level gates."""
+    parsed = parse_resume_detailed(None, text)
+    roles = parsed.get("experience") or []
+    annotated = [r for r in fixture.get("expected_roles") or [] if str(r.get("title") or "").strip()]
+    untitled = []
+    for role in annotated:
+        match = _find_parsed_role(roles, role.get("company") or "")
+        if match is not None and not str(match.get("title") or "").strip():
+            untitled.append(role.get("company") or "?")
+    name = str(parsed.get("name") or "").strip()
+    expected_name = fixture.get("expected_name")
+    bad_name = None
+    if expected_name:
+        bad_name = norm(name) != norm(expected_name)
+    rejected = [norm(n) for n in fixture.get("rejected_names") or []]
+    if rejected and norm(name) in rejected:
+        bad_name = True
+    return {
+        "roles": len(roles),
+        "unassigned_bullets": [str(b) for b in (parsed.get("unassigned_experience_bullets") or [])],
+        "name": name,
+        "bad_name": bad_name,
+        "annotated_titled_roles": len(annotated),
+        "untitled_source_titled_roles": untitled,
+    }
+
+
+def run_golden_fixture(fixture: dict, formats: dict[str, ClientFormat], style_checks) -> dict:
+    """Extract -> intake -> parse -> generate for one fixture across the requested formats."""
+    from app.services.intake_gate import assess_resume_intake
+
+    out: dict = {"id": fixture["id"], "runs": {}, "parse": None, "intake_error": None}
+    text = (GOLDEN_DIR / fixture["source"]).read_text(encoding="utf-8")
+    assessment = assess_resume_intake(text)
+    if not assessment.is_resume:
+        out["intake_error"] = f"unexpected_quarantine:{assessment.reason_code}"
+    try:
+        out["parse"] = golden_parse_facts(fixture, text)
+    except Exception as exc:  # noqa: BLE001
+        out["parse_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
+
+    cand = Candidate(
+        name="Candidate",
+        resume_path=f"{fixture['id']}.txt",
+        extracted_data={"raw_text": text, "resume_text": text, "extraction_meta": {}},
+    )
+    for fname in fixture.get("formats") or list(formats):
+        if fname not in formats:
+            continue
+        run: dict = {"status": "error", "error": None, "expectation_failures": [], "style_failures": None}
+        if out["intake_error"]:
+            run["error"] = out["intake_error"]
+            out["runs"][fname] = run
+            continue
+        service = ResumeGenerationService()
+        try:
+            data = service.generate(cand, formats[fname])
+            report = getattr(service, "last_report", None)
+            run["status"] = getattr(report, "status", "ok") if report else "ok"
+            run["review_reasons"] = [
+                f"{w.get('code', 'legacy')}:{w.get('severity', '?')}" if isinstance(w, dict) else str(w)[:60]
+                for w in list(getattr(report, "warnings", []) or [])[:6]
+            ]
+            preserved = (out["parse"] or {}).get("unassigned_bullets") or []
+            run["expectation_failures"] = golden_expectation_failures(fixture, docx_text(data), preserved)
+            if fixture.get("style_subset"):
+                run["style_failures"] = style_checks.check_style(data, fname, fixture)
+        except Exception as exc:  # noqa: BLE001 - unexpected execution errors stay in the denominator
+            run["status"] = "error"
+            run["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
+        out["runs"][fname] = run
+    return out
+
+
+def _gate(name: str, kind: str, threshold: float, num: int, den: int, failing: list[str], note: str = "") -> dict:
+    pct = round(100 * num / den, 1) if den else None
+    if den == 0:
+        met = None  # not enforceable: no scored inputs for this gate
+    elif kind == "min":
+        met = pct >= threshold
+    else:
+        met = pct <= threshold
+    return {
+        "gate": name,
+        "rule": f"{'>=' if kind == 'min' else '<='} {threshold:g}%",
+        "numerator": num,
+        "denominator": den,
+        "pct": pct,
+        "met": met,
+        "failing_ids": sorted(failing),
+        "note": note,
+    }
+
+
+def compute_golden_gates(manifest: dict, results: list[dict], fixtures_by_id: dict[str, dict]) -> list[dict]:
+    """Aggregate per-fixture results into the manifest gates (numerator/denominator/failing IDs)."""
+    th = manifest["gates"]
+    runs = [(r["id"], fmt, run) for r in results for fmt, run in r["runs"].items()]
+    parsed = [(r["id"], r["parse"]) for r in results if r.get("parse")]
+
+    def run_ok(fid: str, run: dict) -> bool:
+        expected = fixtures_by_id[fid].get("expected_status", "passed")
+        return run["status"] in GOLDEN_STATUS_OK.get(expected, {expected}) and not run["expectation_failures"]
+
+    # passed_pct / failed_pct: every scored valid input x format stays in the denominator.
+    bad_runs = [f"{fid}@{fmt}" for fid, fmt, run in runs if not run_ok(fid, run)]
+    failed_runs = [f"{fid}@{fmt}" for fid, fmt, run in runs if run["status"] in {"failed", "error"}]
+    total = len(runs)
+
+    # Role-bearing = source-labeled employers: fixtures that expect work history AND annotate
+    # roles. Bullet-only / headerless fixtures have no source roles to find.
+    role_bearing = [
+        (fid, p) for fid, p in parsed
+        if fixtures_by_id[fid].get("expects_work_history") and fixtures_by_id[fid].get("expected_roles")
+    ]
+    zero_role = [fid for fid, p in role_bearing if p["roles"] == 0]
+
+    annotated = sum(p["annotated_titled_roles"] for _fid, p in parsed)
+    untitled = [f"{fid}:{c}" for fid, p in parsed for c in p["untitled_source_titled_roles"]]
+
+    named = [(fid, p) for fid, p in parsed if p["bad_name"] is not None]
+    bad_name = [fid for fid, p in named if p["bad_name"]]
+
+    scanned = [r for r in results if fixtures_by_id[r["id"]].get("intake") == "ocr"]
+    scanned_bad = [f"{r['id']}@{fmt}" for r in scanned for fmt, run in r["runs"].items() if not run_ok(r["id"], run)]
+    scanned_total = sum(len(r["runs"]) for r in scanned)
+    docs = [r for r in results if fixtures_by_id[r["id"]].get("builder") == "legacy_doc"]
+    docs_bad = [f"{r['id']}@{fmt}" for r in docs for fmt, run in r["runs"].items() if not run_ok(r["id"], run)]
+    docs_total = sum(len(r["runs"]) for r in docs)
+
+    style_runs = [(fid, fmt, run) for fid, fmt, run in runs if run["style_failures"] is not None]
+    style_bad = [f"{fid}@{fmt}" for fid, fmt, run in style_runs if run["style_failures"]]
+
+    # Zero tolerance, independent of any aggregate rate: expected content missing from a run
+    # that was NOT flagged for review is a silent material omission.
+    silent = [f"{fid}@{fmt}" for fid, fmt, run in runs if run["status"] == "passed" and run["expectation_failures"]]
+
+    unscored_note = "no scored fixtures (stub binary builders stay scored:false until materialize works)"
+    return [
+        _gate("passed_pct", "min", th["passed_pct_min"], total - len(bad_runs), total, bad_runs,
+              "status meets manifest expected_status and every expected role/bullet/etc. is in the output"),
+        _gate("zero_role_pct", "max", th["zero_role_pct_max"], len(zero_role), len(role_bearing), zero_role,
+              "parsed 0 roles on fixtures that expect work history"),
+        _gate("empty_title_pct", "max", th["empty_title_pct_max"], len(untitled), annotated, untitled,
+              "source-titled roles parsed with an empty title"),
+        _gate("bad_name_pct", "max", th["bad_name_pct_max"], len(bad_name), len(named), bad_name,
+              "parsed name differs from expected / equals a rejected tech-token name"),
+        _gate("scanned_recovery_pct", "min", th["scanned_recovery_pct_min"], scanned_total - len(scanned_bad),
+              scanned_total, scanned_bad, "" if scanned_total else unscored_note),
+        _gate("doc_conversion_pct", "min", th["doc_conversion_pct_min"], docs_total - len(docs_bad),
+              docs_total, docs_bad, "" if docs_total else unscored_note),
+        _gate("style_assert_pct", "min", th["style_assert_pct_min"], len(style_runs) - len(style_bad),
+              len(style_runs), style_bad, "name alignment, font family, section order/labels, content on style_subset"),
+        _gate("failed_pct", "max", th["failed_pct_max"], len(failed_runs), total, failed_runs,
+              "integrity status failed or unexpected intake/execution error"),
+        _gate("silent_omission_pct", "max", 0, len(silent), total, silent,
+              "zero tolerance: expected content missing although status is passed (not flagged for review)"),
+    ]
+
+
+def golden_exit_code(gates: list[dict], n_runs: int) -> int:
+    if n_runs == 0:
+        return 1  # nothing was measured: never pass vacuously
+    return 0 if all(g["met"] is not False for g in gates) else 1
+
+
+def format_golden_report(gates: list[dict], results: list[dict], formats: list[str], fixtures_by_id: dict) -> str:
+    lines = [
+        f"GOLDEN GATES  fixtures={len(results)}  runs={sum(len(r['runs']) for r in results)}  formats={','.join(formats)}",
+        f"{'gate':<22}{'rule':<10}{'num/den':<10}{'pct':<8}result",
+    ]
+    for g in gates:
+        result = "n/a (not enforced)" if g["met"] is None else ("PASS" if g["met"] else "FAIL")
+        pct = "-" if g["pct"] is None else f"{g['pct']}%"
+        lines.append(f"{g['gate']:<22}{g['rule']:<10}{g['numerator']}/{g['denominator']:<7}{pct:<8}{result}")
+        if g["note"] and g["met"] is None:
+            lines.append(f"    note: {g['note']}")
+        if g["failing_ids"]:
+            lines.append(f"    failing IDs: {', '.join(g['failing_ids'])}")
+    detail = []
+    for r in results:
+        for fmt, run in r["runs"].items():
+            bits = list(run["expectation_failures"]) + list(run["style_failures"] or [])
+            if run.get("error"):
+                bits.append(f"error={run['error']}")
+            expected = fixtures_by_id[r["id"]].get("expected_status", "passed")
+            if bits or run["status"] != expected:
+                reasons = ",".join(run.get("review_reasons") or [])
+                detail.append(f"  {r['id']}@{fmt}: status={run['status']} (expected {expected}) {'; '.join(bits)} [{reasons}]")
+    if detail:
+        lines.append("Per-run detail (deviations only):")
+        lines.extend(detail)
+    return "\n".join(lines)
+
+
+def run_golden(args) -> int:
+    from app.core.config import settings
+
+    if settings.RESUME_LLM_PARSE_FALLBACK:
+        print("ERROR: RESUME_LLM_PARSE_FALLBACK must be false for golden runs", file=sys.stderr)
+        return 2
+    manifest = json.loads((GOLDEN_DIR / "manifest.json").read_text(encoding="utf-8"))
+    only = {x.strip() for x in (args.fixtures or "").split(",") if x.strip()}
+    scored = [
+        f for f in manifest["fixtures"]
+        if f.get("scored") and f.get("expected_status", "passed") != "quarantine" and (not only or f["id"] in only)
+    ]
+    unknown = only - {f["id"] for f in manifest["fixtures"]}
+    if unknown:
+        print(f"ERROR: unknown fixture ids: {sorted(unknown)}", file=sys.stderr)
+        return 2
+    wanted = {x.strip().lower() for x in args.formats.split(",") if x.strip()}
+    formats, problems = load_golden_formats(wanted)
+    if problems or not formats:
+        for p in problems or ["no formats loaded"]:
+            print(f"ERROR: {p}", file=sys.stderr)
+        return 2
+
+    style_checks = _golden_module("style_checks")
+    fixtures_by_id = {f["id"]: f for f in manifest["fixtures"]}
+    print(f"Golden: {len(scored)} scored fixtures x {list(formats)} (skipped unscored stubs: "
+          f"{sum(1 for f in manifest['fixtures'] if not f.get('scored'))})")
+    results = []
+    for fixture in scored:
+        results.append(run_golden_fixture(fixture, formats, style_checks))
+
+    gates = compute_golden_gates(manifest, results, fixtures_by_id)
+    print(format_golden_report(gates, results, list(formats), fixtures_by_id))
+    code = golden_exit_code(gates, sum(len(r["runs"]) for r in results))
+    out_dir = Path(args.out)
+    out_dir.mkdir(parents=True, exist_ok=True)
+    (out_dir / "golden_latest.json").write_text(
+        json.dumps({"formats": list(formats), "gates": gates, "results": results, "exit_code": code}, indent=2, default=str),
+        encoding="utf-8",
+    )
+    print(f"GOLDEN {'PASS' if code == 0 else 'FAIL'} (exit {code})")
+    return code
+
+
+def main(argv: list[str] | None = None) -> int:
     ap = argparse.ArgumentParser()
     ap.add_argument("--limit", type=int, default=80)
     ap.add_argument("--formats", default="aptino,capgemini,suresh")
     ap.add_argument("--out", default=str(OUT_DIR))
-    args = ap.parse_args()
+    ap.add_argument("--golden", action="store_true", help="run the CI golden quality gates (fixtures only)")
+    ap.add_argument("--fixtures", default="", help="with --golden: comma-separated fixture ids to restrict to")
+    args = ap.parse_args(argv)
+
+    if args.golden:
+        return run_golden(args)
 
     wanted = {x.strip().lower() for x in args.formats.split(",") if x.strip()}
     formats = load_formats(wanted)
     if not formats:
@@ -620,8 +984,9 @@ def main() -> None:
     latest_md.write_text(md, encoding="utf-8")
     print("\nWrote", json_path)
     print("Wrote", md_path)
     print(json.dumps({"summary_formats": summary["formats"], "themes": themes}, indent=2, default=str))
+    return 0
 
 
 if __name__ == "__main__":
-    main()
+    sys.exit(main())
diff --git a/backend/tests/fixtures/golden/manifest.json b/backend/tests/fixtures/golden/manifest.json
index c79a476..45a1dcb 100644
--- a/backend/tests/fixtures/golden/manifest.json
+++ b/backend/tests/fixtures/golden/manifest.json
@@ -83,9 +83,9 @@
         "aptino",
         "capgemini",
         "suresh"
       ],
-      "expected_status": "passed",
+      "expected_status": "needs_review",
       "id": "bullet_only_experience",
       "pattern": "bullet_only",
       "source": "cases/bullet_only.txt",
       "scored": true,
@@ -995,9 +995,9 @@
         "aptino",
         "capgemini",
         "suresh"
       ],
-      "expected_status": "passed",
+      "expected_status": "needs_review",
       "id": "bullet_only_with_date_lines",
       "pattern": "bullet_only",
       "source": "cases/bullet_only_dated.txt",
       "scored": true,
diff --git a/backend/tests/fixtures/golden/style_checks.py b/backend/tests/fixtures/golden/style_checks.py
new file mode 100644
index 0000000..a9f3011
--- /dev/null
+++ b/backend/tests/fixtures/golden/style_checks.py
@@ -0,0 +1,173 @@
+"""Pytest-free style assertions for the Capgemini / Suresh / Aptino client formats.
+
+Shared by ``tests/test_format_style_asserts.py`` and the ``--golden`` CI runner
+(``scripts/corpus_quality_eval.py``), which cannot import pytest. Each ``assert_*``
+helper raises ``AssertionError`` on a style deviation.
+"""
+
+from __future__ import annotations
+
+import io
+import re
+from pathlib import Path
+
+from docx import Document
+from docx.enum.text import WD_ALIGN_PARAGRAPH
+
+GOLDEN = Path(__file__).resolve().parent
+
+# What each client format must produce, independent of the candidate.
+EXPECTED = {
+    "capgemini": {
+        "name_align": WD_ALIGN_PARAGRAPH.RIGHT,
+        "font_family": "Avenir 45",
+        "order": ["summary", "skills", "experience", "projects", "education"],
+        "labels": {
+            "summary": "Professional Summary",
+            "skills": "Skills Profile",
+            "experience": "Professional Experience",
+            "projects": "Summary of Projects",
+            "education": "Education",
+        },
+    },
+    "suresh": {
+        "name_align": WD_ALIGN_PARAGRAPH.CENTER,
+        "font_family": "Arial",
+        "order": ["summary", "skills", "education", "experience", "projects"],
+        "labels": {
+            "summary": "Professional Summary",
+            "skills": "Skill Set Overview",
+            "education": "Educational Details",
+            "experience": "Work Experience",
+            "projects": "Projects",
+        },
+    },
+    "aptino": {
+        "name_align": WD_ALIGN_PARAGRAPH.LEFT,
+        "font_family": "Arial",
+        "order": ["summary", "skills", "education", "experience", "projects"],
+        "labels": {
+            "summary": "Professional Summary",
+            "skills": "Skill Set Overview",
+            "education": "Educational Details",
+            "experience": "Work Experience",
+            "projects": "Projects",
+        },
+    },
+}
+
+
+def source_text(fixture: dict) -> str:
+    return (GOLDEN / fixture["source"]).read_text(encoding="utf-8")
+
+
+def paragraphs(data: bytes) -> list:
+    return [p for p in Document(io.BytesIO(data)).paragraphs if p.text.strip()]
+
+
+def norm(text: str) -> str:
+    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()
+
+
+def heading_positions(data: bytes, fmt: str) -> dict[str, int]:
+    """Paragraph index of each section heading, found by the format's own label."""
+    paras = paragraphs(data)
+    found: dict[str, int] = {}
+    for section, label in EXPECTED[fmt]["labels"].items():
+        for idx, para in enumerate(paras):
+            if norm(para.text) == norm(label):
+                found[section] = idx
+                break
+    return found
+
+
+def section_text(data: bytes, fmt: str, section: str) -> str:
+    """Text between a section heading and the next heading of any section."""
+    paras = paragraphs(data)
+    positions = heading_positions(data, fmt)
+    start = positions[section]
+    later = [pos for pos in positions.values() if pos > start]
+    end = min(later) if later else len(paras)
+    return "\n".join(p.text for p in paras[start + 1 : end])
+
+
+def assert_name_align(data: bytes, fmt: str, expected_name: str) -> None:
+    first = paragraphs(data)[0]
+    assert first.text.strip() == expected_name, (fmt, first.text.strip())
+    assert first.alignment == EXPECTED[fmt]["name_align"], (fmt, first.alignment)
+
+
+def assert_font_family(data: bytes, fmt: str) -> None:
+    wanted = EXPECTED[fmt]["font_family"]
+    named = [run.font.name for p in paragraphs(data) for run in p.runs if run.text.strip() and run.font.name]
+    assert named, "no explicit run fonts found"
+    assert set(named) == {wanted}, (fmt, set(named))
+
+
+def assert_section_order(data: bytes, fmt: str, present: set[str], optional: set[str] = frozenset()) -> None:
+    positions = heading_positions(data, fmt)
+    assert present <= set(positions) <= present | optional, (fmt, sorted(positions), sorted(present))
+    ordered = [s for s in EXPECTED[fmt]["order"] if s in positions]
+    assert sorted(positions, key=positions.get) == ordered, (fmt, sorted(positions, key=positions.get))
+
+
+def assert_labels(data: bytes, fmt: str, present: set[str], optional: set[str] = frozenset()) -> None:
+    body = {norm(p.text) for p in paragraphs(data)}
+    for section in present:
+        assert norm(EXPECTED[fmt]["labels"][section]) in body, (fmt, section)
+    for section, label in EXPECTED[fmt]["labels"].items():
+        if section not in present | optional:
+            assert norm(label) not in body, f"{fmt}: unexpected empty heading {label!r}"
+
+
+def expected_sections(fixture: dict) -> set[str]:
+    """Sections the source actually backs, read from its own headings (never invented)."""
+    headings = {
+        "summary": r"summary|profile|objective",
+        "skills": r"skills?|technical skills",
+        "education": r"education",
+        "experience": r"(?:work |professional )?experience",
+        "projects": r"projects?",
+    }
+    lines = [ln.strip() for ln in source_text(fixture).splitlines()]
+    return {
+        section
+        for section, pattern in headings.items()
+        if any(re.fullmatch(pattern, ln, re.I) for ln in lines)
+    }
+
+
+def assert_content_same(data: bytes, fmt: str, fixture: dict) -> None:
+    """Same source facts land under the format's own experience heading, in every format."""
+    experience = norm(section_text(data, fmt, "experience"))
+    assert fixture["expected_roles"], fixture["id"]
+    for role in fixture["expected_roles"]:
+        assert norm(role["company"]) in experience, (fmt, role["company"])
+        assert norm(role["title"]) in experience, (fmt, role["title"])
+        for token in role.get("dates_contains", []):
+            assert norm(token) in experience, (fmt, token)
+        for bullet in role.get("bullet_substrings", []):
+            assert norm(bullet) in experience, (fmt, bullet)
+    if "education" in expected_sections(fixture):
+        assert "example state college" in norm(section_text(data, fmt, "education"))
+
+
+def check_style(data: bytes, fmt: str, fixture: dict) -> list[str]:
+    """Run every per-fixture style assertion; return failure messages (empty = pass)."""
+    failures: list[str] = []
+    present = expected_sections(fixture)
+    checks = (
+        ("name_align", lambda: assert_name_align(data, fmt, fixture["expected_name"])),
+        ("font_family", lambda: assert_font_family(data, fmt)),
+        ("section_order", lambda: assert_section_order(data, fmt, present, optional={"summary"})),
+        ("labels", lambda: assert_labels(data, fmt, present, optional={"summary"})),
+        ("content", lambda: assert_content_same(data, fmt, fixture)),
+    )
+    for name, check in checks:
+        try:
+            check()
+        except AssertionError as exc:
+            failures.append(f"{name}: {exc}")
+        except Exception as exc:  # noqa: BLE001 - a crashed assertion is still a style failure
+            failures.append(f"{name}: {type(exc).__name__}: {exc}")
+    return failures
diff --git a/backend/tests/fixtures/golden/synthetic_formats.py b/backend/tests/fixtures/golden/synthetic_formats.py
new file mode 100644
index 0000000..5a7b87a
--- /dev/null
+++ b/backend/tests/fixtures/golden/synthetic_formats.py
@@ -0,0 +1,70 @@
+"""Synthetic, anonymized client-format templates for CI.
+
+The real ``Capgemini-Format.docx`` carries a real candidate's resume and is never
+committed. ``build_synthetic_capgemini_docx`` rebuilds only the *style contract* of that
+format with placeholder text: right-aligned name, ``Avenir 45`` font family on every run,
+and the heading order Professional Summary / Skills Profile / Professional Experience /
+Summary of Projects / Education.
+
+Font note: ``Avenir 45`` is a font family *name* written into the run properties. The font
+does not need to be installed for the style assertions (they read the DOCX XML), so CI on
+plain Ubuntu behaves identically; a viewer without the font falls back to its default.
+"""
+
+from __future__ import annotations
+
+import io
+
+from docx import Document
+from docx.enum.text import WD_ALIGN_PARAGRAPH
+from docx.oxml.ns import qn
+from docx.shared import Pt
+
+CAPGEMINI_FONT = "Avenir 45"
+CAPGEMINI_SECTIONS = [
+    "Professional Summary",
+    "Skills Profile",
+    "Professional Experience",
+    "Summary of Projects",
+    "Education",
+]
+
+
+def _run(paragraph, text: str, *, size: float, bold: bool = False):
+    run = paragraph.add_run(text)
+    run.font.name = CAPGEMINI_FONT
+    run.font.size = Pt(size)
+    run.bold = bold
+    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), CAPGEMINI_FONT)
+    return run
+
+
+def build_synthetic_capgemini_docx() -> bytes:
+    """Return a minimal Capgemini-style ClientFormat DOCX (no real candidate text)."""
+    doc = Document()
+    normal = doc.styles["Normal"]
+    normal.font.name = CAPGEMINI_FONT
+    normal.font.size = Pt(10.5)
+
+    name = doc.add_paragraph()
+    name.alignment = WD_ALIGN_PARAGRAPH.RIGHT
+    _run(name, "Sample Candidate", size=14, bold=True)
+
+    for heading in CAPGEMINI_SECTIONS:
+        para = doc.add_paragraph()
+        para.alignment = WD_ALIGN_PARAGRAPH.LEFT
+        _run(para, heading, size=12, bold=True)
+        if heading == "Professional Experience":
+            body = doc.add_paragraph()
+            _run(body, "Sample Company\t2020 - 2022", size=10.5, bold=True)
+            title = doc.add_paragraph()
+            _run(title, "Sample Role", size=10.5)
+            bullet = doc.add_paragraph()
+            _run(bullet, "Placeholder responsibility text.", size=10.5)
+        else:
+            body = doc.add_paragraph()
+            _run(body, "Placeholder text.", size=10.5)
+
+    buffer = io.BytesIO()
+    doc.save(buffer)
+    return buffer.getvalue()
diff --git a/backend/tests/test_format_style_asserts.py b/backend/tests/test_format_style_asserts.py
index a4bf100..23e5b4e 100644
--- a/backend/tests/test_format_style_asserts.py
+++ b/backend/tests/test_format_style_asserts.py
@@ -6,15 +6,13 @@ style deviation here is a rendering problem rather than a parsing one.
 
 import io
 import json
 import logging
-import re
 from pathlib import Path
 
 import pytest
 import structlog
 from docx import Document
-from docx.enum.text import WD_ALIGN_PARAGRAPH
 
 from app.models.candidate import Candidate
 from app.models.client_format import ClientFormat
 from app.models.format_schema import normalize_format_metadata
@@ -25,55 +23,30 @@ from app.services.resume_generation_service import ResumeGenerationService
 import app.services.resume_generation_service as rgs
 
 structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL))
 
-GOLDEN = Path(__file__).parent / "fixtures" / "golden"
+from tests.fixtures.golden.style_checks import (  # noqa: E402
+    GOLDEN,
+    assert_content_same,
+    assert_font_family,
+    assert_labels,
+    assert_name_align,
+    assert_section_order,
+    expected_sections,
+    heading_positions,
+    norm as _norm,
+    paragraphs as _paragraphs,
+    section_text,
+    source_text,
+)
+from tests.fixtures.golden.synthetic_formats import build_synthetic_capgemini_docx  # noqa: E402
+
 FORMAT_DIR = Path(__file__).resolve().parents[2] / "test" / "format"
 TEMPLATES = {
     "capgemini": FORMAT_DIR / "Capgemini-Format.docx",
     "suresh": FORMAT_DIR / "Suresh Duvvada.docx",
 }
 
-# What each client format must produce, independent of the candidate.
-EXPECTED = {
-    "capgemini": {
-        "name_align": WD_ALIGN_PARAGRAPH.RIGHT,
-        "font_family": "Avenir 45",
-        "order": ["summary", "skills", "experience", "projects", "education"],
-        "labels": {
-            "summary": "Professional Summary",
-            "skills": "Skills Profile",
-            "experience": "Professional Experience",
-            "projects": "Summary of Projects",
-            "education": "Education",
-        },
-    },
-    "suresh": {
-        "name_align": WD_ALIGN_PARAGRAPH.CENTER,
-        "font_family": "Arial",
-        "order": ["summary", "skills", "education", "experience", "projects"],
-        "labels": {
-            "summary": "Professional Summary",
-            "skills": "Skill Set Overview",
-            "education": "Educational Details",
-            "experience": "Work Experience",
-            "projects": "Projects",
-        },
-    },
-    "aptino": {
-        "name_align": WD_ALIGN_PARAGRAPH.LEFT,
-        "font_family": "Arial",
-        "order": ["summary", "skills", "education", "experience", "projects"],
-        "labels": {
-            "summary": "Professional Summary",
-            "skills": "Skill Set Overview",
-            "education": "Educational Details",
-            "experience": "Work Experience",
-            "projects": "Projects",
-        },
-    },
-}
-
 
 def _style_fixtures() -> list[dict]:
     manifest = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
     return [f for f in manifest["fixtures"] if f.get("style_subset")]
@@ -94,12 +67,17 @@ def _offline_pipeline(tmp_path_factory):
     mp.undo()
 
 
 @pytest.fixture(scope="module")
-def client_formats() -> dict[str, ClientFormat]:
+def client_formats(tmp_path_factory) -> dict[str, ClientFormat]:
     formats = {"aptino": build_aptino_client_format("Aptino")}
     extractor = FormatExtractionService()
     for key, path in TEMPLATES.items():
+        if not path.exists() and key == "capgemini":
+            # The real Capgemini template holds a real candidate's resume and is never
+            # committed; fall back to the anonymized synthetic style contract.
+            path = tmp_path_factory.mktemp("synthetic_formats") / "Capgemini-Format.docx"
+            path.write_bytes(build_synthetic_capgemini_docx())
         if not path.exists():
             continue
         meta = normalize_format_metadata(extractor.extract(path.name, path.read_bytes()))
         formats[key] = ClientFormat(
@@ -110,14 +88,10 @@ def client_formats() -> dict[str, ClientFormat]:
         )
     return formats
 
 
-def _source_text(fixture: dict) -> str:
-    return (GOLDEN / fixture["source"]).read_text(encoding="utf-8")
-
-
 def _generate(fixture: dict, client_format: ClientFormat) -> bytes:
-    text = _source_text(fixture)
+    text = source_text(fixture)
     candidate = Candidate(
         name="Candidate",
         resume_path="fixture.txt",
         extracted_data={"raw_text": text, "resume_text": text, "extraction_meta": {}},
@@ -140,86 +114,8 @@ def generated(client_formats):
 
     return get
 
 
-# ---------------------------------------------------------------- assert helpers
-
-
-def _paragraphs(data: bytes) -> list:
-    return [p for p in Document(io.BytesIO(data)).paragraphs if p.text.strip()]
-
-
-def _norm(text: str) -> str:
-    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()
-
-
-def heading_positions(data: bytes, fmt: str) -> dict[str, int]:
-    """Paragraph index of each section heading, found by the format's own label."""
-    paras = _paragraphs(data)
-    found: dict[str, int] = {}
-    for section, label in EXPECTED[fmt]["labels"].items():
-        for idx, para in enumerate(paras):
-            if _norm(para.text) == _norm(label):
-                found[section] = idx
-                break
-    return found
-
-
-def section_text(data: bytes, fmt: str, section: str) -> str:
-    """Text between a section heading and the next heading of any section."""
-    paras = _paragraphs(data)
-    positions = heading_positions(data, fmt)
-    start = positions[section]
-    later = [pos for pos in positions.values() if pos > start]
-    end = min(later) if later else len(paras)
-    return "\n".join(p.text for p in paras[start + 1 : end])
-
-
-def assert_name_align(data: bytes, fmt: str, expected_name: str) -> None:
-    first = _paragraphs(data)[0]
-    assert first.text.strip() == expected_name
-    assert first.alignment == EXPECTED[fmt]["name_align"], (fmt, first.alignment)
-
-
-def assert_font_family(data: bytes, fmt: str) -> None:
-    wanted = EXPECTED[fmt]["font_family"]
-    named = [run.font.name for p in _paragraphs(data) for run in p.runs if run.text.strip() and run.font.name]
-    assert named, "no explicit run fonts found"
-    assert set(named) == {wanted}, (fmt, set(named))
-
-
-def assert_section_order(data: bytes, fmt: str, present: set[str], optional: set[str] = frozenset()) -> None:
-    positions = heading_positions(data, fmt)
-    assert present <= set(positions) <= present | optional, (fmt, sorted(positions), sorted(present))
-    ordered = [s for s in EXPECTED[fmt]["order"] if s in positions]
-    assert sorted(positions, key=positions.get) == ordered
-
-
-def assert_labels(data: bytes, fmt: str, present: set[str], optional: set[str] = frozenset()) -> None:
-    body = {_norm(p.text) for p in _paragraphs(data)}
-    for section in present:
-        assert _norm(EXPECTED[fmt]["labels"][section]) in body, (fmt, section)
-    for section, label in EXPECTED[fmt]["labels"].items():
-        if section not in present | optional:
-            assert _norm(label) not in body, f"{fmt}: unexpected empty heading {label!r}"
-
-
-def expected_sections(fixture: dict) -> set[str]:
-    """Sections the source actually backs, read from its own headings (never invented)."""
-    headings = {
-        "summary": r"summary|profile|objective",
-        "skills": r"skills?|technical skills",
-        "education": r"education",
-        "experience": r"(?:work |professional )?experience",
-        "projects": r"projects?",
-    }
-    lines = [ln.strip() for ln in _source_text(fixture).splitlines()]
-    return {
-        section
-        for section, pattern in headings.items()
-        if any(re.fullmatch(pattern, ln, re.I) for ln in lines)
-    }
-
 # ------------------------------------------------------------------------ tests
 
 
 @pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
@@ -263,19 +159,9 @@ def test_section_order_and_labels(generated, fixture_id, fmt):
 def test_content_same_expectations_all_formats(generated, fixture_id, fmt):
     """Same source facts land under the format's own experience heading, in every format."""
     fixture = next(f for f in STYLE_FIXTURES if f["id"] == fixture_id)
     data = generated(fixture_id, fmt)
-    experience = _norm(section_text(data, fmt, "experience"))
-    assert fixture["expected_roles"], fixture_id
-    for role in fixture["expected_roles"]:
-        assert _norm(role["company"]) in experience, (fmt, role["company"])
-        assert _norm(role["title"]) in experience, (fmt, role["title"])
-        for token in role.get("dates_contains", []):
-            assert _norm(token) in experience, (fmt, token)
-        for bullet in role.get("bullet_substrings", []):
-            assert _norm(bullet) in experience, (fmt, bullet)
-    if "education" in expected_sections(fixture):
-        assert "example state college" in _norm(section_text(data, fmt, "education"))
+    assert_content_same(data, fmt, fixture)
 
 
 @pytest.mark.parametrize("fmt", ["capgemini", "suresh", "aptino"])
 def test_project_content_lands_under_projects_heading(generated, fmt):
diff --git a/backend/tests/test_golden_gate_regression.py b/backend/tests/test_golden_gate_regression.py
new file mode 100644
index 0000000..f5d90a2
--- /dev/null
+++ b/backend/tests/test_golden_gate_regression.py
@@ -0,0 +1,182 @@
+"""The golden CI gate must fail loudly: injected regressions flip the exit code.
+
+Loads ``scripts/corpus_quality_eval.py`` in-process so a regression can be injected
+(a dropped bullet, a crashing generator) and the real ``--golden`` exit code asserted.
+"""
+
+import importlib.util
+import io
+import json
+import sys
+from pathlib import Path
+
+import pytest
+from docx import Document
+
+BACKEND = Path(__file__).resolve().parents[1]
+SCRIPT = BACKEND / "scripts" / "corpus_quality_eval.py"
+MANIFEST = BACKEND / "tests" / "fixtures" / "golden" / "manifest.json"
+
+# Ten fixtures that pass cleanly today: one dropped bullet is 1/10 runs, so the aggregate
+# passed_pct (90%) still clears the 85% bar -- only the zero-tolerance gate can catch it.
+CLEAN_IDS = [
+    "clean_guillermo_pattern",
+    "clean_one_role",
+    "emdash_role_header",
+    "title_only_under_experience",
+    "numeric_date_history",
+    "promotion_same_employer",
+    "two_column_body",
+    "long_history_twelve_roles",
+    "pipe_delimited_headers",
+    "unicode_bullet_markers",
+]
+VICTIM = "clean_guillermo_pattern"
+
+
+@pytest.fixture(scope="module")
+def runner(tmp_path_factory):
+    mp = pytest.MonkeyPatch()
+    # The script sets these at import; register them so the originals are restored.
+    for key in (
+        "RESUME_LLM_CONDENSE",
+        "RESUME_AGENT_PIPELINE",
+        "RESUME_LLM_POLISH",
+        "RESUME_LLM_PARSE_FALLBACK",
+        "UPLOAD_DIR",
+    ):
+        mp.setenv(key, "false")
+    mp.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
+    spec = importlib.util.spec_from_file_location("corpus_quality_eval_under_test", SCRIPT)
+    module = importlib.util.module_from_spec(spec)
+    sys.modules[spec.name] = module
+    spec.loader.exec_module(module)
+    yield module
+    mp.undo()
+    sys.modules.pop(spec.name, None)
+
+
+def _run(runner, tmp_path, ids=CLEAN_IDS, formats="aptino"):
+    return runner.main(
+        ["--golden", "--formats", formats, "--fixtures", ",".join(ids), "--out", str(tmp_path)]
+    )
+
+
+def _drop_paragraphs(data: bytes, needle: str) -> bytes:
+    doc = Document(io.BytesIO(data))
+    for paragraph in list(doc.paragraphs):
+        if needle in paragraph.text.lower():
+            paragraph._element.getparent().remove(paragraph._element)
+    out = io.BytesIO()
+    doc.save(out)
+    return out.getvalue()
+
+
+def test_clean_subset_exits_zero(runner, tmp_path, capsys):
+    assert _run(runner, tmp_path) == 0
+    out = capsys.readouterr().out
+    assert "GOLDEN PASS" in out
+    assert "passed_pct" in out and "10/10" in out
+
+
+def test_injected_bullet_omission_exits_nonzero_even_when_aggregate_passes(runner, tmp_path, monkeypatch, capsys):
+    real_generate = runner.ResumeGenerationService.generate
+
+    def lossy(self, candidate, client_format):
+        data = real_generate(self, candidate, client_format)
+        if VICTIM in candidate.resume_path:
+            data = _drop_paragraphs(data, "shipped")  # the manifest's expected bullet
+        return data
+
+    monkeypatch.setattr(runner.ResumeGenerationService, "generate", lossy)
+    code = _run(runner, tmp_path)
+    out = capsys.readouterr().out
+    assert code != 0
+    report = json.loads((tmp_path / "golden_latest.json").read_text(encoding="utf-8"))
+    gates = {g["gate"]: g for g in report["gates"]}
+    # 9/10 = 90% >= 85%: the rate gate alone would pass...
+    assert gates["passed_pct"]["met"] is True
+    assert gates["passed_pct"]["numerator"] == 9 and gates["passed_pct"]["denominator"] == 10
+    # ...the zero-tolerance gate is what fails, and it names the fixture and the lost fact.
+    assert gates["silent_omission_pct"]["met"] is False
+    assert gates["silent_omission_pct"]["failing_ids"] == [f"{VICTIM}@aptino"]
+    assert f"{VICTIM}@aptino" in out and "bullet:shipped" in out
+    assert "GOLDEN FAIL" in out
+
+
+def test_generation_error_stays_in_denominator_and_fails(runner, tmp_path, monkeypatch, capsys):
+    real_generate = runner.ResumeGenerationService.generate
+
+    def boom(self, candidate, client_format):
+        if VICTIM in candidate.resume_path:
+            raise RuntimeError("renderer exploded")
+        return real_generate(self, candidate, client_format)
+
+    monkeypatch.setattr(runner.ResumeGenerationService, "generate", boom)
+    assert _run(runner, tmp_path, ids=CLEAN_IDS[:2]) != 0
+    out = capsys.readouterr().out
+    report = json.loads((tmp_path / "golden_latest.json").read_text(encoding="utf-8"))
+    failed = next(g for g in report["gates"] if g["gate"] == "failed_pct")
+    assert failed["denominator"] == 2 and failed["failing_ids"] == [f"{VICTIM}@aptino"]
+    assert "renderer exploded" in out
+
+
+def test_llm_parse_fallback_must_stay_off(runner, tmp_path, monkeypatch):
+    from app.core.config import settings
+
+    monkeypatch.setattr(settings, "RESUME_LLM_PARSE_FALLBACK", True)
+    assert _run(runner, tmp_path, ids=CLEAN_IDS[:1]) == 2
+
+
+def test_unknown_fixture_or_missing_format_is_a_setup_error(runner, tmp_path):
+    assert _run(runner, tmp_path, ids=["no_such_fixture"]) == 2
+    assert _run(runner, tmp_path, ids=CLEAN_IDS[:1], formats="aptino,nonsense") == 2
+
+
+def test_stub_binary_fixtures_are_not_scored(runner, tmp_path):
+    assert _run(runner, tmp_path, ids=CLEAN_IDS[:1]) == 0
+    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
+    stubs = [f["id"] for f in manifest["fixtures"] if f.get("builder")]
+    assert stubs and all(not f["scored"] for f in manifest["fixtures"] if f.get("builder"))
+    # Asking for a stub explicitly still scores nothing: it is unscored, not a pass.
+    assert _run(runner, tmp_path, ids=[stubs[0]]) == 1  # zero runs is never a vacuous pass
+
+
+def test_gate_math_reports_numerator_denominator_and_ids(runner):
+    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
+    fixtures = {
+        "a": {"id": "a", "expects_work_history": True, "expected_roles": [{"company": "X", "title": "T"}],
+              "expected_name": "N"},
+        "b": {"id": "b", "expects_work_history": True, "expected_roles": [{"company": "Y", "title": "T"}],
+              "expected_name": "N"},
+    }
+    ok = {"status": "passed", "expectation_failures": [], "style_failures": None}
+    lost = {"status": "needs_review", "expectation_failures": ["bullet:x"], "style_failures": None}
+    results = [
+        {"id": "a", "runs": {"aptino": ok}, "parse": {"roles": 1, "bad_name": False, "annotated_titled_roles": 1,
+                                                         "untitled_source_titled_roles": []}},
+        {"id": "b", "runs": {"aptino": lost}, "parse": {"roles": 0, "bad_name": True, "annotated_titled_roles": 1,
+                                                          "untitled_source_titled_roles": ["Y"]}},
+    ]
+    gates = {g["gate"]: g for g in runner.compute_golden_gates(manifest, results, fixtures)}
+    assert (gates["passed_pct"]["numerator"], gates["passed_pct"]["denominator"]) == (1, 2)
+    assert gates["passed_pct"]["failing_ids"] == ["b@aptino"] and gates["passed_pct"]["met"] is False
+    assert gates["zero_role_pct"]["failing_ids"] == ["b"] and gates["zero_role_pct"]["met"] is False
+    assert gates["empty_title_pct"]["failing_ids"] == ["b:Y"]
+    assert gates["bad_name_pct"]["failing_ids"] == ["b"]
+    # No scored OCR / DOC fixtures: reported as not enforced, never silently green.
+    assert gates["scanned_recovery_pct"]["met"] is None and gates["doc_conversion_pct"]["met"] is None
+    assert runner.golden_exit_code(list(gates.values()), 2) == 1
+    assert runner.golden_exit_code(list(gates.values()), 0) == 1
+
+
+def test_numeric_level_suffix_stays_in_the_title():
+    """Regression found by the golden gate: 'Engineer II | dates' parsed as title 'Engineer', company 'II'."""
+    from app.services.detailed_resume_parser import parse_resume_detailed
+
+    text = (BACKEND / "tests" / "fixtures" / "golden" / "cases" / "promotion_ladder.txt").read_text(encoding="utf-8")
+    roles = parse_resume_detailed(None, text)["experience"]
+    assert [(r["title"], r["company"]) for r in roles] == [
+        ("Engineer I", "ExampleCorp"),
+        ("Engineer II", "ExampleCorp"),
+    ]
