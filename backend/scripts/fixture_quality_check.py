"""Parse real fixtures under ../test/resume (no Bedrock). Run via Docker if needed:

    docker run --rm -v \"$PWD:/app\" -v \"$PWD/../test:/test\" -w /app python:3.11-slim \\
      bash -lc 'pip install -q -r requirements.txt && PYTHONPATH=/app python scripts/fixture_quality_check.py'
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.detailed_resume_parser import parse_resume_detailed
from app.services.pdf_parser import extract_text_from_document
from app.services.resume_section_quality import audit_and_repair_document, critical_findings
from app.services.structured_resume_store import build_structured_resume, document_from_store
from app.services.tech_glossary import restore_tech_names
from app.models.format_schema import normalize_format_metadata
from app.services.aptino_template import get_aptino_default_metadata
from app.services.format_validator import has_critical_findings, validate_format_document
from app.agent_pipeline.state import FormatSpec

FIXTURE_DIRS = [
    Path("/test/resume"),
    ROOT.parent / "test" / "resume",
]


def _fixture_dir() -> Path:
    for d in FIXTURE_DIRS:
        if d.is_dir():
            return d
    raise SystemExit("No test/resume fixtures found")


def _blob(doc: dict) -> str:
    return restore_tech_names(json.dumps(doc, default=str))


def check_file(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        text = extract_text_from_document(str(path))
    except Exception as exc:  # noqa: BLE001
        return [f"extract_failed: {exc}"]
    if not (text or "").strip():
        return ["empty_extract"]

    data = parse_resume_detailed(resume_path=None, resume_text=text)
    store = build_structured_resume(data)
    doc = document_from_store(store)
    doc, findings = audit_and_repair_document(doc, store)
    blob = _blob(doc)

    name = str(data.get("name") or "")
    if len(name.split()) < 2:
        errors.append(f"missing_name:{name!r}")

    if not data.get("email"):
        errors.append("missing_email")

    if "AWS AWS" in blob:
        errors.append("aws_aws_repeat")

    for needle in ("Table Tennis", "Mentored 60", "Core Committee"):
        certs = " ".join(str(x) for x in (data.get("certifications") or []))
        if needle.lower() in certs.lower():
            errors.append(f"cert_pollution:{needle}")

    for role in data.get("experience") or []:
        title = str(role.get("title") or "")
        if title[:1].islower() or (title.endswith(".") and len(title.split()) <= 8):
            if not any(
                k in title.lower()
                for k in ("engineer", "developer", "analyst", "manager", "architect")
            ):
                errors.append(f"bad_title:{title[:60]}")

    if path.name.lower().startswith("sachin"):
        if len(data.get("education") or []) < 2:
            errors.append(f"sachin_edu_count:{len(data.get('education') or [])}")
        title0 = str((data.get("experience") or [{}])[0].get("title") or "")
        company0 = str((data.get("experience") or [{}])[0].get("company") or "")
        if "Developer" in title0 and "Aptino" not in company0 and "Aptino" in title0:
            errors.append(f"sachin_title_company_unsplit:{title0}|{company0}")
        if "AI/MLDeveloper" in title0 or "AI/MLDeveloper" in company0:
            errors.append("sachin_mashed_title")

    if path.name.lower().startswith("aditya"):
        for role in data.get("experience") or []:
            title = str(role.get("title") or "")
            if "across squads" in title.lower() or "serving 20,000" in title.lower():
                errors.append(f"aditya_wrap_as_title:{title}")

    crit = critical_findings(findings)
    header_crit = [f for f in crit if f.get("section") == "header"]
    if header_crit:
        errors.append(f"header_critical:{header_crit[0].get('issue')}")

    # Format gate: Aptino schema must not introduce structural criticals beyond
    # missing optional sections already absent from the source store.
    aptino = normalize_format_metadata(get_aptino_default_metadata())
    format_findings = validate_format_document(doc, FormatSpec.from_metadata(aptino))
    for finding in format_findings:
        if finding.get("severity") != "critical":
            continue
        issue = str(finding.get("issue") or "")
        section = str(finding.get("section") or "")
        if "Required section" in issue and not store.get(section):
            continue
        if "Candidate name missing" in issue and not str(data.get("name") or "").strip():
            continue
        errors.append(f"format_gate:{section}:{issue[:80]}")

    return errors


def main() -> None:
    folder = _fixture_dir()
    files = sorted([*folder.glob("*.pdf"), *folder.glob("*.docx")])
    if not files:
        raise SystemExit(f"No pdf/docx fixtures in {folder}")

    failed = 0
    for path in files:
        errs = check_file(path)
        status = "FAIL" if errs else "OK"
        print(f"{status}  {path.name}  {errs or ''}")
        if errs:
            failed += 1
    if failed:
        raise SystemExit(f"fixture_quality_failed:{failed}")
    print("fixture_quality_ok")


if __name__ == "__main__":
    main()
