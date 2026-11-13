# Review package Task 0 (after fix)
BASE: 9b6b1a75ed65142e3e645fb7f93075896eecc9a6
HEAD: 9ea9cfefb3d659106d8992fd91548759b6471a0d

## Commits
9ea9cfe fix: unscored golden fixtures until binary builders exist f924a4b test: pin corpus baseline case map and golden manifest skeleton

## Diff stat
 .superpowers/sdd/task-0-report.md                  |   87 ++  backend/eval_reports/baseline_case_map.md          |   63 +  .../tests/fixtures/golden/build_golden_fixtures.py |  106 ++  .../fixtures/golden/cases/ambiguous_dates.txt      |    7 +  .../fixtures/golden/cases/ambiguous_headers.txt    |    8 +  .../tests/fixtures/golden/cases/ambiguous_name.txt |    7 +  .../tests/fixtures/golden/cases/ambiguous_swap.txt |    7 +  .../tests/fixtures/golden/cases/bullet_only.txt    |    8 +  .../fixtures/golden/cases/bullet_only_dated.txt    |    8 +  .../tests/fixtures/golden/cases/caps_sections.txt  |    9 +  .../tests/fixtures/golden/cases/certifications.txt |    9 +  .../fixtures/golden/cases/clean_conventional.txt   |   13 +  .../tests/fixtures/golden/cases/clean_one_role.txt |    9 +  .../fixtures/golden/cases/clean_with_projects.txt  |   14 +  .../golden/cases/clean_without_projects.txt        |   11 +  .../tests/fixtures/golden/cases/contact_header.txt |    8 +  .../tests/fixtures/golden/cases/current_role.txt   |    7 +  .../fixtures/golden/cases/dice_inside_resume.txt   |   12 +  .../fixtures/golden/cases/dice_labels_only.txt     |   16 +  .../tests/fixtures/golden/cases/dice_wrapper.txt   |   31 +  .../fixtures/golden/cases/education_one_role.txt   |    8 +  .../tests/fixtures/golden/cases/education_only.txt |    6 +  .../tests/fixtures/golden/cases/emdash_header.txt  |    7 +  .../tests/fixtures/golden/cases/empty_title.txt    |    5 +  backend/tests/fixtures/golden/cases/legacy_doc.txt |    7 +  .../fixtures/golden/cases/legacy_doc_contract.txt  |    7 +  .../fixtures/golden/cases/legacy_doc_multi.txt     |    7 +  .../tests/fixtures/golden/cases/long_bullets.txt   |   14 +  .../tests/fixtures/golden/cases/long_history.txt   |   33 +  .../fixtures/golden/cases/missing_optional.txt     |   11 +  .../fixtures/golden/cases/missing_summary.txt      |    9 +  .../fixtures/golden/cases/month_year_roles.txt     |    7 +  .../golden/cases/non_resume_certificate.txt        |    3 +  .../fixtures/golden/cases/non_resume_travel.txt    |    3 +  .../tests/fixtures/golden/cases/numeric_dates.txt  |   12 +  .../tests/fixtures/golden/cases/paren_title.txt    |    8 +  .../tests/fixtures/golden/cases/pipe_headers.txt   |    5 +  .../fixtures/golden/cases/promotion_ladder.txt     |   10 +  backend/tests/fixtures/golden/cases/references.txt |    7 +  .../fixtures/golden/cases/same_month_employers.txt |    7 +  .../tests/fixtures/golden/cases/scanned_mixed.txt  |    9 +  .../tests/fixtures/golden/cases/scanned_stub.txt   |    9 +  .../fixtures/golden/cases/scanned_three_page.txt   |   11 +  .../tests/fixtures/golden/cases/skills_only.txt    |    8 +  .../fixtures/golden/cases/sparse_profile_full.txt  |   18 +  .../tests/fixtures/golden/cases/sparse_valid.txt   |    7 +  .../fixtures/golden/cases/table_education.txt      |    8 +  .../fixtures/golden/cases/table_experience.txt     |    7 +  backend/tests/fixtures/golden/cases/title_only.txt |    7 +  backend/tests/fixtures/golden/cases/two_column.txt |   12 +  .../fixtures/golden/cases/two_column_sidebar.txt   |   12 +  .../fixtures/golden/cases/two_column_skills.txt    |   10 +  .../fixtures/golden/cases/unicode_bullets.txt      |    7 +  backend/tests/fixtures/golden/manifest.json        | 1461 ++++++++++++++++++++  backend/tests/test_golden_manifest.py              |   76 +  55 files changed, 2278 insertions(+)
diff --git a/backend/tests/fixtures/golden/build_golden_fixtures.py b/backend/tests/fixtures/golden/build_golden_fixtures.py
new file mode 100644
index 0000000..96bc999
--- /dev/null
+++ b/backend/tests/fixtures/golden/build_golden_fixtures.py
@@ -0,0 +1,106 @@
+"""Build synthetic golden fixtures from anonymized text cases.
+
+Text patterns already live in ``cases/``. PDF, DOCX-table, and legacy DOC
+builders are stubbed for later waves. This module never reads the corpus or
+``eval_reports/samples``.
+"""
+
+from __future__ import annotations
+
+import argparse
+import json
+from pathlib import Path
+
+ROOT = Path(__file__).resolve().parent
+MANIFEST_PATH = ROOT / "manifest.json"
+
+STUB_REASON = {
+    "scanned_pdf": "Wave C: render the case text into an image-only PDF for OCR recovery.",
+    "mixed_pdf": "Wave C: one selectable-text page plus one image-only page.",
+    "table_docx": "Wave C: write the case rows into a DOCX table.",
+    "legacy_doc": "Wave C: emit a .doc from the case text when LibreOffice is available.",
+}
+# Scored gates must ignore fixtures using these builders until materialization works.
+
+
+def load_manifest() -> dict:
+    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
+
+
+def case_text(fixture: dict) -> str:
+    path = ROOT / fixture["source"]
+    return path.read_text(encoding="utf-8")
+
+
+def build_scanned_pdf(fixture: dict, dest: Path) -> None:
+    raise NotImplementedError(f"{fixture['id']}: {STUB_REASON['scanned_pdf']} source={fixture['source']}")
+
+
+def build_mixed_pdf(fixture: dict, dest: Path) -> None:
+    raise NotImplementedError(f"{fixture['id']}: {STUB_REASON['mixed_pdf']} source={fixture['source']}")
+
+
+def build_table_docx(fixture: dict, dest: Path) -> None:
+    raise NotImplementedError(f"{fixture['id']}: {STUB_REASON['table_docx']} source={fixture['source']}")
+
+
+def build_legacy_doc(fixture: dict, dest: Path) -> None:
+    raise NotImplementedError(f"{fixture['id']}: {STUB_REASON['legacy_doc']} source={fixture['source']}")
+
+
+BUILDERS = {
+    "scanned_pdf": build_scanned_pdf,
+    "mixed_pdf": build_mixed_pdf,
+    "table_docx": build_table_docx,
+    "legacy_doc": build_legacy_doc,
+}
+
+
+def check_sources(manifest: dict | None = None) -> list[str]:
+    data = manifest if manifest is not None else load_manifest()
+    missing: list[str] = []
+    for fixture in data["fixtures"]:
+        path = ROOT / fixture["source"]
+        if not path.is_file():
+            missing.append(fixture["id"])
+        builder = fixture.get("builder")
+        if builder and builder not in BUILDERS:
+            missing.append(f"{fixture['id']}:unknown-builder:{builder}")
+    return missing
+
+
+def materialize(fixture: dict, dest_dir: Path) -> Path:
+    """Copy a text case, or dispatch a binary builder when one is named."""
+    dest_dir.mkdir(parents=True, exist_ok=True)
+    builder_name = fixture.get("builder")
+    if not builder_name:
+        dest = dest_dir / Path(fixture["source"]).name
+        dest.write_text(case_text(fixture), encoding="utf-8")
+        return dest
+    suffix = {"scanned_pdf": ".pdf", "mixed_pdf": ".pdf", "table_docx": ".docx", "legacy_doc": ".doc"}[builder_name]
+    dest = dest_dir / f"{fixture['id']}{suffix}"
+    BUILDERS[builder_name](fixture, dest)
+    return dest
+
+
+def main() -> None:
+    parser = argparse.ArgumentParser(description="Inspect or build synthetic golden fixtures.")
+    parser.add_argument("--list", action="store_true", help="Print fixture id, pattern, and source.")
+    parser.add_argument("--check-sources", action="store_true", help="Exit non-zero if a case file is missing.")
+    args = parser.parse_args()
+    manifest = load_manifest()
+    if args.list:
+        for fixture in manifest["fixtures"]:
+            builder = fixture.get("builder") or "text"
+            print(f"{fixture['id']}\t{fixture['pattern']}\t{fixture['source']}\t{builder}")
+    missing = check_sources(manifest)
+    if args.check_sources and missing:
+        raise SystemExit("missing golden sources: " + ", ".join(missing))
+    if args.check_sources:
+        print(f"ok {len(manifest['fixtures'])} sources")
+    if not args.list and not args.check_sources:
+        parser.print_help()
+
+
+if __name__ == "__main__":
+    main()
diff --git a/backend/tests/fixtures/golden/manifest.json b/backend/tests/fixtures/golden/manifest.json
new file mode 100644
index 0000000..c79a476
--- /dev/null
+++ b/backend/tests/fixtures/golden/manifest.json
@@ -0,0 +1,1461 @@
+{
+  "version": 1,
+  "baseline_run": "corpus_eval_20261111_135025",
+  "fixtures": [
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "clean_guillermo_pattern",
+      "pattern": "conventional_clean",
+      "source": "cases/clean_conventional.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_roles": [
+        {
+          "company": "ExampleCorp",
+          "title": "Senior Engineer",
+          "dates_contains": [
+            "2020"
+          ],
+          "bullet_substrings": [
+            "shipped"
+          ]
+        }
+      ],
+      "expected_name": "Alex Example",
+      "style_subset": true
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "dice_wrapper_full_resume",
+      "pattern": "dice_wrapper",
+      "source": "cases/dice_wrapper.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_roles": [
+        {
+          "company": "Amazon",
+          "title": "Software Engineer",
+          "bullet_substrings": [
+            "onboarding tool"
+          ]
+        }
+      ],
+      "expected_name": "Morgan Hale"
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "paren_title_split_header",
+      "pattern": "paren_title",
+      "source": "cases/paren_title.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_roles": [
+        {
+          "company": "Northwind Labs",
+          "title": "Platform Engineer",
+          "dates_contains": [
+            "03/19"
+          ],
+          "bullet_substrings": [
+            "billing service"
+          ]
+        }
+      ],
+      "expected_name": "Jordan Hale"
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "bullet_only_experience",
+      "pattern": "bullet_only",
+      "source": "cases/bullet_only.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "allow_unassigned_bullets": true,
+      "expected_bullet_substrings": [
+        "onboarding checklist",
+        "finance close",
+        "close checklist"
+      ],
+      "expected_name": "Riley Quinn"
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "education_only_complete",
+      "pattern": "education_only",
+      "source": "cases/education_only.txt",
+      "scored": true,
+      "expects_work_history": false,
+      "expected_name": "Quinn Harper",
+      "expected_education_substrings": [
+        "Example State College",
+        "Computer Science"
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "clean_one_role",
+      "pattern": "conventional_clean",
+      "source": "cases/clean_one_role.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "Litware",
+          "title": "Analyst",
+          "dates_contains": [
+            "2021"
+          ],
+          "bullet_substrings": [
+            "monthly books"
+          ]
+        }
+      ],
+      "style_subset": true
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "emdash_role_header",
+      "pattern": "emdash_header",
+      "source": "cases/emdash_header.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "Fabrikam Studio",
+          "title": "Designer",
+          "dates_contains": [
+            "2019"
+          ],
+          "bullet_substrings": [
+            "settings screens"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "title_only_under_experience",
+      "pattern": "title_only",
+      "source": "cases/title_only.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "title": "Product Designer",
+          "bullet_substrings": [
+            "settings screens"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "numeric_date_history",
+      "pattern": "numeric_dates",
+      "source": "cases/numeric_dates.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "Litware",
+          "title": "Analyst",
+          "dates_contains": [
+            "2021"
+          ],
+          "bullet_substrings": [
+            "monthly books"
+          ]
+        },
+        {
+          "company": "Fabrikam Studio",
+          "title": "Designer",
+          "dates_contains": [
+            "2018"
+          ],
+          "bullet_substrings": [
+            "settings screens"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "promotion_same_employer",
+      "pattern": "promotion",
+      "source": "cases/promotion_ladder.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "ExampleCorp",
+          "title": "Engineer I",
+          "dates_contains": [
+            "2016"
+          ],
+          "bullet_substrings": [
+            "intake form"
+          ]
+        },
+        {
+          "company": "ExampleCorp",
+          "title": "Engineer II",
+          "dates_contains": [
+            "2019"
+          ],
+          "bullet_substrings": [
+            "billing service"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "two_column_body",
+      "pattern": "two_column",
+      "source": "cases/two_column.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "Harbor Analytics",
+          "title": "Analyst",
+          "dates_contains": [
+            "2019"
+          ],
+          "bullet_substrings": [
+            "sales report"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "two_column_sidebar",
+      "pattern": "two_column",
+      "source": "cases/two_column_sidebar.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "Harbor Analytics",
+          "title": "Data Engineer",
+          "dates_contains": [
+            "2019"
+          ],
+          "bullet_substrings": [
+            "ETL pipelines"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "table_docx_experience",
+      "pattern": "table_docx",
+      "source": "cases/table_experience.txt",
+      "scored": false,
+      "expects_work_history": true,
+      "builder": "table_docx",
+      "ext": "docx",
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "Harbor Analytics",
+          "title": "Data Engineer",
+          "dates_contains": [
+            "2019"
+          ],
+          "bullet_substrings": [
+            "ETL pipelines"
+          ]
+        },
+        {
+          "company": "Litware",
+          "title": "Analyst",
+          "dates_contains": [
+            "2015"
+          ],
+          "bullet_substrings": [
+            "finance reports"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "long_history_twelve_roles",
+      "pattern": "long_history",
+      "source": "cases/long_history.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_name": "Alex Example",
+      "expected_roles": [
+        {
+          "company": "ExampleCorp",
+          "title": "Engineer I",
+          "dates_contains": [
+            "2010"
+          ],
+          "bullet_substrings": [
+            "shipped"
+          ]
+        },
+        {
+          "company": "Northwind Labs",
+          "title": "Engineer II",
+          "dates_contains": [
+            "2011"
+          ],
+          "bullet_substrings": [
+            "kept"
+          ]
+        },
+        {
+          "company": "Contoso Labs",
+          "title": "Analyst",
+          "dates_contains": [
+            "2012"
+          ],
+          "bullet_substrings": [
+            "closed"
+          ]
+        },
+        {
+          "company": "Fabrikam Studio",
+          "title": "Designer",
+          "dates_contains": [
+            "2013"
+          ],
+          "bullet_substrings": [
+            "drew"
+          ]
+        },
+        {
+          "company": "Adventure Works",
+          "title": "Consultant",
+          "dates_contains": [
+            "2014"
+          ],
+          "bullet_substrings": [
+            "mapped"
+          ]
+        },
+        {
+          "company": "Litware",
+          "title": "Developer",
+          "dates_contains": [
+            "2015"
+          ],
+          "bullet_substrings": [
+            "added"
+          ]
+        },
+        {
+          "company": "Tailspin Toys",
+          "title": "Lead",
+          "dates_contains": [
+            "2016"
+          ],
+          "bullet_substrings": [
+            "mentored"
+          ]
+        },
+        {
+          "company": "Alpine Retail",
+          "title": "Manager",
+          "dates_contains": [
+            "2017"
+          ],
+          "bullet_substrings": [
+            "ran"
+          ]
+        },
+        {
+          "company": "Harbor Analytics",
+          "title": "Data Engineer",
+          "dates_contains": [
+            "2018"
+          ],
+          "bullet_substrings": [
+            "built"
+          ]
+        },
+        {
+          "company": "Pioneer Mutual",
+          "title": "Engineer",
+          "dates_contains": [
+            "2019"
+          ],
+          "bullet_substrings": [
+            "documented"
+          ]
+        },
+        {
+          "company": "Cedar Systems",
+          "title": "Senior Engineer",
+          "dates_contains": [
+            "2020"
+          ],
+          "bullet_substrings": [
+            "shipped"
+          ]
+        },
+        {
+          "company": "Wide World Importers",
+          "title": "Staff Engineer",
+          "dates_contains": [
+            "2021"
+          ],
+          "bullet_substrings": [
+            "led"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "missing_optional_sections",
+      "pattern": "missing_optional",
+      "source": "cases/missing_optional.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "absent_sections": [
+        "projects",
+        "certifications",
+        "references"
+      ],
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "ExampleCorp",
+          "title": "Senior Engineer",
+          "dates_contains": [
+            "2020"
+          ],
+          "bullet_substrings": [
+            "shipped"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "missing_summary",
+      "pattern": "missing_optional",
+      "source": "cases/missing_summary.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "absent_sections": [
+        "summary"
+      ],
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "Litware",
+          "title": "Analyst",
+          "dates_contains": [
+            "2021"
+          ],
+          "bullet_substrings": [
+            "monthly books"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "scanned_image_stub",
+      "pattern": "scanned",
+      "source": "cases/scanned_stub.txt",
+      "scored": false,
+      "expects_work_history": true,
+      "builder": "scanned_pdf",
+      "ext": "pdf",
+      "intake": "ocr",
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "ExampleCorp",
+          "title": "Senior Engineer",
+          "dates_contains": [
+            "2020"
+          ],
+          "bullet_substrings": [
+            "shipped"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "scanned_mixed_pages",
+      "pattern": "scanned",
+      "source": "cases/scanned_mixed.txt",
+      "scored": false,
+      "expects_work_history": true,
+      "builder": "mixed_pdf",
+      "ext": "pdf",
+      "intake": "ocr",
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "Litware",
+          "title": "Analyst",
+          "dates_contains": [
+            "2021"
+          ],
+          "bullet_substrings": [
+            "monthly books"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "legacy_doc_simple",
+      "pattern": "legacy_doc",
+      "source": "cases/legacy_doc.txt",
+      "scored": false,
+      "expects_work_history": true,
+      "builder": "legacy_doc",
+      "ext": "doc",
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "Litware",
+          "title": "Analyst",
+          "dates_contains": [
+            "2021"
+          ],
+          "bullet_substrings": [
+            "monthly books"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "legacy_doc_multi_role",
+      "pattern": "legacy_doc",
+      "source": "cases/legacy_doc_multi.txt",
+      "scored": false,
+      "expects_work_history": true,
+      "builder": "legacy_doc",
+      "ext": "doc",
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "Litware",
+          "title": "Analyst",
+          "dates_contains": [
+            "2021"
+          ],
+          "bullet_substrings": [
+            "monthly books"
+          ]
+        },
+        {
+          "company": "Fabrikam Studio",
+          "title": "Designer",
+          "dates_contains": [
+            "2018"
+          ],
+          "bullet_substrings": [
+            "settings screens"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "sparse_profile_needs_full_resume",
+      "pattern": "sparse_profile",
+      "source": "cases/sparse_profile_full.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_name": "Casey Example",
+      "expected_summary_substrings": [
+        "weekly retail reports"
+      ],
+      "expected_roles": [
+        {
+          "company": "Litware",
+          "title": "Analyst",
+          "dates_contains": [
+            "2021"
+          ],
+          "bullet_substrings": [
+            "monthly books"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "sparse_valid_resume",
+      "pattern": "sparse_profile",
+      "source": "cases/sparse_valid.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "Litware",
+          "title": "Analyst",
+          "dates_contains": [
+            "2021"
+          ],
+          "bullet_substrings": [
+            "monthly books"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "needs_review",
+      "id": "ambiguous_role_headers",
+      "pattern": "ambiguous",
+      "source": "cases/ambiguous_headers.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_name": "Casey Example",
+      "expected_bullet_substrings": [
+        "monthly books",
+        "settings screens"
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "needs_review",
+      "id": "ambiguous_tech_token_name",
+      "pattern": "ambiguous",
+      "source": "cases/ambiguous_name.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "rejected_names": [
+        "React Native",
+        "React Native."
+      ],
+      "expected_roles": [
+        {
+          "company": "Litware",
+          "title": "Analyst",
+          "dates_contains": [
+            "2021"
+          ],
+          "bullet_substrings": [
+            "monthly books"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "needs_review",
+      "id": "ambiguous_overlapping_dates",
+      "pattern": "ambiguous",
+      "source": "cases/ambiguous_dates.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "Litware",
+          "title": "Analyst",
+          "dates_contains": [
+            "2020"
+          ],
+          "bullet_substrings": [
+            "monthly books"
+          ]
+        },
+        {
+          "company": "Fabrikam Studio",
+          "title": "Designer",
+          "dates_contains": [
+            "2021"
+          ],
+          "bullet_substrings": [
+            "settings screens"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "pipe_delimited_headers",
+      "pattern": "pipe_header",
+      "source": "cases/pipe_headers.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "Litware",
+          "title": "Analyst",
+          "dates_contains": [
+            "2021"
+          ],
+          "bullet_substrings": [
+            "monthly books"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "all_caps_sections",
+      "pattern": "caps_sections",
+      "source": "cases/caps_sections.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "Litware",
+          "title": "Analyst",
+          "dates_contains": [
+            "2021"
+          ],
+          "bullet_substrings": [
+            "monthly books"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "education_with_single_role",
+      "pattern": "education_plus_role",
+      "source": "cases/education_one_role.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "Litware",
+          "title": "Analyst",
+          "dates_contains": [
+            "2021"
+          ],
+          "bullet_substrings": [
+            "monthly books"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "skills_only_no_employment",
+      "pattern": "skills_only",
+      "source": "cases/skills_only.txt",
+      "scored": true,
+      "expects_work_history": false,
+      "expected_name": "Casey Example",
+      "expected_skill_substrings": [
+        "Python",
+        "SQL"
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "certifications_block",
+      "pattern": "certifications",
+      "source": "cases/certifications.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "Harbor Analytics",
+          "title": "Data Engineer",
+          "dates_contains": [
+            "2019"
+          ],
+          "bullet_substrings": [
+            "ETL pipelines"
+          ]
+        }
+      ],
+      "expected_certification_substrings": [
+        "AWS Certified Data Engineer"
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "references_section_present",
+      "pattern": "references",
+      "source": "cases/references.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_name": "Casey Example",
+      "optional_omitted_sections": [
+        "references"
+      ],
+      "expected_roles": [
+        {
+          "company": "Litware",
+          "title": "Analyst",
+          "dates_contains": [
+            "2021"
+          ],
+          "bullet_substrings": [
+            "monthly books"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "needs_review",
+      "id": "empty_title_under_company",
+      "pattern": "empty_title",
+      "source": "cases/empty_title.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "Litware",
+          "dates_contains": [
+            "2021"
+          ],
+          "bullet_substrings": [
+            "monthly books"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "bullet_only_with_date_lines",
+      "pattern": "bullet_only",
+      "source": "cases/bullet_only_dated.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "allow_unassigned_bullets": true,
+      "expected_name": "Casey Example",
+      "expected_bullet_substrings": [
+        "sales report",
+        "inventory count",
+        "monthly books"
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "dice_labels_without_jobs",
+      "pattern": "dice_wrapper",
+      "source": "cases/dice_labels_only.txt",
+      "scored": true,
+      "expects_work_history": false,
+      "expected_name": "Casey Example"
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "two_column_skills_rail",
+      "pattern": "two_column",
+      "source": "cases/two_column_skills.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "Harbor Analytics",
+          "title": "Data Engineer",
+          "dates_contains": [
+            "2019"
+          ],
+          "bullet_substrings": [
+            "ETL pipelines"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "table_docx_education",
+      "pattern": "table_docx",
+      "source": "cases/table_education.txt",
+      "scored": false,
+      "expects_work_history": true,
+      "builder": "table_docx",
+      "ext": "docx",
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "Litware",
+          "title": "Analyst",
+          "dates_contains": [
+            "2021"
+          ],
+          "bullet_substrings": [
+            "monthly books"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "long_bullet_single_role",
+      "pattern": "long_history",
+      "source": "cases/long_bullets.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "ExampleCorp",
+          "title": "Senior Engineer",
+          "dates_contains": [
+            "2020"
+          ],
+          "bullet_substrings": [
+            "shipped",
+            "queue workers",
+            "finance close",
+            "search index"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "contact_header_block",
+      "pattern": "contact_header",
+      "source": "cases/contact_header.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "Litware",
+          "title": "Analyst",
+          "dates_contains": [
+            "2015"
+          ],
+          "bullet_substrings": [
+            "finance reports"
+          ]
+        }
+      ]
+    },
+    {
+      "expected_status": "quarantine",
+      "id": "non_resume_certificate",
+      "pattern": "non_resume",
+      "source": "cases/non_resume_certificate.txt",
+      "scored": false,
+      "expects_work_history": false
+    },
+    {
+      "expected_status": "quarantine",
+      "id": "non_resume_travel_history",
+      "pattern": "non_resume",
+      "source": "cases/non_resume_travel.txt",
+      "scored": false,
+      "expects_work_history": false
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "legacy_doc_contract_dates",
+      "pattern": "legacy_doc",
+      "source": "cases/legacy_doc_contract.txt",
+      "scored": false,
+      "expects_work_history": true,
+      "builder": "legacy_doc",
+      "ext": "doc",
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "Litware",
+          "title": "Contract Analyst",
+          "dates_contains": [
+            "03/20"
+          ],
+          "bullet_substrings": [
+            "monthly books"
+          ]
+        },
+        {
+          "company": "Harbor Analytics",
+          "title": "Analyst",
+          "dates_contains": [
+            "01/21"
+          ],
+          "bullet_substrings": [
+            "sales report"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "scanned_three_page_stub",
+      "pattern": "scanned",
+      "source": "cases/scanned_three_page.txt",
+      "scored": false,
+      "expects_work_history": true,
+      "builder": "scanned_pdf",
+      "ext": "pdf",
+      "intake": "ocr",
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "ExampleCorp",
+          "title": "Senior Engineer",
+          "dates_contains": [
+            "2020"
+          ],
+          "bullet_substrings": [
+            "shipped"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "clean_with_projects",
+      "pattern": "projects_present",
+      "source": "cases/clean_with_projects.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "style_subset": true,
+      "expected_name": "Alex Example",
+      "expected_roles": [
+        {
+          "company": "ExampleCorp",
+          "title": "Senior Engineer",
+          "dates_contains": [
+            "2020"
+          ],
+          "bullet_substrings": [
+            "shipped"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "clean_without_projects",
+      "pattern": "projects_absent",
+      "source": "cases/clean_without_projects.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "style_subset": true,
+      "absent_sections": [
+        "projects"
+      ],
+      "expected_name": "Alex Example",
+      "expected_roles": [
+        {
+          "company": "ExampleCorp",
+          "title": "Senior Engineer",
+          "dates_contains": [
+            "2020"
+          ],
+          "bullet_substrings": [
+            "shipped"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "month_year_range_roles",
+      "pattern": "conventional_clean",
+      "source": "cases/month_year_roles.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "style_subset": true,
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "Litware",
+          "title": "Analyst",
+          "dates_contains": [
+            "2019"
+          ],
+          "bullet_substrings": [
+            "finance reports"
+          ]
+        },
+        {
+          "company": "Harbor Analytics",
+          "title": "Data Engineer",
+          "dates_contains": [
+            "2021"
+          ],
+          "bullet_substrings": [
+            "ETL pipelines"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "current_role_present",
+      "pattern": "conventional_clean",
+      "source": "cases/current_role.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "style_subset": true,
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "Litware",
+          "title": "Analyst",
+          "dates_contains": [
+            "2022"
+          ],
+          "bullet_substrings": [
+            "monthly books"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "dice_labels_inside_real_resume",
+      "pattern": "dice_wrapper",
+      "source": "cases/dice_inside_resume.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_name": "Casey Example",
+      "expected_summary_substrings": [
+        "weekly retail reports"
+      ],
+      "expected_roles": [
+        {
+          "company": "Litware",
+          "title": "Analyst",
+          "dates_contains": [
+            "2021"
+          ],
+          "bullet_substrings": [
+            "monthly books"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "unicode_bullet_markers",
+      "pattern": "unicode_bullets",
+      "source": "cases/unicode_bullets.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "Litware",
+          "title": "Analyst",
+          "dates_contains": [
+            "2021"
+          ],
+          "bullet_substrings": [
+            "monthly books",
+            "sales report",
+            "inventory count"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "passed",
+      "id": "same_month_two_employers",
+      "pattern": "conventional_clean",
+      "source": "cases/same_month_employers.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_name": "Casey Example",
+      "expected_roles": [
+        {
+          "company": "Litware",
+          "title": "Analyst",
+          "dates_contains": [
+            "2020"
+          ],
+          "bullet_substrings": [
+            "monthly books"
+          ]
+        },
+        {
+          "company": "Fabrikam Studio",
+          "title": "Designer",
+          "dates_contains": [
+            "2020"
+          ],
+          "bullet_substrings": [
+            "settings screens"
+          ]
+        }
+      ]
+    },
+    {
+      "formats": [
+        "aptino",
+        "capgemini",
+        "suresh"
+      ],
+      "expected_status": "needs_review",
+      "id": "ambiguous_company_title_swap",
+      "pattern": "ambiguous",
+      "source": "cases/ambiguous_swap.txt",
+      "scored": true,
+      "expects_work_history": true,
+      "expected_name": "Casey Example",
+      "expected_bullet_substrings": [
+        "monthly books"
+      ]
+    }
+  ],
+  "gates": {
+    "passed_pct_min": 85,
+    "zero_role_pct_max": 3,
+    "empty_title_pct_max": 5,
+    "bad_name_pct_max": 5,
+    "scanned_recovery_pct_min": 90,
+    "doc_conversion_pct_min": 90,
+    "style_assert_pct_min": 100,
+    "failed_pct_max": 2
+  }
+}
diff --git a/backend/tests/test_golden_manifest.py b/backend/tests/test_golden_manifest.py
new file mode 100644
index 0000000..b439b37
--- /dev/null
+++ b/backend/tests/test_golden_manifest.py
@@ -0,0 +1,76 @@
+import json
+from pathlib import Path
+
+REQUIRED_IDS = {
+    "clean_guillermo_pattern",
+    "dice_wrapper_full_resume",
+    "paren_title_split_header",
+    "bullet_only_experience",
+    "education_only_complete",
+}
+REQUIRED_PATTERNS = {
+    "conventional_clean",
+    "dice_wrapper",
+    "paren_title",
+    "bullet_only",
+    "education_only",
+    "two_column",
+    "table_docx",
+    "long_history",
+    "missing_optional",
+    "scanned",
+    "legacy_doc",
+    "sparse_profile",
+    "ambiguous",
+}
+GATE_KEYS = {
+    "passed_pct_min",
+    "zero_role_pct_max",
+    "empty_title_pct_max",
+    "bad_name_pct_max",
+    "scanned_recovery_pct_min",
+    "doc_conversion_pct_min",
+    "style_assert_pct_min",
+    "failed_pct_max",
+}
+STUB_BUILDERS = {"scanned_pdf", "mixed_pdf", "table_docx", "legacy_doc"}
+
+
+def _load():
+    path = Path(__file__).parent / "fixtures" / "golden" / "manifest.json"
+    data = json.loads(path.read_text(encoding="utf-8"))
+    return path, data
+
+
+def test_golden_manifest_loads_and_has_scored_fixtures():
+    _path, data = _load()
+    assert data["version"] == 1
+    scored = [f for f in data["fixtures"] if f.get("scored")]
+    assert len(scored) >= 5
+    for f in scored:
+        assert "id" in f and "expects_work_history" in f
+
+
+def test_golden_manifest_covers_pattern_families_and_sources():
+    path, data = _load()
+    assert data["baseline_run"] == "corpus_eval_20261111_135025"
+    fixtures = data["fixtures"]
+    assert len(fixtures) >= 50
+    ids = [f["id"] for f in fixtures]
+    assert len(ids) == len(set(ids))
+    assert REQUIRED_IDS <= set(ids)
+    assert REQUIRED_PATTERNS <= {f["pattern"] for f in fixtures}
+    assert any(f.get("expected_status") for f in fixtures if f["pattern"] == "ambiguous")
+    assert GATE_KEYS <= set(data["gates"])
+    root = path.parent
+    for fixture in fixtures:
+        assert (root / fixture["source"]).is_file(), fixture["id"]
+        if fixture.get("scored"):
+            assert isinstance(fixture["expects_work_history"], bool)
+
+
+def test_stubbed_binary_fixtures_are_not_scored():
+    _path, data = _load()
+    for fixture in data["fixtures"]:
+        if fixture.get("builder") in STUB_BUILDERS:
+            assert fixture.get("scored") is False, fixture["id"]
