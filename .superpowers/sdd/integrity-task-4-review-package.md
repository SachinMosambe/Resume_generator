diff --git a/backend/app/services/integrity_recovery.py b/backend/app/services/integrity_recovery.py
new file mode 100644
index 0000000..424229e
--- /dev/null
+++ b/backend/app/services/integrity_recovery.py
@@ -0,0 +1,231 @@
+"""Grounded recovery for resumes whose generated output dropped source content.
+
+When the integrity check finds fact-bearing source lines missing from the output (or a
+bullet under the wrong role, or no roles at all despite work history), the missing line
+numbers are fed back to the grounded line extractor. The extractor never writes text: it
+answers with line numbers and code copies the source. This module only decides whether to
+try, runs that extractor under call/time caps, and swaps its roles into the store when
+they demonstrably cover more of the source. Nothing here invents or rewrites text.
+"""
+from __future__ import annotations
+
+import threading
+import time
+from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
+from typing import Any
+
+from app.core.config import settings
+from app.core.logging import logger
+from app.services import llm_line_extractor as lle
+from app.services.output_integrity import BLOCKING, IntegrityReport, list_missing_hard_source_lines
+from app.services.source_evidence import detect_employment_evidence
+
+_WRONG_ROLE_CODES = {"bullet_wrong_role", "role_assignment"}
+_IGNORED_STORE_KEYS = {"raw_text", "parse_meta"}
+
+
+def recovery_enabled() -> bool:
+    return bool(getattr(settings, "RESUME_INTEGRITY_RECOVERY", False)) and bool(
+        getattr(settings, "AWS_BEARER_TOKEN_BEDROCK", "")
+    )
+
+
+def hard_source_miss_count(report: IntegrityReport) -> int:
+    return int(((report.checks or {}).get("source_lines") or {}).get("hard") or 0)
+
+
+def has_wrong_role(report: IntegrityReport) -> bool:
+    return any(
+        w.get("severity") == BLOCKING and w.get("code") in _WRONG_ROLE_CODES
+        for w in (report.warnings or [])
+        if isinstance(w, dict)
+    )
+
+
+def should_recover(report: IntegrityReport, store: dict, source_text: str) -> bool:
+    if not recovery_enabled():
+        return False
+    if hard_source_miss_count(report) > 0 or has_wrong_role(report):
+        return True
+    if not (store.get("experience") or []) and detect_employment_evidence(source_text).has_work_history:
+        return True
+    return False
+
+
+def prefer_recovered(before: IntegrityReport, after: IntegrityReport) -> bool:
+    """Keep the recovered output only if it is strictly better and adds no wrong-role finding."""
+    if has_wrong_role(after) and not has_wrong_role(before):
+        return False
+    before_hard, after_hard = hard_source_miss_count(before), hard_source_miss_count(after)
+    if after_hard < before_hard:
+        return True
+    return has_wrong_role(before) and not has_wrong_role(after) and after_hard <= before_hard
+
+
+# ---------------------------------------------------------------------------
+# Recovery
+# ---------------------------------------------------------------------------
+
+def _store_text(store: dict) -> str:
+    """All text values of the store (except raw source and metadata), one per line."""
+    out: list[str] = []
+
+    def walk(value: Any) -> None:
+        if isinstance(value, str):
+            out.append(value)
+        elif isinstance(value, dict):
+            for v in value.values():
+                walk(v)
+        elif isinstance(value, (list, tuple)):
+            for v in value:
+                walk(v)
+
+    for key, value in store.items():
+        if key not in _IGNORED_STORE_KEYS:
+            walk(value)
+    return "\n".join(out)
+
+
+class _Budget:
+    """Wraps the model client: counts calls and refuses calls past the cap or deadline."""
+
+    def __init__(self, call: lle.LineClient, max_calls: int, timeout: float) -> None:
+        self._call = call
+        self._max_calls = max_calls
+        self._deadline = time.monotonic() + timeout
+        self._lock = threading.Lock()
+        self.calls = 0
+
+    def __call__(self, system_prompt: str, user_prompt: str) -> Any:
+        with self._lock:
+            if self.calls >= self._max_calls:
+                raise RuntimeError("call_cap")
+            if time.monotonic() >= self._deadline:
+                raise TimeoutError("recovery_timeout")
+            self.calls += 1
+        return self._call(system_prompt, user_prompt)
+
+
+def _line_numbers(lines: list[str], missing: list[str]) -> list[int]:
+    wanted = {m.strip() for m in missing}
+    return [n for n, line in enumerate(lines, 1) if line in wanted]
+
+
+def _carry_extras(recovered: list[dict], existing: list[dict]) -> list[dict]:
+    """Keep fields the extractor does not produce (e.g. technologies) for the same role."""
+    by_id = {
+        (lle._key(r.get("company")), lle._key(r.get("title"))): r
+        for r in existing
+        if isinstance(r, dict)
+    }
+    merged = []
+    for role in recovered:
+        old = by_id.get((lle._key(role.get("company")), lle._key(role.get("title"))))
+        if old and old.get("technologies") and not role.get("technologies"):
+            role = {**role, "technologies": list(old["technologies"])}
+        merged.append(role)
+    return merged
+
+
+def recover_store(
+    source_text: str,
+    store: dict,
+    report: IntegrityReport,
+    output_text: str = "",
+    *,
+    client: lle.LineClient | None = None,
+) -> tuple[dict, dict]:
+    """Return ``(new_store, meta)``; ``new_store is store`` unless recovery was used.
+
+    Missing hard source lines (against ``output_text``, or the store's own text when it is
+    empty) become line-number hints for the grounded extractor. Its roles replace the
+    store's experience only when they cover more of the source.
+    """
+    meta: dict[str, Any] = {
+        "used": False,
+        "llm_calls": 0,
+        "error": "",
+        "missing_in": 0,
+        "missing_out_estimate": None,
+    }
+    started = time.perf_counter()
+    budget: _Budget | None = None
+    try:
+        baseline_text = output_text or _store_text(store)
+        missing = list_missing_hard_source_lines(source_text, baseline_text, store)
+        meta["missing_in"] = len(missing)
+        hints = _line_numbers(lle.source_lines(source_text), missing) or None
+
+        max_calls = max(1, int(getattr(settings, "RESUME_INTEGRITY_RECOVERY_MAX_CALLS", 4)))
+        timeout = float(getattr(settings, "RESUME_INTEGRITY_RECOVERY_TIMEOUT_SECONDS", 45.0))
+        budget = _Budget(client or lle._default_client, max_calls, timeout)
+        elsewhere = lle.placed_elsewhere(store, source_text)
+
+        pool = ThreadPoolExecutor(max_workers=1)
+        try:
+            future = pool.submit(lle.extract_experience, source_text, budget, elsewhere=elsewhere, hints=hints)
+            try:
+                result = future.result(timeout=timeout)
+            except FutureTimeout:
+                meta["error"] = "timeout"
+                meta["llm_calls"] = budget.calls
+                return store, meta
+        finally:
+            pool.shutdown(wait=False)
+        meta["llm_calls"] = budget.calls
+        meta["llm_roles"] = len(result.roles)
+
+        # Partial or failed extractions are never accepted.
+        if result.error:
+            meta["error"] = result.error
+            return store, meta
+        if not result.roles:
+            meta["error"] = "no_roles"
+            return store, meta
+
+        existing = [r for r in store.get("experience") or [] if isinstance(r, dict)]
+        if lle._is_lumped(existing, result, 1.0):
+            meta["error"] = "lumped"
+            return store, meta
+
+        # Never drop a role the store already had: every prior company must survive.
+        recovered_companies = {lle._key(r.get("company")) for r in result.roles if isinstance(r, dict)}
+        prior_companies = {lle._key(r.get("company")) for r in existing} - {""}
+        if prior_companies - recovered_companies:
+            meta["error"] = "dropped_company"
+            return store, meta
+
+        candidate = dict(store)
+        candidate["experience"] = _carry_extras(result.roles, existing)
+        if result.unassigned:
+            candidate["unassigned_experience_bullets"] = result.unassigned
+        else:
+            candidate.pop("unassigned_experience_bullets", None)
+
+        before = len(list_missing_hard_source_lines(source_text, _store_text(store), store))
+        after = len(list_missing_hard_source_lines(source_text, _store_text(candidate), candidate))
+        meta["missing_out_estimate"] = after
+        # Wrong-role / zero-role cases are not measurable by store-text line coverage;
+        # accept the grounded candidate and let the caller's post-render
+        # ``prefer_recovered`` decide. The source-lines-only path needs a real drop.
+        text_unmeasurable = has_wrong_role(report) or (
+            not existing and detect_employment_evidence(source_text).has_work_history
+        )
+        if not text_unmeasurable and after >= before:
+            meta["error"] = "no_improvement"
+            return store, meta
+
+        meta["used"] = True
+        return candidate, meta
+    except Exception as exc:  # noqa: BLE001 - recovery must never break generation
+        meta["error"] = type(exc).__name__
+        if budget is not None:
+            meta["llm_calls"] = budget.calls
+        return store, meta
+    finally:
+        meta["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
+        logger.info(
+            "integrity_recovery_done",
+            **{k: v for k, v in meta.items() if k != "error"},
+            error_type=meta["error"] or None,
+        )
diff --git a/backend/tests/test_integrity_recovery.py b/backend/tests/test_integrity_recovery.py
index 192d5cc..634f090 100644
--- a/backend/tests/test_integrity_recovery.py
+++ b/backend/tests/test_integrity_recovery.py
@@ -1,7 +1,259 @@
-from app.core.config import Settings
+from app.core.config import Settings, settings
+from app.services import integrity_recovery as ir
+from app.services.output_integrity import BLOCKING, IntegrityReport
 
 
 def test_integrity_recovery_settings_defaults():
     assert Settings.model_fields["RESUME_INTEGRITY_RECOVERY"].default is True
     assert Settings.model_fields["RESUME_INTEGRITY_RECOVERY_MAX_CALLS"].default == 4
     assert Settings.model_fields["RESUME_INTEGRITY_RECOVERY_TIMEOUT_SECONDS"].default == 45.0
+
+
+def _enable(monkeypatch):
+    monkeypatch.setattr(settings, "RESUME_INTEGRITY_RECOVERY", True)
+    monkeypatch.setattr(settings, "AWS_BEARER_TOKEN_BEDROCK", "token")
+
+
+def _blocking(code="source_lines", hard=3):
+    return IntegrityReport(
+        status="needs_review",
+        checks={"source_lines": {"ok": False, "hard": hard, "soft": 1, "changed_numbers": 0}},
+        warnings=[{"severity": BLOCKING, "code": code, "message": "x"}],
+    )
+
+
+def test_should_recover_on_blocking_source_lines(monkeypatch):
+    _enable(monkeypatch)
+    assert ir.should_recover(
+        _blocking(), {"experience": [{"company": "Acme"}]}, "Acme\n• Built things carefully here.\n"
+    ) is True
+
+
+def test_should_not_recover_on_clean_pass(monkeypatch):
+    _enable(monkeypatch)
+    report = IntegrityReport(status="passed", checks={"source_lines": {"ok": True, "hard": 0}}, warnings=[])
+    assert ir.should_recover(report, {"experience": [{"company": "Acme"}]}, "x") is False
+
+
+def test_should_recover_zero_roles_with_work_evidence(monkeypatch):
+    _enable(monkeypatch)
+    report = IntegrityReport(status="needs_review", checks={}, warnings=[])
+    source = "Experience\nAcme Corp Engineer 2020-2021\n• Shipped the billing platform for customers.\n"
+    assert ir.should_recover(report, {"experience": []}, source) is True
+
+
+def test_should_not_recover_when_disabled(monkeypatch):
+    _enable(monkeypatch)
+    monkeypatch.setattr(settings, "RESUME_INTEGRITY_RECOVERY", False)
+    assert ir.should_recover(_blocking(), {"experience": [{"company": "Acme"}]}, "x") is False
+    monkeypatch.setattr(settings, "RESUME_INTEGRITY_RECOVERY", True)
+    monkeypatch.setattr(settings, "AWS_BEARER_TOKEN_BEDROCK", "")
+    assert ir.recovery_enabled() is False
+    assert ir.should_recover(_blocking(), {"experience": [{"company": "Acme"}]}, "x") is False
+
+
+def test_should_recover_on_wrong_role_even_without_hard_misses(monkeypatch):
+    _enable(monkeypatch)
+    report = _blocking(code="bullet_wrong_role", hard=0)
+    assert ir.has_wrong_role(report) is True
+    assert ir.hard_source_miss_count(report) == 0
+    assert ir.should_recover(report, {"experience": [{"company": "Acme"}]}, "x") is True
+
+
+def test_prefer_recovered_only_when_hard_drops_without_new_wrong_role():
+    before = _blocking(hard=5)
+    after_better = _blocking(hard=1)
+    after_worse_role = IntegrityReport(
+        status="failed",
+        checks={"source_lines": {"hard": 0}},
+        warnings=[{"severity": BLOCKING, "code": "bullet_wrong_role", "message": "x"}],
+    )
+    assert ir.prefer_recovered(before, after_better) is True
+    assert ir.prefer_recovered(before, after_worse_role) is False
+    assert ir.prefer_recovered(before, _blocking(hard=5)) is False
+    assert ir.prefer_recovered(before, _blocking(hard=7)) is False
+
+
+def test_prefer_recovered_when_wrong_role_is_cleared_without_more_misses():
+    before = _blocking(code="bullet_wrong_role", hard=2)
+    after = IntegrityReport(status="needs_review", checks={"source_lines": {"hard": 2}}, warnings=[])
+    assert ir.prefer_recovered(before, after) is True
+
+
+SOURCE = "\n".join(
+    [
+        "Casey Example",  # 1
+        "Experience",  # 2
+        "Acme Corp",  # 3
+        "Engineer 2020-2022",  # 4
+        "• Shipped the onboarding checklist for new analysts in 2021.",  # 5
+    ]
+)
+SECTIONS = {"sections": [{"line": 1, "type": "header"}, {"line": 2, "type": "experience"}]}
+
+
+def _role(company, company_line=3):
+    return {
+        "title": {"line": 4, "text": "Engineer"},
+        "company": {"line": company_line, "text": company},
+        "dates": {"line": 4, "text": "2020-2022"},
+        "header_lines": [3, 4],
+        "content": [[5, 5]],
+    }
+
+
+def _client(roles_payload, calls=None):
+    def call(system_prompt, user_prompt):
+        if calls is not None:
+            calls.append(system_prompt[:20])
+        if "label the sections" in system_prompt:
+            return SECTIONS
+        return roles_payload
+
+    return call
+
+
+def _store():
+    return {"experience": [], "name": "Casey Example", "raw_text": SOURCE}
+
+
+def test_recover_store_merges_only_grounded_roles():
+    store = _store()
+    new_store, meta = ir.recover_store(
+        SOURCE, store, _blocking(hard=2), "Casey Example", client=_client({"roles": [_role("Acme Corp")]})
+    )
+
+    assert meta["used"] is True
+    assert meta["llm_calls"] == 2
+    assert meta["missing_in"] == 1
+    assert meta["missing_out_estimate"] == 0
+    roles = new_store["experience"]
+    assert [r["company"] for r in roles] == ["Acme Corp"]
+    assert roles[0]["description"] == ["Shipped the onboarding checklist for new analysts in 2021."]
+    assert store["experience"] == []  # input not mutated
+
+
+def test_recover_store_drops_invented_company():
+    new_store, meta = ir.recover_store(
+        SOURCE, _store(), _blocking(hard=2), "Casey Example", client=_client({"roles": [_role("Globex Invented")]})
+    )
+
+    assert all(r.get("company") != "Globex Invented" for r in new_store["experience"])
+    assert "Globex Invented" not in str(new_store)
+    for role in new_store["experience"]:
+        for value in (role.get("title"), role.get("company"), role.get("duration"), *role["description"]):
+            assert not value or value in SOURCE
+
+
+def test_recover_store_keeps_store_when_not_improved():
+    # The model returns a role that does not cover the missing bullet: no gain, no swap.
+    payload = {"roles": [{**_role("Acme Corp"), "header_lines": [3, 4, 5], "content": []}]}
+    existing = {
+        "experience": [{"title": "Engineer", "company": "Acme Corp", "duration": "2020-2022",
+                        "description": ["Shipped the onboarding checklist for new analysts in 2021."]}],
+    }
+    store = {**existing, "raw_text": SOURCE}
+    new_store, meta = ir.recover_store(SOURCE, store, _blocking(hard=1), "Casey Example", client=_client(payload))
+
+    assert new_store is store
+    assert meta["used"] is False
+
+
+def test_recover_store_returns_original_on_error():
+    def broken(system_prompt, user_prompt):
+        raise TimeoutError("bedrock down")
+
+    store = _store()
+    new_store, meta = ir.recover_store(SOURCE, store, _blocking(hard=2), "Casey Example", client=broken)
+
+    assert new_store is store
+    assert meta["used"] is False
+    assert meta["error"]
+
+
+def test_recover_store_respects_call_cap(monkeypatch):
+    monkeypatch.setattr(settings, "RESUME_INTEGRITY_RECOVERY_MAX_CALLS", 1)
+    calls: list[str] = []
+    store = _store()
+    new_store, meta = ir.recover_store(
+        SOURCE, store, _blocking(hard=2), "Casey Example", client=_client({"roles": [_role("Acme Corp")]}, calls)
+    )
+
+    assert len(calls) == 1  # the role call was refused by the cap
+    assert meta["llm_calls"] == 1
+    assert meta["used"] is False
+    assert new_store is store
+
+
+def test_recover_store_aborts_when_result_is_lumped():
+    existing_roles = [
+        {"title": "Engineer", "company": "Acme Corp", "duration": "2020-2022", "description": ["a"]},
+        {"title": "Analyst", "company": "Globex", "duration": "2018-2020", "description": ["b"]},
+        {"title": "Intern", "company": "Initech", "duration": "2017-2018", "description": ["c"]},
+    ]
+    store = {"experience": existing_roles, "raw_text": SOURCE}
+    new_store, meta = ir.recover_store(
+        SOURCE, store, _blocking(hard=2), "Casey Example", client=_client({"roles": [_role("Acme Corp")]})
+    )
+
+    assert new_store is store
+    assert meta["used"] is False
+    assert meta["error"] == "lumped"
+
+
+def test_recover_store_wrong_role_path_accepts_without_text_estimate_drop():
+    # The store text already contains every source line, so the hard-line estimate cannot
+    # drop; a wrong-role finding must still let the grounded candidate through.
+    existing = {
+        "experience": [{"title": "Engineer", "company": "Acme Corp", "duration": "2020-2022",
+                        "description": ["Shipped the onboarding checklist for new analysts in 2021."]}],
+    }
+    store = {**existing, "raw_text": SOURCE}
+    report = _blocking(code="bullet_wrong_role", hard=0)
+    new_store, meta = ir.recover_store(
+        SOURCE, store, report, "Casey Example", client=_client({"roles": [_role("Acme Corp")]})
+    )
+
+    assert meta["used"] is True
+    assert new_store is not store
+    assert [r["company"] for r in new_store["experience"]] == ["Acme Corp"]
+    assert store["experience"][0]["company"] == "Acme Corp"  # input not mutated
+
+
+def test_recover_store_aborts_on_errored_extraction(monkeypatch):
+    partial = ir.lle.ExtractResult(roles=[{"company": "Acme Corp", "title": "Engineer", "description": ["x"]}],
+                                   error="roles:TimeoutError")
+    monkeypatch.setattr(ir.lle, "extract_experience", lambda *a, **k: partial)
+    store = _store()
+    new_store, meta = ir.recover_store(
+        SOURCE, store, _blocking(hard=2), "Casey Example", client=_client({"roles": []})
+    )
+
+    assert new_store is store
+    assert meta["used"] is False
+    assert meta["error"] == "roles:TimeoutError"
+
+
+def test_recover_store_aborts_when_replacement_drops_existing_company():
+    store = {
+        "experience": [{"title": "Analyst", "company": "Globex", "duration": "2018-2020", "description": ["b"]}],
+        "raw_text": SOURCE,
+    }
+    new_store, meta = ir.recover_store(
+        SOURCE, store, _blocking(hard=2), "Casey Example", client=_client({"roles": [_role("Acme Corp")]})
+    )
+
+    assert new_store is store
+    assert meta["used"] is False
+    assert meta["error"] == "dropped_company"
+    assert [r["company"] for r in new_store["experience"]] == ["Globex"]
+
+
+def test_recover_store_timeout_reports_budget_calls_and_no_estimate():
+    def broken(system_prompt, user_prompt):
+        raise TimeoutError("bedrock down")
+
+    _, meta = ir.recover_store(SOURCE, _store(), _blocking(hard=2), "Casey Example", client=broken)
+
+    assert meta["used"] is False
+    assert meta["missing_out_estimate"] is None
