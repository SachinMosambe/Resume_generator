"""Production-pipeline retest of the hard corpus resumes.

Loads backend/.env, keeps Bedrock + RESUME_LLM_LINE_EXTRACT on (real prod path).
Does NOT import corpus_quality_eval (that script strips the Bedrock token).
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def _resolve_resume_dir() -> Path:
    """Private corpus may sit next to the nested repo or one level up (Downloads layout)."""
    candidates = [
        REPO / "Sachin resume AI" / "Sachin resume AI",
        REPO.parent / "Sachin resume AI" / "Sachin resume AI",
        REPO / "Sachin resume AI",
        REPO.parent / "Sachin resume AI",
    ]
    for path in candidates:
        if path.is_dir():
            return path
    return candidates[0]


RESUME_DIR = _resolve_resume_dir()
OUT = ROOT / "eval_reports" / "prod_hard_resume_retest.json"
PRIOR = ROOT / "eval_reports" / "hard_resume_retest.json"

# Load production env BEFORE any app import (settings are cached at import time).
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=True)
os.environ["RESUME_OUTPUT_MODE"] = os.environ.get("RESUME_OUTPUT_MODE") or "faithful"
os.environ["RESUME_AGENT_PIPELINE"] = os.environ.get("RESUME_AGENT_PIPELINE") or "false"
os.environ["RESUME_LLM_CONDENSE"] = os.environ.get("RESUME_LLM_CONDENSE") or "false"
os.environ["RESUME_LLM_LINE_EXTRACT"] = "true"
os.environ["RESUME_LLM_PARSE_FALLBACK"] = "true"
# Wave 2 path on for production measurement.
os.environ["RESUME_SOURCE_LEDGER"] = "true"
os.environ["RESUME_RENDER_MANIFEST"] = "true"
os.environ["RESUME_GROUNDED_GROUPING"] = "true"
os.environ["RESUME_CANONICAL_STORE"] = "true"
os.environ["RESUME_ARTIFACT_CACHE"] = "true"

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()
settings = get_settings()

from app.models.candidate import Candidate  # noqa: E402
from app.services.aptino_template import build_aptino_client_format  # noqa: E402
from app.services.llm_line_extractor import enabled as line_extract_enabled  # noqa: E402
from app.services.extraction_adapters import extract_with_adapter  # noqa: E402
from app.services.resume_generation_service import ResumeGenerationService  # noqa: E402


def hard_files() -> list[str]:
    if PRIOR.exists():
        return list(json.loads(PRIOR.read_text(encoding="utf-8")).get("files") or [])
    raise SystemExit(f"Missing prior hard list: {PRIOR}")


def resolve(name: str) -> Path | None:
    """Resolve a hard-list filename, including Windows 'Copy (1)' duplicate names.

    The hard corpus list often keeps ``Foo (1).pdf`` while disk has ``Foo.pdf``.
    """
    direct = RESUME_DIR / name
    if direct.exists():
        return direct
    hits = list(RESUME_DIR.rglob(name))
    if hits:
        return hits[0]
    # Strip trailing " (N)" before the extension: "Resume (1).pdf" → "Resume.pdf"
    stem = Path(name).stem
    suffix = Path(name).suffix
    import re

    alt_stem = re.sub(r"\s*\(\d+\)$", "", stem).strip()
    if alt_stem and alt_stem != stem:
        alt_name = f"{alt_stem}{suffix}"
        alt_direct = RESUME_DIR / alt_name
        if alt_direct.exists():
            return alt_direct
        alt_hits = list(RESUME_DIR.rglob(alt_name))
        if alt_hits:
            return alt_hits[0]
    return None


WRONG_ROLE_CODES = {"bullet_wrong_role", "role_assignment"}


def integrity_flags(report, store: dict) -> dict:
    """Recovery meta + whether blocking source_lines / wrong-role findings remain.

    `meets_bar` = passed OR (needs_review with no blocking source_lines and no wrong-role).
    """
    parse_meta = (store or {}).get("parse_meta") or {}
    rec = parse_meta.get("integrity_recovery") if isinstance(parse_meta, dict) else None
    rec = rec if isinstance(rec, dict) else {}
    warnings = [w for w in (getattr(report, "warnings", None) or []) if isinstance(w, dict)]
    blocking = [w for w in warnings if w.get("severity") == "blocking"]
    blocking_src = any(w.get("code") == "source_lines" for w in blocking)
    wrong_role = any(w.get("code") in WRONG_ROLE_CODES for w in blocking)
    # Wrong-role findings counted regardless of severity too (strict reading of the bar).
    wrong_role_any = any(w.get("code") in WRONG_ROLE_CODES for w in warnings)
    src_check = ((getattr(report, "checks", None) or {}).get("source_lines") or {})
    status = getattr(report, "status", None) if report is not None else None
    meets = status == "passed" or (
        status == "needs_review" and not blocking_src and not wrong_role and not wrong_role_any
    )
    return {
        "integrity_recovery": {
            k: rec.get(k) for k in ("used", "preferred", "error", "calls", "recovered_lines", "reason") if k in rec
        } or rec,
        "recovery_used": bool(rec.get("used")),
        "recovery_preferred": bool(rec.get("preferred")),
        "blocking_source_lines": blocking_src,
        "source_lines_hard": src_check.get("hard"),
        "wrong_role": wrong_role or wrong_role_any,
        "blocking_codes": sorted({str(w.get("code")) for w in blocking}),
        "meets_bar": bool(meets),
    }


def role_bullet_counts(store: dict) -> tuple[int, int]:
    exp = store.get("experience") or []
    if not isinstance(exp, list):
        return 0, 0
    bullets = 0
    for role in exp:
        if not isinstance(role, dict):
            continue
        desc = role.get("description") or role.get("bullets") or []
        if isinstance(desc, list):
            bullets += len(desc)
        elif desc:
            bullets += 1
    return len(exp), bullets


def main() -> int:
    files = hard_files()
    token_present = bool(settings.AWS_BEARER_TOKEN_BEDROCK)
    print("PRODUCTION PIPELINE CHECK")
    print(f"  RESUME_OUTPUT_MODE={settings.RESUME_OUTPUT_MODE}")
    print(f"  RESUME_AGENT_PIPELINE={settings.RESUME_AGENT_PIPELINE}")
    print(f"  RESUME_LLM_LINE_EXTRACT={settings.RESUME_LLM_LINE_EXTRACT}")
    print(f"  RESUME_LLM_PARSE_FALLBACK={settings.RESUME_LLM_PARSE_FALLBACK}")
    print(f"  BEDROCK_MODEL={settings.BEDROCK_MODEL}")
    print(f"  AWS_BEARER_TOKEN_BEDROCK present={token_present}")
    print(f"  line_extract_enabled()={line_extract_enabled()}")
    print(f"  RESUME_SOURCE_LEDGER={getattr(settings, 'RESUME_SOURCE_LEDGER', None)}")
    print(f"  RESUME_RENDER_MANIFEST={getattr(settings, 'RESUME_RENDER_MANIFEST', None)}")
    print(f"  RESUME_GROUNDED_GROUPING={getattr(settings, 'RESUME_GROUNDED_GROUPING', None)}")
    if not line_extract_enabled():
        raise SystemExit("ABORT: production line extract is not enabled (token/flag missing)")

    client_format = build_aptino_client_format("Aptino")
    rows: list[dict] = []
    for i, name in enumerate(files, 1):
        path = resolve(name)
        row: dict = {"file": name}
        if path is None:
            row["stage"] = "missing"
            print(f"[{i}/{len(files)}] MISSING {name}")
            rows.append(row)
            continue

        print(f"[{i}/{len(files)}] {path.name[:70]}")
        t0 = time.perf_counter()
        try:
            extraction = extract_with_adapter(str(path))
            text = extraction.text or ""
            meta = dict(extraction.meta or {})
            meta["extraction_adapter"] = {
                "method": extraction.method,
                "status": extraction.status,
                "limits_ok": extraction.limits_ok,
                "diagnostics": extraction.diagnostics,
            }
            if extraction.ledger is not None:
                meta["source_ledger"] = extraction.ledger.to_dict()
                meta["source_revision"] = extraction.ledger.source_revision
            if not text.strip():
                row.update({"stage": "extract", "error": "no_text", "elapsed_s": round(time.perf_counter() - t0, 2)})
                print("  extract=no_text")
                rows.append(row)
                continue

            cand = Candidate(
                name="Candidate",
                resume_path=str(path),
                extracted_data={
                    "raw_text": text,
                    "resume_text": text,
                    "extraction_meta": meta if isinstance(meta, dict) else {},
                },
            )
            service = ResumeGenerationService()
            data = service.generate(cand, client_format)
            report = getattr(service, "last_report", None)
            store = (cand.extracted_data or {}).get("structured_resume") or {}
            parse_meta = store.get("parse_meta") or (cand.extracted_data or {}).get("parse_meta") or {}
            # Prefer experience living on the store / detailed path used by generate.
            roles, bullets = role_bullet_counts(store)
            if roles == 0:
                # fallback: candidate extracted experience if store shaped differently
                exp = (cand.extracted_data or {}).get("experience")
                if isinstance(exp, list):
                    roles = len(exp)
            line_extract = parse_meta.get("line_extract") if isinstance(parse_meta, dict) else {}
            if not isinstance(line_extract, dict):
                line_extract = {}

            status = getattr(report, "status", None) if report else None
            warnings = []
            if report is not None:
                for w in list(getattr(report, "warnings", []) or [])[:6]:
                    if isinstance(w, dict):
                        warnings.append({"severity": w.get("severity"), "code": w.get("code"), "message": w.get("message")})
                    else:
                        warnings.append({"message": str(w)})

            row.update(
                {
                    "stage": "done",
                    "status": status,
                    "roles": roles,
                    "bullets": bullets,
                    "docx_kb": round(len(data) / 1024, 1),
                    "line_extract": {
                        "used": line_extract.get("used"),
                        "reason": line_extract.get("reason") or line_extract.get("why"),
                        "keys": sorted(line_extract.keys()),
                    },
                    "warnings": warnings,
                    **integrity_flags(report, store),
                    "elapsed_s": round(time.perf_counter() - t0, 2),
                }
            )
            print(
                f"  status={status} roles={roles} bullets={bullets} "
                f"line_extract.used={line_extract.get('used')} "
                f"recovery={row['integrity_recovery']} block_src={row['blocking_source_lines']} "
                f"wrong_role={row['wrong_role']} meets_bar={row['meets_bar']} ({row['elapsed_s']}s)"
            )
        except Exception as exc:  # noqa: BLE001
            row.update(
                {
                    "stage": "error",
                    "error": type(exc).__name__,
                    "error_detail": str(exc)[:240],
                    "traceback": traceback.format_exc().splitlines()[-4:],
                    "elapsed_s": round(time.perf_counter() - t0, 2),
                }
            )
            print(f"  ERROR {row['error']}: {row['error_detail']}")
        rows.append(row)

    status_counts: dict[str, int] = {}
    zero_roles = 0
    line_used = 0
    rec_used = rec_pref = block_src = wrong_role = meets = 0
    for r in rows:
        if r.get("stage") == "done":
            status_counts[str(r.get("status"))] = status_counts.get(str(r.get("status")), 0) + 1
            if not r.get("roles"):
                zero_roles += 1
            if (r.get("line_extract") or {}).get("used"):
                line_used += 1
            rec_used += bool(r.get("recovery_used"))
            rec_pref += bool(r.get("recovery_preferred"))
            block_src += bool(r.get("blocking_source_lines"))
            wrong_role += bool(r.get("wrong_role"))
            meets += bool(r.get("meets_bar"))
    meets_pct = round(100.0 * meets / len(rows), 1) if rows else 0.0

    out = {
        "mode": "production",
        "settings": {
            "RESUME_OUTPUT_MODE": settings.RESUME_OUTPUT_MODE,
            "RESUME_AGENT_PIPELINE": settings.RESUME_AGENT_PIPELINE,
            "RESUME_LLM_LINE_EXTRACT": settings.RESUME_LLM_LINE_EXTRACT,
            "RESUME_LLM_PARSE_FALLBACK": settings.RESUME_LLM_PARSE_FALLBACK,
            "BEDROCK_MODEL": settings.BEDROCK_MODEL,
            "token_present": token_present,
            "line_extract_enabled": line_extract_enabled(),
        },
        "n": len(rows),
        "status_counts": status_counts,
        "zero_role_count": zero_roles,
        "line_extract_used_count": line_used,
        "recovery_used_count": rec_used,
        "recovery_preferred_count": rec_pref,
        "blocking_source_lines_count": block_src,
        "wrong_role_count": wrong_role,
        "meets_bar_count": meets,
        "meets_bar_pct": meets_pct,
        "failing": [r.get("file") for r in rows if not r.get("meets_bar")],
        "rows": rows,
    }
    OUT.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print("Wrote", OUT)
    print(
        f"RESULT production aptino: status_counts={status_counts} "
        f"zero_roles={zero_roles}/{len(rows)} line_extract_used={line_used}/{len(rows)} "
        f"recovery_used={rec_used} recovery_preferred={rec_pref} blocking_source_lines={block_src} "
        f"wrong_role={wrong_role} meets_bar={meets}/{len(rows)} ({meets_pct}%)"
    )
    for r in rows:
        if not r.get("meets_bar"):
            print(f"  FAIL BAR: {r.get('file')} status={r.get('status')} codes={r.get('blocking_codes')} stage={r.get('stage')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
