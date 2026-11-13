"""Spot-check Capgemini/Aptino/Suresh layout compliance on a few resumes."""
from __future__ import annotations

import io
import logging
import os
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

_TMP = Path(tempfile.mkdtemp())
os.environ["UPLOAD_DIR"] = str(_TMP)
os.environ["RESUME_LLM_CONDENSE"] = "false"
os.environ["RESUME_AGENT_PIPELINE"] = "false"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import structlog
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL))

from app.models.candidate import Candidate
from app.models.client_format import ClientFormat
from app.models.format_schema import normalize_format_metadata
from app.services.aptino_template import build_aptino_client_format
from app.services.detailed_resume_parser import parse_resume_detailed
from app.services.format_extraction_service import FormatExtractionService
from app.services.pdf_parser import extract_document
from app.services.resume_generation_service import ResumeGenerationService
import app.services.resume_generation_service as rgs

rgs.upload_bytes_to_key = lambda **kwargs: None  # type: ignore[assignment]

RESUME = ROOT.parent / "Sachin resume AI" / "Sachin resume AI"
FORMAT_DIR = ROOT.parent / "test" / "format"
OUT = ROOT / "eval_reports" / "samples"
OUT.mkdir(parents=True, exist_ok=True)

ALIGN = {
    WD_ALIGN_PARAGRAPH.LEFT: "left",
    WD_ALIGN_PARAGRAPH.CENTER: "center",
    WD_ALIGN_PARAGRAPH.RIGHT: "right",
    WD_ALIGN_PARAGRAPH.JUSTIFY: "justify",
    None: "none",
}

PICKS = [
    "Guillermo Arellano LinkedIn 09052024 (1).pdf",
    "ManavKapoor_PgM_FINAL_May 2024.docx",
    "US Marco Perez Tech Lead and FullStack Net Developer (1).pdf",
    "Dice_Resume_CV_Mukesh_Kumar.pdf",
    "Anil_Java_AWS (1).docx",
    "geraldcashresume2024.docx",
]


def inspect(data: bytes, expected_labels: list[str]) -> dict:
    doc = Document(io.BytesIO(data))
    paras = [p for p in doc.paragraphs if p.text.strip()]
    first = paras[0] if paras else None
    fonts: Counter = Counter()
    sizes: Counter = Counter()
    headings = []
    for p in paras[:100]:
        t = p.text.strip()
        for r in p.runs:
            if r.font.name:
                fonts[r.font.name] += 1
            if r.font.size:
                sizes[str(round(r.font.size.pt, 1))] += 1
        if any(r.bold for r in p.runs) and len(t) < 60 and not t.endswith("."):
            headings.append(t)
    body = "\n".join(p.text for p in paras)
    label_hits = {lab: (lab.lower() in body.lower()) for lab in expected_labels}
    return {
        "first_text": (first.text.strip()[:70] if first else None),
        "first_align": ALIGN.get(first.alignment, str(first.alignment)) if first else None,
        "para_count": len(paras),
        "top_fonts": fonts.most_common(5),
        "top_sizes": sizes.most_common(5),
        "headings": headings[:12],
        "label_hits": label_hits,
        "tables": len(doc.tables),
    }


def main() -> None:
    extractor = FormatExtractionService()
    formats: dict[str, ClientFormat] = {"aptino": build_aptino_client_format("Aptino")}
    for key, name in [
        ("capgemini", "Capgemini-Format.docx"),
        ("suresh", "Suresh Duvvada.docx"),
    ]:
        path = FORMAT_DIR / name
        meta = normalize_format_metadata(extractor.extract(path.name, path.read_bytes()))
        formats[key] = ClientFormat(
            client_id=key,
            format_template_path=f"upload://{name}",
            format_metadata=meta,
            template_bytes_path=str(path),
        )

    for fname in PICKS:
        path = RESUME / fname
        if not path.exists():
            print("missing", fname)
            continue
        text, meta = extract_document(str(path))
        parsed = parse_resume_detailed(None, text or "")
        exp = parsed.get("experience") or []
        print("\n===", fname, "chars", len(text or ""), "roles", len(exp), "name", repr((parsed.get("name") or "")[:40]))
        if len(exp) == 0:
            lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()][:20]
            print("  SOURCE_HEAD:")
            for ln in lines:
                print("   ", ln[:120])
        cand = Candidate(
            name="Candidate",
            resume_path=str(path),
            extracted_data={
                "raw_text": text or "",
                "resume_text": text or "",
                "extraction_meta": meta,
            },
        )
        safe = re.sub(r"[^A-Za-z0-9_]+", "_", path.stem)[:40]
        for fk, cf in formats.items():
            svc = ResumeGenerationService()
            data = svc.generate(cand, cf)
            outp = OUT / f"{fk}__{safe}.docx"
            outp.write_bytes(data)
            labels = list((normalize_format_metadata(cf.format_metadata or {}).get("section_labels") or {}).values())
            # only section-like labels
            labels = [x for x in labels if x and x.lower() not in {"name", "email", "phone", "location"}]
            info = inspect(data, labels)
            expected_align = (normalize_format_metadata(cf.format_metadata or {}).get("layout") or {}).get("name_alignment")
            expected_font = (normalize_format_metadata(cf.format_metadata or {}).get("styling") or {}).get("font_family")
            print(
                f"  {fk}: status={getattr(svc.last_report, 'status', None)} "
                f"name_align={info['first_align']}(expected {expected_align}) "
                f"fonts={info['top_fonts'][:2]}(expected {expected_font})"
            )
            print(f"    labels={info['label_hits']}")
            print(f"    headings={info['headings'][:8]}")


if __name__ == "__main__":
    main()
