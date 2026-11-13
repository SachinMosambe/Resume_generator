#!/usr/bin/env python3
"""Extract one Task N section from an implementation plan."""
from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) not in (3, 4):
        print("usage: extract_brief.py PLAN_FILE TASK_NUMBER [OUTFILE]", file=sys.stderr)
        return 2
    plan = Path(sys.argv[1])
    n = sys.argv[2]
    out = Path(sys.argv[3]) if len(sys.argv) == 4 else Path(f".superpowers/sdd/task-{n}-brief.md")
    if not plan.is_file():
        print(f"no such plan file: {plan}", file=sys.stderr)
        return 2
    lines = plan.read_text(encoding="utf-8").splitlines(keepends=True)
    collected: list[str] = []
    intask = False
    infence = False
    heading = re.compile(r"^#+[ \t]+Task[ \t]+([0-9]+)\b")
    for line in lines:
        if line.startswith("```"):
            infence = not infence
        if not infence:
            m = heading.match(line)
            if m:
                intask = m.group(1) == n
        if intask:
            collected.append(line)
    if not collected:
        print(f"task {n} not found in {plan}", file=sys.stderr)
        return 3
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(collected), encoding="utf-8")
    print(f"wrote {out}: {len(collected)} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
