diff --git a/backend/app/services/resume_generation_service.py b/backend/app/services/resume_generation_service.py
index 64e4044..6e53250 100644
--- a/backend/app/services/resume_generation_service.py
+++ b/backend/app/services/resume_generation_service.py
@@ -34,10 +34,11 @@ from app.services.aptino_template import (
     get_aptino_default_metadata,
     is_aptino_template,
 )
 from app.services.s3_service import download_to_local_path, sanitize_filename, upload_bytes_to_key
 from app.services.detailed_resume_parser import parse_resume_detailed
+from app.services import integrity_recovery
 from app.services.output_integrity import IntegrityReport, check_output_integrity
 from app.services.pdf_parser import extract_text_from_document
 from app.services.structured_resume_store import (
     apply_store_to_candidate_data,
     attach_unassigned_experience,
@@ -129,10 +130,75 @@ class ResumeGenerationService:
             status=report.status,
             checks={k: f"{v['found']}/{v['expected']}" for k, v in report.checks.items()},
         )
         return report
 
+    def _maybe_integrity_recover(
+        self,
+        candidate: Candidate,
+        client_format: ClientFormat,
+        store: dict[str, Any],
+        detailed_data: dict[str, Any],
+        document: dict[str, Any],
+        format_metadata: dict[str, Any],
+        header_logos: list[dict[str, Any]],
+        footer_logos: list[dict[str, Any]],
+        docx_bytes: bytes,
+        report: IntegrityReport | None,
+    ) -> tuple[bytes, IntegrityReport | None, dict[str, Any], dict[str, Any]]:
+        """One grounded recovery pass; returns the preferred ``(docx, report, store, document)``.
+
+        Never raises: any failure keeps the first draft and is recorded in
+        ``parse_meta.integrity_recovery``.
+        """
+        meta: dict[str, Any] = {"used": False}
+        try:
+            source_text = (candidate.extracted_data or {}).get("raw_text") or ""
+            if report is not None and integrity_recovery.should_recover(report, store, source_text):
+                from app.services.output_integrity import _docx_text
+
+                new_store, meta = integrity_recovery.recover_store(
+                    source_text, store, report, _docx_text(docx_bytes)
+                )
+                meta = dict(meta)
+                if meta.get("used"):
+                    new_doc = self._generate_professional_document(
+                        apply_store_to_candidate_data(detailed_data, new_store), format_metadata
+                    )
+                    new_doc = attach_unassigned_experience(new_doc, new_store, format_metadata)
+                    for key in ("company_footer_lines", "company_header_lines",
+                                "client_header_text", "client_footer_text"):
+                        if key in document:
+                            new_doc[key] = document[key]
+                    findings = self._soften_missing_section_findings(
+                        validate_format_document(new_doc, format_metadata, kb=None), new_store, new_doc
+                    )
+                    if has_critical_findings(findings):
+                        meta["preferred"] = False
+                        meta["error"] = "format_validation"
+                    else:
+                        new_docx = self._render_with_format_strategy(
+                            new_doc, format_metadata, header_logos, footer_logos, client_format=client_format
+                        )
+                        new_report = self._integrity_report(
+                            new_store, new_docx, new_doc, format_metadata, client_format, candidate
+                        )
+                        meta["preferred"] = bool(
+                            new_report is not None and integrity_recovery.prefer_recovered(report, new_report)
+                        )
+                        if meta["preferred"]:
+                            store, docx_bytes, report, document = new_store, new_docx, new_report, new_doc
+                            candidate.extracted_data = {
+                                **(candidate.extracted_data or {}),
+                                "structured_resume": store,
+                            }
+        except Exception as exc:  # noqa: BLE001 - recovery must never fail generation
+            logger.warning("integrity_recovery_failed", error_type=type(exc).__name__)
+            meta = {**meta, "preferred": False, "error": type(exc).__name__}
+        store["parse_meta"] = {**(store.get("parse_meta") or {}), "integrity_recovery": meta}
+        return docx_bytes, report, store, document
+
     def generate(self, candidate: Candidate, client_format: ClientFormat) -> bytes:
         self.last_report = None
         logger.info(
             "starting_resume_generation",
             candidate_id=str(candidate.id),
@@ -266,11 +332,16 @@ class ResumeGenerationService:
                 error=str(e),
                 exc_info=True,
             )
             raise ResumeGenerationError(f"Failed to render DOCX: {e}") from e
 
-        self.last_report = self._integrity_report(store, docx_bytes, document, format_metadata, client_format, candidate)
+        report = self._integrity_report(store, docx_bytes, document, format_metadata, client_format, candidate)
+        docx_bytes, report, store, document = self._maybe_integrity_recover(
+            candidate, client_format, store, detailed_data, document, format_metadata,
+            header_logos, footer_logos, docx_bytes, report,
+        )
+        self.last_report = report
 
         safe_client = sanitize_filename(getattr(client_format, "client_id", None) or "client")
         object_key = f"resumes/{candidate.recruiter_id}/generated/{candidate.id}_{safe_client}.docx"
 
         logger.info(
diff --git a/backend/tests/test_integrity_recovery.py b/backend/tests/test_integrity_recovery.py
index 634f090..9808795 100644
--- a/backend/tests/test_integrity_recovery.py
+++ b/backend/tests/test_integrity_recovery.py
@@ -255,5 +255,159 @@ def test_recover_store_timeout_reports_budget_calls_and_no_estimate():
 
     _, meta = ir.recover_store(SOURCE, _store(), _blocking(hard=2), "Casey Example", client=broken)
 
     assert meta["used"] is False
     assert meta["missing_out_estimate"] is None
+
+
+# ---------------------------------------------------------------------------
+# Wiring into ResumeGenerationService
+# ---------------------------------------------------------------------------
+
+import io
+from types import SimpleNamespace
+
+from docx import Document
+
+from app.services.resume_generation_service import ResumeGenerationService
+
+
+def _docx(text: str) -> bytes:
+    buf = io.BytesIO()
+    doc = Document()
+    doc.add_paragraph(text)
+    doc.save(buf)
+    return buf.getvalue()
+
+
+def _ok_report(hard=0):
+    return IntegrityReport(status="passed", checks={"source_lines": {"ok": hard == 0, "hard": hard}}, warnings=[])
+
+
+class _Wiring:
+    """Service with the heavy collaborators stubbed; records what was called."""
+
+    def __init__(self, monkeypatch, *, first_hard=3, second_hard=0, recovered=True, enabled=True):
+        self.svc = ResumeGenerationService()
+        self.recover_calls = []
+        self.render_calls = 0
+        self.reports = [_ok_report(second_hard)]
+        self.new_store = {"experience": [{"company": "Acme Corp"}], "raw_text": SOURCE, "parse_meta": {}}
+        self.old_store = {"experience": [], "raw_text": SOURCE, "parse_meta": {}}
+        self.first_report = _ok_report(first_hard)
+        if enabled:
+            _enable(monkeypatch)
+        else:
+            monkeypatch.setattr(settings, "RESUME_INTEGRITY_RECOVERY", False)
+
+        def fake_recover(source_text, store, report, output_text="", *, client=None):
+            self.recover_calls.append((source_text, output_text))
+            if recovered:
+                return self.new_store, {"used": True, "llm_calls": 2, "error": ""}
+            return store, {"used": False, "llm_calls": 1, "error": "no_roles"}
+
+        def fake_render(document, *a, **k):
+            self.render_calls += 1
+            return _docx("recovered output")
+
+        monkeypatch.setattr(ir, "recover_store", fake_recover)
+        monkeypatch.setattr(self.svc, "_render_with_format_strategy", fake_render)
+        monkeypatch.setattr(
+            self.svc, "_generate_professional_document",
+            lambda data, meta: {"sections": [{"title": "Experience"}], "marker": "new"},
+        )
+        monkeypatch.setattr(self.svc, "_integrity_report", lambda *a, **k: self.reports[0])
+        monkeypatch.setattr(
+            "app.services.resume_generation_service.validate_format_document", lambda *a, **k: []
+        )
+        self.candidate = SimpleNamespace(
+            id="c1", extracted_data={"raw_text": SOURCE, "structured_resume": self.old_store}
+        )
+        self.client_format = SimpleNamespace(id="f1", format_metadata={})
+
+    def run(self):
+        original_docx = _docx("original output")
+        self.original_docx = original_docx
+        self.original_doc = {"sections": [], "marker": "old", "company_footer_lines": ["Footer"]}
+        return self.svc._maybe_integrity_recover(
+            self.candidate, self.client_format, self.old_store, {"experience": []},
+            self.original_doc, {}, [], [], original_docx, self.first_report,
+        )
+
+
+def test_maybe_integrity_recover_prefers_better_recovered_draft(monkeypatch):
+    w = _Wiring(monkeypatch, first_hard=3, second_hard=0)
+    docx_bytes, report, store, document = w.run()
+
+    assert len(w.recover_calls) == 1
+    assert "original output" in w.recover_calls[0][1]  # DOCX text passed as output_text
+    assert w.render_calls == 1
+    assert report is w.reports[0]
+    assert docx_bytes != w.original_docx
+    assert store["experience"] == [{"company": "Acme Corp"}]
+    assert document["marker"] == "new"
+    assert document["company_footer_lines"] == ["Footer"]  # branding carried over
+    assert w.candidate.extracted_data["structured_resume"] is store
+    meta = store["parse_meta"]["integrity_recovery"]
+    assert meta["used"] is True and meta["preferred"] is True
+
+
+def test_maybe_integrity_recover_keeps_original_when_recovery_not_better(monkeypatch):
+    w = _Wiring(monkeypatch, first_hard=3, second_hard=3)
+    docx_bytes, report, store, document = w.run()
+
+    assert w.render_calls == 1
+    assert report is w.first_report
+    assert docx_bytes == w.original_docx
+    assert store is w.old_store
+    assert document is w.original_doc
+    meta = store["parse_meta"]["integrity_recovery"]
+    assert meta["used"] is True and meta["preferred"] is False
+
+
+def test_maybe_integrity_recover_skips_render_when_recovery_unused(monkeypatch):
+    w = _Wiring(monkeypatch, recovered=False)
+    docx_bytes, report, store, _ = w.run()
+
+    assert w.render_calls == 0
+    assert docx_bytes == w.original_docx
+    assert report is w.first_report
+    assert store["parse_meta"]["integrity_recovery"]["used"] is False
+    assert store["parse_meta"]["integrity_recovery"]["error"] == "no_roles"
+
+
+def test_maybe_integrity_recover_noop_when_not_needed_or_disabled(monkeypatch):
+    w = _Wiring(monkeypatch, first_hard=0)
+    w.old_store["experience"] = [{"company": "Acme Corp"}]  # roles present: nothing to recover
+    _, report, store, _ = w.run()
+    assert w.recover_calls == [] and w.render_calls == 0
+    assert report is w.first_report
+    assert store["parse_meta"]["integrity_recovery"] == {"used": False}
+
+    w = _Wiring(monkeypatch, first_hard=3, enabled=False)
+    w.run()
+    assert w.recover_calls == [] and w.render_calls == 0
+
+
+def test_maybe_integrity_recover_never_raises_when_rerender_fails(monkeypatch):
+    w = _Wiring(monkeypatch)
+
+    def boom(*a, **k):
+        raise RuntimeError("render exploded")
+
+    monkeypatch.setattr(w.svc, "_render_with_format_strategy", boom)
+    docx_bytes, report, store, document = w.run()
+
+    assert docx_bytes == w.original_docx
+    assert report is w.first_report
+    assert document is w.original_doc
+    meta = store["parse_meta"]["integrity_recovery"]
+    assert meta["preferred"] is False
+    assert meta["error"] == "RuntimeError"
+
+
+def test_maybe_integrity_recover_skips_when_report_missing(monkeypatch):
+    w = _Wiring(monkeypatch)
+    w.first_report = None
+    _, report, _, _ = w.run()
+    assert report is None
+    assert w.recover_calls == []
