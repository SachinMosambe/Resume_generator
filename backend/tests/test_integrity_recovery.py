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


def test_recover_store_keeps_store_when_not_improved():
    # The model returns a role that does not cover the missing bullet: no gain, no swap.
    payload = {"roles": [{**_role("Acme Corp"), "header_lines": [3, 4, 5], "content": []}]}
    existing = {
        "experience": [{"title": "Engineer", "company": "Acme Corp", "duration": "2020-2022",
                        "description": ["Shipped the onboarding checklist for new analysts in 2021."]}],
    }
    store = {**existing, "raw_text": SOURCE}
    new_store, meta = ir.recover_store(SOURCE, store, _blocking(hard=1), "Casey Example", client=_client(payload))

    assert new_store is store
    assert meta["used"] is False


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
