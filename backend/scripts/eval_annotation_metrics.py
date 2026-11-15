"""Phase 7 helper: score a store/output against human annotations (no Bedrock).

Usage (from backend/):
  python scripts/eval_annotation_metrics.py tests/fixtures/eval_annotations/schema_example.json

Reports numerators/denominators for required-content retention and role ownership
when a companion generated text file is provided; otherwise validates annotation shape.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _norm(s: str) -> str:
    return " ".join((s or "").casefold().split())


def score(annotation: dict, output_text: str) -> dict:
    hay = _norm(output_text)
    required = list(annotation.get("required_content") or [])
    found = [r for r in required if _norm(r) and _norm(r) in hay]
    ownership = annotation.get("role_ownership") or []
    owner_hits = 0
    owner_total = 0
    for row in ownership:
        if not isinstance(row, dict):
            continue
        for bullet in row.get("bullets") or []:
            owner_total += 1
            if _norm(bullet) in hay:
                owner_hits += 1
    return {
        "required_content_retention": {
            "num": len(found),
            "den": len(required),
            "pct": (100.0 * len(found) / len(required)) if required else None,
            "definition": "share of annotated required strings present in output text (normalized)",
        },
        "role_ownership_proxy": {
            "num": owner_hits,
            "den": owner_total,
            "pct": (100.0 * owner_hits / owner_total) if owner_total else None,
            "definition": "bullet strings present anywhere in output (proxy; per-owner regions need DOCX reopen)",
        },
        "split": annotation.get("split"),
        "holdout": bool(annotation.get("holdout")),
        "note": "This is not unseen evaluation unless holdout annotations are used.",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("annotation_json")
    ap.add_argument("--output-text", default="", help="Path to generated plain text for scoring")
    args = ap.parse_args()
    annotation = json.loads(Path(args.annotation_json).read_text(encoding="utf-8"))
    required_keys = {
        "id",
        "required_content",
        "role_ownership",
        "dates_names_metrics",
        "intentional_exclusions",
        "expected_sections",
        "split",
        "holdout",
    }
    missing = sorted(required_keys - set(annotation))
    if missing:
        print(json.dumps({"ok": False, "missing_keys": missing}))
        return 2
    if not args.output_text:
        print(json.dumps({"ok": True, "schema": "valid", "id": annotation.get("id")}, indent=2))
        return 0
    text = Path(args.output_text).read_text(encoding="utf-8")
    print(json.dumps({"ok": True, "metrics": score(annotation, text)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
