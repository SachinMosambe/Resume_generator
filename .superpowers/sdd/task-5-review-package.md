# Review package Task 5 (after validation fixes)
BASE: 324ed95429acd6bcdfd90f101a3d0c4dce36d7cb
HEAD: 1fcaf3a200950b6edeb3d8d31be4d1d5589898c6
## Commits
1fcaf3a fix: tighten LLM repair source checks for dates, survival, and role blocks 1356893 feat: add optional source-checked LLM parse repair fallback
## Diff stat
 backend/app/core/config.py                        |   4 +  backend/app/services/llm_structure_repair.py      | 437 ++++++++++++++++++++++  backend/app/services/resume_generation_service.py |  11 +  backend/tests/test_llm_structure_repair.py        | 353 +++++++++++++++++  4 files changed, 805 insertions(+)
diff --git a/backend/app/core/config.py b/backend/app/core/config.py
index 5f4c1d7..7c9d910 100644
--- a/backend/app/core/config.py
+++ b/backend/app/core/config.py
@@ -30,8 +30,12 @@ class Settings(BaseSettings):
     # Optional deploy stamp so /api/health can prove which build is live.
     APP_BUILD_ID: str = "dev"
     # When false (default), skip slow full-document LLM polish loops.
     RESUME_LLM_POLISH: bool = False
+    # Optional one-shot, source-checked LLM structure repair when the deterministic parse is
+    # weak. Default OFF (golden/scored CI stays deterministic). Rejected output is discarded.
+    RESUME_LLM_PARSE_FALLBACK: bool = False
+    RESUME_LLM_PARSE_TIMEOUT_SECONDS: float = 45.0
 
     # Multi-agent pipeline (extract -> plan -> write -> critique -> refine).
     # Runs inside the same service; enable per-deploy to compare against classic.
     RESUME_AGENT_PIPELINE: bool = False
diff --git a/backend/app/services/llm_structure_repair.py b/backend/app/services/llm_structure_repair.py
new file mode 100644
index 0000000..5ac3352
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
+        base["location"] = r.location.strip() or str(base.get("location") or "").strip()
+        base["duration"] = r.duration.strip() or str(base.get("duration") or "").strip()
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
diff --git a/backend/tests/test_llm_structure_repair.py b/backend/tests/test_llm_structure_repair.py
new file mode 100644
index 0000000..dd27803
--- /dev/null
+++ b/backend/tests/test_llm_structure_repair.py
@@ -0,0 +1,353 @@
+"""Optional LLM structure repair: all LLM calls are stubbed."""
+from __future__ import annotations
+
+import copy
+
+from app.core.config import Settings
+from app.services import llm_structure_repair as lsr
+from app.services.llm_structure_repair import is_repair_eligible, maybe_repair_parse
+from app.services.parse_confidence import score_parse
+
+SOURCE = """Jane Doe
+EXPERIENCE
+Senior Engineer
+Acme Inc 2020 - Present
+• Built the billing pipeline for enterprise clients.
+• Reduced deploy time by 40 percent.
+Developer
+Beta LLC 2017 - 2019
+• Maintained the legacy reporting service.
+EDUCATION
+B.S. Computer Science
+"""
+
+
+def _weak_parse(**over):
+    data = {"name": "Jane Doe", "experience": [], "education": [{"degree": "B.S. Computer Science"}]}
+    data.update(over)
+    data["parse_meta"] = score_parse(data, SOURCE)
+    return data
+
+
+def _good_repair():
+    return {
+        "experience": [
+            {
+                "title": "Senior Engineer",
+                "company": "Acme Inc",
+                "location": "",
+                "duration": "2020 - Present",
+                "description": [
+                    "Built the billing pipeline for enterprise clients.",
+                    "Reduced deploy time by 40 percent.",
+                ],
+            },
+            {
+                "title": "Developer",
+                "company": "Beta LLC",
+                "location": "",
+                "duration": "2017 - 2019",
+                "description": ["Maintained the legacy reporting service."],
+            },
+        ]
+    }
+
+
+def _stub(payload, calls=None):
+    def client(system_prompt, user_prompt):
+        if calls is not None:
+            calls.append(1)
+        return payload
+
+    return client
+
+
+def test_accepts_schema_valid_source_backed_repair():
+    parsed = _weak_parse()
+    assert is_repair_eligible(SOURCE, parsed)
+    calls: list[int] = []
+    out = maybe_repair_parse(SOURCE, parsed, client=_stub(_good_repair(), calls))
+    assert calls == [1]
+    assert out["parse_meta"]["llm_repaired"] is True
+    assert [r["company"] for r in out["experience"]] == ["Acme Inc", "Beta LLC"]
+    assert out["experience"][1]["description"] == ["Maintained the legacy reporting service."]
+    assert out["parse_meta"]["confidence"] > parsed["parse_meta"]["confidence"]
+    assert out["name"] == "Jane Doe" and out["education"] == parsed["education"]
+    assert parsed["experience"] == [] and parsed["parse_meta"]["llm_repaired"] is False
+
+
+def test_accepts_json_string_response_and_clears_placed_unassigned_bullets():
+    parsed = _weak_parse(unassigned_experience_bullets=["Reduced deploy time by 40 percent."])
+    import json
+
+    out = maybe_repair_parse(SOURCE, parsed, client=_stub(json.dumps(_good_repair())))
+    assert out["parse_meta"]["llm_repaired"] is True
+    assert "unassigned_experience_bullets" not in out
+
+
+def test_rejects_fabricated_employer():
+    bad = _good_repair()
+    bad["experience"][0]["company"] = "Globex Corporation"
+    parsed = _weak_parse()
+    before = copy.deepcopy(parsed)
+    out = maybe_repair_parse(SOURCE, parsed, client=_stub(bad))
+    assert out == before
+    assert out["parse_meta"]["llm_repaired"] is False
+
+
+def test_rejects_fabricated_bullet_title_and_date():
+    for mutate in (
+        lambda r: r["experience"][0]["description"].append("Led a team of 50 engineers."),
+        lambda r: r["experience"][0].update(title="Chief Technology Officer"),
+        lambda r: r["experience"][0].update(duration="2010 - 2012"),
+    ):
+        bad = _good_repair()
+        mutate(bad)
+        parsed = _weak_parse()
+        out = maybe_repair_parse(SOURCE, parsed, client=_stub(bad))
+        assert out["experience"] == [] and out["parse_meta"]["llm_repaired"] is False
+
+
+def test_rejects_bullet_wrong_employer():
+    bad = _good_repair()
+    # Real bullet from the source, but it belongs under Beta LLC, not Acme Inc.
+    bad["experience"][0]["description"].append("Maintained the legacy reporting service.")
+    bad["experience"][1]["description"] = []
+    parsed = _weak_parse()
+    out = maybe_repair_parse(SOURCE, parsed, client=_stub(bad))
+    assert out["experience"] == []
+    assert out["parse_meta"]["llm_repaired"] is False
+
+
+def test_rejects_when_existing_verified_facts_dropped():
+    parsed = _weak_parse(
+        experience=[
+            {
+                "title": "",
+                "company": "Acme Inc",
+                "description": ["Built the billing pipeline for enterprise clients."],
+            },
+            {"title": "", "company": "Beta LLC", "description": []},
+        ]
+    )
+    assert is_repair_eligible(SOURCE, parsed)
+    bad = _good_repair()
+    bad["experience"][0]["description"] = ["Reduced deploy time by 40 percent."]
+    out = maybe_repair_parse(SOURCE, parsed, client=_stub(bad))
+    assert out["parse_meta"]["llm_repaired"] is False
+    assert out["experience"][0]["description"] == ["Built the billing pipeline for enterprise clients."]
+    # Keeping everything verified, and resolving the titles, is accepted.
+    ok = maybe_repair_parse(SOURCE, parsed, client=_stub(_good_repair()))
+    assert ok["parse_meta"]["llm_repaired"] is True
+    assert [r["title"] for r in ok["experience"]] == ["Senior Engineer", "Developer"]
+
+
+def test_rejects_schema_invalid_output():
+    for payload in ({"experience": "nope"}, {"experience": [{"company": 5}]}, "not json", None, {}):
+        parsed = _weak_parse()
+        out = maybe_repair_parse(SOURCE, parsed, client=_stub(payload))
+        assert out is parsed
+
+
+def test_unavailable_client_keeps_deterministic():
+    def boom(system_prompt, user_prompt):
+        raise TimeoutError("bedrock down")
+
+    parsed = _weak_parse()
+    before = copy.deepcopy(parsed)
+    out = maybe_repair_parse(SOURCE, parsed, client=boom)
+    assert out is parsed and out == before
+    assert out["parse_meta"]["llm_repaired"] is False
+
+
+def test_default_client_failure_keeps_deterministic(monkeypatch):
+    import app.agents.tools.llm_client as llm_client
+
+    def fail(*args, **kwargs):
+        raise RuntimeError("no credentials")
+
+    monkeypatch.setattr(llm_client, "llm_call_json_with_metrics", fail)
+    parsed = _weak_parse()
+    assert maybe_repair_parse(SOURCE, parsed) is parsed
+
+
+def test_education_only_not_eligible():
+    src = "Jane Doe\nEDUCATION\nB.S. Computer Science, State University 2016\n"
+    parsed = {"name": "Jane Doe", "experience": [], "education": [{"degree": "B.S."}]}
+    parsed["parse_meta"] = score_parse(parsed, src)
+    assert not is_repair_eligible(src, parsed)
+    calls: list[int] = []
+    out = maybe_repair_parse(src, parsed, client=_stub(_good_repair(), calls))
+    assert out is parsed and calls == []
+
+
+def test_healthy_parse_not_eligible():
+    parsed = _weak_parse(experience=_good_repair()["experience"])
+    parsed["parse_meta"] = score_parse(parsed, SOURCE)
+    assert parsed["parse_meta"]["confidence"] == 1.0
+    assert not is_repair_eligible(SOURCE, parsed)
+
+
+def test_unresolved_titles_eligible():
+    roles = [
+        {"title": "", "company": "Acme Inc", "description": []},
+        {"title": "", "company": "Beta LLC", "description": []},
+    ]
+    parsed = _weak_parse(experience=roles)
+    assert "source_backed_titles_unresolved" in parsed["parse_meta"]["reasons"]
+    assert is_repair_eligible(SOURCE, parsed)
+
+
+def test_already_repaired_not_repeated():
+    parsed = _weak_parse()
+    once = maybe_repair_parse(SOURCE, parsed, client=_stub(_good_repair()))
+    calls: list[int] = []
+    again = maybe_repair_parse(SOURCE, once, client=_stub(_good_repair(), calls))
+    assert again is once and calls == []
+
+
+def test_flag_defaults_off():
+    assert Settings.model_fields["RESUME_LLM_PARSE_FALLBACK"].default is False
+    assert lsr.settings.RESUME_LLM_PARSE_FALLBACK is False
+
+
+def test_generation_service_skips_repair_when_flag_off(monkeypatch):
+    from types import SimpleNamespace
+
+    from app.services import resume_generation_service as svc
+
+    called = []
+    monkeypatch.setattr(lsr, "maybe_repair_parse", lambda *a, **k: called.append(1))
+    monkeypatch.setattr(svc.settings, "RESUME_LLM_PARSE_FALLBACK", False)
+    candidate = SimpleNamespace(
+        id="c1", extracted_data={"raw_text": SOURCE}, resume_path=None, name="Jane Doe"
+    )
+    try:
+        svc.ResumeGenerationService()._get_detailed_resume_data(candidate)
+    except Exception:
+        pass  # downstream merge needs a full Candidate; only the repair call matters here
+    assert called == []
+
+
+def test_generation_service_calls_repair_once_when_flag_on(monkeypatch):
+    from types import SimpleNamespace
+
+    from app.services import resume_generation_service as svc
+
+    calls = []
+
+    def fake(source, parsed, **kwargs):
+        calls.append(source)
+        return parsed
+
+    monkeypatch.setattr(lsr, "maybe_repair_parse", fake)
+    monkeypatch.setattr(svc.settings, "RESUME_LLM_PARSE_FALLBACK", True)
+    candidate = SimpleNamespace(
+        id="c1", extracted_data={"raw_text": SOURCE}, resume_path=None, name="Jane Doe"
+    )
+    try:
+        svc.ResumeGenerationService()._get_detailed_resume_data(candidate)
+    except Exception:
+        pass
+    assert len(calls) == 1
+
+
+def test_rejects_invented_range_from_other_roles_years():
+    # "2017" belongs to Beta LLC and "Present" to Acme Inc; "2017 - Present" never appears together.
+    bad = _good_repair()
+    bad["experience"][1]["duration"] = "2017 - Present"
+    parsed = _weak_parse()
+    out = maybe_repair_parse(SOURCE, parsed, client=_stub(bad))
+    assert out["experience"] == [] and out["parse_meta"]["llm_repaired"] is False
+
+
+def test_accepts_contiguous_duration_with_different_punctuation():
+    good = _good_repair()
+    good["experience"][0]["duration"] = "2020 – Present"
+    out = maybe_repair_parse(SOURCE, _weak_parse(), client=_stub(good))
+    assert out["parse_meta"]["llm_repaired"] is True
+
+
+def test_survival_keeps_verified_duration_location_technologies():
+    parsed = _weak_parse(
+        experience=[
+            {
+                "title": "",
+                "company": "Acme Inc",
+                "location": "Remote",
+                "duration": "2020 - Present",
+                "technologies": ["Python", "AWS"],
+                "description": ["Built the billing pipeline for enterprise clients."],
+            },
+            {"title": "", "company": "Beta LLC", "duration": "2017 - 2019", "description": []},
+        ]
+    )
+    assert is_repair_eligible(SOURCE, parsed)
+    repair = _good_repair()  # omits location / technologies; "Remote" is not even in the source
+    repair["experience"][0]["duration"] = ""
+    repair["experience"][1]["duration"] = ""
+    out = maybe_repair_parse(SOURCE, parsed, client=_stub(repair))
+    assert out["parse_meta"]["llm_repaired"] is True
+    acme, beta = out["experience"]
+    assert acme["title"] == "Senior Engineer"
+    assert acme["duration"] == "2020 - Present"
+    assert acme["location"] == "Remote"
+    assert acme["technologies"] == ["Python", "AWS"]
+    assert beta["duration"] == "2017 - 2019"
+    assert beta["technologies"] == []
+
+
+MENTION_SOURCE = """Jane Doe
+EXPERIENCE
+Senior Engineer
+Acme Inc 2020 - Present
+• Migrated services away from Beta LLC infrastructure.
+• Reduced deploy time by 40 percent.
+Developer
+Beta LLC 2017 - 2019
+• Maintained the legacy reporting service.
+EDUCATION
+B.S. Computer Science
+"""
+
+
+def _mention_repair():
+    return {
+        "experience": [
+            {
+                "title": "Senior Engineer",
+                "company": "Acme Inc",
+                "duration": "2020 - Present",
+                "description": [
+                    "Migrated services away from Beta LLC infrastructure.",
+                    "Reduced deploy time by 40 percent.",
+                ],
+            },
+            {
+                "title": "Developer",
+                "company": "Beta LLC",
+                "duration": "2017 - 2019",
+                "description": ["Maintained the legacy reporting service."],
+            },
+        ]
+    }
+
+
+def test_company_mentioned_in_other_roles_bullet_does_not_split_block():
+    parsed = {"name": "Jane Doe", "experience": [], "education": [{"degree": "B.S."}]}
+    parsed["parse_meta"] = score_parse(parsed, MENTION_SOURCE)
+    out = maybe_repair_parse(MENTION_SOURCE, parsed, client=_stub(_mention_repair()))
+    assert out["parse_meta"]["llm_repaired"] is True
+    assert out["experience"][0]["description"][1] == "Reduced deploy time by 40 percent."
+
+
+def test_rejects_bullet_under_employer_only_mentioned_in_another_bullet():
+    bad = _mention_repair()
+    # Acme's second bullet sits after the "Beta LLC" mention inside Acme's own bullet;
+    # it must not be treated as Beta LLC's block.
+    moved = bad["experience"][0]["description"].pop()
+    bad["experience"][1]["description"].append(moved)
+    parsed = {"name": "Jane Doe", "experience": [], "education": [{"degree": "B.S."}]}
+    parsed["parse_meta"] = score_parse(parsed, MENTION_SOURCE)
+    out = maybe_repair_parse(MENTION_SOURCE, parsed, client=_stub(bad))
+    assert out["experience"] == [] and out["parse_meta"]["llm_repaired"] is False
