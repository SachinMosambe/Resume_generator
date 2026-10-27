"""Count-only fidelity report on synthetic fixtures. Prints no resume text.

Columns:
  extract   facts found in extracted text / expected facts
  roles     expected (company, title, dates) tuples parsed as one role / expected roles
  out_apt   facts + role fields found in the Aptino-default DOCX / expected
  out_tpl   same, rendered into a client DOCX template that contains sample-candidate text
  leak      template sample lines found in the client-template output (should be 0)
  bad       text that must not reach the output, e.g. a reference's contact details (should be 0)
  status    review status when available, else ok / error type

Usage: python scripts/fidelity_report.py
"""
from __future__ import annotations

import io
import os
import re
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="fidelity_"))
os.environ["RESUME_LLM_CONDENSE"] = "false"
os.environ["RESUME_AGENT_PIPELINE"] = "false"
os.environ["UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import logging  # noqa: E402

import structlog  # noqa: E402

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL))

from docx import Document  # noqa: E402

from app.models.candidate import Candidate  # noqa: E402
from app.models.client_format import ClientFormat  # noqa: E402
from app.services.aptino_template import build_aptino_client_format  # noqa: E402
from app.services.detailed_resume_parser import parse_resume_detailed  # noqa: E402
from app.services.format_extraction_service import FormatExtractionService  # noqa: E402
from app.services.pdf_parser import extract_document, extract_text_from_document  # noqa: E402
from app.services.resume_generation_service import ResumeGenerationService  # noqa: E402
from tests.fixtures.build_fixtures import EXPECTED, TEMPLATE_SAMPLE_LINES, build_all  # noqa: E402


def norm(text: str) -> str:
    text = re.sub(r"[\u2010-\u2015]", "-", str(text or "")).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def docx_text(data: bytes) -> str:
    doc = Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            parts.extend(c.text for c in row.cells)
    return "\n".join(parts)


def coverage(needles: list[str], hay: str) -> tuple[int, int]:
    hay_n = norm(hay)
    items = [norm(n) for n in needles if norm(n)]
    return sum(1 for n in items if n in hay_n), len(items)


def role_matches(expected: list[tuple[str, str, str]], parsed: list[dict]) -> tuple[int, int]:
    hits = 0
    for company, title, dates in expected:
        for role in parsed:
            if (
                norm(company) in norm(role.get("company"))
                and norm(title) in norm(role.get("title"))
                and norm(dates) in norm(role.get("duration") or role.get("dates"))
            ):
                hits += 1
                break
    return hits, len(expected)


def output_needles(exp: dict) -> list[str]:
    needles = list(exp.get("facts", []))
    for company, title, dates in exp.get("roles", []):
        needles += [company, title, dates]
    return needles


def generate(path: Path, text: str, client_format) -> tuple[bytes | None, str]:
    _, meta = extract_document(str(path))
    cand = Candidate(
        name="Candidate",
        resume_path=str(path),
        extracted_data={"raw_text": text, "resume_text": text, "extraction_meta": meta},
    )
    service = ResumeGenerationService()
    try:
        data = service.generate(cand, client_format)
    except Exception as exc:  # noqa: BLE001
        return None, type(exc).__name__
    report = getattr(service, "last_report", None)
    return data, getattr(report, "status", "ok")


def template_format(path: Path) -> ClientFormat:
    raw = path.read_bytes()
    metadata = FormatExtractionService().extract(path.name, raw)
    return ClientFormat(
        client_id="Client",
        format_template_path=f"upload://{path.name}",
        format_metadata=metadata,
        template_bytes_path=str(path),
    )


def fmt(pair: tuple[int, int]) -> str:
    found, total = pair
    return f"{found}/{total}" if total else "-"


def main() -> None:
    paths = build_all(_TMP / "fixtures")
    tpl = template_format(paths["template_with_sample"])
    header = f"{'fixture':22} {'extract':>8} {'roles':>7} {'out_apt':>8} {'out_tpl':>8} {'leak':>5} {'bad':>4}  status"
    print(header)
    print("-" * len(header))
    totals = {"extract": [0, 0], "roles": [0, 0], "out_apt": [0, 0], "out_tpl": [0, 0]}
    for key, exp in EXPECTED.items():
        path = paths[key]
        try:
            text = extract_text_from_document(str(path)) or ""
        except Exception as exc:  # noqa: BLE001
            print(f"{key:22} extract error: {type(exc).__name__}")
            totals["extract"][1] += len(exp.get("facts", []))
            continue
        ext = coverage(exp.get("facts", []), text)
        if not text.strip():
            print(f"{key:22} {fmt(ext):>8} {'-':>7} {'-':>8} {'-':>8} {'-':>5}  no_text")
            totals["extract"][1] += ext[1]
            continue
        roles = role_matches(exp.get("roles", []), parse_resume_detailed(None, text).get("experience") or [])
        needles = output_needles(exp)
        apt_bytes, apt_status = generate(path, text, build_aptino_client_format("Client"))
        out_apt = coverage(needles, docx_text(apt_bytes)) if apt_bytes else (0, len(needles))
        tpl_bytes, tpl_status = generate(path, text, tpl)
        out_tpl = coverage(needles, docx_text(tpl_bytes)) if tpl_bytes else (0, len(needles))
        leak = coverage(TEMPLATE_SAMPLE_LINES, docx_text(tpl_bytes))[0] if tpl_bytes else 0
        bad = coverage(exp.get("not_in_output", []), docx_text(apt_bytes))[0] if apt_bytes else 0
        status = apt_status if apt_status == tpl_status else f"{apt_status}/{tpl_status}"
        print(
            f"{key:22} {fmt(ext):>8} {fmt(roles):>7} {fmt(out_apt):>8} {fmt(out_tpl):>8} {leak:>5} {bad:>4}  {status}"
        )
        if "--missing" in sys.argv and apt_bytes:
            hay = norm(docx_text(apt_bytes))
            for needle in needles:
                if norm(needle) and norm(needle) not in hay:
                    print(f"    missing: {needle}")
        for name, pair in (("extract", ext), ("roles", roles), ("out_apt", out_apt), ("out_tpl", out_tpl)):
            totals[name][0] += pair[0]
            totals[name][1] += pair[1]
    print("-" * len(header))
    print(
        f"{'TOTAL':22} {fmt(tuple(totals['extract'])):>8} {fmt(tuple(totals['roles'])):>7} "
        f"{fmt(tuple(totals['out_apt'])):>8} {fmt(tuple(totals['out_tpl'])):>8}"
    )


if __name__ == "__main__":
    main()
