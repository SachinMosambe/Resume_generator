"""Production-pipeline fidelity sample over the resume corpus (Bedrock + recovery ON).

Does NOT import corpus_quality_eval (it strips the Bedrock token at import). The
stratified picker is copied here. Reuses `integrity_flags` from prod_hard_resume_retest
(which loads backend/.env with production LLM + integrity recovery enabled).

Usage: python scripts/prod_corpus_fidelity_sample.py [--limit 60] [--format aptino]
Meeting bar: status == passed OR (needs_review without blocking source_lines and
without wrong-role/bullet_wrong_role).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prod_hard_resume_retest as base  # noqa: E402  (loads .env, prod settings; main() is guarded)

from app.models.candidate import Candidate  # noqa: E402
from app.services.aptino_template import build_aptino_client_format  # noqa: E402
from app.services.pdf_parser import extract_document  # noqa: E402
from app.services.resume_generation_service import ResumeGenerationService  # noqa: E402
import app.services.resume_generation_service as rgs  # noqa: E402

rgs.upload_bytes_to_key = lambda **kwargs: None  # type: ignore[assignment]  # no S3 writes

RESUME_DIR = base.RESUME_DIR
OUT_DIR = base.ROOT / "eval_reports"
SKIP_NAME = re.compile(
    r"(?i)(travel history|i94|passport|ssn|w2|offer letter|aptino - executive|"
    r"capgemini-format|format\.docx|format\.doc$|\.exe$|zoom_|install)"
)
RESUME_EXT = {".pdf", ".docx", ".doc"}


def pick_resumes(limit: int) -> list[Path]:
    """Copy of corpus_quality_eval.pick_resumes (same stratified selection)."""
    files = [
        p
        for p in RESUME_DIR.iterdir()
        if p.is_file()
        and p.suffix.lower() in RESUME_EXT
        and not SKIP_NAME.search(p.name)
        and "Aptino" not in p.name
        and "Capgemini" not in p.name
    ]
    seen: set[str] = set()
    unique: list[Path] = []
    for p in sorted(files, key=lambda x: (x.suffix.lower(), -x.stat().st_size, x.name.lower())):
        stem = re.sub(r"\s*\(\d+\)\s*$", "", p.stem).strip().lower()
        key = f"{stem}{p.suffix.lower()}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)

    by_ext: dict[str, list[Path]] = defaultdict(list)
    for p in unique:
        by_ext[p.suffix.lower()].append(p)

    picked: list[Path] = []
    quotas = {
        ".pdf": max(1, int(limit * 0.45)),
        ".docx": max(1, int(limit * 0.45)),
        ".doc": max(0, limit - int(limit * 0.45) - int(limit * 0.45)),
    }
    for ext, quota in quotas.items():
        pool = by_ext.get(ext, [])
        if not pool:
            continue
        n = min(quota, len(pool))
        idxs = [0] if n == 1 else sorted({int(i * (len(pool) - 1) / (n - 1)) for i in range(n)})
        for i in idxs:
            picked.append(pool[i])
    for p in [p for p in unique if p not in picked]:
        if len(picked) >= limit:
            break
        picked.append(p)
    return picked[:limit]


def file_id(path: Path) -> str:
    h = hashlib.sha1(path.name.encode("utf-8", errors="ignore")).hexdigest()[:8]
    return f"{path.suffix.lower()[1:]}-{h}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--out", default=str(OUT_DIR / "prod_corpus_fidelity_sample.json"))
    args = ap.parse_args()

    settings = base.settings
    if not base.line_extract_enabled():
        raise SystemExit("ABORT: production line extract is not enabled (token/flag missing)")
    print(
        f"PRODUCTION: token={bool(settings.AWS_BEARER_TOKEN_BEDROCK)} "
        f"line_extract={settings.RESUME_LLM_LINE_EXTRACT} recovery={settings.RESUME_INTEGRITY_RECOVERY}"
    )

    files = pick_resumes(args.limit)
    client_format = build_aptino_client_format("Aptino")
    out_path = Path(args.out)
    rows: list[dict] = []
    print(f"Sampling {len(files)} resumes (aptino)")

    def summarize() -> dict:
        done = [r for r in rows if r.get("stage") == "done"]
        counts: dict[str, int] = {}
        for r in done:
            counts[str(r.get("status"))] = counts.get(str(r.get("status")), 0) + 1
        meets = sum(1 for r in rows if r.get("meets_bar"))
        return {
            "mode": "production",
            "format": "aptino",
            "n_target": len(files),
            "n_run": len(rows),
            "status_counts": counts,
            "errors": sum(1 for r in rows if r.get("stage") in {"error", "extract"}),
            "zero_role_count": sum(1 for r in done if not r.get("roles")),
            "recovery_used_count": sum(1 for r in done if r.get("recovery_used")),
            "recovery_preferred_count": sum(1 for r in done if r.get("recovery_preferred")),
            "blocking_source_lines_count": sum(1 for r in done if r.get("blocking_source_lines")),
            "wrong_role_count": sum(1 for r in done if r.get("wrong_role")),
            "meets_bar_count": meets,
            "meets_bar_pct": round(100.0 * meets / len(rows), 1) if rows else 0.0,
            "failing": [{"id": r["id"], "file": r["file"], "status": r.get("status"),
                         "stage": r.get("stage"), "codes": r.get("blocking_codes")}
                        for r in rows if not r.get("meets_bar")],
            "rows": rows,
        }

    for i, path in enumerate(files, 1):
        row: dict = {"id": file_id(path), "file": path.name, "ext": path.suffix.lower()}
        print(f"[{i}/{len(files)}] {path.name[:70]}", flush=True)
        t0 = time.perf_counter()
        try:
            text, meta = extract_document(str(path))
            text = text or ""
            if not text.strip():
                row.update({"stage": "extract", "error": "no_text", "meets_bar": False})
                print("  extract=no_text", flush=True)
            else:
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
                service.generate(cand, client_format)
                report = getattr(service, "last_report", None)
                store = (cand.extracted_data or {}).get("structured_resume") or {}
                roles, bullets = base.role_bullet_counts(store)
                row.update(
                    {
                        "stage": "done",
                        "status": getattr(report, "status", None) if report else None,
                        "roles": roles,
                        "bullets": bullets,
                        **base.integrity_flags(report, store),
                    }
                )
                print(
                    f"  status={row['status']} roles={roles} rec_used={row['recovery_used']} "
                    f"block_src={row['blocking_source_lines']} wrong_role={row['wrong_role']} "
                    f"meets_bar={row['meets_bar']}",
                    flush=True,
                )
        except Exception as exc:  # noqa: BLE001
            row.update({"stage": "error", "error": type(exc).__name__, "error_detail": str(exc)[:200],
                        "traceback": traceback.format_exc().splitlines()[-3:], "meets_bar": False})
            print(f"  ERROR {row['error']}: {row['error_detail']}", flush=True)
        row["elapsed_s"] = round(time.perf_counter() - t0, 2)
        rows.append(row)
        out_path.write_text(json.dumps(summarize(), indent=2, default=str), encoding="utf-8")  # incremental

    s = summarize()
    print(
        f"RESULT production aptino n={s['n_run']}: status_counts={s['status_counts']} errors={s['errors']} "
        f"zero_roles={s['zero_role_count']} recovery_used={s['recovery_used_count']} "
        f"blocking_source_lines={s['blocking_source_lines_count']} wrong_role={s['wrong_role_count']} "
        f"meets_bar={s['meets_bar_count']}/{s['n_run']} ({s['meets_bar_pct']}%)"
    )
    for f in s["failing"]:
        print(f"  FAIL BAR: {f['id']} {f['file'][:60]} status={f['status']} stage={f['stage']} codes={f['codes']}")
    print("Wrote", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
