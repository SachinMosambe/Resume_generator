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
from app.services.output_integrity import BLOCKING, IntegrityReport, list_missing_hard_source_lines
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


def should_recover(report: IntegrityReport, store: dict, source_text: str) -> bool:
    if not recovery_enabled():
        return False
    if hard_source_miss_count(report) > 0 or has_wrong_role(report):
        return True
    if not (store.get("experience") or []) and detect_employment_evidence(source_text).has_work_history:
        return True
    return False


def prefer_recovered(before: IntegrityReport, after: IntegrityReport) -> bool:
    """Keep the recovered output only if it is strictly better and adds no wrong-role finding."""
    if has_wrong_role(after) and not has_wrong_role(before):
        return False
    before_hard, after_hard = hard_source_miss_count(before), hard_source_miss_count(after)
    if after_hard < before_hard:
        return True
    return has_wrong_role(before) and not has_wrong_role(after) and after_hard <= before_hard


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
        "missing_out_estimate": 0,
    }
    started = time.perf_counter()
    try:
        baseline_text = output_text or _store_text(store)
        missing = list_missing_hard_source_lines(source_text, baseline_text, store)
        meta["missing_in"] = len(missing)
        meta["missing_out_estimate"] = len(missing)
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
                return store, meta
        finally:
            pool.shutdown(wait=False)
        meta["llm_calls"] = budget.calls
        meta["llm_roles"] = len(result.roles)

        if result.error:
            meta["error"] = result.error
        if not result.roles:
            meta["error"] = meta["error"] or "no_roles"
            return store, meta

        existing = [r for r in store.get("experience") or [] if isinstance(r, dict)]
        if lle._is_lumped(existing, result, 1.0):
            meta["error"] = "lumped"
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
        if after >= before:
            meta["error"] = meta["error"] or "no_improvement"
            return store, meta

        meta["used"] = True
        return candidate, meta
    except Exception as exc:  # noqa: BLE001 - recovery must never break generation
        meta["error"] = type(exc).__name__
        return store, meta
    finally:
        meta["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        logger.info(
            "integrity_recovery_done",
            **{k: v for k, v in meta.items() if k != "error"},
            error_type=meta["error"] or None,
        )
