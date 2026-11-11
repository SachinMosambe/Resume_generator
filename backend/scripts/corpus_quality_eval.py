"""Corpus quality evaluation on real resumes (counts / statuses; no resume body text).

Usage (from backend/):
  python scripts/corpus_quality_eval.py
  python scripts/corpus_quality_eval.py --limit 120
  python scripts/corpus_quality_eval.py --limit 40 --formats aptino,capgemini

Outputs JSON + Markdown under backend/eval_reports/.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
import re
import sys
import tempfile
import time
import traceback
from collections import Counter, defaultdict
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="corpus_eval_"))
os.environ["RESUME_LLM_CONDENSE"] = "false"
os.environ["RESUME_AGENT_PIPELINE"] = "false"
os.environ["RESUME_LLM_POLISH"] = "false"
os.environ["UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

import structlog  # noqa: E402

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL))

from docx import Document  # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402

from app.models.candidate import Candidate  # noqa: E402
from app.models.client_format import ClientFormat  # noqa: E402
from app.models.format_schema import normalize_format_metadata  # noqa: E402
from app.services.aptino_template import build_aptino_client_format  # noqa: E402
from app.services.detailed_resume_parser import parse_resume_detailed  # noqa: E402
from app.services.format_extraction_service import FormatExtractionService  # noqa: E402
from app.services.format_validator import (  # noqa: E402
    document_section_types,
    has_critical_findings,
    validate_format_document,
)
from app.services.pdf_parser import extract_document, extract_text_from_document  # noqa: E402
from app.services.resume_generation_service import ResumeGenerationService  # noqa: E402
import app.services.resume_generation_service as rgs  # noqa: E402

rgs.upload_bytes_to_key = lambda **kwargs: None  # type: ignore[assignment]

RESUME_DIR = REPO / "Sachin resume AI" / "Sachin resume AI"
FORMAT_DIR = REPO / "test" / "format"
OUT_DIR = ROOT / "eval_reports"

SKIP_NAME = re.compile(
    r"(?i)(travel history|i94|passport|ssn|w2|offer letter|aptino - executive|"
    r"capgemini-format|format\.docx|format\.doc$|\.exe$|zoom_|install)"
)
RESUME_EXT = {".pdf", ".docx", ".doc"}


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


def source_line_coverage(source: str, out: str, min_words: int = 4) -> tuple[int, int]:
    hay = norm(out)
    total = hits = 0
    for raw in (source or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        words = norm(line).split()
        if len(words) < min_words:
            continue
        total += 1
        if " ".join(words) in hay:
            hits += 1
            continue
        # partial: majority of 3-grams present
        grams = [" ".join(words[i : i + 3]) for i in range(max(0, len(words) - 2))]
        if grams and sum(1 for g in grams if g in hay) >= 0.5 * len(grams):
            hits += 1
    return hits, total


def file_id(path: Path) -> str:
    h = hashlib.sha1(str(path.name).encode("utf-8", errors="ignore")).hexdigest()[:8]
    return f"{path.suffix.lower()[1:]}-{h}-{path.stem[:40]}"


def pick_resumes(limit: int) -> list[Path]:
    files = [
        p
        for p in RESUME_DIR.iterdir()
        if p.is_file()
        and p.suffix.lower() in RESUME_EXT
        and not SKIP_NAME.search(p.name)
        and "Aptino" not in p.name
        and "Capgemini" not in p.name
    ]
    # Deduplicate near-identical names: keep first of "(1)" variants by stem base
    seen: set[str] = set()
    unique: list[Path] = []
    for p in sorted(files, key=lambda x: (x.suffix.lower(), -x.stat().st_size, x.name.lower())):
        base = re.sub(r"\s*\(\d+\)\s*$", "", p.stem).strip().lower()
        key = f"{base}{p.suffix.lower()}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)

    # Stratify by extension + size buckets
    by_ext: dict[str, list[Path]] = defaultdict(list)
    for p in unique:
        by_ext[p.suffix.lower()].append(p)

    picked: list[Path] = []
    # Prefer more pdf/docx; fewer doc (LibreOffice may be missing)
    quotas = {
        ".pdf": max(1, int(limit * 0.45)),
        ".docx": max(1, int(limit * 0.45)),
        ".doc": max(0, limit - int(limit * 0.45) - int(limit * 0.45)),
    }
    for ext, quota in quotas.items():
        pool = by_ext.get(ext, [])
        if not pool:
            continue
        # take from head/mid/tail of size-sorted pool for diversity
        n = min(quota, len(pool))
        if n == 1:
            idxs = [0]
        else:
            idxs = sorted({int(i * (len(pool) - 1) / (n - 1)) for i in range(n)})
        for i in idxs:
            picked.append(pool[i])

    # Fill remaining from leftover unique files
    leftover = [p for p in unique if p not in picked]
    for p in leftover:
        if len(picked) >= limit:
            break
        picked.append(p)
    return picked[:limit]


def load_formats(wanted: set[str]) -> dict[str, ClientFormat]:
    formats: dict[str, ClientFormat] = {}
    if "aptino" in wanted:
        formats["aptino"] = build_aptino_client_format("Aptino")
    extractor = FormatExtractionService()
    mapping = {
        "capgemini": FORMAT_DIR / "Capgemini-Format.docx",
        "suresh": FORMAT_DIR / "Suresh Duvvada.docx",
        "juhi": FORMAT_DIR / "Juhi Patil - Aptino format.docx",
    }
    for key, path in mapping.items():
        if key not in wanted:
            continue
        if not path.exists():
            print(f"WARN missing format: {path}")
            continue
        meta = normalize_format_metadata(extractor.extract(path.name, path.read_bytes()))
        formats[key] = ClientFormat(
            client_id=key.title(),
            format_template_path=f"upload://{path.name}",
            format_metadata=meta,
            template_bytes_path=str(path),
        )
    return formats


def layout_signals(text: str) -> dict:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return {
        "line_count": len(lines),
        "char_count": len(text or ""),
        "has_pipe_headers": sum(1 for ln in lines if ln.count("|") >= 2),
        "all_caps_headings": sum(1 for ln in lines if ln.isupper() and 3 < len(ln) < 40),
        "bulletish": sum(1 for ln in lines if re.match(r"^[\u2022\-\*\u25cf\u25e6]", ln) or ln[:2] in {"- ", "* "}),
    }


def parse_stats(text: str) -> dict:
    parsed = parse_resume_detailed(None, text)
    exp = parsed.get("experience") or []
    edu = parsed.get("education") or []
    skills = parsed.get("skills") or []
    if isinstance(skills, dict):
        skill_n = sum(len(v or []) for v in skills.values())
    elif isinstance(skills, list):
        skill_n = len(skills)
    else:
        skill_n = 0
    bullets = 0
    empty_title = 0
    empty_company = 0
    for role in exp:
        if not str(role.get("title") or "").strip():
            empty_title += 1
        if not str(role.get("company") or "").strip():
            empty_company += 1
        desc = role.get("description") or role.get("bullets") or []
        if isinstance(desc, list):
            bullets += len(desc)
        elif desc:
            bullets += 1
    return {
        "roles": len(exp),
        "bullets": bullets,
        "education": len(edu) if isinstance(edu, list) else (1 if edu else 0),
        "skills": skill_n,
        "empty_title_roles": empty_title,
        "empty_company_roles": empty_company,
        "name_present": bool(str(parsed.get("name") or "").strip()),
        "additional_sections": len(parsed.get("additional_sections") or {}),
    }


def name_alignment(data: bytes) -> str | None:
    doc = Document(io.BytesIO(data))
    for p in doc.paragraphs:
        if p.text.strip():
            a = p.alignment
            if a == WD_ALIGN_PARAGRAPH.CENTER:
                return "center"
            if a == WD_ALIGN_PARAGRAPH.RIGHT:
                return "right"
            if a == WD_ALIGN_PARAGRAPH.LEFT:
                return "left"
            return str(a)
    return None


def evaluate_one(path: Path, formats: dict[str, ClientFormat]) -> dict:
    row: dict = {
        "id": file_id(path),
        "file": path.name,
        "ext": path.suffix.lower(),
        "size_kb": round(path.stat().st_size / 1024, 1),
    }
    t0 = time.perf_counter()
    try:
        text, meta = extract_document(str(path))
        text = text or ""
    except Exception as exc:  # noqa: BLE001
        row["stage"] = "extract"
        row["error"] = type(exc).__name__
        row["error_detail"] = str(exc)[:180]
        row["elapsed_s"] = round(time.perf_counter() - t0, 2)
        return row

    row["extract_chars"] = len(text)
    row["extract_meta"] = {
        k: meta.get(k)
        for k in ("source_type", "ocr_used", "ocr_pages", "unread_pages", "page_count", "columns")
        if isinstance(meta, dict) and k in meta
    }
    row["layout"] = layout_signals(text)
    if not text.strip():
        row["stage"] = "extract"
        row["error"] = "no_text"
        row["elapsed_s"] = round(time.perf_counter() - t0, 2)
        return row

    try:
        row["parse"] = parse_stats(text)
    except Exception as exc:  # noqa: BLE001
        row["stage"] = "parse"
        row["error"] = type(exc).__name__
        row["error_detail"] = str(exc)[:180]
        row["elapsed_s"] = round(time.perf_counter() - t0, 2)
        return row

    cand = Candidate(
        name="Candidate",
        resume_path=str(path),
        extracted_data={"raw_text": text, "resume_text": text, "extraction_meta": meta if isinstance(meta, dict) else {}},
    )
    formats_out: dict[str, dict] = {}
    for fname, cf in formats.items():
        fr: dict = {}
        t1 = time.perf_counter()
        service = ResumeGenerationService()
        try:
            data = service.generate(cand, cf)
            report = getattr(service, "last_report", None)
            out_txt = docx_text(data)
            cov = source_line_coverage(text, out_txt)
            fr["status"] = getattr(report, "status", "ok") if report else "ok"
            structured = list(getattr(report, "warnings", []) or [])[:8]
            fr["warnings_structured"] = [w if isinstance(w, dict) else {"severity": "blocking", "code": "legacy", "message": str(w)} for w in structured]
            fr["warnings"] = [w["message"] for w in fr["warnings_structured"]]
            fr["checks"] = getattr(report, "checks", {}) if report else {}
            fr["line_cov"] = {"found": cov[0], "total": cov[1], "pct": round(100 * cov[0] / cov[1], 1) if cov[1] else None}
            # Two different metrics -- do not conflate:
            #  raw_line_cov: diagnostic ratio of source lines found verbatim in the output (baseline median ~84.8%).
            #  integrity_source_lines: the integrity check's classified source-line result (hard/soft/changed).
            fr["raw_line_cov"] = fr["line_cov"]
            fr["integrity_source_lines"] = fr["checks"].get("source_lines")
            fr["out_chars"] = len(out_txt)
            fr["name_alignment"] = name_alignment(data)
            fr["docx_kb"] = round(len(data) / 1024, 1)
            # Format validation against expected metadata section order when available
            try:
                # Rebuild document section types via a light regenerate path is heavy;
                # use integrity checks + heading presence instead.
                meta = normalize_format_metadata(cf.format_metadata or {})
                expected = [s for s in (meta.get("section_order") or meta.get("sections") or []) if s != "header"]
                out_n = norm(out_txt)
                labels = meta.get("section_labels") or {}
                label_hits = 0
                label_total = 0
                for key in expected:
                    label = labels.get(key) or key
                    label_total += 1
                    if norm(str(label)) in out_n or norm(str(key)) in out_n:
                        label_hits += 1
                fr["section_label_cov"] = {"found": label_hits, "total": label_total}
                fr["expected_sections"] = expected
            except Exception as exc:  # noqa: BLE001
                fr["format_error"] = type(exc).__name__
            # Template leak heuristic for client formats with sample content
            if fname != "aptino":
                sample_needles = ["sample candidate", "old employer", "lorem ipsum", "john doe", "jane doe"]
                fr["template_leak_hits"] = sum(1 for n in sample_needles if n in norm(out_txt))
        except Exception as exc:  # noqa: BLE001
            fr["status"] = "error"
            fr["error"] = type(exc).__name__
            fr["error_detail"] = str(exc)[:200]
            fr["traceback"] = traceback.format_exc().splitlines()[-3:]
        fr["elapsed_s"] = round(time.perf_counter() - t1, 2)
        formats_out[fname] = fr

    row["formats"] = formats_out
    row["elapsed_s"] = round(time.perf_counter() - t0, 2)
    row["stage"] = "done"
    return row


def summarize(rows: list[dict], format_names: list[str]) -> dict:
    summary: dict = {
        "n": len(rows),
        "by_ext": Counter(r["ext"] for r in rows),
        "extract_errors": Counter(r.get("error") for r in rows if r.get("stage") == "extract" and r.get("error")),
        "parse_errors": Counter(r.get("error") for r in rows if r.get("stage") == "parse" and r.get("error")),
        "formats": {},
    }
    parse_ok = [r for r in rows if r.get("parse")]
    if parse_ok:
        summary["parse_averages"] = {
            "roles": round(sum(r["parse"]["roles"] for r in parse_ok) / len(parse_ok), 2),
            "bullets": round(sum(r["parse"]["bullets"] for r in parse_ok) / len(parse_ok), 2),
            "skills": round(sum(r["parse"]["skills"] for r in parse_ok) / len(parse_ok), 2),
            "empty_title_rate": round(
                sum(r["parse"]["empty_title_roles"] for r in parse_ok)
                / max(1, sum(r["parse"]["roles"] for r in parse_ok)),
                3,
            ),
            "name_present_pct": round(100 * sum(1 for r in parse_ok if r["parse"]["name_present"]) / len(parse_ok), 1),
            "zero_role_pct": round(100 * sum(1 for r in parse_ok if r["parse"]["roles"] == 0) / len(parse_ok), 1),
            "zero_bullet_pct": round(100 * sum(1 for r in parse_ok if r["parse"]["bullets"] == 0) / len(parse_ok), 1),
        }

    for fname in format_names:
        statuses = Counter()
        covs = []
        errors = Counter()
        warning_tokens = Counter()
        check_miss = Counter()
        for r in rows:
            fr = (r.get("formats") or {}).get(fname)
            if not fr:
                continue
            statuses[fr.get("status", "missing")] += 1
            if fr.get("error"):
                errors[fr["error"]] += 1
            lc = fr.get("line_cov") or {}
            if lc.get("pct") is not None:
                covs.append(lc["pct"])
            for w in fr.get("warnings") or []:
                # bucket by leading phrase
                key = re.split(r"\d", w, maxsplit=1)[0].strip().rstrip(".").lower()[:60]
                warning_tokens[key or w[:60]] += 1
            for cname, cval in (fr.get("checks") or {}).items():
                if isinstance(cval, dict) and not cval.get("ok", True):
                    check_miss[cname] += 1
        summary["formats"][fname] = {
            "status_counts": dict(statuses),
            "errors": dict(errors),
            "avg_raw_line_cov_pct": round(sum(covs) / len(covs), 1) if covs else None,
            "integrity_source_lines": {
                "blocking": sum(1 for r in rows if ((r.get("formats") or {}).get(fname) or {}).get("integrity_source_lines", {}) and not ((r.get("formats") or {}).get(fname) or {})["integrity_source_lines"].get("ok", True)),
                "soft_lines_total": sum(((r.get("formats") or {}).get(fname) or {}).get("integrity_source_lines", {}).get("soft", 0) for r in rows if ((r.get("formats") or {}).get(fname) or {}).get("integrity_source_lines")),
            },
            "avg_line_coverage_pct": round(sum(covs) / len(covs), 1) if covs else None,
            "p25_line_coverage_pct": round(sorted(covs)[len(covs) // 4], 1) if covs else None,
            "p75_line_coverage_pct": round(sorted(covs)[(3 * len(covs)) // 4], 1) if covs else None,
            "top_warning_buckets": warning_tokens.most_common(12),
            "failed_checks": dict(check_miss),
            "pass_rate_pct": round(100 * statuses.get("passed", 0) / max(1, sum(statuses.values())), 1),
            "fail_rate_pct": round(100 * statuses.get("failed", 0) / max(1, sum(statuses.values())), 1),
            "needs_review_pct": round(100 * statuses.get("needs_review", 0) / max(1, sum(statuses.values())), 1),
            "error_rate_pct": round(100 * statuses.get("error", 0) / max(1, sum(statuses.values())), 1),
        }
    return summary


def worst_cases(rows: list[dict], fname: str, n: int = 15) -> list[dict]:
    scored = []
    for r in rows:
        fr = (r.get("formats") or {}).get(fname) or {}
        if not fr:
            continue
        pct = (fr.get("line_cov") or {}).get("pct")
        status = fr.get("status")
        score = 0
        if status == "error":
            score = -1
        elif status == "failed":
            score = pct if pct is not None else 0
        elif status == "needs_review":
            score = (pct if pct is not None else 50) + 20
        else:
            score = (pct if pct is not None else 80) + 40
        scored.append(
            {
                "file": r["file"],
                "ext": r["ext"],
                "status": status,
                "line_cov_pct": pct,
                "parse_roles": (r.get("parse") or {}).get("roles"),
                "parse_bullets": (r.get("parse") or {}).get("bullets"),
                "empty_title_roles": (r.get("parse") or {}).get("empty_title_roles"),
                "error": fr.get("error"),
                "warnings": fr.get("warnings", [])[:4],
                "extract_chars": r.get("extract_chars"),
            }
        )
    scored.sort(key=lambda x: (0 if x["status"] == "error" else 1, x["line_cov_pct"] if x["line_cov_pct"] is not None else -1))
    return scored[:n]


def to_markdown(summary: dict, rows: list[dict], format_names: list[str]) -> str:
    lines = []
    lines.append("# Resume Generator Corpus Evaluation Report")
    lines.append("")
    lines.append(f"- Corpus folder: `Sachin resume AI/Sachin resume AI`")
    lines.append(f"- Sampled resumes tested: **{summary['n']}**")
    lines.append(f"- Extensions: {dict(summary['by_ext'])}")
    lines.append(f"- Formats tested: {', '.join(format_names)}")
    lines.append(f"- Mode: faithful (LLM condense/agent pipeline off)")
    lines.append("")
    lines.append("## Executive summary")
    lines.append("")
    for fname in format_names:
        f = summary["formats"].get(fname, {})
        lines.append(
            f"- **{fname}**: pass {f.get('pass_rate_pct')}%, needs_review {f.get('needs_review_pct')}%, "
            f"failed {f.get('fail_rate_pct')}%, error {f.get('error_rate_pct')}%, "
            f"avg raw_line_cov {f.get('avg_line_coverage_pct')}% (diagnostic), "
            f"integrity source_lines blocking {(f.get('integrity_source_lines') or {}).get('blocking')}"
        )
    lines.append("")
    if summary.get("parse_averages"):
        pa = summary["parse_averages"]
        lines.append("## Parsing health")
        lines.append("")
        lines.append(f"- Avg roles / resume: {pa['roles']}")
        lines.append(f"- Avg bullets / resume: {pa['bullets']}")
        lines.append(f"- Avg skills tokens: {pa['skills']}")
        lines.append(f"- Empty job-title rate among roles: {pa['empty_title_rate']}")
        lines.append(f"- Name detected: {pa['name_present_pct']}%")
        lines.append(f"- Resumes with 0 roles: {pa['zero_role_pct']}%")
        lines.append(f"- Resumes with 0 bullets: {pa['zero_bullet_pct']}%")
        lines.append("")
    if summary.get("extract_errors"):
        lines.append("## Extraction failures")
        lines.append("")
        for k, v in summary["extract_errors"].items():
            lines.append(f"- {k}: {v}")
        lines.append("")
    for fname in format_names:
        f = summary["formats"][fname]
        lines.append(f"## Format: {fname}")
        lines.append("")
        lines.append(f"- Status counts: `{f.get('status_counts')}`")
        lines.append(
            f"- raw_line_cov avg / p25 / p75 (diagnostic, verbatim source lines found): "
            f"{f.get('avg_line_coverage_pct')} / {f.get('p25_line_coverage_pct')} / {f.get('p75_line_coverage_pct')}"
        )
        lines.append(f"- integrity source_lines (blocking resumes / soft lines): `{f.get('integrity_source_lines')}`")
        lines.append(f"- Failed integrity checks: `{f.get('failed_checks')}`")
        if f.get("errors"):
            lines.append(f"- Generation errors: `{f.get('errors')}`")
        lines.append("- Top warning buckets:")
        for k, v in f.get("top_warning_buckets") or []:
            lines.append(f"  - {k}: {v}")
        lines.append("")
        lines.append("### Worst cases")
        lines.append("")
        lines.append("| File | Ext | Status | raw_line_cov% | Roles | Bullets | Empty titles | Notes |")
        lines.append("|---|---|---|---:|---:|---:|---:|---|")
        for w in worst_cases(rows, fname, 12):
            note = w.get("error") or ("; ".join(w.get("warnings") or [])[:80])
            note = (note or "").replace("|", "/")
            lines.append(
                f"| {w['file'][:50]} | {w['ext']} | {w['status']} | {w['line_cov_pct']} | "
                f"{w['parse_roles']} | {w['parse_bullets']} | {w['empty_title_roles']} | {note[:80]} |"
            )
        lines.append("")
    lines.append("## Improvement priorities (from this run)")
    lines.append("")
    lines.append(
        "Auto-ranked themes appear in the companion analysis; see the JSON for per-file detail."
    )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=80)
    ap.add_argument("--formats", default="aptino,capgemini,suresh")
    ap.add_argument("--out", default=str(OUT_DIR))
    args = ap.parse_args()

    wanted = {x.strip().lower() for x in args.formats.split(",") if x.strip()}
    formats = load_formats(wanted)
    if not formats:
        raise SystemExit("No formats loaded")
    if not RESUME_DIR.exists():
        raise SystemExit(f"Resume dir missing: {RESUME_DIR}")

    resumes = pick_resumes(args.limit)
    print(f"Testing {len(resumes)} resumes x {list(formats)} formats")
    rows = []
    for i, path in enumerate(resumes, 1):
        print(f"[{i}/{len(resumes)}] {path.name[:70]}")
        row = evaluate_one(path, formats)
        rows.append(row)
        status_bits = []
        for fn, fr in (row.get("formats") or {}).items():
            status_bits.append(f"{fn}={fr.get('status')}")
        print("  ", row.get("stage"), row.get("error") or "", " ".join(status_bits), f"{row.get('elapsed_s')}s")

    summary = summarize(rows, list(formats))
    # Derive improvement themes
    themes = []
    pa = summary.get("parse_averages") or {}
    if pa.get("zero_role_pct", 0) >= 10:
        themes.append({"theme": "experience_parse_miss", "severity": "P0", "evidence": f"{pa['zero_role_pct']}% resumes parsed with 0 roles"})
    if pa.get("empty_title_rate", 0) >= 0.15:
        themes.append({"theme": "empty_job_titles", "severity": "P0", "evidence": f"empty_title_rate={pa['empty_title_rate']}"})
    if pa.get("zero_bullet_pct", 0) >= 15:
        themes.append({"theme": "bullet_extraction", "severity": "P0", "evidence": f"{pa['zero_bullet_pct']}% resumes with 0 bullets"})
    if pa.get("name_present_pct", 100) < 85:
        themes.append({"theme": "name_detection", "severity": "P1", "evidence": f"name_present={pa['name_present_pct']}%"})
    if summary.get("extract_errors"):
        themes.append({"theme": "extraction_failures", "severity": "P0", "evidence": dict(summary["extract_errors"])})
    for fname, f in summary["formats"].items():
        if f.get("fail_rate_pct", 0) >= 15:
            themes.append({"theme": f"{fname}_integrity_fail", "severity": "P0", "evidence": f"fail_rate={f['fail_rate_pct']}%"})
        if f.get("needs_review_pct", 0) >= 40:
            themes.append({"theme": f"{fname}_needs_review_heavy", "severity": "P1", "evidence": f"needs_review={f['needs_review_pct']}%"})
        if (f.get("avg_line_coverage_pct") or 100) < 70:
            themes.append({"theme": f"{fname}_low_source_coverage", "severity": "P0", "evidence": f"avg_cov={f['avg_line_coverage_pct']}%"})
        for check, n in (f.get("failed_checks") or {}).items():
            if n >= max(3, int(0.15 * summary["n"])):
                themes.append({"theme": f"{fname}_missing_{check}", "severity": "P0", "evidence": f"{n}/{summary['n']} missing {check}"})

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    payload = {
        "generated_at": stamp,
        "resume_dir": str(RESUME_DIR),
        "formats": list(formats),
        "summary": summary,
        "themes": themes,
        "rows": rows,
        "worst": {fn: worst_cases(rows, fn, 20) for fn in formats},
    }
    # Make counters JSON-safe
    payload["summary"]["by_ext"] = dict(summary["by_ext"])
    payload["summary"]["extract_errors"] = dict(summary["extract_errors"])
    payload["summary"]["parse_errors"] = dict(summary["parse_errors"])

    json_path = out_dir / f"corpus_eval_{stamp}.json"
    md_path = out_dir / f"corpus_eval_{stamp}.md"
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md = to_markdown(summary, rows, list(formats))
    md += "\n## Auto-detected improvement themes\n\n"
    for t in themes:
        md += f"- **{t['severity']} — {t['theme']}**: {t['evidence']}\n"
    md_path.write_text(md, encoding="utf-8")
    latest_json = out_dir / "corpus_eval_latest.json"
    latest_md = out_dir / "corpus_eval_latest.md"
    latest_json.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
    latest_md.write_text(md, encoding="utf-8")
    print("\nWrote", json_path)
    print("Wrote", md_path)
    print(json.dumps({"summary_formats": summary["formats"], "themes": themes}, indent=2, default=str))


if __name__ == "__main__":
    main()
