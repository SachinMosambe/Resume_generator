"""Build synthetic golden fixtures from anonymized text cases.

Text patterns already live in ``cases/``. PDF, DOCX-table, and legacy DOC
builders are stubbed for later waves. This module never reads the corpus or
``eval_reports/samples``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "manifest.json"

STUB_REASON = {
    "scanned_pdf": "Wave C: render the case text into an image-only PDF for OCR recovery.",
    "mixed_pdf": "Wave C: one selectable-text page plus one image-only page.",
    "table_docx": "Wave C: write the case rows into a DOCX table.",
    "legacy_doc": "Wave C: emit a .doc from the case text when LibreOffice is available.",
}


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def case_text(fixture: dict) -> str:
    path = ROOT / fixture["source"]
    return path.read_text(encoding="utf-8")


def build_scanned_pdf(fixture: dict, dest: Path) -> None:
    raise NotImplementedError(f"{fixture['id']}: {STUB_REASON['scanned_pdf']} source={fixture['source']}")


def build_mixed_pdf(fixture: dict, dest: Path) -> None:
    raise NotImplementedError(f"{fixture['id']}: {STUB_REASON['mixed_pdf']} source={fixture['source']}")


def build_table_docx(fixture: dict, dest: Path) -> None:
    raise NotImplementedError(f"{fixture['id']}: {STUB_REASON['table_docx']} source={fixture['source']}")


def build_legacy_doc(fixture: dict, dest: Path) -> None:
    raise NotImplementedError(f"{fixture['id']}: {STUB_REASON['legacy_doc']} source={fixture['source']}")


BUILDERS = {
    "scanned_pdf": build_scanned_pdf,
    "mixed_pdf": build_mixed_pdf,
    "table_docx": build_table_docx,
    "legacy_doc": build_legacy_doc,
}


def check_sources(manifest: dict | None = None) -> list[str]:
    data = manifest if manifest is not None else load_manifest()
    missing: list[str] = []
    for fixture in data["fixtures"]:
        path = ROOT / fixture["source"]
        if not path.is_file():
            missing.append(fixture["id"])
        builder = fixture.get("builder")
        if builder and builder not in BUILDERS:
            missing.append(f"{fixture['id']}:unknown-builder:{builder}")
    return missing


def materialize(fixture: dict, dest_dir: Path) -> Path:
    """Copy a text case, or dispatch a binary builder when one is named."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    builder_name = fixture.get("builder")
    if not builder_name:
        dest = dest_dir / Path(fixture["source"]).name
        dest.write_text(case_text(fixture), encoding="utf-8")
        return dest
    suffix = {"scanned_pdf": ".pdf", "mixed_pdf": ".pdf", "table_docx": ".docx", "legacy_doc": ".doc"}[builder_name]
    dest = dest_dir / f"{fixture['id']}{suffix}"
    BUILDERS[builder_name](fixture, dest)
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect or build synthetic golden fixtures.")
    parser.add_argument("--list", action="store_true", help="Print fixture id, pattern, and source.")
    parser.add_argument("--check-sources", action="store_true", help="Exit non-zero if a case file is missing.")
    args = parser.parse_args()
    manifest = load_manifest()
    if args.list:
        for fixture in manifest["fixtures"]:
            builder = fixture.get("builder") or "text"
            print(f"{fixture['id']}\t{fixture['pattern']}\t{fixture['source']}\t{builder}")
    missing = check_sources(manifest)
    if args.check_sources and missing:
        raise SystemExit("missing golden sources: " + ", ".join(missing))
    if args.check_sources:
        print(f"ok {len(manifest['fixtures'])} sources")
    if not args.list and not args.check_sources:
        parser.print_help()


if __name__ == "__main__":
    main()
