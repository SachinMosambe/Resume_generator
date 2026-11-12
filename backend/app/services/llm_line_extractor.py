"""Grounded LLM extraction of work history using line numbers.

The model never writes resume text. It sees numbered source lines and answers with
line numbers (plus, for title / company / dates, the exact words it read on a cited
line). Code then copies text from the source and checks every answer:

* a cited line must exist and belong to the chunk the model was shown;
* a title / company / date / location must appear verbatim on the line it cites,
  otherwise that field is dropped;
* a line can belong to one role only.

Every experience line that no role claims is returned as an unassigned bullet so it
reaches the output and is flagged for review. No resume text is logged.

Call 1 maps sections (where each one starts). Call 2 runs per experience chunk.
"""
from __future__ import annotations

import json
import re
import time
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from app.core.config import settings
from app.core.logging import logger
from app.services.source_evidence import detect_employment_evidence

# client(system_prompt, user_prompt) -> dict (parsed JSON) or JSON string
LineClient = Callable[[str, str], Any]

SECTION_TYPES = {
    "header", "summary", "skills", "experience", "education", "projects", "certifications",
    "achievements", "languages", "other", "noise",
}
CHUNK_LINES = 120
MAX_LINES = 1500
_BULLET_RE = re.compile(r"^\s*[•●▪◦‣·■➢✓\-\*–—>]+\s*")
_DATE_TOKEN_RE = re.compile(r"(?i)\b(?:19|20)\d{2}\b|\b(?:present|current|till date|to date|now)\b|\b\d{1,2}/\d{2,4}\b|['’]\d{2}\b")
_MON = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_POINT = rf"(?:{_MON}\s*[,.]?\s*['’‘]?\s*(?:\d{{4}}|\d{{2}})(?!\d)|\d{{1,2}}/\d{{2,4}}|(?:19|20)\d{{2}})"
_END = rf"(?:{_POINT}|present|current|till\s*date|till\s*now|to\s*date|now|ongoing)"
_RANGE_RE = re.compile(rf"(?i){_POINT}\s*(?:-|–|—|to|until)\s*{_END}")
_OPEN_TAIL_RE = re.compile(rf"(?i)\s*\(?\s*{_POINT}\s*(?:-|–|—|to)?\s*\)?\s*$")
_LABEL_RE = re.compile(r"^\s*[A-Za-z][A-Za-z &/\-]{1,40}:\s*$")
_END_START_RE = re.compile(rf"(?i)^\s*({_END})\b")


@dataclass
class ExtractResult:
    roles: list[dict[str, Any]] = field(default_factory=list)
    unassigned: list[str] = field(default_factory=list)
    sections: list[dict[str, Any]] = field(default_factory=list)
    experience_lines: int = 0
    claimed_lines: int = 0
    llm_calls: int = 0
    rejected_fields: int = 0
    # Experience lines with a date range that no job header claims: a missed or merged job.
    missed_dated: list[int] = field(default_factory=list)
    error: str = ""

    @property
    def coverage(self) -> float:
        return self.claimed_lines / self.experience_lines if self.experience_lines else 1.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _key(text: Any) -> str:
    return re.sub(r"[^0-9a-z]+", "", str(text or "").casefold())


def source_lines(text: str) -> list[str]:
    """Non-empty source lines in reading order; index i is line number i + 1."""
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()][:MAX_LINES]


def _numbered(lines: list[str], start: int, end: int) -> str:
    return "\n".join(f"{n}| {lines[n - 1]}" for n in range(start, end + 1))


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        m = re.fullmatch(r"\s*L?(\d+)\s*", value)
        return int(m.group(1)) if m else None
    return None


def _load(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        cleaned = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()
        try:
            data = json.loads(cleaned)
        except ValueError:
            m = re.search(r"\{.*\}", cleaned, re.DOTALL)
            data = json.loads(m.group()) if m else {}
        return data if isinstance(data, dict) else {}
    return {}


# ---------------------------------------------------------------------------
# Call 1: section map
# ---------------------------------------------------------------------------

_SECTION_PROMPT = (
    "You label the sections of a resume. The resume is given as numbered lines 'N| text'. "
    "Return where each section STARTS, in order. Section types: "
    "header (name, contact, headline), summary, skills, experience (jobs, employment, work history, "
    "client engagements, any list of positions held), education, projects, certifications, "
    "achievements, languages, other (any other real section such as volunteering, publications, "
    "references), noise (job-board profile fields such as 'Preferred Location', 'Willing to "
    "Relocate', 'Profile Source', page numbers, repeated page headers). "
    "Headings can have any wording or language, or there may be no heading at all: decide by "
    "content. A section runs until the next section start. Do not split one job history into "
    "several experience sections because of job titles or company names. "
    'Return ONLY JSON: {"sections":[{"line":1,"type":"header"},{"line":7,"type":"summary"}]}'
)


def map_sections(lines: list[str], call: LineClient) -> list[dict[str, Any]]:
    """[{start, end, type}] covering every line, from the model's section starts."""
    data = _load(call(_SECTION_PROMPT, _numbered(lines, 1, len(lines))))
    starts: dict[int, str] = {}
    for item in data.get("sections") or []:
        if not isinstance(item, dict):
            continue
        line = _as_int(item.get("line"))
        kind = str(item.get("type") or "").strip().lower()
        if line is None or not 1 <= line <= len(lines) or kind not in SECTION_TYPES:
            continue
        starts.setdefault(line, kind)
    if not starts:
        return []
    starts.setdefault(1, "header")
    ordered = sorted(starts.items())
    sections: list[dict[str, Any]] = []
    for idx, (start, kind) in enumerate(ordered):
        end = ordered[idx + 1][0] - 1 if idx + 1 < len(ordered) else len(lines)
        if sections and sections[-1]["type"] == kind:
            sections[-1]["end"] = end  # adjacent sections of one type are one section
        else:
            sections.append({"start": start, "end": end, "type": kind})
    return sections


# ---------------------------------------------------------------------------
# Call 2: roles per experience chunk
# ---------------------------------------------------------------------------

_ROLE_PROMPT = (
    "You read the WORK EXPERIENCE part of a resume, given as numbered lines 'N| text'. "
    "Identify every job / position / client engagement. For each one return:\n"
    "- title, company, dates, location: each as {\"line\": N, \"text\": \"...\"} where text is "
    "copied EXACTLY, character for character, from line N (a part of the line is fine). "
    "Use null when the resume does not state it. Never guess or reword.\n"
    "- header_lines: the line numbers that make up the job heading (title / company / dates / location).\n"
    "- content: [[first, last], ...] line ranges of everything else that belongs to this job "
    "(bullets, descriptions, responsibilities, environment / tech lines, project names inside the job).\n"
    "- continues_previous: true only if the first lines shown continue a job that started before "
    "these lines (no heading of its own).\n"
    "Several titles at one company (promotions) are separate jobs with the same company. "
    "Every line should belong to exactly one job. "
    'Return ONLY JSON: {"roles":[{"title":{"line":3,"text":"..."},"company":{"line":3,"text":"..."},'
    '"dates":{"line":4,"text":"..."},"location":null,"header_lines":[3,4],"content":[[5,9]],'
    '"continues_previous":false}]}'
)


def _chunks(start: int, end: int, size: int = CHUNK_LINES) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    cur = start
    while cur <= end:
        out.append((cur, min(end, cur + size - 1)))
        cur += size
    return out


def _grounded(field_value: Any, lines: list[str], lo: int, hi: int) -> tuple[str, int | None, bool]:
    """(text, line, rejected) for a {line, text} answer; text must be on that line."""
    if not isinstance(field_value, dict):
        return "", None, False
    line = _as_int(field_value.get("line"))
    text = str(field_value.get("text") or "").strip()
    if not text:
        return "", None, False
    if line is None or not lo <= line <= hi:
        return "", None, True
    if _key(text) and _key(text) in _key(lines[line - 1]):
        return text, line, False
    return "", None, True


def _full_dates(text: str, line: int | None, lines: list[str]) -> str:
    """Complete a partial date answer from the source ('Jun 2019 -' + 'Present' below)."""
    if not text or line is None:
        return text
    src = lines[line - 1]
    for m in _RANGE_RE.finditer(src):
        if _key(text) in _key(m.group()) and len(m.group()) > len(text):
            text = m.group().strip()
            break
    if re.search(r"(?i)(?:[-–—]|\bto)\s*$", text) and line < len(lines):
        rest = src[src.find(text) + len(text):] if text in src else ""
        nxt = rest if rest.strip() else lines[line]
        m = _END_START_RE.match(nxt)
        if m:
            text = f"{text} {m.group(1)}"
    return text


def _clean_identity(value: str, dates: str, location: str) -> str:
    """Drop date / location text the model copied into a title or company."""
    v = value
    for part in (dates, location):
        if part and part in v:
            v = v.replace(part, " ")
    v = _RANGE_RE.sub(" ", v)
    v = _OPEN_TAIL_RE.sub("", v)
    v = re.sub(r"\(\s*\)", " ", v)
    m = re.fullmatch(r"\s*\(\s*(.+?)\s*\)\s*", v)
    if m:
        v = m.group(1)
    v = re.sub(r"\s{2,}", " ", v).strip(" -–—|,;:")
    if not re.search(r"[A-Za-z]{2,}", v):
        return ""
    return v


def lines_to_bullets(texts: list[str]) -> list[str]:
    """Join wrapped lines back into bullets; text is copied from the source unchanged."""
    bullets: list[str] = []
    in_bullet = False  # the previous line was a bullet (or its wrapped continuation)
    pending = False  # a lone bullet glyph: the next text line starts a new bullet
    for raw in texts:
        marked = bool(_BULLET_RE.match(raw)) or pending
        pending = False
        text = _BULLET_RE.sub("", raw).strip()
        if not text:
            pending = bool(_BULLET_RE.match(raw))
            continue
        prev = bullets[-1] if bullets else ""
        wrapped = (
            not marked
            and in_bullet
            and prev
            and (text[:1].islower() or not prev.rstrip().endswith((".", "!", "?", ":")))
        )
        if wrapped:
            bullets[-1] = f"{prev} {text}"
        else:
            bullets.append(text)
            in_bullet = marked
    return bullets


def extract_roles_chunk(
    lines: list[str], lo: int, hi: int, call: LineClient, hints: list[int] | None = None
) -> tuple[list[dict], int]:
    """Validated roles for lines lo..hi (1-based, inclusive) and the count of rejected fields.

    ``hints``: lines a previous read left out of every job header although they hold a
    date range; the model is asked to look at them again.
    """
    prompt = _numbered(lines, lo, hi)
    own = [n for n in hints or [] if lo <= n <= hi]
    if own:
        prompt += (
            "\n\nNOTE: lines " + ", ".join(str(n) for n in own)
            + " contain date ranges but were not part of any job heading in an earlier read. "
            "Check whether each one starts or dates a separate job (including promotions at the "
            "same company), and make sure no two jobs are merged into one."
        )
    data = _load(call(_ROLE_PROMPT, prompt))
    rejected = 0
    roles: list[dict[str, Any]] = []
    for item in data.get("roles") or []:
        if not isinstance(item, dict):
            continue
        fields: dict[str, str] = {}
        header: set[int] = set()
        for name in ("title", "company", "dates", "location"):
            text, line, bad = _grounded(item.get(name), lines, lo, hi)
            rejected += int(bad)
            if name == "dates" and text:
                if not _DATE_TOKEN_RE.search(text):
                    text, line = "", None
                    rejected += 1
                else:
                    text = _full_dates(text, line, lines)
            fields[name] = text
            if line is not None:
                header.add(line)
        for name in ("title", "company"):
            fields[name] = _clean_identity(fields[name], fields["dates"], fields["location"])
        if fields["title"] and _key(fields["title"]) == _key(fields["company"]):
            fields["title"] = ""  # the model repeated the employer as the title
        header.update(n for n in (_as_int(x) for x in item.get("header_lines") or []) if n and lo <= n <= hi)
        continues = bool(item.get("continues_previous")) and not (fields["title"] or fields["company"])
        if not (fields["title"] or fields["company"]) and not continues:
            continue  # no identity and not a continuation: its lines fall to the ledger
        roles.append({**fields, "header": sorted(header), "continues": continues})
    return roles, rejected


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_experience(
    text: str,
    call: LineClient,
    *,
    max_workers: int = 4,
    elsewhere: set[int] | None = None,
    hints: list[int] | None = None,
) -> ExtractResult:
    """Section map + per-chunk role extraction, all answers checked against the source.

    ``elsewhere``: lines already placed in another section; they are neither counted
    as experience nor returned as unassigned.
    """
    elsewhere = elsewhere or set()
    result = ExtractResult()
    lines = source_lines(text)
    if not lines:
        result.error = "no_text"
        return result
    try:
        result.sections = map_sections(lines, call)
    except Exception as exc:  # noqa: BLE001
        result.error = f"sections:{type(exc).__name__}"
        return result
    result.llm_calls += 1
    exp = [s for s in result.sections if s["type"] == "experience"]
    if not exp:
        return result

    jobs = [chunk for s in exp for chunk in _chunks(s["start"], s["end"])]
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(jobs)))) as pool:
        futures = [pool.submit(extract_roles_chunk, lines, lo, hi, call, hints) for lo, hi in jobs]
        outputs = []
        for fut in futures:
            try:
                outputs.append(fut.result())
            except Exception as exc:  # noqa: BLE001 - a failed chunk falls to the ledger
                result.error = result.error or f"roles:{type(exc).__name__}"
                outputs.append(([], 0))
    result.llm_calls += len(jobs)

    for _roles, rejected in outputs:
        result.rejected_fields += rejected

    # The model names the job headers; every other line goes to the job whose header is
    # above it, the way a reader assigns it. Content ranges from the model are not used:
    # they skip small lines and sometimes overlap the next job.
    anchored: list[tuple[int, dict[str, Any]]] = []
    seen_anchors: set[int] = set()
    for chunk_roles, _rejected in outputs:
        for role in chunk_roles:
            if role["continues"] or not role["header"]:
                continue
            anchor = min(role["header"])
            if anchor in seen_anchors:
                continue  # the same job reported twice
            seen_anchors.add(anchor)
            anchored.append((anchor, role))
    anchored.sort(key=lambda item: item[0])
    header_lines = {n for _a, role in anchored for n in role["header"]}

    # The section's own heading line ("EXPERIENCE") and labels such as "Responsibilities:"
    # are structure, not content.
    headings = {
        s["start"]
        for s in exp
        if len(lines[s["start"] - 1].split()) <= 4 and not _DATE_TOKEN_RE.search(lines[s["start"] - 1])
    }
    exp_lines = [
        n
        for s in exp
        for n in range(s["start"], s["end"] + 1)
        if n not in elsewhere and n not in headings and not _LABEL_RE.match(lines[n - 1])
    ]

    content: dict[int, list[int]] = {i: [] for i in range(len(anchored))}
    leftover: list[int] = []
    anchors = [a for a, _role in anchored]
    for n in exp_lines:
        if n in header_lines:
            continue
        idx = bisect_right(anchors, n) - 1
        if idx < 0:
            leftover.append(n)  # above the first job header: no job to attach it to
        else:
            content[idx].append(n)

    result.roles = []
    for i, (_anchor, role) in enumerate(anchored):
        result.roles.append({
            "title": role["title"],
            "company": role["company"],
            "location": role["location"],
            "duration": role["dates"],
            "description": lines_to_bullets([lines[n - 1] for n in content[i]]),
            "technologies": [],
        })
    result.experience_lines = len(exp_lines)
    result.claimed_lines = len(exp_lines) - len(leftover)
    result.unassigned = lines_to_bullets([lines[n - 1] for n in leftover])
    result.missed_dated = [
        n
        for n in exp_lines
        if n not in header_lines and _RANGE_RE.search(lines[n - 1]) and not _BULLET_RE.match(lines[n - 1])
    ]
    return result


def _default_client(system_prompt: str, user_prompt: str) -> Any:
    from app.agents.tools.llm_client import llm_call_json_with_metrics

    return llm_call_json_with_metrics(
        system_prompt,
        user_prompt,
        repair_attempts=1,
        validation_attempts=0,
        max_tokens=4096,
    ).data


_NON_EXPERIENCE_KEYS = (
    "name", "email", "phone", "location", "linkedin", "portfolio", "headline", "summary",
    "skills", "skills_by_category", "education", "projects", "certifications", "achievements",
    "languages", "additional_sections",
)


def _flatten(value: Any, out: list[str]) -> None:
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for k, v in value.items():
            if isinstance(k, str):
                out.append(k)
            _flatten(v, out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _flatten(v, out)


def placed_elsewhere(parsed: dict, text: str) -> set[int]:
    """Line numbers the rule parse already put in a non-experience field."""
    pool: list[str] = []
    for key in _NON_EXPERIENCE_KEYS:
        _flatten(parsed.get(key), pool)
    pool_key = _key(" ".join(pool))
    out: set[int] = set()
    for n, line in enumerate(source_lines(text), 1):
        k = _key(_BULLET_RE.sub("", line))
        if len(k) >= 6 and k in pool_key:
            out.add(n)
    return out


def _experience_coverage(parsed: dict, text: str, result: ExtractResult, elsewhere: set[int]) -> float:
    """Share of the model-mapped experience lines that the rule parse placed."""
    lines = source_lines(text)
    exp = [
        n
        for s in result.sections
        if s["type"] == "experience"
        for n in range(s["start"], s["end"] + 1)
        if n not in elsewhere
    ]
    if not exp:
        return 1.0
    pool = " ".join(
        str(v)
        for r in parsed.get("experience") or []
        for v in [r.get("title"), r.get("company"), r.get("duration"), r.get("location"), *(r.get("description") or [])]
        if v
    )
    pool_key = _key(pool)
    hit = sum(1 for n in exp if _key(_BULLET_RE.sub("", lines[n - 1])) and _key(_BULLET_RE.sub("", lines[n - 1])) in pool_key)
    return hit / len(exp)


def _role_quality(roles: list[dict]) -> float:
    if not roles:
        return 0.0
    complete = sum(1 for r in roles if r.get("title") and r.get("company") and r.get("duration"))
    return complete / len(roles)


def _is_lumped(rule_roles: list[dict], result: ExtractResult, rule_cov: float) -> bool:
    """Clearly fewer jobs than a good rule parse: several jobs were merged into one.

    Claiming every line by lumping jobs together also scores full coverage, so coverage
    alone cannot catch it.
    """
    return len(rule_roles) >= 2 and len(result.roles) < 0.75 * len(rule_roles) and rule_cov >= 0.6


def _passes_gate(result: ExtractResult, lumped: bool) -> bool:
    """A read worth keeping without a retry."""
    return (
        bool(result.roles)
        and not lumped
        and result.coverage >= 0.9
        and not result.missed_dated
        and result.rejected_fields <= max(2, len(result.roles) // 2)
    )


def _attempt_score(result: ExtractResult, _rule_cov: float, lumped: bool) -> tuple:
    return (
        bool(result.roles),
        not lumped,
        -len(result.missed_dated),
        round(result.coverage, 2),
        _role_quality(result.roles),
        -result.rejected_fields,
    )


def apply_line_extraction(text: str, parsed: dict, *, client: LineClient | None = None) -> dict:
    """Use the grounded LLM roles when they explain the source better than the rule parse.

    Never raises: any failure returns ``parsed`` unchanged (with the reason in parse_meta).
    """
    started = time.perf_counter()
    meta = dict(parsed.get("parse_meta") or {})
    elsewhere = placed_elsewhere(parsed, text)
    rule_roles = parsed.get("experience") or []
    call = client or _default_client
    max_attempts = max(1, int(getattr(settings, "RESUME_LLM_LINE_EXTRACT_MAX_ATTEMPTS", 2)))

    attempts: list[tuple[ExtractResult, float, bool]] = []
    hints: list[int] | None = None
    for _attempt in range(max_attempts):
        try:
            res = extract_experience(text, call, elsewhere=elsewhere, hints=hints)
        except Exception as exc:  # noqa: BLE001
            res = ExtractResult(error=type(exc).__name__)
        cov = _experience_coverage(parsed, text, res, elsewhere) if res.sections else 1.0
        lumped_try = _is_lumped(rule_roles, res, cov)
        attempts.append((res, cov, lumped_try))
        if res.error.startswith("sections") or _passes_gate(res, lumped_try):
            break  # good enough, or Bedrock unavailable: do not retry
        if not res.roles and not rule_roles and not detect_employment_evidence(text).has_work_history:
            break  # no work history to find (e.g. a student CV)
        hints = res.missed_dated or None
    result, rule_cov, lumped = max(attempts, key=lambda a: _attempt_score(*a))
    if not result.sections and result.error and not result.roles:
        meta["line_extract"] = {"used": False, "error": result.error, "attempts": len(attempts)}
        return {**parsed, "parse_meta": meta}

    info = {
        "used": False,
        "attempts": len(attempts),
        "gate_passed": _passes_gate(result, lumped),
        "missed_dated_lines": len(result.missed_dated),
        "llm_calls": sum(a[0].llm_calls for a in attempts),
        "llm_roles": len(result.roles),
        "rule_roles": len(rule_roles),
        "llm_coverage": round(result.coverage, 3),
        "rule_coverage": round(rule_cov, 3),
        "rejected_fields": result.rejected_fields,
        "unassigned_lines": len(result.unassigned),
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }
    if result.error:
        info["error"] = result.error

    info["lumped"] = lumped
    better = bool(result.roles) and not lumped and (
        not rule_roles
        or result.coverage > rule_cov + 0.02
        or (result.coverage >= rule_cov - 0.02 and _role_quality(result.roles) > _role_quality(rule_roles))
    )
    out = dict(parsed)
    if better:
        out["experience"] = result.roles
        if result.unassigned:
            out["unassigned_experience_bullets"] = result.unassigned
        else:
            out.pop("unassigned_experience_bullets", None)
        info["used"] = True
    info["disagree"] = bool(rule_roles) and abs(len(result.roles) - len(rule_roles)) > max(1, len(rule_roles) // 4)
    meta["line_extract"] = info
    out["parse_meta"] = meta
    logger.info("line_extract_done", **{k: v for k, v in info.items() if k != "error"})
    return out


def enabled() -> bool:
    return bool(getattr(settings, "RESUME_LLM_LINE_EXTRACT", False)) and bool(settings.AWS_BEARER_TOKEN_BEDROCK)
