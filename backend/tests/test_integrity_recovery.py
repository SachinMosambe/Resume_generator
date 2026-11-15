from app.core.config import Settings, settings
from app.services import integrity_recovery as ir
from app.services.output_integrity import BLOCKING, IntegrityReport


def test_integrity_recovery_settings_defaults():
    assert Settings.model_fields["RESUME_INTEGRITY_RECOVERY"].default is True
    assert Settings.model_fields["RESUME_INTEGRITY_RECOVERY_MAX_CALLS"].default == 4
    assert Settings.model_fields["RESUME_INTEGRITY_RECOVERY_TIMEOUT_SECONDS"].default == 45.0


def _enable(monkeypatch):
    monkeypatch.setattr(settings, "RESUME_INTEGRITY_RECOVERY", True)
    monkeypatch.setattr(settings, "AWS_BEARER_TOKEN_BEDROCK", "token")


def _blocking(code="source_lines", hard=3):
    return IntegrityReport(
        status="needs_review",
        checks={"source_lines": {"ok": False, "hard": hard, "soft": 1, "changed_numbers": 0}},
        warnings=[{"severity": BLOCKING, "code": code, "message": "x"}],
    )


def test_should_recover_on_blocking_source_lines(monkeypatch):
    _enable(monkeypatch)
    assert ir.should_recover(
        _blocking(), {"experience": [{"company": "Acme"}]}, "Acme\n• Built things carefully here.\n"
    ) is True


def test_should_not_recover_on_clean_pass(monkeypatch):
    _enable(monkeypatch)
    report = IntegrityReport(status="passed", checks={"source_lines": {"ok": True, "hard": 0}}, warnings=[])
    assert ir.should_recover(report, {"experience": [{"company": "Acme"}]}, "x") is False


def test_should_recover_zero_roles_with_work_evidence(monkeypatch):
    _enable(monkeypatch)
    report = IntegrityReport(status="needs_review", checks={}, warnings=[])
    source = "Experience\nAcme Corp Engineer 2020-2021\n• Shipped the billing platform for customers.\n"
    assert ir.should_recover(report, {"experience": []}, source) is True


def test_should_not_recover_when_disabled(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(settings, "RESUME_INTEGRITY_RECOVERY", False)
    assert ir.should_recover(_blocking(), {"experience": [{"company": "Acme"}]}, "x") is False
    monkeypatch.setattr(settings, "RESUME_INTEGRITY_RECOVERY", True)
    monkeypatch.setattr(settings, "AWS_BEARER_TOKEN_BEDROCK", "")
    assert ir.recovery_enabled() is False
    assert ir.should_recover(_blocking(), {"experience": [{"company": "Acme"}]}, "x") is False


def test_should_recover_on_wrong_role_even_without_hard_misses(monkeypatch):
    _enable(monkeypatch)
    report = _blocking(code="bullet_wrong_role", hard=0)
    assert ir.has_wrong_role(report) is True
    assert ir.hard_source_miss_count(report) == 0
    assert ir.should_recover(report, {"experience": [{"company": "Acme"}]}, "x") is True


def test_prefer_recovered_only_when_hard_drops_without_new_wrong_role():
    before = _blocking(hard=5)
    after_better = _blocking(hard=1)
    after_worse_role = IntegrityReport(
        status="failed",
        checks={"source_lines": {"hard": 0}},
        warnings=[{"severity": BLOCKING, "code": "bullet_wrong_role", "message": "x"}],
    )
    assert ir.prefer_recovered(before, after_better) is True
    assert ir.prefer_recovered(before, after_worse_role) is False
    assert ir.prefer_recovered(before, _blocking(hard=5)) is False
    assert ir.prefer_recovered(before, _blocking(hard=7)) is False


def test_prefer_recovered_when_wrong_role_is_cleared_without_more_misses():
    before = _blocking(code="bullet_wrong_role", hard=2)
    after = IntegrityReport(status="needs_review", checks={"source_lines": {"hard": 2}}, warnings=[])
    assert ir.prefer_recovered(before, after) is True


def test_prefer_recovered_when_more_bullets_land_without_hard_regression():
    before = IntegrityReport(
        status="needs_review",
        checks={"source_lines": {"hard": 3}, "bullets": {"ok": False, "expected": 10, "found": 5}},
        warnings=[{"severity": BLOCKING, "code": "source_lines", "message": "x"}],
    )
    after = IntegrityReport(
        status="needs_review",
        checks={"source_lines": {"hard": 3}, "bullets": {"ok": False, "expected": 10, "found": 9}},
        warnings=[{"severity": BLOCKING, "code": "source_lines", "message": "x"}],
    )
    assert ir.prefer_recovered(before, after) is True



SOURCE = "\n".join(
    [
        "Casey Example",  # 1
        "Experience",  # 2
        "Acme Corp",  # 3
        "Engineer 2020-2022",  # 4
        "• Shipped the onboarding checklist for new analysts in 2021.",  # 5
    ]
)
SECTIONS = {"sections": [{"line": 1, "type": "header"}, {"line": 2, "type": "experience"}]}


def _role(company, company_line=3):
    return {
        "title": {"line": 4, "text": "Engineer"},
        "company": {"line": company_line, "text": company},
        "dates": {"line": 4, "text": "2020-2022"},
        "header_lines": [3, 4],
        "content": [[5, 5]],
    }


def _client(roles_payload, calls=None):
    def call(system_prompt, user_prompt):
        if calls is not None:
            calls.append(system_prompt[:20])
        if "label the sections" in system_prompt:
            return SECTIONS
        return roles_payload

    return call


def _store():
    return {"experience": [], "name": "Casey Example", "raw_text": SOURCE}


def test_recover_store_merges_only_grounded_roles():
    store = _store()
    new_store, meta = ir.recover_store(
        SOURCE, store, _blocking(hard=2), "Casey Example", client=_client({"roles": [_role("Acme Corp")]})
    )

    assert meta["used"] is True
    assert meta["llm_calls"] == 2
    assert meta["missing_in"] == 1
    assert meta["missing_out_estimate"] == 0
    roles = new_store["experience"]
    assert [r["company"] for r in roles] == ["Acme Corp"]
    assert roles[0]["description"] == ["Shipped the onboarding checklist for new analysts in 2021."]
    assert store["experience"] == []  # input not mutated


def test_recover_store_drops_invented_company():
    new_store, meta = ir.recover_store(
        SOURCE, _store(), _blocking(hard=2), "Casey Example", client=_client({"roles": [_role("Globex Invented")]})
    )

    assert all(r.get("company") != "Globex Invented" for r in new_store["experience"])
    assert "Globex Invented" not in str(new_store)
    for role in new_store["experience"]:
        for value in (role.get("title"), role.get("company"), role.get("duration"), *role["description"]):
            assert not value or value in SOURCE


def test_stitch_missing_hard_lines_appends_unassigned():
    """Deterministic recovery: copy missing source lines into unassigned (no LLM rewrite)."""
    store = {
        "experience": [
            {
                "title": "Engineer",
                "company": "Acme Corp",
                "duration": "2020-2022",
                "description": [],
            }
        ]
    }
    # Output has employer but not the bullet — classic source_lines hard miss.
    output = "Casey Example\nAcme Corp\nEngineer 2020-2022"
    new_store, meta = ir.stitch_missing_hard_lines(SOURCE, store, output)

    assert meta["used"] is True
    assert meta["stitched"] >= 1
    assert meta["method"] == "stitch"
    joined = " ".join(new_store.get("unassigned_experience_bullets") or []).lower()
    assert "shipped the onboarding checklist" in joined
    assert store.get("unassigned_experience_bullets") in (None, [])  # input not mutated


def test_repair_wrong_role_moves_misassigned_bullet_to_unassigned():
    # Same layout as output_integrity wrong-employer fail: bullets swapped under headings.
    store = {
        "experience": [
            {
                "company": "Acme Corp",
                "title": "Staff Engineer",
                "description": ["Led migration to event-driven payments."],
            },
            {
                "company": "Globex Inc",
                "title": "Developer",
                "description": ["Built nightly reconciliation jobs for treasury."],
            },
        ]
    }
    # Acme heading, then Globex bullet; Globex heading, then Acme bullet.
    docx_text = (
        "Staff Engineer Acme Corp Jul. 2021 – Present\n"
        "Built nightly reconciliation jobs for treasury.\n"
        "Developer Globex Inc Jan. 2015 – Jun. 2021\n"
        "Led migration to event-driven payments."
    )
    out, meta = ir.repair_wrong_role_assignments(store, docx_text)
    assert meta["used"] is True and meta["moved"] >= 1
    joined_roles = " ".join(
        b for r in out["experience"] for b in (r.get("description") or [])
    ).lower()
    assert "led migration" not in joined_roles or "reconciliation" not in joined_roles
    unassigned = " ".join(out.get("unassigned_experience_bullets") or []).lower()
    assert "led migration" in unassigned or "reconciliation" in unassigned


def test_ensure_missing_lines_in_unassigned_adds_exact_source():
    store = {
        "experience": [
            {
                "title": "Engineer",
                "company": "Acme Corp",
                "description": ["Shipped onboarding"],  # shortened — not full source line
            }
        ],
        "unassigned_experience_bullets": [],
    }
    missing = ["• Shipped the onboarding checklist for new analysts in 2021."]
    out = ir.ensure_missing_lines_in_unassigned(store, missing)
    joined = " ".join(out.get("unassigned_experience_bullets") or []).lower()
    assert "shipped the onboarding checklist for new analysts in 2021" in joined


def test_stitch_copies_exact_source_even_when_role_already_has_line():
    """DOCX-hard-miss lines must land verbatim in unassigned even if a role holds them.

    Store presence does not guarantee DOCX 4-gram coverage (re-punctuation / Environment rows).
    """
    store = {
        "experience": [
            {
                "title": "Engineer",
                "company": "Acme Corp",
                "duration": "2020-2022",
                "description": ["Shipped the onboarding checklist for new analysts in 2021."],
            }
        ]
    }
    output = "Casey Example\nAcme Corp\nEngineer"
    new_store, meta = ir.stitch_missing_hard_lines(SOURCE, store, output)

    assert meta["used"] is True
    assert meta.get("method") == "stitch"
    assert meta["stitched"] >= 1
    joined = " ".join(new_store.get("unassigned_experience_bullets") or []).lower()
    assert "shipped the onboarding checklist for new analysts in 2021" in joined


def test_recover_store_falls_back_to_stitch_when_llm_does_not_help(monkeypatch):
    # Force LLM candidate to leave the bullet out of the store so stitch runs.
    def fake_extract(text, call, elsewhere=None, hints=None):
        return ir.lle.ExtractResult(
            roles=[
                {
                    "title": "Engineer",
                    "company": "Acme Corp",
                    "location": "",
                    "duration": "2020-2022",
                    "description": [],
                    "technologies": [],
                }
            ],
            experience_lines=1,
            claimed_lines=1,
        )

    monkeypatch.setattr(ir.lle, "extract_experience", fake_extract)
    store = {
        "experience": [
            {
                "title": "Engineer",
                "company": "Acme Corp",
                "duration": "2020-2022",
                "description": [],
            }
        ],
        "raw_text": SOURCE,
    }
    new_store, meta = ir.recover_store(
        SOURCE, store, _blocking(hard=1), "Casey Example\nAcme Corp", client=_client({"roles": []})
    )

    assert meta["used"] is True
    assert meta.get("method") == "stitch"
    assert "shipped the onboarding checklist" in " ".join(
        new_store.get("unassigned_experience_bullets") or []
    ).lower()


def test_recover_store_stitches_exact_when_llm_flat_but_lines_already_in_store():
    # Bullet already in the store but missing from DOCX → stitch exact wording into unassigned.
    payload = {"roles": [{**_role("Acme Corp"), "header_lines": [3, 4, 5], "content": []}]}
    existing = {
        "experience": [{"title": "Engineer", "company": "Acme Corp", "duration": "2020-2022",
                        "description": ["Shipped the onboarding checklist for new analysts in 2021."]}],
    }
    store = {**existing, "raw_text": SOURCE}
    new_store, meta = ir.recover_store(SOURCE, store, _blocking(hard=1), "Casey Example", client=_client(payload))

    assert meta["used"] is True
    assert meta.get("method") == "stitch"
    assert "shipped the onboarding checklist" in " ".join(
        new_store.get("unassigned_experience_bullets") or []
    ).lower()


def test_recover_store_returns_original_on_error():
    def broken(system_prompt, user_prompt):
        raise TimeoutError("bedrock down")

    store = _store()
    new_store, meta = ir.recover_store(SOURCE, store, _blocking(hard=2), "Casey Example", client=broken)

    assert new_store is store
    assert meta["used"] is False
    assert meta["error"]


def test_recover_store_respects_call_cap(monkeypatch):
    monkeypatch.setattr(settings, "RESUME_INTEGRITY_RECOVERY_MAX_CALLS", 1)
    calls: list[str] = []
    store = _store()
    new_store, meta = ir.recover_store(
        SOURCE, store, _blocking(hard=2), "Casey Example", client=_client({"roles": [_role("Acme Corp")]}, calls)
    )

    assert len(calls) == 1  # the role call was refused by the cap
    assert meta["llm_calls"] == 1
    assert meta["used"] is False
    assert new_store is store


def test_recover_store_aborts_when_result_is_lumped():
    existing_roles = [
        {"title": "Engineer", "company": "Acme Corp", "duration": "2020-2022", "description": ["a"]},
        {"title": "Analyst", "company": "Globex", "duration": "2018-2020", "description": ["b"]},
        {"title": "Intern", "company": "Initech", "duration": "2017-2018", "description": ["c"]},
    ]
    store = {"experience": existing_roles, "raw_text": SOURCE}
    new_store, meta = ir.recover_store(
        SOURCE, store, _blocking(hard=2), "Casey Example", client=_client({"roles": [_role("Acme Corp")]})
    )

    assert new_store is store
    assert meta["used"] is False
    assert meta["error"] == "lumped"


def test_recover_store_wrong_role_path_accepts_without_text_estimate_drop():
    # The store text already contains every source line, so the hard-line estimate cannot
    # drop; a wrong-role finding must still let the grounded candidate through.
    existing = {
        "experience": [{"title": "Engineer", "company": "Acme Corp", "duration": "2020-2022",
                        "description": ["Shipped the onboarding checklist for new analysts in 2021."]}],
    }
    store = {**existing, "raw_text": SOURCE}
    report = _blocking(code="bullet_wrong_role", hard=0)
    new_store, meta = ir.recover_store(
        SOURCE, store, report, "Casey Example", client=_client({"roles": [_role("Acme Corp")]})
    )

    assert meta["used"] is True
    assert new_store is not store
    assert [r["company"] for r in new_store["experience"]] == ["Acme Corp"]
    assert store["experience"][0]["company"] == "Acme Corp"  # input not mutated


def test_recover_store_aborts_on_errored_extraction(monkeypatch):
    partial = ir.lle.ExtractResult(roles=[{"company": "Acme Corp", "title": "Engineer", "description": ["x"]}],
                                   error="roles:TimeoutError")
    monkeypatch.setattr(ir.lle, "extract_experience", lambda *a, **k: partial)
    store = _store()
    new_store, meta = ir.recover_store(
        SOURCE, store, _blocking(hard=2), "Casey Example", client=_client({"roles": []})
    )

    assert new_store is store
    assert meta["used"] is False
    assert meta["error"] == "roles:TimeoutError"


def test_recover_store_aborts_when_replacement_drops_existing_company():
    store = {
        "experience": [{"title": "Analyst", "company": "Globex", "duration": "2018-2020", "description": ["b"]}],
        "raw_text": SOURCE,
    }
    new_store, meta = ir.recover_store(
        SOURCE, store, _blocking(hard=2), "Casey Example", client=_client({"roles": [_role("Acme Corp")]})
    )

    assert new_store is store
    assert meta["used"] is False
    assert meta["error"] == "dropped_company"
    assert [r["company"] for r in new_store["experience"]] == ["Globex"]


def test_recover_store_timeout_reports_budget_calls_and_no_estimate():
    def broken(system_prompt, user_prompt):
        raise TimeoutError("bedrock down")

    _, meta = ir.recover_store(SOURCE, _store(), _blocking(hard=2), "Casey Example", client=broken)

    assert meta["used"] is False
    assert meta["missing_out_estimate"] is None


# ---------------------------------------------------------------------------
# Wiring into ResumeGenerationService
# ---------------------------------------------------------------------------

import io
from types import SimpleNamespace

from docx import Document

from app.services.resume_generation_service import ResumeGenerationService


def _docx(text: str) -> bytes:
    buf = io.BytesIO()
    doc = Document()
    doc.add_paragraph(text)
    doc.save(buf)
    return buf.getvalue()


def _ok_report(hard=0):
    return IntegrityReport(status="passed", checks={"source_lines": {"ok": hard == 0, "hard": hard}}, warnings=[])


class _Wiring:
    """Service with the heavy collaborators stubbed; records what was called."""

    def __init__(self, monkeypatch, *, first_hard=3, second_hard=0, recovered=True, enabled=True):
        self.svc = ResumeGenerationService()
        self.recover_calls = []
        self.render_calls = 0
        self.reports = [_ok_report(second_hard)]
        self.new_store = {"experience": [{"company": "Acme Corp"}], "raw_text": SOURCE, "parse_meta": {}}
        self.old_store = {"experience": [], "raw_text": SOURCE, "parse_meta": {}}
        self.first_report = _ok_report(first_hard)
        if enabled:
            _enable(monkeypatch)
        else:
            monkeypatch.setattr(settings, "RESUME_INTEGRITY_RECOVERY", False)

        def fake_recover(source_text, store, report, output_text="", *, client=None):
            self.recover_calls.append((source_text, output_text))
            if recovered:
                return self.new_store, {"used": True, "llm_calls": 2, "error": ""}
            return store, {"used": False, "llm_calls": 1, "error": "no_roles"}

        def fake_render(document, *a, **k):
            self.render_calls += 1
            return _docx("recovered output")

        monkeypatch.setattr(ir, "recover_store", fake_recover)
        monkeypatch.setattr(self.svc, "_render_with_format_strategy", fake_render)
        monkeypatch.setattr(
            self.svc, "_generate_professional_document",
            lambda data, meta: {"sections": [{"title": "Experience"}], "marker": "new"},
        )
        monkeypatch.setattr(self.svc, "_integrity_report", lambda *a, **k: self.reports[0])
        monkeypatch.setattr(
            "app.services.resume_generation_service.validate_format_document", lambda *a, **k: []
        )
        self.candidate = SimpleNamespace(
            id="c1", extracted_data={"raw_text": SOURCE, "structured_resume": self.old_store}
        )
        self.client_format = SimpleNamespace(id="f1", format_metadata={})

    def run(self):
        original_docx = _docx("original output")
        self.original_docx = original_docx
        self.original_doc = {"sections": [], "marker": "old", "company_footer_lines": ["Footer"]}
        return self.svc._maybe_integrity_recover(
            self.candidate, self.client_format, self.old_store, {"experience": []},
            self.original_doc, {}, [], [], original_docx, self.first_report,
        )


def test_maybe_integrity_recover_prefers_better_recovered_draft(monkeypatch):
    w = _Wiring(monkeypatch, first_hard=3, second_hard=0)
    docx_bytes, report, store, document = w.run()

    assert len(w.recover_calls) == 1
    assert "original output" in w.recover_calls[0][1]  # DOCX text passed as output_text
    assert w.render_calls >= 1
    assert report is w.reports[0]
    assert docx_bytes != w.original_docx
    assert store["experience"] == [{"company": "Acme Corp"}]
    # Recovery builds via document_from_store + attach (not the quality pipeline).
    assert any(
        isinstance(s, dict) and s.get("type") == "experience"
        for s in (document.get("sections") or [])
    )
    assert document.get("company_footer_lines") == ["Footer"]  # branding carried over
    assert w.candidate.extracted_data["structured_resume"] is store
    meta = store["parse_meta"]["integrity_recovery"]
    assert meta["used"] is True and meta["preferred"] is True


def test_maybe_integrity_recover_keeps_original_when_recovery_not_better(monkeypatch):
    w = _Wiring(monkeypatch, first_hard=3, second_hard=3)
    docx_bytes, report, store, document = w.run()

    assert w.render_calls == 1
    assert report is w.first_report
    assert docx_bytes == w.original_docx
    assert store is w.old_store
    assert document is w.original_doc
    meta = store["parse_meta"]["integrity_recovery"]
    assert meta["used"] is True and meta["preferred"] is False


def test_maybe_integrity_recover_skips_render_when_recovery_unused(monkeypatch):
    """When LLM recovery fails but hard lines remain, render-complete still re-renders."""
    w = _Wiring(monkeypatch, recovered=False, first_hard=3, second_hard=0)
    docx_bytes, report, store, _ = w.run()

    assert w.render_calls == 1
    assert store["parse_meta"]["integrity_recovery"]["used"] is True
    assert store["parse_meta"]["integrity_recovery"].get("render_complete") is True
    assert store["parse_meta"]["integrity_recovery"]["preferred"] is True
    assert report is w.reports[0]
    assert docx_bytes != w.original_docx


def test_maybe_integrity_recover_noop_when_not_needed_or_disabled(monkeypatch):
    w = _Wiring(monkeypatch, first_hard=0)
    w.old_store["experience"] = [{"company": "Acme Corp"}]  # roles present: nothing to recover
    _, report, store, _ = w.run()
    assert w.recover_calls == [] and w.render_calls == 0
    assert report is w.first_report
    assert store["parse_meta"]["integrity_recovery"] == {"used": False}

    w = _Wiring(monkeypatch, first_hard=3, enabled=False)
    w.run()
    assert w.recover_calls == [] and w.render_calls == 0


def test_maybe_integrity_recover_never_raises_when_rerender_fails(monkeypatch):
    w = _Wiring(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("render exploded")

    monkeypatch.setattr(w.svc, "_render_with_format_strategy", boom)
    docx_bytes, report, store, document = w.run()

    assert docx_bytes == w.original_docx
    assert report is w.first_report
    assert document is w.original_doc
    meta = store["parse_meta"]["integrity_recovery"]
    assert meta["preferred"] is False
    assert meta["error"] == "RuntimeError"


def test_maybe_integrity_recover_skips_when_report_missing(monkeypatch):
    w = _Wiring(monkeypatch)
    w.first_report = None
    _, report, _, _ = w.run()
    assert report is None
    assert w.recover_calls == []
