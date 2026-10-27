"""Compare extracted text between two checkouts for local debugging only.

Usage: python scripts/compare_extraction.py <other_backend_dir> [--show]
Prints per-file counts of changed lines; --show prints the changed lines (local use only,
never paste into docs or tickets because real resumes contain personal data).
"""
from __future__ import annotations

import difflib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
RESUMES = sorted((HERE.parent / "test" / "resume").glob("*.*"))

SNIPPET = (
    "import sys, json, logging, structlog;"
    "structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL));"
    "from app.services.pdf_parser import extract_text_from_document as e;"
    "out={}\n"
    "for p in sys.argv[1:]:\n"
    "    try: out[p]=e(p)\n"
    "    except Exception as x: out[p]='ERROR '+type(x).__name__\n"
    "print(json.dumps(out))"
)


def run(backend: Path) -> dict[str, str]:
    proc = subprocess.run(
        [sys.executable, "-W", "ignore", "-c", SNIPPET, *map(str, RESUMES)],
        cwd=backend, capture_output=True, text=True, timeout=600,
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])


def main() -> None:
    other = Path(sys.argv[1]).resolve()
    show = "--show" in sys.argv
    mine, theirs = run(HERE), run(other)
    for path in map(str, RESUMES):
        a = theirs.get(path, "").splitlines()
        b = mine.get(path, "").splitlines()
        diff = [d for d in difflib.unified_diff(a, b, lineterm="", n=0) if d[:1] in "+-" and d[:3] not in ("+++", "---")]
        print(f"{Path(path).name[:30]:30} other_lines={len(a):4} this_lines={len(b):4} changed={len(diff)}")
        if show:
            for d in diff[:60]:
                print("   ", d[:160])


if __name__ == "__main__":
    main()
