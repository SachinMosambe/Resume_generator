diff --git a/.superpowers/sdd/integrity-task-3-report.md b/.superpowers/sdd/integrity-task-3-report.md
new file mode 100644
index 0000000..9cdd55f
--- /dev/null
+++ b/.superpowers/sdd/integrity-task-3-report.md
@@ -0,0 +1,21 @@
+# Integrity Task 3 Report
+
+## Status
+
+Implemented and verified the first-pass line-extraction recovery behavior: when the rule parser finds zero roles, a non-empty, non-lumped LLM result is accepted even when the normal coverage gate is weak.
+
+## Changes
+
+- Kept lumped-result rejection intact.
+- Added the empty-rule-role override to the `better` decision without changing comparisons for non-empty rule parses.
+- Added a regression test with 0.5 rule/LLM coverage, a non-lumped incomplete grounded role, and a failed normal gate.
+
+## TDD Evidence
+
+- Red: the new regression test failed with `used` equal to `False` when the empty-rule override was absent; 17 passed, 1 failed.
+- Green: `tests/test_llm_line_extractor.py -v` completed with 18 passed.
+- IDE diagnostics reported no linter errors in the two scoped Python files.
+
+## Concerns
+
+The requested command path and test path assume different working directories. Verification used the specified virtual environment from the `backend` directory as `.venv\Scripts\python.exe -m pytest tests/test_llm_line_extractor.py -v`.
diff --git a/backend/app/services/llm_line_extractor.py b/backend/app/services/llm_line_extractor.py
new file mode 100644
index 0000000..b87dd8f
--- /dev/null
+++ b/backend/app/services/llm_line_extractor.py
@@ -0,0 +1,605 @@
+"""Grounded LLM extraction of work history using line numbers.
+
+The model never writes resume text. It sees numbered source lines and answers with
+line numbers (plus, for title / company / dates, the exact words it read on a cited
+line). Code then copies text from the source and checks every answer:
+
+* a cited line must exist and belong to the chunk the model was shown;
+* a title / company / date / location must appear verbatim on the line it cites,
+  otherwise that field is dropped;
+* a line can belong to one role only.
+
+Every experience line that no role claims is returned as an unassigned bullet so it
+reaches the output and is flagged for review. No resume text is logged.
+
+Call 1 maps sections (where each one starts). Call 2 runs per experience chunk.
+"""
+from __future__ import annotations
+
+import json
+import re
+import time
+from bisect import bisect_right
+from concurrent.futures import ThreadPoolExecutor
+from dataclasses import dataclass, field
+from typing import Any, Callable
+
+from app.core.config import settings
+from app.core.logging import logger
+from app.services.source_evidence import detect_employment_evidence
+
+# client(system_prompt, user_prompt) -> dict (parsed JSON) or JSON string
+LineClient = Callable[[str, str], Any]
+
+SECTION_TYPES = {
+    "header", "summary", "skills", "experience", "education", "projects", "certifications",
+    "achievements", "languages", "other", "noise",
+}
+CHUNK_LINES = 120
+MAX_LINES = 1500
+_BULLET_RE = re.compile(r"^\s*[•●▪◦‣·■➢✓\-\*–—>]+\s*")
+_DATE_TOKEN_RE = re.compile(r"(?i)\b(?:19|20)\d{2}\b|\b(?:present|current|till date|to date|now)\b|\b\d{1,2}/\d{2,4}\b|['’]\d{2}\b")
+_MON = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
+_POINT = rf"(?:{_MON}\s*[,.]?\s*['’‘]?\s*(?:\d{{4}}|\d{{2}})(?!\d)|\d{{1,2}}/\d{{2,4}}|(?:19|20)\d{{2}})"
+_END = rf"(?:{_POINT}|present|current|till\s*date|till\s*now|to\s*date|now|ongoing)"
+_RANGE_RE = re.compile(rf"(?i){_POINT}\s*(?:-|–|—|to|until)\s*{_END}")
+_OPEN_TAIL_RE = re.compile(rf"(?i)\s*\(?\s*{_POINT}\s*(?:-|–|—|to)?\s*\)?\s*$")
+_LABEL_RE = re.compile(r"^\s*[A-Za-z][A-Za-z &/\-]{1,40}:\s*$")
+_END_START_RE = re.compile(rf"(?i)^\s*({_END})\b")
+
+
+@dataclass
+class ExtractResult:
+    roles: list[dict[str, Any]] = field(default_factory=list)
+    unassigned: list[str] = field(default_factory=list)
+    sections: list[dict[str, Any]] = field(default_factory=list)
+    experience_lines: int = 0
+    claimed_lines: int = 0
+    llm_calls: int = 0
+    rejected_fields: int = 0
+    # Experience lines with a date range that no job header claims: a missed or merged job.
+    missed_dated: list[int] = field(default_factory=list)
+    error: str = ""
+
+    @property
+    def coverage(self) -> float:
+        return self.claimed_lines / self.experience_lines if self.experience_lines else 1.0
+
+
+# ---------------------------------------------------------------------------
+# Helpers
+# ---------------------------------------------------------------------------
+
+def _key(text: Any) -> str:
+    return re.sub(r"[^0-9a-z]+", "", str(text or "").casefold())
+
+
+def source_lines(text: str) -> list[str]:
+    """Non-empty source lines in reading order; index i is line number i + 1."""
+    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()][:MAX_LINES]
+
+
+def _numbered(lines: list[str], start: int, end: int) -> str:
+    return "\n".join(f"{n}| {lines[n - 1]}" for n in range(start, end + 1))
+
+
+def _as_int(value: Any) -> int | None:
+    if isinstance(value, bool):
+        return None
+    if isinstance(value, int):
+        return value
+    if isinstance(value, str):
+        m = re.fullmatch(r"\s*L?(\d+)\s*", value)
+        return int(m.group(1)) if m else None
+    return None
+
+
+def _load(raw: Any) -> dict:
+    if isinstance(raw, dict):
+        return raw
+    if isinstance(raw, str):
+        cleaned = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()
+        try:
+            data = json.loads(cleaned)
+        except ValueError:
+            m = re.search(r"\{.*\}", cleaned, re.DOTALL)
+            data = json.loads(m.group()) if m else {}
+        return data if isinstance(data, dict) else {}
+    return {}
+
+
+# ---------------------------------------------------------------------------
+# Call 1: section map
+# ---------------------------------------------------------------------------
+
+_SECTION_PROMPT = (
+    "You label the sections of a resume. The resume is given as numbered lines 'N| text'. "
+    "Return where each section STARTS, in order. Section types: "
+    "header (name, contact, headline), summary, skills, experience (jobs, employment, work history, "
+    "client engagements, any list of positions held), education, projects, certifications, "
+    "achievements, languages, other (any other real section such as volunteering, publications, "
+    "references), noise (job-board profile fields such as 'Preferred Location', 'Willing to "
+    "Relocate', 'Profile Source', page numbers, repeated page headers). "
+    "Headings can have any wording or language, or there may be no heading at all: decide by "
+    "content. A section runs until the next section start. Do not split one job history into "
+    "several experience sections because of job titles or company names. "
+    'Return ONLY JSON: {"sections":[{"line":1,"type":"header"},{"line":7,"type":"summary"}]}'
+)
+
+
+def map_sections(lines: list[str], call: LineClient) -> list[dict[str, Any]]:
+    """[{start, end, type}] covering every line, from the model's section starts."""
+    data = _load(call(_SECTION_PROMPT, _numbered(lines, 1, len(lines))))
+    starts: dict[int, str] = {}
+    for item in data.get("sections") or []:
+        if not isinstance(item, dict):
+            continue
+        line = _as_int(item.get("line"))
+        kind = str(item.get("type") or "").strip().lower()
+        if line is None or not 1 <= line <= len(lines) or kind not in SECTION_TYPES:
+            continue
+        starts.setdefault(line, kind)
+    if not starts:
+        return []
+    starts.setdefault(1, "header")
+    ordered = sorted(starts.items())
+    sections: list[dict[str, Any]] = []
+    for idx, (start, kind) in enumerate(ordered):
+        end = ordered[idx + 1][0] - 1 if idx + 1 < len(ordered) else len(lines)
+        if sections and sections[-1]["type"] == kind:
+            sections[-1]["end"] = end  # adjacent sections of one type are one section
+        else:
+            sections.append({"start": start, "end": end, "type": kind})
+    return sections
+
+
+# ---------------------------------------------------------------------------
+# Call 2: roles per experience chunk
+# ---------------------------------------------------------------------------
+
+_ROLE_PROMPT = (
+    "You read the WORK EXPERIENCE part of a resume, given as numbered lines 'N| text'. "
+    "Identify every job / position / client engagement. For each one return:\n"
+    "- title, company, dates, location: each as {\"line\": N, \"text\": \"...\"} where text is "
+    "copied EXACTLY, character for character, from line N (a part of the line is fine). "
+    "Use null when the resume does not state it. Never guess or reword.\n"
+    "- header_lines: the line numbers that make up the job heading (title / company / dates / location).\n"
+    "- content: [[first, last], ...] line ranges of everything else that belongs to this job "
+    "(bullets, descriptions, responsibilities, environment / tech lines, project names inside the job).\n"
+    "- continues_previous: true only if the first lines shown continue a job that started before "
+    "these lines (no heading of its own).\n"
+    "Several titles at one company (promotions) are separate jobs with the same company. "
+    "Every line should belong to exactly one job. "
+    'Return ONLY JSON: {"roles":[{"title":{"line":3,"text":"..."},"company":{"line":3,"text":"..."},'
+    '"dates":{"line":4,"text":"..."},"location":null,"header_lines":[3,4],"content":[[5,9]],'
+    '"continues_previous":false}]}'
+)
+
+
+def _chunks(start: int, end: int, size: int = CHUNK_LINES) -> list[tuple[int, int]]:
+    out: list[tuple[int, int]] = []
+    cur = start
+    while cur <= end:
+        out.append((cur, min(end, cur + size - 1)))
+        cur += size
+    return out
+
+
+def _grounded(field_value: Any, lines: list[str], lo: int, hi: int) -> tuple[str, int | None, bool]:
+    """(text, line, rejected) for a {line, text} answer; text must be on that line."""
+    if not isinstance(field_value, dict):
+        return "", None, False
+    line = _as_int(field_value.get("line"))
+    text = str(field_value.get("text") or "").strip()
+    if not text:
+        return "", None, False
+    if line is None or not lo <= line <= hi:
+        return "", None, True
+    if _key(text) and _key(text) in _key(lines[line - 1]):
+        return text, line, False
+    return "", None, True
+
+
+def _full_dates(text: str, line: int | None, lines: list[str]) -> str:
+    """Complete a partial date answer from the source ('Jun 2019 -' + 'Present' below)."""
+    if not text or line is None:
+        return text
+    src = lines[line - 1]
+    for m in _RANGE_RE.finditer(src):
+        if _key(text) in _key(m.group()) and len(m.group()) > len(text):
+            text = m.group().strip()
+            break
+    if re.search(r"(?i)(?:[-–—]|\bto)\s*$", text) and line < len(lines):
+        rest = src[src.find(text) + len(text):] if text in src else ""
+        nxt = rest if rest.strip() else lines[line]
+        m = _END_START_RE.match(nxt)
+        if m:
+            text = f"{text} {m.group(1)}"
+    return text
+
+
+def _clean_identity(value: str, dates: str, location: str) -> str:
+    """Drop date / location text the model copied into a title or company."""
+    v = value
+    for part in (dates, location):
+        if part and part in v:
+            v = v.replace(part, " ")
+    v = _RANGE_RE.sub(" ", v)
+    v = _OPEN_TAIL_RE.sub("", v)
+    v = re.sub(r"\(\s*\)", " ", v)
+    m = re.fullmatch(r"\s*\(\s*(.+?)\s*\)\s*", v)
+    if m:
+        v = m.group(1)
+    v = re.sub(r"\s{2,}", " ", v).strip(" -–—|,;:")
+    if not re.search(r"[A-Za-z]{2,}", v):
+        return ""
+    return v
+
+
+def lines_to_bullets(texts: list[str]) -> list[str]:
+    """Join wrapped lines back into bullets; text is copied from the source unchanged."""
+    bullets: list[str] = []
+    in_bullet = False  # the previous line was a bullet (or its wrapped continuation)
+    pending = False  # a lone bullet glyph: the next text line starts a new bullet
+    for raw in texts:
+        marked = bool(_BULLET_RE.match(raw)) or pending
+        pending = False
+        text = _BULLET_RE.sub("", raw).strip()
+        if not text:
+            pending = bool(_BULLET_RE.match(raw))
+            continue
+        prev = bullets[-1] if bullets else ""
+        wrapped = (
+            not marked
+            and in_bullet
+            and prev
+            and (text[:1].islower() or not prev.rstrip().endswith((".", "!", "?", ":")))
+        )
+        if wrapped:
+            bullets[-1] = f"{prev} {text}"
+        else:
+            bullets.append(text)
+            in_bullet = marked
+    return bullets
+
+
+def extract_roles_chunk(
+    lines: list[str], lo: int, hi: int, call: LineClient, hints: list[int] | None = None
+) -> tuple[list[dict], int]:
+    """Validated roles for lines lo..hi (1-based, inclusive) and the count of rejected fields.
+
+    ``hints``: lines a previous read left out of every job header although they hold a
+    date range; the model is asked to look at them again.
+    """
+    prompt = _numbered(lines, lo, hi)
+    own = [n for n in hints or [] if lo <= n <= hi]
+    if own:
+        prompt += (
+            "\n\nNOTE: lines " + ", ".join(str(n) for n in own)
+            + " contain date ranges but were not part of any job heading in an earlier read. "
+            "Check whether each one starts or dates a separate job (including promotions at the "
+            "same company), and make sure no two jobs are merged into one."
+        )
+    data = _load(call(_ROLE_PROMPT, prompt))
+    rejected = 0
+    roles: list[dict[str, Any]] = []
+    for item in data.get("roles") or []:
+        if not isinstance(item, dict):
+            continue
+        fields: dict[str, str] = {}
+        header: set[int] = set()
+        for name in ("title", "company", "dates", "location"):
+            text, line, bad = _grounded(item.get(name), lines, lo, hi)
+            rejected += int(bad)
+            if name == "dates" and text:
+                if not _DATE_TOKEN_RE.search(text):
+                    text, line = "", None
+                    rejected += 1
+                else:
+                    text = _full_dates(text, line, lines)
+            fields[name] = text
+            if line is not None:
+                header.add(line)
+        for name in ("title", "company"):
+            fields[name] = _clean_identity(fields[name], fields["dates"], fields["location"])
+        if fields["title"] and _key(fields["title"]) == _key(fields["company"]):
+            fields["title"] = ""  # the model repeated the employer as the title
+        header.update(n for n in (_as_int(x) for x in item.get("header_lines") or []) if n and lo <= n <= hi)
+        continues = bool(item.get("continues_previous")) and not (fields["title"] or fields["company"])
+        if not (fields["title"] or fields["company"]) and not continues:
+            continue  # no identity and not a continuation: its lines fall to the ledger
+        roles.append({**fields, "header": sorted(header), "continues": continues})
+    return roles, rejected
+
+
+# ---------------------------------------------------------------------------
+# Public API
+# ---------------------------------------------------------------------------
+
+def extract_experience(
+    text: str,
+    call: LineClient,
+    *,
+    max_workers: int = 4,
+    elsewhere: set[int] | None = None,
+    hints: list[int] | None = None,
+) -> ExtractResult:
+    """Section map + per-chunk role extraction, all answers checked against the source.
+
+    ``elsewhere``: lines already placed in another section; they are neither counted
+    as experience nor returned as unassigned.
+    """
+    elsewhere = elsewhere or set()
+    result = ExtractResult()
+    lines = source_lines(text)
+    if not lines:
+        result.error = "no_text"
+        return result
+    try:
+        result.sections = map_sections(lines, call)
+    except Exception as exc:  # noqa: BLE001
+        result.error = f"sections:{type(exc).__name__}"
+        return result
+    result.llm_calls += 1
+    exp = [s for s in result.sections if s["type"] == "experience"]
+    if not exp:
+        return result
+
+    jobs = [chunk for s in exp for chunk in _chunks(s["start"], s["end"])]
+    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(jobs)))) as pool:
+        futures = [pool.submit(extract_roles_chunk, lines, lo, hi, call, hints) for lo, hi in jobs]
+        outputs = []
+        for fut in futures:
+            try:
+                outputs.append(fut.result())
+            except Exception as exc:  # noqa: BLE001 - a failed chunk falls to the ledger
+                result.error = result.error or f"roles:{type(exc).__name__}"
+                outputs.append(([], 0))
+    result.llm_calls += len(jobs)
+
+    for _roles, rejected in outputs:
+        result.rejected_fields += rejected
+
+    # The model names the job headers; every other line goes to the job whose header is
+    # above it, the way a reader assigns it. Content ranges from the model are not used:
+    # they skip small lines and sometimes overlap the next job.
+    anchored: list[tuple[int, dict[str, Any]]] = []
+    seen_anchors: set[int] = set()
+    for chunk_roles, _rejected in outputs:
+        for role in chunk_roles:
+            if role["continues"] or not role["header"]:
+                continue
+            anchor = min(role["header"])
+            if anchor in seen_anchors:
+                continue  # the same job reported twice
+            seen_anchors.add(anchor)
+            anchored.append((anchor, role))
+    anchored.sort(key=lambda item: item[0])
+    header_lines = {n for _a, role in anchored for n in role["header"]}
+
+    # The section's own heading line ("EXPERIENCE") and labels such as "Responsibilities:"
+    # are structure, not content.
+    headings = {
+        s["start"]
+        for s in exp
+        if len(lines[s["start"] - 1].split()) <= 4 and not _DATE_TOKEN_RE.search(lines[s["start"] - 1])
+    }
+    exp_lines = [
+        n
+        for s in exp
+        for n in range(s["start"], s["end"] + 1)
+        if n not in elsewhere and n not in headings and not _LABEL_RE.match(lines[n - 1])
+    ]
+
+    content: dict[int, list[int]] = {i: [] for i in range(len(anchored))}
+    leftover: list[int] = []
+    anchors = [a for a, _role in anchored]
+    for n in exp_lines:
+        if n in header_lines:
+            continue
+        idx = bisect_right(anchors, n) - 1
+        if idx < 0:
+            leftover.append(n)  # above the first job header: no job to attach it to
+        else:
+            content[idx].append(n)
+
+    result.roles = []
+    for i, (_anchor, role) in enumerate(anchored):
+        result.roles.append({
+            "title": role["title"],
+            "company": role["company"],
+            "location": role["location"],
+            "duration": role["dates"],
+            "description": lines_to_bullets([lines[n - 1] for n in content[i]]),
+            "technologies": [],
+        })
+    result.experience_lines = len(exp_lines)
+    result.claimed_lines = len(exp_lines) - len(leftover)
+    result.unassigned = lines_to_bullets([lines[n - 1] for n in leftover])
+    result.missed_dated = [
+        n
+        for n in exp_lines
+        if n not in header_lines and _RANGE_RE.search(lines[n - 1]) and not _BULLET_RE.match(lines[n - 1])
+    ]
+    return result
+
+
+def _default_client(system_prompt: str, user_prompt: str) -> Any:
+    from app.agents.tools.llm_client import llm_call_json_with_metrics
+
+    return llm_call_json_with_metrics(
+        system_prompt,
+        user_prompt,
+        repair_attempts=1,
+        validation_attempts=0,
+        max_tokens=4096,
+    ).data
+
+
+_NON_EXPERIENCE_KEYS = (
+    "name", "email", "phone", "location", "linkedin", "portfolio", "headline", "summary",
+    "skills", "skills_by_category", "education", "projects", "certifications", "achievements",
+    "languages", "additional_sections",
+)
+
+
+def _flatten(value: Any, out: list[str]) -> None:
+    if isinstance(value, str):
+        out.append(value)
+    elif isinstance(value, dict):
+        for k, v in value.items():
+            if isinstance(k, str):
+                out.append(k)
+            _flatten(v, out)
+    elif isinstance(value, (list, tuple)):
+        for v in value:
+            _flatten(v, out)
+
+
+def placed_elsewhere(parsed: dict, text: str) -> set[int]:
+    """Line numbers the rule parse already put in a non-experience field."""
+    pool: list[str] = []
+    for key in _NON_EXPERIENCE_KEYS:
+        _flatten(parsed.get(key), pool)
+    pool_key = _key(" ".join(pool))
+    out: set[int] = set()
+    for n, line in enumerate(source_lines(text), 1):
+        k = _key(_BULLET_RE.sub("", line))
+        if len(k) >= 6 and k in pool_key:
+            out.add(n)
+    return out
+
+
+def _experience_coverage(parsed: dict, text: str, result: ExtractResult, elsewhere: set[int]) -> float:
+    """Share of the model-mapped experience lines that the rule parse placed."""
+    lines = source_lines(text)
+    exp = [
+        n
+        for s in result.sections
+        if s["type"] == "experience"
+        for n in range(s["start"], s["end"] + 1)
+        if n not in elsewhere
+    ]
+    if not exp:
+        return 1.0
+    pool = " ".join(
+        str(v)
+        for r in parsed.get("experience") or []
+        for v in [r.get("title"), r.get("company"), r.get("duration"), r.get("location"), *(r.get("description") or [])]
+        if v
+    )
+    pool_key = _key(pool)
+    hit = sum(1 for n in exp if _key(_BULLET_RE.sub("", lines[n - 1])) and _key(_BULLET_RE.sub("", lines[n - 1])) in pool_key)
+    return hit / len(exp)
+
+
+def _role_quality(roles: list[dict]) -> float:
+    if not roles:
+        return 0.0
+    complete = sum(1 for r in roles if r.get("title") and r.get("company") and r.get("duration"))
+    return complete / len(roles)
+
+
+def _is_lumped(rule_roles: list[dict], result: ExtractResult, rule_cov: float) -> bool:
+    """Clearly fewer jobs than a good rule parse: several jobs were merged into one.
+
+    Claiming every line by lumping jobs together also scores full coverage, so coverage
+    alone cannot catch it.
+    """
+    return len(rule_roles) >= 2 and len(result.roles) < 0.75 * len(rule_roles) and rule_cov >= 0.6
+
+
+def _passes_gate(result: ExtractResult, lumped: bool) -> bool:
+    """A read worth keeping without a retry."""
+    return (
+        bool(result.roles)
+        and not lumped
+        and result.coverage >= 0.9
+        and not result.missed_dated
+        and result.rejected_fields <= max(2, len(result.roles) // 2)
+    )
+
+
+def _attempt_score(result: ExtractResult, _rule_cov: float, lumped: bool) -> tuple:
+    return (
+        bool(result.roles),
+        not lumped,
+        -len(result.missed_dated),
+        round(result.coverage, 2),
+        _role_quality(result.roles),
+        -result.rejected_fields,
+    )
+
+
+def apply_line_extraction(text: str, parsed: dict, *, client: LineClient | None = None) -> dict:
+    """Use the grounded LLM roles when they explain the source better than the rule parse.
+
+    Never raises: any failure returns ``parsed`` unchanged (with the reason in parse_meta).
+    """
+    started = time.perf_counter()
+    meta = dict(parsed.get("parse_meta") or {})
+    elsewhere = placed_elsewhere(parsed, text)
+    rule_roles = parsed.get("experience") or []
+    call = client or _default_client
+    max_attempts = max(1, int(getattr(settings, "RESUME_LLM_LINE_EXTRACT_MAX_ATTEMPTS", 2)))
+
+    attempts: list[tuple[ExtractResult, float, bool]] = []
+    hints: list[int] | None = None
+    for _attempt in range(max_attempts):
+        try:
+            res = extract_experience(text, call, elsewhere=elsewhere, hints=hints)
+        except Exception as exc:  # noqa: BLE001
+            res = ExtractResult(error=type(exc).__name__)
+        cov = _experience_coverage(parsed, text, res, elsewhere) if res.sections else 1.0
+        lumped_try = _is_lumped(rule_roles, res, cov)
+        attempts.append((res, cov, lumped_try))
+        if res.error.startswith("sections") or _passes_gate(res, lumped_try):
+            break  # good enough, or Bedrock unavailable: do not retry
+        if not res.roles and not rule_roles and not detect_employment_evidence(text).has_work_history:
+            break  # no work history to find (e.g. a student CV)
+        hints = res.missed_dated or None
+    result, rule_cov, lumped = max(attempts, key=lambda a: _attempt_score(*a))
+    if not result.sections and result.error and not result.roles:
+        meta["line_extract"] = {"used": False, "error": result.error, "attempts": len(attempts)}
+        return {**parsed, "parse_meta": meta}
+
+    info = {
+        "used": False,
+        "attempts": len(attempts),
+        "gate_passed": _passes_gate(result, lumped),
+        "missed_dated_lines": len(result.missed_dated),
+        "llm_calls": sum(a[0].llm_calls for a in attempts),
+        "llm_roles": len(result.roles),
+        "rule_roles": len(rule_roles),
+        "llm_coverage": round(result.coverage, 3),
+        "rule_coverage": round(rule_cov, 3),
+        "rejected_fields": result.rejected_fields,
+        "unassigned_lines": len(result.unassigned),
+        "elapsed_ms": int((time.perf_counter() - started) * 1000),
+    }
+    if result.error:
+        info["error"] = result.error
+
+    info["lumped"] = lumped
+    better = bool(result.roles) and not lumped and (
+        not rule_roles
+        or result.coverage > rule_cov + 0.02
+        or (result.coverage >= rule_cov - 0.02 and _role_quality(result.roles) > _role_quality(rule_roles))
+    )
+    out = dict(parsed)
+    if better:
+        out["experience"] = result.roles
+        if result.unassigned:
+            out["unassigned_experience_bullets"] = result.unassigned
+        else:
+            out.pop("unassigned_experience_bullets", None)
+        info["used"] = True
+    info["disagree"] = bool(rule_roles) and abs(len(result.roles) - len(rule_roles)) > max(1, len(rule_roles) // 4)
+    meta["line_extract"] = info
+    out["parse_meta"] = meta
+    logger.info("line_extract_done", **{k: v for k, v in info.items() if k != "error"})
+    return out
+
+
+def enabled() -> bool:
+    return bool(getattr(settings, "RESUME_LLM_LINE_EXTRACT", False)) and bool(settings.AWS_BEARER_TOKEN_BEDROCK)
diff --git a/backend/tests/test_llm_line_extractor.py b/backend/tests/test_llm_line_extractor.py
new file mode 100644
index 0000000..4ec96e5
--- /dev/null
+++ b/backend/tests/test_llm_line_extractor.py
@@ -0,0 +1,301 @@
+"""Grounded line extraction: the model answers with line numbers; code copies and checks."""
+from __future__ import annotations
+
+from app.services import llm_line_extractor
+from app.services.llm_line_extractor import (
+    apply_line_extraction,
+    extract_experience,
+    lines_to_bullets,
+)
+
+RESUME = "\n".join(
+    [
+        "Jane Candidate",  # 1
+        "jane@example.com",  # 2
+        "Where I have worked",  # 3  (heading the rule parser does not know)
+        "Acme Corp",  # 4
+        "(Senior Engineer) 01/2018 - Present",  # 5
+        "• Built the billing platform used by",  # 6
+        "every customer in the region.",  # 7
+        "• Cut deploy time to ten minutes.",  # 8
+        "Globex",  # 9
+        "(Engineer) 06/2015 - 12/2017",  # 10
+        "• Maintained the order system.",  # 11
+        "Volunteered at the food bank.",  # 12  (no role claims it)
+        "Education",  # 13
+        "B.S. Computer Science, State University",  # 14
+    ]
+)
+
+SECTIONS = {"sections": [{"line": 1, "type": "header"}, {"line": 3, "type": "experience"}, {"line": 13, "type": "education"}]}
+
+
+def _role(title, company, dates, header, content, **extra):
+    return {
+        "title": title,
+        "company": company,
+        "dates": dates,
+        "location": None,
+        "header_lines": header,
+        "content": content,
+        **extra,
+    }
+
+
+def fake_client(roles_payload):
+    def call(system_prompt, user_prompt):
+        if "label the sections" in system_prompt:
+            return SECTIONS
+        return roles_payload
+
+    return call
+
+
+GOOD_ROLES = {
+    "roles": [
+        _role({"line": 5, "text": "Senior Engineer"}, {"line": 4, "text": "Acme Corp"},
+              {"line": 5, "text": "01/2018 - Present"}, [4, 5], [[6, 8]]),
+        _role({"line": 10, "text": "Engineer"}, {"line": 9, "text": "Globex"},
+              {"line": 10, "text": "06/2015 - 12/2017"}, [9, 10], [[11, 11]]),
+    ]
+}
+
+
+def test_roles_are_copied_from_cited_lines():
+    result = extract_experience(RESUME, fake_client(GOOD_ROLES))
+
+    assert [(r["title"], r["company"], r["duration"]) for r in result.roles] == [
+        ("Senior Engineer", "Acme Corp", "01/2018 - Present"),
+        ("Engineer", "Globex", "06/2015 - 12/2017"),
+    ]
+    # Wrapped bullet rejoined; text is the source's, not the model's.
+    assert result.roles[0]["description"] == [
+        "Built the billing platform used by every customer in the region.",
+        "Cut deploy time to ten minutes.",
+    ]
+
+
+def test_lines_go_to_the_job_whose_header_is_above_them():
+    result = extract_experience(RESUME, fake_client(GOOD_ROLES))
+
+    # The model's content range for Globex stopped at line 11; line 12 still sits under it.
+    assert result.roles[1]["description"] == ["Maintained the order system.", "Volunteered at the food bank."]
+    assert result.unassigned == []
+    assert result.claimed_lines == result.experience_lines
+
+
+def test_line_above_the_first_job_header_is_kept_as_unassigned():
+    text = RESUME.replace("Where I have worked\n", "Where I have worked\nSelected consulting work across retail clients\n")
+    sections = {"sections": [{"line": 1, "type": "header"}, {"line": 3, "type": "experience"}, {"line": 14, "type": "education"}]}
+    roles = {"roles": [_role({"line": 6, "text": "Senior Engineer"}, {"line": 5, "text": "Acme Corp"}, None, [5, 6], [])]}
+
+    def call(system_prompt, user_prompt):
+        return sections if "label the sections" in system_prompt else roles
+
+    result = extract_experience(text, call)
+
+    assert result.unassigned == ["Selected consulting work across retail clients"]
+
+
+def test_label_lines_are_structure_not_bullets():
+    text = "Experience\nAcme Corp | Engineer | 2019 - Present\nResponsibilities:\n• Built the billing platform."
+    sections = {"sections": [{"line": 1, "type": "experience"}]}
+    roles = {"roles": [_role({"line": 2, "text": "Engineer"}, {"line": 2, "text": "Acme Corp"},
+                             {"line": 2, "text": "2019 - Present"}, [2], [])]}
+
+    def call(system_prompt, user_prompt):
+        return sections if "label the sections" in system_prompt else roles
+
+    result = extract_experience(text, call)
+
+    assert result.roles[0]["description"] == ["Built the billing platform."]
+    assert result.unassigned == []
+
+
+def test_invented_text_is_rejected_field_by_field():
+    payload = {
+        "roles": [
+            _role({"line": 5, "text": "Principal Architect"},  # not on line 5
+                  {"line": 4, "text": "Acme Corp"}, {"line": 5, "text": "01/2018 - Present"}, [4, 5], [[6, 8]]),
+        ]
+    }
+    result = extract_experience(RESUME, fake_client(payload))
+
+    assert result.roles[0]["title"] == ""
+    assert result.roles[0]["company"] == "Acme Corp"
+    assert result.rejected_fields == 1
+
+
+def test_out_of_range_line_is_rejected():
+    payload = {"roles": [_role(None, {"line": 99, "text": "Acme Corp"}, None, [], [[6, 8]])]}
+    result = extract_experience(RESUME, fake_client(payload))
+
+    assert result.roles == []
+    assert result.rejected_fields == 1
+    assert len(result.unassigned) >= 2  # its lines were not lost
+
+
+def test_a_line_belongs_to_one_role_only():
+    payload = {
+        "roles": [
+            GOOD_ROLES["roles"][0],
+            _role({"line": 10, "text": "Engineer"}, {"line": 9, "text": "Globex"}, None, [9, 10], [[6, 11]]),
+        ]
+    }
+    result = extract_experience(RESUME, fake_client(payload))
+
+    # Globex's model range [6, 11] overlapped Acme; position decides instead.
+    assert result.roles[0]["description"] == [
+        "Built the billing platform used by every customer in the region.",
+        "Cut deploy time to ten minutes.",
+    ]
+    assert result.roles[1]["description"] == ["Maintained the order system.", "Volunteered at the food bank."]
+
+
+def test_rule_parse_kept_when_model_fails():
+    parsed = {"experience": [{"title": "X", "company": "Y", "duration": "2019", "description": []}], "parse_meta": {}}
+
+    def broken(system_prompt, user_prompt):
+        raise TimeoutError("bedrock down")
+
+    out = apply_line_extraction(RESUME, parsed, client=broken)
+
+    assert out["experience"] == parsed["experience"]
+    assert out["parse_meta"]["line_extract"]["used"] is False
+
+
+def test_model_roles_used_when_rule_parse_found_none():
+    parsed = {"experience": [], "parse_meta": {}}
+    out = apply_line_extraction(RESUME, parsed, client=fake_client(GOOD_ROLES))
+
+    assert out["parse_meta"]["line_extract"]["used"] is True
+    assert [r["company"] for r in out["experience"]] == ["Acme Corp", "Globex"]
+    assert "unassigned_experience_bullets" not in out
+
+
+def test_apply_uses_non_lumped_llm_role_when_rule_has_zero_and_coverage_is_weak(monkeypatch):
+    text = "\n".join([
+        "Experience",
+        "Selected client engagements",
+        "Cloud transformation program",
+        "Senior Engineer",
+        "• Built the billing platform.",
+    ])
+    sections = {"sections": [{"line": 1, "type": "experience"}]}
+    roles = {"roles": [_role({"line": 4, "text": "Senior Engineer"}, None, None, [4], [[5, 5]])]}
+
+    def call(system_prompt, user_prompt):
+        return sections if "label the sections" in system_prompt else roles
+
+    monkeypatch.setattr(llm_line_extractor, "_experience_coverage", lambda *_args: 0.5)
+    out = apply_line_extraction(text, {"experience": [], "parse_meta": {}}, client=call)
+
+    assert out["parse_meta"]["line_extract"]["gate_passed"] is False
+    assert out["parse_meta"]["line_extract"]["used"] is True
+    assert [role["title"] for role in out["experience"]] == ["Senior Engineer"]
+
+
+def test_dates_copied_into_title_and_company_are_removed():
+    text = "Experience\nTechnical Project Manager (Jul’ 14 – Present)\nInfosys – Rosemead Jul. ’14 to\nPresent\n• Led delivery."
+    sections = {"sections": [{"line": 1, "type": "experience"}]}
+    roles = {"roles": [_role({"line": 2, "text": "Technical Project Manager (Jul’ 14 – Present)"},
+                             {"line": 3, "text": "Infosys – Rosemead Jul. ’14 to"},
+                             {"line": 3, "text": "Jul. ’14 to"}, [2, 3, 4], [[5, 5]])]}
+
+    def call(system_prompt, user_prompt):
+        return sections if "label the sections" in system_prompt else roles
+
+    role = extract_experience(text, call).roles[0]
+
+    assert role["title"] == "Technical Project Manager"
+    assert role["company"] == "Infosys – Rosemead"
+    assert role["duration"] == "Jul. ’14 to Present"  # end date read from the next line
+
+
+def test_title_that_repeats_the_company_is_blanked():
+    payload = {"roles": [_role({"line": 4, "text": "Acme Corp"}, {"line": 4, "text": "Acme Corp"},
+                               {"line": 5, "text": "01/2018 - Present"}, [4, 5], [[6, 8]])]}
+    role = extract_experience(RESUME, fake_client(payload)).roles[0]
+
+    assert role["title"] == ""
+    assert role["company"] == "Acme Corp"
+
+
+def test_lumped_result_does_not_replace_a_good_rule_parse():
+    lumped = {"roles": [_role({"line": 5, "text": "Senior Engineer"}, {"line": 4, "text": "Acme Corp"},
+                              None, [4, 5], [[6, 12]])]}
+    rule_roles = [
+        {"title": "Senior Engineer", "company": "Acme Corp", "duration": "01/2018 - Present",
+         "description": ["Built the billing platform used by every customer in the region.",
+                         "Cut deploy time to ten minutes."]},
+        {"title": "Engineer", "company": "Globex", "duration": "06/2015 - 12/2017",
+         "description": ["Maintained the order system.", "Volunteered at the food bank."]},
+    ]
+    out = apply_line_extraction(RESUME, {"experience": rule_roles, "parse_meta": {}}, client=fake_client(lumped))
+
+    assert out["experience"] == rule_roles
+    assert out["parse_meta"]["line_extract"]["lumped"] is True
+
+
+def test_lines_the_rule_parse_placed_elsewhere_are_not_reassigned():
+    parsed = {
+        "experience": [],
+        "additional_sections": [{"title": "Volunteering", "lines": ["Volunteered at the food bank."]}],
+        "parse_meta": {},
+    }
+    out = apply_line_extraction(RESUME, parsed, client=fake_client(GOOD_ROLES))
+
+    assert "unassigned_experience_bullets" not in out
+    assert out["parse_meta"]["line_extract"]["llm_coverage"] == 1.0
+
+
+def test_missed_job_is_retried_with_the_dated_line_named():
+    # First read merges Globex into Acme; the gate sees line 10's date range outside any
+    # heading and retries, naming that line.
+    merged = {"roles": [GOOD_ROLES["roles"][0]]}
+    prompts: list[str] = []
+
+    def call(system_prompt, user_prompt):
+        if "label the sections" in system_prompt:
+            return SECTIONS
+        prompts.append(user_prompt)
+        return GOOD_ROLES if "NOTE: lines 10" in user_prompt else merged
+
+    out = apply_line_extraction(RESUME, {"experience": [], "parse_meta": {}}, client=call)
+    info = out["parse_meta"]["line_extract"]
+
+    assert len(prompts) == 2
+    assert info["attempts"] == 2 and info["gate_passed"] is True
+    assert [r["company"] for r in out["experience"]] == ["Acme Corp", "Globex"]
+
+
+def test_clean_read_is_not_retried():
+    calls: list[str] = []
+
+    def call(system_prompt, user_prompt):
+        calls.append(system_prompt[:20])
+        return SECTIONS if "label the sections" in system_prompt else GOOD_ROLES
+
+    out = apply_line_extraction(RESUME, {"experience": [], "parse_meta": {}}, client=call)
+
+    assert len(calls) == 2  # one section map + one role chunk
+    assert out["parse_meta"]["line_extract"]["attempts"] == 1
+
+
+def test_better_attempt_is_kept_when_retry_is_worse():
+    good_then_bad = iter([{"roles": [GOOD_ROLES["roles"][0]]}, {"roles": []}])
+
+    def call(system_prompt, user_prompt):
+        return SECTIONS if "label the sections" in system_prompt else next(good_then_bad)
+
+    out = apply_line_extraction(RESUME, {"experience": [], "parse_meta": {}}, client=call)
+
+    assert out["parse_meta"]["line_extract"]["attempts"] == 2
+    assert [r["company"] for r in out["experience"]] == ["Acme Corp"]
+
+
+def test_lone_bullet_glyph_starts_a_new_bullet():
+    assert lines_to_bullets(["• First item", "•", "Second item", "wraps here"]) == [
+        "First item",
+        "Second item wraps here",
+    ]
