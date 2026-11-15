"""Production holdout eval: generate full Aptino resumes on *unseen* corpus files.

Excludes hard-set + prior fidelity-sample filenames so the run measures
generalization, not memorized eval cases. Writes DOCX artifacts + JSON report.
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
import prod_hard_resume_retest as base  # noqa: E402  (loads .env + prod settings)

from app.models.candidate import Candidate  # noqa: E402
from app.services.aptino_template import build_aptino_client_format  # noqa: E402
from app.services.extraction_adapters import extract_with_adapter  # noqa: E402
from app.services.resume_generation_service import ResumeGenerationService  # noqa: E402
import app.services.resume_generation_service as rgs  # noqa: E402

RESUME_DIR = base.RESUME_DIR
OUT_DIR = base.ROOT / "eval_reports"
DOCX_DIR = OUT_DIR / "unseen_holdout_docx"
HARD_LIST = base.ROOT / "eval_reports" / "hard_resume_retest.json"
PRIOR_CORPUS = base.ROOT / "eval_reports" / "prod_corpus_fidelity_sample.json"

SKIP_NAME = re.compile(
    r"(?i)(travel\s*hist(?:ory|roy)|i[-\s]?94|i[-\s]?797|notice\s*of\s*action|passport|ssn|w[-\s]?2|"
    r"offer letter|aptino - executive|capgemini-format|format\.docx|format\.doc$|\.exe$|zoom_|install)"
)
RESUME_EXT = {".pdf", ".docx", ".doc"}
_DUP_SUFFIX = re.compile(r"\s*\(\d+\)\s*$")


def _canon_name(name: str) -> str:
    p = Path(name)
    stem = _DUP_SUFFIX.sub("", p.stem).strip().lower()
    return f"{stem}{p.suffix.lower()}"


def previously_tested() -> set[str]:
    names: set[str] = set()
    if HARD_LIST.exists():
        for f in json.loads(HARD_LIST.read_text(encoding="utf-8")).get("files") or []:
            names.add(_canon_name(str(f)))
    if PRIOR_CORPUS.exists():
        data = json.loads(PRIOR_CORPUS.read_text(encoding="utf-8"))
        for row in data.get("rows") or []:
            if row.get("file"):
                names.add(_canon_name(str(row["file"])))
        for row in data.get("failing") or []:
            if isinstance(row, dict) and row.get("file"):
                names.add(_canon_name(str(row["file"])))
            elif isinstance(row, str):
                names.add(_canon_name(row))
    return names


def pick_unseen(limit: int, seed: str = "unseen-holdout-v1") -> list[Path]:
    tested = previously_tested()
    files = [
        p
        for p in RESUME_DIR.iterdir()
        if p.is_file()
        and p.suffix.lower() in RESUME_EXT
        and not SKIP_NAME.search(p.name)
        and "Aptino" not in p.name
        and "Capgemini" not in p.name
        and _canon_name(p.name) not in tested
    ]
    seen: set[str] = set()
    unique: list[Path] = []
    for p in sorted(files, key=lambda x: (x.suffix.lower(), -x.stat().st_size, x.name.lower())):
        key = _canon_name(p.name)
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)

    by_ext: dict[str, list[Path]] = defaultdict(list)
    for p in unique:
        by_ext[p.suffix.lower()].append(p)

    # Stable shuffle within each ext using seed hash offsets.
    def seeded(pool: list[Path]) -> list[Path]:
        ranked = sorted(
            pool,
            key=lambda p: hashlib.sha1(f"{seed}:{p.name}".encode()).hexdigest(),
        )
        return ranked

    quotas = {
        ".pdf": max(1, int(limit * 0.45)),
        ".docx": max(1, int(limit * 0.45)),
        ".doc": max(0, limit - int(limit * 0.45) - int(limit * 0.45)),
    }
    picked: list[Path] = []
    for ext, quota in quotas.items():
        pool = seeded(by_ext.get(ext, []))
        for p in pool[:quota]:
            picked.append(p)
    for p in seeded(unique):
        if len(picked) >= limit:
            break
        if p not in picked:
            picked.append(p)
    return picked[:limit]


def file_id(path: Path) -> str:
    h = hashlib.sha1(path.name.encode("utf-8", errors="ignore")).hexdigest()[:8]
    return f"{path.suffix.lower()[1:]}-{h}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--save-docx", action="store_true", default=True)
    ap.add_argument("--out", default=str(OUT_DIR / "prod_unseen_holdout.json"))
    args = ap.parse_args()

    if not base.line_extract_enabled():
        raise SystemExit("ABORT: production line extract is not enabled")

    # Keep local DOCX; skip S3.
    rgs.upload_bytes_to_key = lambda **kwargs: None  # type: ignore[assignment]

    tested_n = len(previously_tested())
    files = pick_unseen(args.limit)
    print(
        f"UNSEEN HOLDOUT production aptino: limit={args.limit} picked={len(files)} "
        f"excluded_prior={tested_n} dir={RESUME_DIR}"
    )
    print(
        f"  recovery={base.settings.RESUME_INTEGRITY_RECOVERY} "
        f"line_extract={base.settings.RESUME_LLM_LINE_EXTRACT} "
        f"ledger={getattr(base.settings, 'RESUME_SOURCE_LEDGER', None)}"
    )

    if args.save_docx:
        DOCX_DIR.mkdir(parents=True, exist_ok=True)

    client_format = build_aptino_client_format("Aptino")
    rows: list[dict] = []

    for i, path in enumerate(files, 1):
        rid = file_id(path)
        row: dict = {
            "id": rid,
            "file": path.name,
            "ext": path.suffix.lower(),
            "stage": "start",
            "meets_bar": False,
        }
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
                row.update(
                    {
                        "stage": "extract",
                        "error": "no_text",
                        "elapsed_s": round(time.perf_counter() - t0, 2),
                    }
                )
                print("  extract=no_text")
                rows.append(row)
                continue

            cand = Candidate(
                name="Candidate",
                resume_path=str(path),
                extracted_data={
                    "raw_text": text,
                    "resume_text": text,
                    "extraction_meta": meta,
                },
            )
            service = ResumeGenerationService()
            data = service.generate(cand, client_format)
            report = getattr(service, "last_report", None)
            store = (cand.extracted_data or {}).get("structured_resume") or {}
            roles, bullets = base.role_bullet_counts(store)
            flags = base.integrity_flags(report, store)

            docx_path = None
            if args.save_docx and data:
                safe = re.sub(r"[^\w.\-]+", "_", path.stem)[:80]
                docx_path = DOCX_DIR / f"{rid}_{safe}_Aptino.docx"
                docx_path.write_bytes(data)

            status = getattr(report, "status", None) if report else None
            warnings = []
            if report is not None:
                for w in list(getattr(report, "warnings", []) or [])[:8]:
                    if isinstance(w, dict):
                        warnings.append(
                            {
                                "severity": w.get("severity"),
                                "code": w.get("code"),
                                "message": w.get("message"),
                            }
                        )

            row.update(
                {
                    "stage": "done",
                    "status": status,
                    "roles": roles,
                    "bullets": bullets,
                    "docx_kb": round(len(data) / 1024, 1),
                    "docx_path": str(docx_path) if docx_path else None,
                    "warnings": warnings,
                    **flags,
                    "elapsed_s": round(time.perf_counter() - t0, 2),
                }
            )
            print(
                f"  status={status} roles={roles} rec_used={row.get('recovery_used')} "
                f"block_src={row.get('blocking_source_lines')} wrong_role={row.get('wrong_role')} "
                f"meets_bar={row.get('meets_bar')} ({row['elapsed_s']}s)"
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
            print(f"  ERROR {row['error']}: {row.get('error_detail')}")
        rows.append(row)

    done = [r for r in rows if r.get("stage") == "done"]
    status_counts: dict[str, int] = {}
    for r in done:
        status_counts[str(r.get("status"))] = status_counts.get(str(r.get("status")), 0) + 1
    meets = sum(1 for r in rows if r.get("meets_bar"))
    summary = {
        "mode": "production_unseen_holdout",
        "format": "aptino",
        "n_target": len(files),
        "n_run": len(rows),
        "excluded_prior_names": tested_n,
        "status_counts": status_counts,
        "errors": sum(1 for r in rows if r.get("stage") in {"error", "extract"}),
        "zero_role_count": sum(1 for r in done if not r.get("roles")),
        "recovery_used_count": sum(1 for r in done if r.get("recovery_used")),
        "recovery_preferred_count": sum(1 for r in done if r.get("recovery_preferred")),
        "blocking_source_lines_count": sum(1 for r in done if r.get("blocking_source_lines")),
        "wrong_role_count": sum(1 for r in done if r.get("wrong_role")),
        "meets_bar_count": meets,
        "meets_bar_pct": round(100.0 * meets / len(rows), 1) if rows else 0.0,
        "docx_dir": str(DOCX_DIR) if args.save_docx else None,
        "failing": [
            {
                "id": r["id"],
                "file": r["file"],
                "status": r.get("status"),
                "stage": r.get("stage"),
                "codes": r.get("blocking_codes"),
                "error": r.get("error"),
            }
            for r in rows
            if not r.get("meets_bar")
        ],
        "rows": rows,
    }
    out_path = Path(args.out)
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        f"RESULT unseen holdout aptino n={len(rows)}: status_counts={status_counts} "
        f"errors={summary['errors']} zero_roles={summary['zero_role_count']} "
        f"recovery_used={summary['recovery_used_count']} "
        f"blocking_source_lines={summary['blocking_source_lines_count']} "
        f"wrong_role={summary['wrong_role_count']} "
        f"meets_bar={meets}/{len(rows)} ({summary['meets_bar_pct']}%)"
    )
    for f in summary["failing"]:
        print(
            f"  FAIL BAR: {f['id']} {f['file']} status={f.get('status')} "
            f"stage={f.get('stage')} codes={f.get('codes')} error={f.get('error')}"
        )
    print(f"Wrote {out_path}")
    if args.save_docx:
        print(f"DOCX artifacts: {DOCX_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
