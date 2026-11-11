"""Optional one-shot LLM structure repair for weak deterministic parses.

The LLM may only *re-arrange* text that already exists in the source resume. Every
company / title / location / date / bullet it returns must be found in the source, and
every bullet must sit inside the source block of the employer it is assigned to.
Anything else rejects the whole repair and the deterministic parse is returned unchanged.

No resume text is logged.
"""
from __future__ import annotations

import copy
import json
import re
import threading
from typing import Any, Callable

from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings
from app.core.logging import logger
from app.services.parse_confidence import score_parse
from app.services.source_evidence import detect_employment_evidence

# client(system_prompt, user_prompt) -> parsed JSON dict (or raw JSON string)
RepairClient = Callable[[str, str], Any]

ELIGIBILITY_CONFIDENCE = 0.55
MAX_SOURCE_CHARS = 48000
_MIN_FACT_CHARS = 2


class _RepairRole(BaseModel):
    title: str = ""
    company: str = ""
    location: str = ""
    duration: str = ""
    description: list[str] = Field(default_factory=list)


class _RepairPayload(BaseModel):
    experience: list[_RepairRole] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------

def _roles(parsed: dict) -> list[dict]:
    return [r for r in (parsed.get("experience") or []) if isinstance(r, dict)]


def is_repair_eligible(source_text: str, parsed: dict) -> bool:
    """True when the deterministic parse is weak AND the source shows work history."""
    if not isinstance(parsed, dict) or not (source_text or "").strip():
        return False
    meta = parsed.get("parse_meta") or {}
    if meta.get("llm_repaired"):
        return False
    evidence = detect_employment_evidence(source_text)
    roles = _roles(parsed)
    if not roles and evidence.has_work_history:
        return True
    if not evidence.has_work_history and not roles:
        return False
    confidence = meta.get("confidence")
    if confidence is None:
        confidence = score_parse(parsed, source_text)["confidence"]
    if float(confidence) < ELIGIBILITY_CONFIDENCE:
        return True
    if roles:
        empty = sum(1 for r in roles if not str(r.get("title") or "").strip())
        reasons = meta.get("reasons")
        if reasons is None:
            reasons = score_parse(parsed, source_text)["reasons"]
        if empty / len(roles) >= 0.5 and "source_backed_titles_unresolved" in reasons:
            return True
    return False


# ---------------------------------------------------------------------------
# Source matching
# ---------------------------------------------------------------------------

def _norm(text: Any) -> str:
    """Casefold, drop everything that is not a letter/digit (survives reflow and bullets)."""
    return re.sub(r"[^0-9a-z]+", "", str(text or "").casefold())


def _positions(haystack: str, needle: str) -> list[int]:
    out: list[int] = []
    if not needle:
        return out
    start = 0
    while True:
        idx = haystack.find(needle, start)
        if idx < 0:
            return out
        out.append(idx)
        start = idx + 1


def _words(text: Any) -> list[str]:
    return re.findall(r"[0-9a-z]+", str(text or "").casefold())


def _duration_in_source(duration: str, source_norm: str, source_words: set[str]) -> bool:
    if not duration.strip():
        return True
    if _norm(duration) in source_norm:
        return True
    words = _words(duration)
    # Dates may be reformatted ("01/2020" -> "Jan 2020"); every token must still exist in source.
    return bool(words) and all(w in source_words for w in words)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _parse_payload(raw: Any) -> _RepairPayload | None:
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip())
        except (ValueError, TypeError):
            return None
    if not isinstance(data, dict) or not isinstance(data.get("experience"), list):
        return None
    for role in data["experience"]:
        if not isinstance(role, dict):
            return None
        for key in ("title", "company", "location", "duration"):
            if role.get(key) is not None and not isinstance(role.get(key), str):
                return None
        desc = role.get("description", [])
        if desc is not None and (
            not isinstance(desc, list) or any(not isinstance(b, str) for b in desc)
        ):
            return None
    try:
        return _RepairPayload.model_validate(data)
    except ValidationError:
        return None


def _validate_repair(
    payload: _RepairPayload, source_text: str, parsed: dict
) -> tuple[list[dict[str, Any]] | None, str]:
    """Return (normalized roles, "") when accepted, else (None, reason)."""
    roles = payload.experience
    if not roles:
        return None, "empty_repair"

    source_norm = _norm(source_text)
    source_words = set(_words(source_text))

    anchors: list[tuple[int, int]] = []  # (position, role index)
    role_positions: list[list[int]] = []
    for i, role in enumerate(roles):
        company = role.company.strip()
        title = role.title.strip()
        if not company and not title:
            return None, "role_without_identity"
        for label, value in (("company", company), ("title", title), ("location", role.location.strip())):
            if not value:
                continue
            key = _norm(value)
            if len(key) < _MIN_FACT_CHARS or key not in source_norm:
                return None, f"{label}_not_in_source"
        if not _duration_in_source(role.duration, source_norm, source_words):
            return None, "duration_not_in_source"
        anchor_key = _norm(company or title)
        positions = _positions(source_norm, anchor_key)
        if not positions:
            return None, "anchor_not_in_source"
        role_positions.append(positions)
        anchors.extend((p, i) for p in positions)

    anchors.sort()
    anchor_points = [p for p, _ in anchors]

    def block_end(start: int) -> int:
        for p in anchor_points:
            if p > start:
                return p
        return len(source_norm) + 1

    for i, role in enumerate(roles):
        blocks = [(p, block_end(p)) for p in role_positions[i]]
        for bullet in role.description:
            key = _norm(bullet)
            if not key:
                continue
            if len(key) < _MIN_FACT_CHARS:
                return None, "bullet_not_in_source"
            hits = _positions(source_norm, key)
            if not hits:
                return None, "bullet_not_in_source"
            # The bullet text may legitimately start inside the header block; require
            # it to sit under THIS role's employer, not another role's.
            if not any(start <= h < end for h in hits for start, end in blocks):
                return None, "bullet_wrong_employer"

    # Existing verified facts must survive.
    repaired_by_company: dict[str, list[_RepairRole]] = {}
    for role in roles:
        repaired_by_company.setdefault(_norm(role.company or role.title), []).append(role)
    for old in _roles(parsed):
        old_company = _norm(old.get("company"))
        old_title = _norm(old.get("title"))
        key = old_company or old_title
        if not key:
            continue
        matches = repaired_by_company.get(key)
        if not matches:
            return None, "existing_role_dropped"
        if old_title and old_company and not any(_norm(m.title) == old_title for m in matches):
            return None, "existing_title_changed"
        pool = {_norm(b) for m in matches for b in m.description}
        for bullet in old.get("description") or []:
            if _norm(bullet) and _norm(bullet) not in pool:
                return None, "existing_bullet_dropped"

    normalized = [
        {
            "title": r.title.strip(),
            "company": r.company.strip(),
            "location": r.location.strip(),
            "duration": r.duration.strip(),
            "description": [b.strip() for b in r.description if b.strip()],
            "technologies": [],
        }
        for r in roles
    ]
    return normalized, ""


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You repair the STRUCTURE of the work-experience section of a resume. "
    "Copy text exactly as written in the source. Never invent, paraphrase, translate, "
    "merge or summarize. Never add a company, title, date, location or bullet that is not "
    "in the source. Put each bullet under the employer whose block it appears in. "
    "If you are unsure of a field, return an empty string for it. "
    "Return ONLY one JSON object: "
    '{"experience":[{"title":"","company":"","location":"","duration":"","description":["..."]}]}'
)


def _build_user_prompt(source_text: str, parsed: dict) -> str:
    current = [
        {
            "title": r.get("title") or "",
            "company": r.get("company") or "",
            "location": r.get("location") or "",
            "duration": r.get("duration") or "",
            "description": list(r.get("description") or []),
        }
        for r in _roles(parsed)
    ]
    unassigned = list(parsed.get("unassigned_experience_bullets") or [])
    return (
        "Current draft (may be incomplete or wrong; keep every correct role and bullet):\n"
        f"{json.dumps({'experience': current, 'unassigned_bullets': unassigned}, ensure_ascii=False)}\n\n"
        "SOURCE RESUME TEXT:\n"
        f"{source_text}\n"
    )


def _default_client(system_prompt: str, user_prompt: str) -> Any:
    """One Bedrock call, no JSON/validation retry loops, bounded by a wall-clock timeout."""
    from app.agents.tools.llm_client import llm_call_json_with_metrics

    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["data"] = llm_call_json_with_metrics(
                system_prompt,
                user_prompt,
                repair_attempts=0,
                validation_attempts=0,
                max_tokens=settings.RESUME_GENERATION_MAX_TOKENS,
            ).data
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller as unavailable
            box["error"] = exc

    thread = threading.Thread(target=run, name="llm-structure-repair", daemon=True)
    thread.start()
    thread.join(timeout=float(settings.RESUME_LLM_PARSE_TIMEOUT_SECONDS))
    if thread.is_alive():
        raise TimeoutError("llm_structure_repair_timeout")
    if "error" in box:
        raise box["error"]
    return box.get("data")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def maybe_repair_parse(
    source_text: str,
    parsed: dict,
    *,
    client: RepairClient | None = None,
) -> dict:
    """Return a repaired parse dict, or ``parsed`` itself when ineligible / rejected.

    ``parse_meta.llm_repaired`` is set to True only when a repair was accepted.
    The caller is responsible for invoking this at most once per generation.
    """
    if not is_repair_eligible(source_text, parsed):
        return parsed
    if len(source_text) > MAX_SOURCE_CHARS:
        logger.info("llm_structure_repair_skipped", reason="source_too_large")
        return parsed

    call = client or _default_client
    try:
        raw = call(_SYSTEM_PROMPT, _build_user_prompt(source_text, parsed))
    except Exception as exc:  # noqa: BLE001 - never block generation
        logger.warning("llm_structure_repair_unavailable", error_type=type(exc).__name__)
        return parsed

    payload = _parse_payload(raw)
    if payload is None:
        logger.warning("llm_structure_repair_rejected", reason="schema_invalid")
        return parsed
    roles, reason = _validate_repair(payload, source_text, parsed)
    if roles is None:
        logger.warning("llm_structure_repair_rejected", reason=reason)
        return parsed

    repaired = copy.deepcopy(parsed)
    previous_meta = dict(parsed.get("parse_meta") or {})
    repaired["experience"] = roles

    # Bullets the deterministic parse could not place stay in review unless the repair used them.
    placed = {_norm(b) for r in roles for b in r["description"]}
    leftover = [
        b for b in (parsed.get("unassigned_experience_bullets") or []) if _norm(b) not in placed
    ]
    if leftover:
        repaired["unassigned_experience_bullets"] = leftover
    else:
        repaired.pop("unassigned_experience_bullets", None)

    meta = score_parse(repaired, source_text)
    meta["llm_repaired"] = True
    if previous_meta.get("confidence") is not None:
        meta["pre_repair_confidence"] = previous_meta["confidence"]
    repaired["parse_meta"] = meta
    logger.info("llm_structure_repair_accepted", roles=len(roles))
    return repaired
