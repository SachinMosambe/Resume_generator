"""One-off: retest hardest corpus resumes from corpus_eval_latest.json."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# Import after path setup; corpus_quality_eval clears Bedrock and forces faithful mode.
import corpus_quality_eval as cqe  # noqa: E402

REPORT = ROOT / "eval_reports" / "corpus_eval_latest.json"
OUT = ROOT / "eval_reports" / "hard_resume_retest.json"
FORMATS = ("aptino",)  # one format is enough to re-check parse + integrity path
MAX_HARD = 12


def pick_hard_names(payload: dict) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    def add(name: str | None) -> None:
        if not name or name in seen:
            return
        seen.add(name)
        names.append(name)

    for items in (payload.get("worst") or {}).values():
        for it in items or []:
            add(it.get("file") or it.get("name"))

    for row in payload.get("rows") or []:
        parse = row.get("parse") or {}
        apt = (row.get("formats") or {}).get("aptino") or {}
        if (parse.get("roles") or 0) == 0 or apt.get("status") == "failed":
            add(row.get("file") or row.get("name") or Path(str(row.get("path") or "")).name)

    return names[:MAX_HARD]


def resolve(name: str) -> Path | None:
    direct = cqe.RESUME_DIR / name
    if direct.exists():
        return direct
    matches = list(cqe.RESUME_DIR.rglob(name))
    return matches[0] if matches else None


def main() -> int:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    hard_names = pick_hard_names(payload)
    formats = cqe.load_formats(set(FORMATS))
    if not formats:
        raise SystemExit("No formats loaded")

    print(f"Hard resumes selected: {len(hard_names)}")
    rows = []
    for i, name in enumerate(hard_names, 1):
        path = resolve(name)
        if path is None:
            print(f"[{i}/{len(hard_names)}] MISSING {name}")
            rows.append({"file": name, "stage": "missing"})
            continue
        print(f"[{i}/{len(hard_names)}] {path.name[:70]}")
        row = cqe.evaluate_one(path, formats)
        rows.append(row)
        apt = (row.get("formats") or {}).get("aptino") or {}
        parse = row.get("parse") or {}
        print(
            f"  status={apt.get('status')} roles={parse.get('roles')} "
            f"bullets={parse.get('bullets')} err={row.get('error') or '-'}"
        )

    summary = cqe.summarize(rows, list(formats))
    out = {
        "n": len(rows),
        "files": hard_names,
        "summary": {
            "by_ext": dict(summary.get("by_ext") or {}),
            "extract_errors": dict(summary.get("extract_errors") or {}),
            "parse_errors": dict(summary.get("parse_errors") or {}),
            "parse_averages": summary.get("parse_averages"),
            "formats": summary.get("formats"),
        },
        "rows": [
            {
                "file": r.get("file") or r.get("name") or Path(str(r.get("path") or "")).name,
                "stage": r.get("stage"),
                "error": r.get("error"),
                "parse": r.get("parse"),
                "aptino": (r.get("formats") or {}).get("aptino"),
            }
            for r in rows
        ],
    }
    OUT.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print("Wrote", OUT)
    fmt = (summary.get("formats") or {}).get("aptino") or {}
    print(
        "RESULT aptino:",
        f"passed={fmt.get('status_counts', {}).get('passed', 0)}",
        f"needs_review={fmt.get('status_counts', {}).get('needs_review', 0)}",
        f"failed={fmt.get('status_counts', {}).get('failed', 0)}",
        f"zero_role_pct={summary.get('parse_averages', {}).get('zero_role_pct')}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
