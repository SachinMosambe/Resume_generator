"""Probe the grounded line extractor on real corpus resumes (calls Bedrock).

python scripts/line_extract_probe.py --hard 12 --normal 10 [--show]

Prints counts per resume. --show also prints extracted titles / companies / dates
(never bullets) for the hard cases so a person can judge them.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

os.environ["RESUME_LLM_PARSE_FALLBACK"] = "false"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import structlog  # noqa: E402

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL))
logging.disable(logging.WARNING)

from app.services.detailed_resume_parser import parse_resume_detailed  # noqa: E402
from app.services.llm_line_extractor import apply_line_extraction  # noqa: E402
from app.services.pdf_parser import extract_text_from_document  # noqa: E402
from app.services.source_evidence import detect_employment_evidence  # noqa: E402
from corpus_quality_eval import pick_resumes  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", type=int, default=250)
    ap.add_argument("--hard", type=int, default=12)
    ap.add_argument("--normal", type=int, default=10)
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()

    hard, normal = [], []
    for path in pick_resumes(args.pool):
        try:
            text = extract_text_from_document(str(path))
        except Exception:
            continue
        if not text.strip() or not detect_employment_evidence(text).has_work_history:
            continue
        parsed = parse_resume_detailed(None, text)
        roles = parsed.get("experience") or []
        empty = sum(1 for r in roles if not str(r.get("title") or "").strip())
        if not roles or empty / max(1, len(roles)) >= 0.5:
            hard.append((path, text, parsed))
        elif len(normal) < args.normal:
            normal.append((path, text, parsed))
    hard = hard[: args.hard]
    print(f"hard cases: {len(hard)}, normal cases: {len(normal)}\n")

    totals = {"hard": [0, 0, 0], "normal": [0, 0, 0]}
    for group, items in (("hard", hard), ("normal", normal)):
        print(f"== {group}")
        for i, (path, text, parsed) in enumerate(items, 1):
            t = time.perf_counter()
            out = apply_line_extraction(text, parsed)
            secs = time.perf_counter() - t
            info = out["parse_meta"].get("line_extract", {})
            roles = out.get("experience") or []
            empty = sum(1 for r in roles if not str(r.get("title") or "").strip())
            print(
                f"  {i:>2} {path.suffix:<5} rule roles {info.get('rule_roles', '?'):>2} "
                f"llm roles {info.get('llm_roles', '?'):>2} used={str(info.get('used')):<5} "
                f"cov rule {info.get('rule_coverage', 0):.0%} llm {info.get('llm_coverage', 0):.0%} "
                f"empty titles {empty} unassigned {info.get('unassigned_lines', 0)} "
                f"rejected {info.get('rejected_fields', 0)} calls {info.get('llm_calls', 0)} "
                f"{secs:.0f}s {info.get('error', '')}",
                flush=True,
            )
            totals[group][0] += 1
            totals[group][1] += int(bool(info.get("used")))
            totals[group][2] += int(bool(roles))
            if args.show and group == "hard" and info.get("used"):
                for r in roles[:12]:
                    print(f"        - {r['title'][:45]!s:<45} | {r['company'][:35]!s:<35} | {r['duration'][:25]}")
    for g, (n, used, with_roles) in totals.items():
        print(f"{g}: {n} resumes, LLM result used in {used}, resumes with roles after: {with_roles}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
