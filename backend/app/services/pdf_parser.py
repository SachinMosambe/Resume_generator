"""Utility service for extracting raw text from PDF and Word documents."""
import html as html_lib
import re
from contextvars import ContextVar
from html.parser import HTMLParser
from pathlib import Path

import pdfplumber

from app.core.logging import logger

try:
    import docx
except ImportError:  # pragma: no cover
    docx = None


def _normalize_line(line: str) -> str:
    return " ".join((line or "").strip().split()).casefold()


def _strip_repeated_header_footer(
    page_texts: list[str], *, top_n: int = 3, bottom_n: int = 3, min_repeats: int = 2
) -> list[str]:
    """Remove repeated header/footer lines that appear on most pages.

    Many resumes repeat the same name/contact line at the top and a footer/page
    marker at the bottom of each page; keeping these confuses parsers by
    duplicating content.
    """
    if not page_texts or len(page_texts) < min_repeats:
        return page_texts

    # Collect top/bottom line candidates across pages.
    top_counts: dict[str, int] = {}
    bottom_counts: dict[str, int] = {}
    top_raw: dict[str, str] = {}
    bottom_raw: dict[str, str] = {}

    for text in page_texts:
        lines = [ln for ln in (text or "").splitlines() if ln.strip()]
        if not lines:
            continue
        for ln in lines[:top_n]:
            key = _normalize_line(ln)
            if not key:
                continue
            top_counts[key] = top_counts.get(key, 0) + 1
            top_raw.setdefault(key, ln)
        for ln in lines[-bottom_n:]:
            key = _normalize_line(ln)
            if not key:
                continue
            bottom_counts[key] = bottom_counts.get(key, 0) + 1
            bottom_raw.setdefault(key, ln)

    # Mark as header/footer if repeated on a majority of pages.
    page_count = max(1, len(page_texts))
    threshold = max(min_repeats, int(page_count * 0.6))

    header_keys = {k for k, c in top_counts.items() if c >= threshold}
    footer_keys = {k for k, c in bottom_counts.items() if c >= threshold}

    if not header_keys and not footer_keys:
        return page_texts

    # Keep the first occurrence: a name/contact line repeated as a page header is
    # still candidate content and must survive once.
    cleaned_pages: list[str] = []
    kept_once: set[str] = set()
    for text in page_texts:
        raw_lines = (text or "").splitlines()
        kept: list[str] = []
        for ln in raw_lines:
            key = _normalize_line(ln)
            if key and (key in header_keys or key in footer_keys):
                if key in kept_once:
                    continue
                kept_once.add(key)
            kept.append(ln)
        cleaned_pages.append("\n".join(kept).strip())

    return cleaned_pages


_HTML_BLOCK_TAGS = {
    "address", "article", "blockquote", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6",
    "header", "li", "ol", "p", "section", "table", "tr", "ul",
}
_HTML_SKIP_TAGS = {"script", "style", "noscript"}


class _HTMLTextExtractor(HTMLParser):
    """Keep block structure so contact lines stay in the header, and drop script/style."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        name = tag.lower()
        if name in _HTML_SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if name in _HTML_BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name in _HTML_SKIP_TAGS:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if name in _HTML_BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        chunk = (data or "").strip()
        if chunk:
            self._parts.append(chunk)
            self._parts.append(" ")

    def text(self) -> str:
        raw = html_lib.unescape("".join(self._parts))
        lines = []
        for line in raw.splitlines():
            cleaned = re.sub(r"[ \t]+", " ", line).strip()
            if cleaned:
                lines.append(cleaned)
        return "\n".join(lines)


def _extract_html(path: str) -> str:
    raw = Path(path).read_text(encoding="utf-8", errors="ignore")
    parser = _HTMLTextExtractor()
    parser.feed(raw)
    return parser.text()


def _new_meta() -> dict:
    return {"ocr_pages": [], "ocr_missing_pages": []}


_LAST_META: ContextVar[dict] = ContextVar("document_extraction_meta", default=_new_meta())


def last_extraction_meta() -> dict:
    """Metadata (OCR'd / unreadable pages) of the latest extraction in this context."""
    return dict(_LAST_META.get())


def extract_document(path: str, **kwargs) -> tuple[str, dict]:
    text = extract_text_from_document(path, **kwargs)
    return text, last_extraction_meta()


def extract_text_from_document(
    path: str,
    *,
    lightweight: bool = False,
    max_chars: int = 12_000,
    max_pdf_pages: int = 2,
) -> str:
    """Extract text from a supported document type.

    Full extraction is the default so generation sees the whole resume.
    ``lightweight=True`` reads only the first pages / a character budget.
    """
    ext = Path(path).suffix.lower()
    meta = _new_meta()
    _LAST_META.set(meta)
    try:
        if ext == ".pdf":
            if lightweight:
                text = _extract_pymupdf(path, max_pages=max_pdf_pages).strip()
                if not text:
                    text = _extract_pdfplumber(path, max_pages=max_pdf_pages).strip()
            else:
                text = _extract_pdf(path, meta).strip()
        elif ext == ".docx":
            text = _extract_docx(path, max_chars=max_chars if lightweight else None).strip()
        elif ext == ".doc":
            text = _extract_doc(path, max_chars=max_chars if lightweight else None).strip()
        elif ext in (".html", ".htm"):
            text = _extract_html(path).strip()
        else:
            return ""
    except Exception as exc:
        from app.services.doc_converter import DocConversionError

        if isinstance(exc, DocConversionError):
            logger.error(
                "doc_extraction_failed",
                path=path,
                lightweight=lightweight,
                error=str(exc),
            )
            if lightweight:
                return ""
            raise
        logger.warning(
            "document_extraction_failed",
            path=path,
            ext=ext,
            lightweight=lightweight,
            error=str(exc),
        )
        if lightweight:
            return ""
        raise

    if lightweight and text and len(text) > max_chars:
        text = text[:max_chars]
    return repair_collapsed_spaces(text)


def repair_collapsed_spaces(text: str) -> str:
    """Repair PDF/DOCX extraction that jammed words together (missing spaces)."""
    import re

    from app.services.tech_glossary import (
        protect_tech_and_emails,
        restore_tech_names,
        unprotect_placeholders,
    )

    if not text or len(text) < 24:
        return text
    letters = sum(1 for c in text if c.isalpha())
    spaces = text.count(" ")
    if letters < 24:
        return restore_tech_names(text)
    density = spaces / max(letters, 1)
    force_scan = density < 0.10

    protected, restore_map = protect_tech_and_emails(text)

    def _split_jams(line: str) -> str:
        # Split camelCase/digit joins only inside long jammed tokens. Short mixed-case
        # names (LinkedIn, SageMaker, StoreKit, iPhone) are real words and stay intact.
        def _fix(match: re.Match) -> str:
            token = match.group(0)
            if "⟦" in token or sum(c.isalpha() for c in token) < 16:
                return token
            token = re.sub(r"([a-z])([A-Z])", r"\1 \2", token)
            token = re.sub(r"([A-Za-z])(\d)", r"\1 \2", token)
            return re.sub(r"(\d)([A-Za-z])", r"\1 \2", token)

        return re.sub(r"\S+", _fix, line)

    lexicon = {
        "the", "and", "with", "for", "from", "into", "using", "based", "ready", "native",
        "system", "systems", "service", "services", "agent", "agents", "model", "models",
        "data", "cloud", "backend", "frontend", "platform", "platforms", "interview",
        "candidate", "resume", "parsing", "evaluation", "workflow", "workflows", "tool",
        "tools", "search", "vector", "database", "databases", "context", "protocol",
        "semantic", "multi", "real", "time", "voice", "question", "generation", "insights",
        "production", "grade", "business", "impact", "strong", "focus", "world",
        "architected", "developed", "designed", "implemented", "built", "improved",
        "enabled", "processed", "optimized", "deployed", "integrated", "containerized",
        "reducing", "achieving", "performing", "engineering", "learning", "language",
        "processing", "specialization", "certified", "program", "committee", "member",
        "mentored", "students", "teaching", "assistant", "championship", "table", "tennis",
        "specializing", "building", "applications", "experienced", "developing",
        "scalable", "solutions", "enterprise", "integrations", "reliability",
        "observability", "graduate", "expertise", "institute", "college", "university",
        "bachelor", "master", "technology", "computer", "science", "python",
        "docker", "kubernetes", "machine", "deep", "natural", "large", "prompt",
        "retrieval", "augmented", "protocol", "engineer", "developer", "technologies",
        "celery", "redis", "intelligent", "matching", "analysis", "structured",
        "outputs", "fallback", "strategies", "guardrails", "routing", "bedrock",
        "transcribe", "polly", "enabling", "automated", "recruiter", "velocity",
        "windsurf", "delivering", "across", "multiple", "document", "sources",
        "measured", "citation", "backed", "answer", "financial", "records", "cleaning",
        "feature", "imputation", "outlier", "handling", "robust", "classification",
        "streamlit", "experiment", "tracking", "loan", "conversational", "assistant",
        "external", "capabilities", "interactive", "experiences", "kharagpur",
        "leadership", "achievements", "certifications", "conference",
        "grade", "question", "answering", "cross", "encoder", "ranking", "accuracy",
        "citation", "backed", "metrics", "evaluation", "documents", "sources",
        "through", "quality", "improving", "improved", "achieving", "measured",
    }

    def _segment_token(word: str) -> str:
        original = word
        if "⟦KEEP" in original:
            return original
        # Mixed-case words are deliberate names (DeepLearning, RetrieveIQ), not jams.
        if any(ch.isupper() for ch in original[1:]):
            return original
        w = word.lower()
        if len(w) < 10:
            return original
        if any(ch.isdigit() for ch in w) and len(w) < 16:
            return original
        parts: list[str] = []
        i = 0
        while i < len(w):
            match = None
            for j in range(min(len(w), i + 24), i + 3, -1):
                piece = w[i:j]
                if piece in lexicon:
                    match = piece
                    break
            if match:
                parts.append(match)
                i += len(match)
            else:
                if parts and parts[-1] not in lexicon:
                    parts[-1] += w[i]
                else:
                    parts.append(w[i])
                i += 1
        lexicon_hits = sum(1 for p in parts if p in lexicon)
        if lexicon_hits < 2 or len(parts) <= 1:
            return original
        return " ".join(parts)

    out_lines: list[str] = []
    changed = False
    for line in protected.splitlines():
        if not line.strip():
            out_lines.append(line)
            continue
        # Never aggressively rewrite pure contact lines (emails/URLs only).
        if "@" in line or "http://" in line.lower() or "https://" in line.lower():
            out_lines.append(line)
            continue
        # Placeholders are fine to keep; strip them from density checks only.
        visible = re.sub(r"⟦KEEP\d+⟧", "", line)
        line_letters = sum(1 for c in visible if c.isalpha())
        dens = visible.count(" ") / max(line_letters, 1)
        long_tokens = re.findall(r"[A-Za-z]{14,}", visible)
        needs_fix = dens < 0.12 or len(long_tokens) >= 1
        if not needs_fix or line_letters < 16:
            out_lines.append(line)
            continue
        split = _split_jams(line)
        chunks = re.findall(r"[A-Za-z]+|[^A-Za-z]+", split)
        rebuilt = "".join(_segment_token(ch) if ch.isalpha() else ch for ch in chunks)
        rebuilt = re.sub(r"\s+", " ", rebuilt).strip()
        if rebuilt != line.strip():
            changed = True
        out_lines.append(rebuilt)

    if not force_scan and not changed and density >= 0.10:
        result = protected
    else:
        result = "\n".join(out_lines)
    # Tech casing runs while emails/URLs are still placeholders so links stay byte-exact.
    return unprotect_placeholders(restore_tech_names(result), restore_map)


def extract_text_from_pdf(path: str) -> str:
    """Backward-compatible alias for PDF text extraction."""
    return extract_text_from_document(path)


def _extract_doc(path: str, *, max_chars: int | None = None) -> str:
    """Extract text from legacy .doc by converting to .docx first."""
    from app.services.doc_converter import DocConversionError, convert_doc_to_docx

    try:
        converted = convert_doc_to_docx(Path(path), output_dir=Path(path).parent)
        return _extract_docx(str(converted), max_chars=max_chars).strip()
    except DocConversionError as exc:
        logger.error("doc_conversion_failed", path=path, error=str(exc))
        raise
    except Exception as exc:
        logger.error("doc_extraction_unexpected", path=path, error=str(exc))
        raise DocConversionError(f"Unexpected .doc extraction failure: {exc}") from exc


_ICON_TOKEN = re.compile(r"^\(cid:\d+\)$")
_DATE_ONLY_TEXT = re.compile(
    r"(?i)^(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{4}\s*[-–—/]\s*"
    r"(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{4}|present|current|\d{4})$"
)
_HYPHEN_FRAGMENT = {
    "age", "crease", "ing", "ment", "orous", "tecture", "tion", "ture", "ware",
}
_LAYOUT_HEADINGS = {
    "summary", "professional summary", "profile", "objective",
    "skills", "technical skills", "core skills",
    "experience", "work experience", "professional experience", "employment",
    "education", "projects", "certifications",
}


def _is_layout_heading(text: str) -> bool:
    normalized = re.sub(r"[^a-z ]+", "", (text or "").lower()).strip()
    return normalized in _LAYOUT_HEADINGS


def _keep_layout_token(token: str) -> bool:
    text = (token or "").strip()
    if not text or _ICON_TOKEN.match(text):
        return False
    if any(ch.isalnum() or ch in "@.+#/&" for ch in text):
        return True
    return any(ch in "-–—|•·●▪►*" for ch in text)


def _join_layout_words(words: list) -> str:
    tokens = [w[4].strip() for w in sorted(words, key=lambda w: w[0]) if _keep_layout_token(w[4])]
    if not tokens:
        return ""
    text = " ".join(tokens)
    text = re.sub(r"\s+([,.;:)\]])", r"\1", text)
    text = re.sub(r"([(])\s+", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def _cluster_layout_lines(words: list) -> list[list]:
    kept = [w for w in words if _keep_layout_token(w[4])]
    kept.sort(key=lambda w: (round(w[1], 1), w[0]))
    lines: list[list] = []
    current: list = []
    anchor: float | None = None
    for word in kept:
        y = float(word[1])
        if anchor is None or abs(y - anchor) <= 2:
            current.append(word)
            anchor = y if anchor is None else anchor
            continue
        if current:
            lines.append(current)
        current = [word]
        anchor = y
    if current:
        lines.append(current)
    return lines


def _gap_around(line: list, gutter: float) -> float | None:
    """Width of the whitespace that contains this x, if the x is between words."""
    ordered = sorted(line, key=lambda w: float(w[0]))
    for left, right in zip(ordered, ordered[1:]):
        start = float(left[2])
        end = float(right[0])
        if start <= gutter <= end:
            return end - start
    return None


def _column_gutter(lines: list[list], width: float) -> float | None:
    """X just left of a repeated right-column margin.

    Word-gap voting picks up right-aligned dates and ordinary spaces. A real
    second column is a second left edge shared by several lines, well to the
    right of the page margin.
    """
    if width <= 0 or len(lines) < 6:
        return None
    bins: dict[int, int] = {}
    for line in lines:
        if not line:
            continue
        start = min(float(word[0]) for word in line)
        bucket = int(round(start / 8.0) * 8)
        bins[bucket] = bins.get(bucket, 0) + 1
    if not bins:
        return None
    left_margin = max(bins, key=lambda bucket: (bins[bucket], -bucket))
    candidates = [
        (count, start)
        for start, count in bins.items()
        if start >= left_margin + 100 and width * 0.32 <= start <= width * 0.82 and count >= 4
    ]
    if not candidates:
        return None
    _count, start = max(candidates)
    return float(start) - 6.0


def _line_crosses_gutter(line: list, gutter: float) -> bool:
    gap = _gap_around(line, gutter)
    if gap is None:
        has_left = any((float(w[0]) + float(w[2])) / 2 < gutter for w in line)
        has_right = any((float(w[0]) + float(w[2])) / 2 >= gutter for w in line)
        return has_left and has_right
    return gap < 12


def _dehyphenate_lines(lines: list[str]) -> list[str]:
    """Join words split only because a column line wrapped."""
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.endswith("-") and index + 1 < len(lines):
            nxt = lines[index + 1].lstrip()
            match = re.match(r"([A-Za-z]+)", nxt)
            if match:
                cont = match.group(1)
                if cont[:1].islower() and (len(cont) <= 4 or cont.lower() in _HYPHEN_FRAGMENT):
                    output.append(line[:-1] + nxt)
                    index += 2
                    continue
                if cont[:1].islower() or len(cont) <= 2:
                    output.append(line + nxt)
                    index += 2
                    continue
        output.append(line)
        index += 1
    return output


def _line_top(line: list) -> float:
    return min(float(w[1]) for w in line)


def _free_at(line: list, x: float, pad: float = 1.5) -> bool:
    return all(not (float(w[0]) - pad <= x <= float(w[2]) + pad) for w in line)


def _splits_at(line: list, x: float) -> bool:
    """True when the gutter separates this row into column content.

    A row like "Title  Company ........ Jan 2020 - Present" is free at the gutter but
    is one full-width row; a right side holding only a date never counts as a column.
    """
    if not _free_at(line, x):
        return False
    left = [w for w in line if float(w[2]) < x]
    right = [w for w in line if float(w[0]) > x]
    return not (left and right and _DATE_ONLY_TEXT.match(_join_layout_words(right)))


def _gutter_candidates(lines: list[list], width: float) -> list[float]:
    """X positions of vertical whitespace corridors with a left-aligned column to their right.

    Right-aligned dates/locations also leave a corridor, but their left edges vary,
    so requiring an aligned right edge separates real columns from row metadata.
    """
    if width <= 0 or len(lines) < 4:
        return []
    xs = [float(x) for x in range(int(width * 0.12), int(width * 0.88), 2)]
    scored: list[tuple[int, float]] = []
    for x in xs:
        starts: list[float] = []
        date_only = 0
        for line in lines:
            if not _free_at(line, x):
                continue
            left = [w for w in line if float(w[2]) < x]
            right = [w for w in line if float(w[0]) > x]
            if not right:
                continue
            starts.append(min(float(w[0]) for w in right))
            if left and _DATE_ONLY_TEXT.match(_join_layout_words(right)):
                date_only += 1
        if len(starts) < 3 or date_only * 2 >= len(starts):
            continue
        anchor = sorted(starts)[len(starts) // 2]
        aligned = sum(1 for s in starts if abs(s - anchor) <= 12)
        if aligned >= 3 and aligned >= 0.6 * len(starts) and anchor - x <= 40:
            scored.append((aligned, x))
    if not scored:
        return []
    # One gutter per corridor: keep the best-scoring x of each contiguous run.
    scored.sort(key=lambda item: item[1])
    groups: list[list[tuple[int, float]]] = [[scored[0]]]
    for item in scored[1:]:
        if item[1] - groups[-1][-1][1] <= 4:
            groups[-1].append(item)
        else:
            groups.append([item])
    return [max(group)[1] for group in groups]


def _band_gutter(window: list[list], candidates: list[float]) -> float | None:
    """A gutter that splits this run of lines into two real columns, if any."""
    best: tuple[int, float] | None = None
    for x in candidates:
        run: list[list] = []
        for line in window:
            if not _splits_at(line, x):
                break
            run.append(line)
        if len(run) < 3 or not _is_column_band(run, x):
            continue
        score = len(run)
        if best is None or score > best[0]:
            best = (score, x)
    return best[1] if best else None


_WORDY = re.compile(r"[A-Za-z]{3,}")
# Profile-sheet field names. A band of these is a form, not two resume columns.
_PROFILE_LABELS = {
    "previous", "preferred", "desired work", "settings", "willing to relocate",
    "employment type", "total experience", "profile source", "profile downloaded",
    "work authorization", "visa sponsorship", "desired salary",
}
_CONTACT_TEXT = re.compile(
    r"(@|\d{3}[-.\s]\d{3}[-.\s]\d{4}|\b[A-Z]{2}\s+\d{5}\b|"
    r"\b(?:st|street|dr|drive|ave|avenue|rd|road|ln|lane|blvd|way)\b)",
    re.IGNORECASE,
)


def _is_profile_label(text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9 ]+", "", (text or "").lower()).strip()
    if normalized in _PROFILE_LABELS:
        return True
    return any(normalized.startswith(f"{label} ") for label in _PROFILE_LABELS)


def _is_column_band(run: list[list], x: float) -> bool:
    """Reject label/value tables, hanging bullet glyphs, and right-aligned dates."""
    lefts: list[str] = []
    rights: list[str] = []
    paired = 0
    for line in run:
        lt = _join_layout_words([w for w in line if float(w[2]) < x])
        rt = _join_layout_words([w for w in line if float(w[0]) > x])
        if lt:
            lefts.append(lt)
        if rt:
            rights.append(rt)
        if lt and rt:
            paired += 1
    left_text = [t for t in lefts if _WORDY.search(t)]
    right_text = [t for t in rights if _WORDY.search(t) and not _DATE_ONLY_TEXT.match(t)]
    if len(left_text) < 2 or len(right_text) < 2:
        return False
    dates = sum(1 for t in rights if _DATE_ONLY_TEXT.match(t))
    if dates * 3 >= len(rights):
        return False
    short_labels = sum(1 for t in lefts if len(t.split()) <= 3)
    if paired >= 0.8 * len(lefts) and short_labels >= 0.8 * len(lefts):
        return False
    # A profile form lists field names down the left. Read each row across.
    if sum(1 for text in lefts if _is_profile_label(text)) >= 2:
        return False
    # Name beside an address is a header, not a second column of the resume.
    sides = lefts + rights
    long_lines = sum(1 for text in sides if len(text.split()) >= 10)
    contact_lines = sum(1 for text in sides if _CONTACT_TEXT.search(text))
    if contact_lines >= 2 and long_lines < 2:
        return False
    return True


def _split_is_form_or_header(lines: list[list], width: float) -> bool:
    """True when the page gutter is a profile form or a name-beside-address header.

    Those must be read across each row. A real sidebar still has sentences on the buffered side.
    """
    gutter = _column_gutter(lines, width)
    if gutter is None:
        return False
    lefts: list[str] = []
    rights: list[str] = []
    for line in lines:
        if _line_crosses_gutter(line, gutter):
            continue
        left = _join_layout_words([w for w in line if (float(w[0]) + float(w[2])) / 2 < gutter])
        right = _join_layout_words([w for w in line if (float(w[0]) + float(w[2])) / 2 >= gutter])
        if left:
            lefts.append(left)
        if right:
            rights.append(right)
    if sum(1 for text in lefts if _is_profile_label(text)) >= 2:
        return True
    sides = lefts + rights
    long_lines = sum(1 for text in sides if len(text.split()) >= 10)
    contact_lines = sum(1 for text in sides if _CONTACT_TEXT.search(text))
    return contact_lines >= 2 and long_lines < 2


def _emit_band(band: list[list], gutter: float) -> list[str]:
    """Whole left column, then whole right column; full-width rows already ended the band."""
    def rows(side: list[list]) -> list[tuple[float, str]]:
        # Fragments of one visual row (e.g. company + right-aligned date in a smaller
        # font) can land in separate clusters; rejoin them left-to-right.
        merged: list[list] = []
        for words in side:
            top = min(float(w[1]) for w in words)
            bottom = max(float(w[3]) for w in words)
            if merged:
                p_top, p_bottom = merged[-1][0], merged[-1][1]
                overlap = min(bottom, p_bottom) - max(top, p_top)
                if overlap >= 0.6 * min(bottom - top, p_bottom - p_top):
                    merged[-1][1] = max(p_bottom, bottom)
                    merged[-1][2].extend(words)
                    continue
            merged.append([top, bottom, list(words)])
        return [
            (top, _join_layout_words(sorted(ws, key=lambda w: float(w[0]))))
            for top, _, ws in merged
        ]

    left_words: list[list] = []
    right_words: list[list] = []
    for line in band:
        lw = [w for w in line if (float(w[0]) + float(w[2])) / 2 < gutter]
        rw = [w for w in line if (float(w[0]) + float(w[2])) / 2 >= gutter]
        if lw:
            left_words.append(lw)
        if rw:
            right_words.append(rw)
    left = [t for _, t in rows(left_words)]
    right = [t for _, t in rows(right_words)]
    return _dehyphenate_lines(left) + _dehyphenate_lines(right)


def _layout_page_text(words: list, width: float) -> tuple[str, bool]:
    """Read a page in visual order, keeping side-by-side columns apart.

    The page is cut into horizontal bands. A band starts where a column gutter
    appears and ends at a line that crosses it (full-width heading/paragraph) or at
    a large vertical gap, so full-width headers, sidebars, and layouts that change
    partway down the page are each read in their own order.
    """
    lines = _cluster_layout_lines(words)
    candidates = _gutter_candidates(lines, width)
    if not candidates:
        return _legacy_layout_page_text(lines, width)
    tops = [_line_top(line) for line in lines]
    pitches = sorted(b - a for a, b in zip(tops, tops[1:]) if b - a > 0)
    pitch = pitches[len(pitches) // 2] if pitches else 12.0
    big_gap = max(3.0 * pitch, 30.0)

    out: list[str] = []
    used_columns = False
    i = 0
    while i < len(lines):
        gutter = _band_gutter(lines[i : i + 12], candidates)
        if gutter is None:
            text = _join_layout_words(lines[i])
            if text:
                out.append(text)
            i += 1
            continue
        band = [lines[i]]
        last_top: dict[str, float] = {}

        def sides(line: list) -> list[str]:
            out_sides = []
            if any(float(w[2]) < gutter for w in line):
                out_sides.append("L")
            if any(float(w[0]) > gutter for w in line):
                out_sides.append("R")
            return out_sides

        for side in sides(lines[i]):
            last_top[side] = tops[i]
        j = i + 1
        while j < len(lines) and _splits_at(lines[j], gutter) and tops[j] - tops[j - 1] <= big_gap:
            # A heading after a column has gone quiet (e.g. full-width EXPERIENCE under a
            # short sidebar) starts a new region rather than continuing that column.
            if any(tops[j] - last_top.get(s, tops[j]) > big_gap for s in sides(lines[j])):
                break
            for side in sides(lines[j]):
                last_top[side] = tops[j]
            band.append(lines[j])
            j += 1
        out.extend(t for t in _emit_band(band, gutter) if t)
        used_columns = True
        i = j
    if not used_columns:
        # A rejected gutter can still be a real sidebar, which the legacy reader keeps intact.
        # A profile form or a contact header must stay in row order instead.
        if candidates and _split_is_form_or_header(lines, width):
            return _stitch_hyphens("\n".join(out).strip()), False
        return _legacy_layout_page_text(lines, width)
    return _stitch_hyphens("\n".join(out).strip()), used_columns


def _legacy_layout_page_text(lines: list[list], width: float) -> tuple[str, bool]:
    """Single-gutter reader kept for pages without an aligned column corridor."""
    gutter = _column_gutter(lines, width)
    chunks: list[str] = []
    left_buf: list[str] = []
    right_buf: list[str] = []

    def flush() -> None:
        nonlocal left_buf, right_buf
        if not left_buf and not right_buf:
            return
        left = _dehyphenate_lines([line for line in left_buf if line])
        right = _dehyphenate_lines([line for line in right_buf if line])
        block = "\n".join([*left, *right]).strip()
        if block:
            chunks.append(block)
        left_buf = []
        right_buf = []

    def emit_full(line: list) -> None:
        flush()
        text = _join_layout_words(line)
        if text:
            chunks.append(text)

    for line in lines:
        if gutter is None or _line_crosses_gutter(line, gutter):
            emit_full(line)
            continue
        left_words = [w for w in line if (float(w[0]) + float(w[2])) / 2 < gutter]
        right_words = [w for w in line if (float(w[0]) + float(w[2])) / 2 >= gutter]
        right_text = _join_layout_words(right_words)
        if right_words and _DATE_ONLY_TEXT.match(right_text):
            emit_full(line)
            continue
        # A left-side heading such as EXPERIENCE ends the column band above it.
        if left_words and not right_words and _is_layout_heading(_join_layout_words(left_words)):
            emit_full(line)
            continue
        if left_words:
            left_buf.append(_join_layout_words(left_words))
        if right_words:
            right_buf.append(right_text)
    flush()
    return _stitch_hyphens("\n".join(chunks).strip()), gutter is not None


def _stitch_hyphens(text: str) -> str:
    """Pull a wrapped fragment back onto the line that ended with a hyphen."""
    lines = text.splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        nxt_index = index + 1
        while nxt_index < len(lines) and not re.sub(r"[\-\*\u2022•\s]+", "", lines[nxt_index]):
            nxt_index += 1
        stripped = line.rstrip()
        if stripped.endswith("-") and nxt_index < len(lines):
            nxt = re.sub(r"^[\-\*\u2022•]+\s*", "", lines[nxt_index].strip())
            match = re.match(r"([A-Za-z]+)", nxt)
            if match and nxt:
                cont = match.group(1)
                if cont[:1].islower() and (len(cont) <= 4 or cont.lower() in _HYPHEN_FRAGMENT):
                    output.append(stripped[:-1] + nxt)
                elif cont[:1].islower() or len(cont) <= 2:
                    output.append(stripped + nxt)
                else:
                    output.append(line)
                    index += 1
                    continue
                index = nxt_index + 1
                continue
        output.append(line)
        index += 1
    return "\n".join(output)


def _jam_ratio(text: str) -> float:
    letters = sum(1 for ch in text if ch.isalpha())
    if letters < 40:
        return 0.0
    long_tokens = re.findall(r"[A-Za-z]{14,}", text)
    return sum(len(token) for token in long_tokens) / letters


def _extract_pdf_layout(path: str, *, max_pages: int | None = None) -> tuple[str, int]:
    try:
        import fitz  # pymupdf
    except Exception as exc:
        logger.warning("pymupdf_layout_unavailable", path=path, error=str(exc))
        return "", 0
    try:
        doc = fitz.open(path)
    except Exception as exc:
        logger.warning("pymupdf_layout_open_failed", path=path, error=str(exc))
        return "", 0
    pages: list[str] = []
    column_pages = 0
    try:
        limit = len(doc) if max_pages is None else min(len(doc), max_pages)
        for index in range(limit):
            page = doc[index]
            text, used_columns = _layout_page_text(page.get_text("words"), float(page.rect.width))
            if used_columns:
                column_pages += 1
            if text:
                pages.append(text)
    finally:
        doc.close()
    pages = _strip_repeated_header_footer(pages)
    return "\n\n".join(pages).strip(), column_pages


def _prefer_layout_text(layout: str, plain: str, column_pages: int) -> bool:
    """Use positioned reading when columns or jammed lines would hide sections."""
    if not layout.strip():
        return False
    if not plain.strip():
        return True
    if column_pages > 0:
        return True
    plain_jam = _jam_ratio(plain)
    layout_jam = _jam_ratio(layout)
    return plain_jam >= 0.12 and layout_jam <= plain_jam * 0.6


def _pdf_links(path: str) -> list[str]:
    """External link targets (e.g. LinkedIn behind the word 'LinkedIn')."""
    try:
        import pymupdf as fitz
    except Exception:
        return []
    urls: list[str] = []
    try:
        with fitz.open(path) as doc:
            for page in doc:
                for link in page.get_links():
                    uri = str(link.get("uri") or "").strip()
                    low = uri.lower()
                    if low.startswith("mailto:"):
                        uri = uri[7:]
                    elif low.startswith("tel:") or "google.com/maps" in low or "maps.google." in low:
                        continue
                    if uri and uri not in urls:
                        urls.append(uri)
    except Exception as exc:
        logger.warning("pdf_links_failed", error_type=type(exc).__name__)
    return urls


def _append_links(text: str, links: list[str]) -> str:
    low = text.lower()
    missing = []
    for url in links:
        bare = re.sub(r"^https?://(www\.)?", "", url, flags=re.I).rstrip("/").lower()
        parts = bare.split("/")
        # Authors sometimes paste a full URL into the link target ("…/in/linkedin.com/in/x");
        # any domain-led suffix already visible in the text counts as present.
        shown = any(
            "." in parts[k] and "/".join(parts[k:]) in low for k in range(len(parts))
        )
        if bare and not shown:
            missing.append(url)
    if not missing:
        return text
    return f"{text}\n\n" + "\n".join(missing)


def _pages_needing_ocr(path: str) -> list[int]:
    from app.services import pdf_ocr

    try:
        import pymupdf as fitz

        with fitz.open(path) as doc:
            return [i for i, page in enumerate(doc) if pdf_ocr.page_needs_ocr(page)]
    except Exception as exc:
        logger.warning("pdf_ocr_scan_failed", error_type=type(exc).__name__)
        return []


def _extract_pdf_with_ocr(path: str, need: list[int], meta: dict) -> str:
    """Native pages via the layout reader; flagged pages via OCR when installed."""
    import pymupdf as fitz

    from app.core.config import settings
    from app.services import pdf_ocr

    available = pdf_ocr.ocr_available()
    budget = max(0, int(settings.RESUME_OCR_MAX_PAGES))
    pages: list[str] = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc):
            if i not in need:
                text, _ = _layout_page_text(page.get_text("words"), float(page.rect.width))
                pages.append(text)
                continue
            text = ""
            if available and len(meta["ocr_pages"]) < budget:
                try:
                    text = pdf_ocr.ocr_page_text(page)
                except Exception as exc:
                    logger.warning("pdf_ocr_page_failed", page=i + 1, error_type=type(exc).__name__)
            if text.strip():
                meta["ocr_pages"].append(i + 1)
            else:
                meta["ocr_missing_pages"].append(i + 1)
                text = page.get_text("text") or ""
            pages.append(text)
    combined = "\n\n".join(_strip_repeated_header_footer([p for p in pages if p.strip()])).strip()
    if meta["ocr_missing_pages"] and sum(c.isalpha() for c in combined) < 100:
        raise pdf_ocr.OcrUnavailableError("PDF has no readable text layer and OCR is unavailable")
    logger.info(
        "pdf_ocr_used",
        ocr_pages=len(meta["ocr_pages"]),
        missing_pages=len(meta["ocr_missing_pages"]),
    )
    return combined


def _extract_pdf(path: str, meta: dict | None = None) -> str:
    meta = meta if meta is not None else _new_meta()
    need = _pages_needing_ocr(path)
    if need:
        return _append_links(_extract_pdf_with_ocr(path, need, meta), _pdf_links(path))
    layout, column_pages = _extract_pdf_layout(path)
    text = _extract_pdfplumber(path)
    if not text.strip():
        text = _extract_pymupdf(path)
    if _prefer_layout_text(layout, text, column_pages):
        logger.info("pdf_layout_reading_used", column_pages=column_pages)
        text = layout
    return _append_links(text, _pdf_links(path))


def _extract_pdfplumber(path: str, *, max_pages: int | None = None) -> str:
    try:
        with pdfplumber.open(path) as pdf:
            pages: list[str] = []
            for i, page in enumerate(pdf.pages):
                if max_pages is not None and i >= max_pages:
                    break
                page_text = page.extract_text()
                if page_text:
                    pages.append(page_text)
            pages = _strip_repeated_header_footer(pages)
            return "\n\n".join(pages)
    except Exception as exc:
        logger.warning("pdfplumber_extract_failed", path=path, error=str(exc))
        return ""


def _extract_pymupdf(path: str, *, max_pages: int | None = None) -> str:
    try:
        import fitz  # pymupdf
        doc = fitz.open(path)
        try:
            limit = len(doc) if max_pages is None else min(len(doc), max_pages)
            pages = [doc[i].get_text() for i in range(limit)]
        finally:
            doc.close()
        pages = _strip_repeated_header_footer(pages)
        return "\n\n".join(pages)
    except Exception as exc:
        logger.warning("pymupdf_extract_failed", path=path, error=str(exc))
        return ""


def _extract_docx(path: str, *, max_chars: int | None = None) -> str:
    if docx is None:
        logger.warning("python_docx_unavailable", path=path)
        return ""
    from app.services.docx_reader import DocxLimitError, read_docx_blocks
    from app.services.source_blocks import blocks_to_text

    try:
        text = blocks_to_text(read_docx_blocks(path))
    except DocxLimitError:
        raise
    except Exception as exc:
        logger.warning("docx_extract_failed", error_type=type(exc).__name__)
        return ""
    if max_chars is not None and len(text) > max_chars:
        text = text[:max_chars]
    return text
