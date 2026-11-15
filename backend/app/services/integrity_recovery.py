"""Grounded recovery for resumes whose generated output dropped source content.

When the integrity check finds fact-bearing source lines missing from the output (or a
bullet under the wrong role, or no roles at all despite work history), the missing line
numbers are fed back to the grounded line extractor. The extractor never writes text: it
answers with line numbers and code copies the source. This module only decides whether to
try, runs that extractor under call/time caps, and swaps its roles into the store when
they demonstrably cover more of the source. Nothing here invents or rewrites text.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any

from app.core.config import settings
from app.core.logging import logger
from app.services import llm_line_extractor as lle
from app.services.output_integrity import (
    BLOCKING,
    IntegrityReport,
    list_misassigned_bullet_texts,
    list_missing_hard_source_lines,
)
from app.services.output_integrity import _norm as _oi_norm
from app.services.source_evidence import detect_employment_evidence

_WRONG_ROLE_CODES = {"bullet_wrong_role", "role_assignment"}
_IGNORED_STORE_KEYS = {"raw_text", "parse_meta"}


def recovery_enabled() -> bool:
    return bool(getattr(settings, "RESUME_INTEGRITY_RECOVERY", False)) and bool(
        getattr(settings, "AWS_BEARER_TOKEN_BEDROCK", "")
    )


def hard_source_miss_count(report: IntegrityReport) -> int:
    return int(((report.checks or {}).get("source_lines") or {}).get("hard") or 0)


def has_wrong_role(report: IntegrityReport) -> bool:
    return any(
        w.get("severity") == BLOCKING and w.get("code") in _WRONG_ROLE_CODES
        for w in (report.warnings or [])
        if isinstance(w, dict)
    )


def _bullets_missing(report: IntegrityReport) -> bool:
    check = (report.checks or {}).get("bullets") or {}
    if check.get("ok") is False:
        return True
    return any(
        isinstance(w, dict) and w.get("severity") == BLOCKING and w.get("code") == "bullets_missing"
        for w in (report.warnings or [])
    )


def should_recover(report: IntegrityReport, store: dict, source_text: str) -> bool:
    if not recovery_enabled():
        return False
    if hard_source_miss_count(report) > 0 or has_wrong_role(report) or _bullets_missing(report):
        return True
    if not (store.get("experience") or []) and detect_employment_evidence(source_text).has_work_history:
        return True
    return False


def _bullets_found(report: IntegrityReport) -> int:
    return int(((report.checks or {}).get("bullets") or {}).get("found") or 0)


def prefer_recovered(before: IntegrityReport, after: IntegrityReport) -> bool:
    """Keep the recovered output only if it is strictly better and adds no wrong-role finding."""
    if has_wrong_role(after) and not has_wrong_role(before):
        return False
    before_hard, after_hard = hard_source_miss_count(before), hard_source_miss_count(after)
    if after_hard < before_hard:
        return True
    if has_wrong_role(before) and not has_wrong_role(after) and after_hard <= before_hard:
        return True
    # More store bullets landed in the DOCX without raising hard misses / wrong-role.
    if after_hard <= before_hard and _bullets_found(after) > _bullets_found(before):
        return True
    return False


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------

def _store_text(store: dict) -> str:
    """All text values of the store (except raw source and metadata), one per line."""
    out: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, (list, tuple)):
            for v in value:
                walk(v)

    for key, value in store.items():
        if key not in _IGNORED_STORE_KEYS:
            walk(value)
    return "\n".join(out)


class _Budget:
    """Wraps the model client: counts calls and refuses calls past the cap or deadline."""

    def __init__(self, call: lle.LineClient, max_calls: int, timeout: float) -> None:
        self._call = call
        self._max_calls = max_calls
        self._deadline = time.monotonic() + timeout
        self._lock = threading.Lock()
        self.calls = 0

    def __call__(self, system_prompt: str, user_prompt: str) -> Any:
        with self._lock:
            if self.calls >= self._max_calls:
                raise RuntimeError("call_cap")
            if time.monotonic() >= self._deadline:
                raise TimeoutError("recovery_timeout")
            self.calls += 1
        return self._call(system_prompt, user_prompt)


def _line_numbers(lines: list[str], missing: list[str]) -> list[int]:
    wanted = {m.strip() for m in missing}
    return [n for n, line in enumerate(lines, 1) if line in wanted]


def _experience_corpus(store: dict) -> str:
    """Text that must carry experience/cert content — not skills (false matches)."""
    parts: list[str] = []
    for role in store.get("experience") or []:
        if not isinstance(role, dict):
            continue
        for key in ("company", "title", "duration", "location"):
            if role.get(key):
                parts.append(str(role.get(key)))
        for bullet in role.get("description") or []:
            parts.append(str(bullet))
    for bullet in store.get("unassigned_experience_bullets") or []:
        parts.append(str(bullet))
    for cert in store.get("certifications") or []:
        parts.append(str(cert))
    return "\n".join(parts)


def _already_in_store(store: dict, line: str) -> bool:
    needle = lle._key(lle._BULLET_RE.sub("", line))
    if len(needle) < 12:
        return True
    hay = lle._key(_experience_corpus(store))
    return needle in hay


def list_missing_store_bullets(store: dict, output_text: str) -> list[str]:
    """Store experience bullets whose normalized text is absent from the DOCX haystack."""
    from app.services.output_integrity import _norm

    hay = _norm(output_text or "")
    missing: list[str] = []
    for role in store.get("experience") or []:
        if not isinstance(role, dict):
            continue
        for bullet in role.get("description") or []:
            if not isinstance(bullet, str) or not bullet.strip():
                continue
            n = _norm(bullet)
            if len(n.split()) < 5:
                continue
            if n not in hay:
                missing.append(bullet.strip())
    return list(dict.fromkeys(missing))


def ensure_missing_lines_in_unassigned(store: dict, missing_lines: list[str]) -> dict:
    """Copy missing source lines into unassigned verbatim (render-complete path).

    Uses exact source wording so integrity ``source_lines`` 4-grams can match the DOCX.
    Always copies DOCX-hard-miss lines even when a role already holds a shortened or
    re-punctuated form — store presence does not guarantee DOCX 4-gram coverage
    (common for ``Environment:`` tool rows). Only skips URLs and unassigned dupes.
    """
    prior = [str(x) for x in (store.get("unassigned_experience_bullets") or []) if str(x).strip()]
    prior_keys = {lle._key(x) for x in prior if lle._key(x)}
    cleaned = lle.lines_to_bullets(list(missing_lines or []))
    to_add: list[str] = []
    for text in cleaned:
        if not text:
            continue
        low = text.strip().lower()
        if low.startswith(("http://", "https://", "www.", "mailto:")):
            continue
        k = lle._key(text)
        if len(k) < 12 or k in prior_keys:
            continue
        # Unassigned already has a longer/shorter form of this line.
        if any(k in pk or pk in k for pk in prior_keys if len(pk) >= 12):
            continue
        to_add.append(text)
        prior_keys.add(k)
    if not to_add:
        return store
    candidate = dict(store)
    candidate["unassigned_experience_bullets"] = list(dict.fromkeys([*prior, *to_add]))
    return candidate


def repair_wrong_role_assignments(store: dict, output_text: str) -> tuple[dict, dict]:
    """Move bullets that appear under the wrong employer in the DOCX into unassigned.

    Deterministic: copies existing bullet text only. Clearing ownership under the
    mis-rendered role removes the ``bullet_wrong_role`` integrity finding so a
    re-render can place them under the review placeholder instead.
    """
    meta: dict[str, Any] = {"used": False, "moved": 0, "method": "wrong_role_repair", "error": ""}
    roles = [r for r in (store.get("experience") or []) if isinstance(r, dict)]
    if len(roles) < 2 or not (output_text or "").strip():
        return store, meta
    # Integrity compares against normalized DOCX hay; match that here.
    wrong = set(list_misassigned_bullet_texts(roles, _oi_norm(output_text)))
    if not wrong:
        return store, meta

    moved: list[str] = []
    new_roles: list[dict] = []
    for role in roles:
        keep: list[str] = []
        for bullet in role.get("description") or []:
            if not isinstance(bullet, str):
                continue
            if _oi_norm(bullet) in wrong:
                moved.append(bullet)
            else:
                keep.append(bullet)
        new_roles.append({**role, "description": keep})
    if not moved:
        return store, meta

    candidate = dict(store)
    candidate["experience"] = new_roles
    prior = [str(x) for x in (candidate.get("unassigned_experience_bullets") or []) if str(x).strip()]
    candidate["unassigned_experience_bullets"] = list(dict.fromkeys([*prior, *moved]))
    meta["used"] = True
    meta["moved"] = len(moved)
    return candidate, meta


def stitch_missing_hard_lines(
    source_text: str, store: dict, output_text: str
) -> tuple[dict, dict]:
    """Deterministic recovery: append missing hard source lines into unassigned.

    No LLM. Copies source text only. Used when Gemma recovery cannot cover the miss
    (common ``no_improvement`` path) so a re-render can put the lines in the DOCX.
    """
    meta: dict[str, Any] = {"used": False, "stitched": 0, "method": "stitch", "error": ""}
    missing = list_missing_hard_source_lines(source_text, output_text or "", store)
    if not missing:
        return store, meta

    candidate = ensure_missing_lines_in_unassigned(store, missing)
    added = len(candidate.get("unassigned_experience_bullets") or []) - len(
        store.get("unassigned_experience_bullets") or []
    )
    if added > 0:
        meta["used"] = True
        meta["stitched"] = added
        return candidate, meta

    # Exact lines already in the store (or unassigned) but missing from DOCX → re-render.
    if missing:
        meta["used"] = True
        meta["method"] = "rerender"
        meta["stitched"] = 0
        meta["force_rerender"] = True
        return dict(store), meta

    meta["error"] = "nothing_to_stitch"
    return store, meta


def _carry_extras(recovered: list[dict], existing: list[dict]) -> list[dict]:
    """Keep fields the extractor does not produce (e.g. technologies) for the same role."""
    by_id = {
        (lle._key(r.get("company")), lle._key(r.get("title"))): r
        for r in existing
        if isinstance(r, dict)
    }
    merged = []
    for role in recovered:
        old = by_id.get((lle._key(role.get("company")), lle._key(role.get("title"))))
        if old and old.get("technologies") and not role.get("technologies"):
            role = {**role, "technologies": list(old["technologies"])}
        merged.append(role)
    return merged


def recover_store(
    source_text: str,
    store: dict,
    report: IntegrityReport,
    output_text: str = "",
    *,
    client: lle.LineClient | None = None,
) -> tuple[dict, dict]:
    """Return ``(new_store, meta)``; ``new_store is store`` unless recovery was used.

    Missing hard source lines (against ``output_text``, or the store's own text when it is
    empty) become line-number hints for the grounded extractor. Its roles replace the
    store's experience only when they cover more of the source.
    """
    meta: dict[str, Any] = {
        "used": False,
        "llm_calls": 0,
        "error": "",
        "missing_in": 0,
        "missing_out_estimate": None,
    }
    started = time.perf_counter()
    budget: _Budget | None = None
    try:
        baseline_text = output_text or _store_text(store)
        missing = list_missing_hard_source_lines(source_text, baseline_text, store)
        meta["missing_in"] = len(missing)
        hints = _line_numbers(lle.source_lines(source_text), missing) or None

        max_calls = max(1, int(getattr(settings, "RESUME_INTEGRITY_RECOVERY_MAX_CALLS", 4)))
        timeout = float(getattr(settings, "RESUME_INTEGRITY_RECOVERY_TIMEOUT_SECONDS", 45.0))
        budget = _Budget(client or lle._default_client, max_calls, timeout)
        elsewhere = lle.placed_elsewhere(store, source_text)

        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(lle.extract_experience, source_text, budget, elsewhere=elsewhere, hints=hints)
            try:
                result = future.result(timeout=timeout)
            except FutureTimeout:
                meta["error"] = "timeout"
                meta["llm_calls"] = budget.calls
                return store, meta
        finally:
            pool.shutdown(wait=False)
        meta["llm_calls"] = budget.calls
        meta["llm_roles"] = len(result.roles)

        # Partial or failed extractions are never accepted.
        if result.error:
            meta["error"] = result.error
            return store, meta
        if not result.roles:
            meta["error"] = "no_roles"
            return store, meta

        existing = [r for r in store.get("experience") or [] if isinstance(r, dict)]
        if lle._is_lumped(existing, result, 1.0):
            meta["error"] = "lumped"
            return store, meta

        # Never drop a role the store already had: every prior company must survive.
        recovered_companies = {lle._key(r.get("company")) for r in result.roles if isinstance(r, dict)}
        prior_companies = {lle._key(r.get("company")) for r in existing} - {""}
        if prior_companies - recovered_companies:
            meta["error"] = "dropped_company"
            return store, meta

        candidate = dict(store)
        candidate["experience"] = _carry_extras(result.roles, existing)
        if result.unassigned:
            candidate["unassigned_experience_bullets"] = result.unassigned
        else:
            candidate.pop("unassigned_experience_bullets", None)

        before = len(list_missing_hard_source_lines(source_text, _store_text(store), store))
        after = len(list_missing_hard_source_lines(source_text, _store_text(candidate), candidate))
        meta["missing_out_estimate"] = after
        # Wrong-role / zero-role cases are not measurable by store-text line coverage;
        # accept the grounded candidate and let the caller's post-render
        # ``prefer_recovered`` decide. The source-lines-only path needs a real drop.
        text_unmeasurable = has_wrong_role(report) or (
            not existing and detect_employment_evidence(source_text).has_work_history
        )
        if not text_unmeasurable and after >= before:
            # LLM did not cover more source text — stitch missing lines into unassigned.
            stitched, stitch_meta = stitch_missing_hard_lines(source_text, store, baseline_text)
            if stitch_meta.get("used"):
                out = {**meta, **stitch_meta, "llm_error": "no_improvement"}
                out["error"] = ""
                return stitched, out
            meta["error"] = "no_improvement"
            return store, meta

        meta["used"] = True
        return candidate, meta
    except Exception as exc:  # noqa: BLE001 - recovery must never break generation
        meta["error"] = type(exc).__name__
        if budget is not None:
            meta["llm_calls"] = budget.calls
        return store, meta
    finally:
        meta["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        logger.info(
            "integrity_recovery_done",
            **{k: v for k, v in meta.items() if k != "error"},
            error_type=meta["error"] or None,
        )
