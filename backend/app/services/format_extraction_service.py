import re
import tempfile
import logging
from pathlib import Path
from typing import Any

try:
    from langsmith import traceable
except ImportError:  # pragma: no cover
    def traceable(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

logger = logging.getLogger(__name__)


class FormatExtractionError(ValueError):
    pass


SECTION_ALIASES: dict[str, list[str]] = {
    "header": ["header", "contact", "profile"],
    "summary": ["summary", "professional summary", "profile summary", "objective"],
    "experience": ["experience", "work experience", "professional experience", "employment"],
    "education": ["education", "academic", "academics", "qualifications"],
    "skills": ["skills", "technical skills", "core skills", "competencies"],
    "projects": ["projects", "selected projects", "project experience"],
    "certifications": ["certifications", "certificates", "licenses"],
}

DEFAULT_SECTIONS = [
    "header",
    "summary",
    "skills",
    "experience",
    "projects",
    "education",
    "certifications",
    "achievements",
]


class FormatExtractionService:
    allowed_extensions = {".pdf", ".docx"}

    @traceable(run_type="retriever", tags=["format", "extraction", "client-template"])
    def extract(self, filename: str, content: bytes) -> dict[str, Any]:
        logger.info(f"Extracting client format from: {filename} ({len(content)} bytes)")
        
        ext = Path(filename or "").suffix.lower()
        if ext not in self.allowed_extensions:
            raise FormatExtractionError("Client format must be a PDF or DOCX file")
        if not content:
            raise FormatExtractionError("Client format file is empty")

        text, styling, logos, header_text, footer_text = self._extract_document(ext, content)
        sections, section_labels = self._infer_sections_with_labels(text)

        # Prefer formal header/footer branding; fall back to body heuristics.
        header_sign = self._company_sign_from_text(header_text)
        footer_sign = self._company_sign_from_text(footer_text)
        company_header = header_sign or self._infer_company_header(text)
        company_footer = footer_sign or company_header

        preview_text = self._build_format_preview(text, sections, section_labels)

        logger.info(
            "Extraction complete: %s sections, %s logos, header_branding=%s, footer_branding=%s",
            len(sections),
            len(logos),
            bool(company_header),
            bool(company_footer),
        )
        if logos:
            for i, logo in enumerate(logos):
                data_len = len(logo.get("data", "")) if logo.get("data") else 0
                logger.info("  Logo %s: %s (%s chars, source=%s)", i + 1, logo.get("position"), data_len, logo.get("source"))

        return {
            "source_filename": filename,
            "source_type": ext.replace(".", ""),
            "sections": sections,
            "section_order": list(range(len(sections))),
            "styling": styling,
            "field_mapping": self._build_field_mapping(sections, section_labels),
            "section_labels": section_labels,
            "layout": {
                "type": self._infer_layout(text),
                "logo_position": "top_right",
                "name_position": "top_left",
                "company_header": "center" if company_header else None,
                "company_footer": "center" if company_footer else None,
                "dates": "right_aligned",
                "section_dividers": True,
            },
            "company_header": company_header,
            "company_footer": company_footer,
            "preview_text": preview_text,
            "logos": logos,
            "logo_count": len(logos),
            # Intentionally blank: sample resume candidate names must not be copied.
            "header_text": "",
            "footer_text": "",
        }

    def _extract_document(self, ext: str, content: bytes) -> tuple[str, dict[str, Any], list[dict], str, str]:
        """Extract document content, styling, logos, header text, and footer text."""
        suffix = ext or ".tmp"
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(content)
                tmp_path = Path(tmp.name)

            if ext == ".pdf":
                return self._extract_pdf(tmp_path)
            if ext == ".docx":
                return self._extract_docx(tmp_path)
            return "", self._default_styling(), [], "", ""
        finally:
            if tmp_path:
                tmp_path.unlink(missing_ok=True)

    def _extract_pdf(self, path: Path) -> tuple[str, dict[str, Any], list[dict], str, str]:
        try:
            import pdfplumber
        except ImportError as exc:
            raise FormatExtractionError("pdfplumber is required to extract PDF formats") from exc

        pages: list[str] = []
        font_names: list[str] = []
        font_sizes: list[float] = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    pages.append(page_text)
                
                for char in page.chars[:300]:
                    if char.get("fontname"):
                        font_names.append(str(char["fontname"]))
                    if char.get("size"):
                        font_sizes.append(float(char["size"]))

        # Extract top/bottom page bands for company branding (not candidate bio).
        first_page_lines, last_page_lines = self._pdf_edge_lines(path, pages)
        header_text = self._pick_branding_lines(first_page_lines, region="header")
        footer_text = self._pick_branding_lines(last_page_lines, region="footer")
        if header_text:
            logger.info("Detected PDF header branding: %s", header_text[:120])
        if footer_text:
            logger.info("Detected PDF footer branding: %s", footer_text[:120])

        # Try multiple methods to extract logo (+ optional footer stamp)
        logos = self._extract_logo_from_pdf(path)

        body_size = round(sum(font_sizes) / len(font_sizes), 1) if font_sizes else 11
        font_family = self._clean_font_name(font_names[0]) if font_names else "Helvetica"
        styling = {
            "font_family": font_family,
            "font_size_header": max(14, int(body_size + 3)),
            "font_size_body": int(body_size) or 11,
        }
        return "\n".join(pages), styling, logos, header_text, footer_text
    
    def _extract_logo_from_pdf(self, path: Path) -> list[dict]:
        """Extract logo images from top header area of the first page."""
        logos: list[dict] = []
        logger.info(f"Starting logo extraction from PDF: {path}")
        
        # Method 1: Try PyMuPDF (fitz) for direct image extraction
        try:
            import fitz  # PyMuPDF
            import base64
            
            logger.info("Attempting PyMuPDF extraction...")
            doc = fitz.open(str(path))
            
            if len(doc) > 0:
                page = doc[0]
                page_h = float(page.rect.height or 0)
                header_cutoff = page_h * 0.55 if page_h > 0 else 400.0
                footer_floor = page_h * 0.72 if page_h > 0 else 550.0
                images = page.get_images(full=True)
                logger.info(f"Found {len(images)} images on first page")

                for img_index, img in enumerate(images):
                    try:
                        xref = img[0]
                        rects = page.get_image_rects(xref)
                        if not rects:
                            logger.debug(f"Skipping image {img_index}: no placement rect found")
                            continue
                        top_y = min(float(r.y0) for r in rects)
                        bottom_y = max(float(r.y1) for r in rects)
                        in_header = top_y <= header_cutoff
                        in_footer = bottom_y >= footer_floor
                        if not in_header and not in_footer:
                            logger.debug(
                                "Skipping image %s: outside header/footer (y0=%.1f y1=%.1f)",
                                img_index,
                                top_y,
                                bottom_y,
                            )
                            continue

                        base_image = doc.extract_image(xref)
                        image_bytes = base_image["image"]
                        image_ext = base_image["ext"]

                        if len(image_bytes) < 300:
                            logger.debug(f"Skipping small image {img_index}: {len(image_bytes)} bytes")
                            continue
                        if len(image_bytes) > 5_000_000:
                            logger.debug(f"Skipping large image {img_index}: {len(image_bytes)} bytes")
                            continue

                        image_bytes, image_ext = self._normalize_image_bytes(image_bytes, image_ext)
                        if not image_bytes:
                            continue

                        logo_b64 = base64.b64encode(image_bytes).decode("utf-8")
                        position = "footer_center" if in_footer and not in_header else "header_right"
                        source = "pymupdf_footer" if position.startswith("footer") else "pymupdf_header"
                        logos.append({
                            "data": f"data:image/{image_ext};base64,{logo_b64}",
                            "position": position,
                            "width": 150,
                            "height": 75,
                            "source": source,
                            "index": img_index,
                        })
                        logger.info(
                            "Extracted image %s (%s): %s, %s bytes",
                            img_index,
                            source,
                            image_ext,
                            len(image_bytes),
                        )
                        if len(logos) >= 4:
                            break
                    except Exception as img_err:
                        logger.warning(f"Failed to extract image {img_index}: {img_err}")
                        continue

                doc.close()
                if logos:
                    logger.info(f"PyMuPDF extraction successful: {len(logos)} logos")
                    return logos
        except ImportError:
            logger.warning("PyMuPDF (fitz) not available")
        except Exception as e:
            logger.error(f"PyMuPDF extraction failed: {e}")
        
        # Method 2: Try pdfplumber for embedded images
        try:
            import pdfplumber
            import base64
            from io import BytesIO
            from PIL import Image
            
            logger.info("Attempting pdfplumber image extraction...")
            with pdfplumber.open(str(path)) as pdf:
                if len(pdf.pages) > 0:
                    page = pdf.pages[0]
                    try:
                        im = page.to_image(resolution=150)
                        # Try to detect images in page objects
                        if hasattr(page, 'objects') and 'image' in page.objects:
                            for img_obj in page.objects['image'][:3]:
                                try:
                                    # Crop the image region
                                    bbox = (img_obj['x0'], img_obj['top'], 
                                           img_obj['x1'], img_obj['bottom'])
                                    cropped = im.original.crop(bbox)
                                    buffer = BytesIO()
                                    cropped.save(buffer, format='PNG')
                                    logo_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                                    logos.append({
                                        "data": f"data:image/png;base64,{logo_b64}",
                                        "position": "detected",
                                        "width": 150,
                                        "height": 75,
                                        "source": "pdfplumber"
                                    })
                                    logger.info(f"pdfplumber extracted image from bbox: {bbox}")
                                except Exception as crop_err:
                                    logger.debug(f"Failed to crop image: {crop_err}")
                    except Exception as page_err:
                        logger.warning(f"pdfplumber page processing failed: {page_err}")
                        
            if logos:
                logger.info(f"pdfplumber extraction successful: {len(logos)} logos")
                return logos
        except ImportError:
            logger.warning("pdfplumber image extraction not available")
        except Exception as e:
            logger.error(f"pdfplumber extraction failed: {e}")
        
        # Method 3: Screenshot-based extraction with better cropping
        try:
            from pdf2image import convert_from_path
            import base64
            from io import BytesIO
            from PIL import Image
            
            logger.info("Attempting pdf2image screenshot extraction...")
            pil_images = convert_from_path(str(path), first_page=1, last_page=1, dpi=200)
            
            if pil_images:
                img = pil_images[0]
                width, height = img.size
                logger.info(f"PDF page size: {width}x{height}")
                
                # Multiple crop strategies for logo detection
                crop_regions = [
                    # Top-right (most common for logos)
                    (width * 0.5, 0, width, height * 0.3, "top_right_wide"),
                    # Narrower top-right
                    (width * 0.7, 0, width, height * 0.2, "top_right_narrow"),
                    # Top-left (alternative)
                    (0, 0, width * 0.4, height * 0.25, "top_left"),
                    # Top center
                    (width * 0.3, 0, width * 0.7, height * 0.2, "top_center"),
                ]
                
                for left, top, right, bottom, region_name in crop_regions:
                    try:
                        left, top, right, bottom = int(left), int(top), int(right), int(bottom)
                        if right > left and bottom > top:
                            cropped = img.crop((left, top, right, bottom))
                            buffer = BytesIO()
                            cropped.save(buffer, format='PNG')
                            logo_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                            
                            # Only keep if it has content (not just white space)
                            if len(logo_b64) > 1000:  # Meaningful image
                                logos.append({
                                    "data": f"data:image/png;base64,{logo_b64}",
                                    "position": region_name,
                                    "width": right - left,
                                    "height": bottom - top,
                                    "source": "pdf2image_crop"
                                })
                                logger.info(f"pdf2image extracted from {region_name}: {len(logo_b64)} chars")
                                if len(logos) >= 2:
                                    break
                    except Exception as crop_err:
                        logger.debug(f"Crop {region_name} failed: {crop_err}")
                        continue
                
                if logos:
                    logger.info(f"pdf2image extraction successful: {len(logos)} logos")
                    return logos
        except ImportError:
            logger.warning("pdf2image not available")
        except Exception as e:
            logger.error(f"pdf2image extraction failed: {e}")
        
        logger.warning("No logos extracted from PDF")
        return logos

    def _extract_docx(self, path: Path) -> tuple[str, dict[str, Any], list[dict], str, str]:
        try:
            import docx
            from docx.oxml import parse_xml
            import base64
            from io import BytesIO
            from PIL import Image
        except ImportError as exc:
            raise FormatExtractionError("python-docx and Pillow are required to extract DOCX formats") from exc

        logger.info(f"Extracting DOCX format from: {path}")
        document = docx.Document(str(path))
        lines = [p.text.strip() for p in document.paragraphs if p.text.strip()]
        logos: list[dict] = self._extract_docx_header_logos(document)
        footer_logos = self._extract_docx_footer_logos(document)
        if footer_logos:
            logos.extend(footer_logos)
        if not logos:
            # Some templates place logo in top body area (not formal header part).
            logos = self._extract_docx_top_body_logos(document)

        if logos:
            logger.info(f"Extracted {len(logos)} logo(s) from DOCX")
        else:
            logger.warning("No logos found in DOCX")

        # Extract header text from DOCX headers
        header_text = ""
        try:
            for section in document.sections:
                if section.header:
                    header_paras = [p.text.strip() for p in section.header.paragraphs if p.text.strip()]
                    if header_paras:
                        header_text = " | ".join(header_paras[:3])
                        logger.info(f"Extracted DOCX header: {header_text[:100]}...")
                        break
        except Exception as header_err:
            logger.debug(f"Could not extract DOCX header: {header_err}")

        # Extract footer text from DOCX footers
        footer_text = ""
        try:
            for section in document.sections:
                if section.footer:
                    footer_paras = [p.text.strip() for p in section.footer.paragraphs if p.text.strip()]
                    if footer_paras:
                        footer_text = " | ".join(footer_paras[:3])
                        logger.info(f"Extracted DOCX footer: {footer_text[:100]}...")
                        break
        except Exception as footer_err:
            logger.debug(f"Could not extract DOCX footer: {footer_err}")

        # If no header/footer branding, carefully infer company block from body top lines.
        if not header_text and not footer_text and lines:
            inferred = self._infer_company_header("\n".join(lines[:12]))
            if inferred and inferred.get("lines"):
                header_text = " | ".join(inferred["lines"])
                logger.info("Inferred company branding from DOCX body top lines")

        normal_style = document.styles["Normal"]
        font = normal_style.font
        font_size = int(font.size.pt) if font.size else 11
        styling = {
            "font_family": font.name or "Calibri",
            "font_size_header": max(14, font_size + 3),
            "font_size_body": font_size,
            "font_size_name": max(18, font_size + 8),
            "margin_inches": 0.7,
        }
        logger.info(f"DOCX extraction complete: {len(lines)} text lines, {len(logos)} logos, header={bool(header_text)}, footer={bool(footer_text)}")
        return "\n".join(lines), styling, logos, header_text, footer_text

    def _extract_docx_header_logos(self, document: Any) -> list[dict]:
        """Extract only images referenced from DOCX header parts."""
        logos: list[dict] = []
        try:
            import base64
            from io import BytesIO
            from PIL import Image
        except Exception:
            return logos

        seen_rids: set[str] = set()
        try:
            for section in document.sections:
                header = section.header
                if not header:
                    continue
                blips = header._element.xpath(".//*[local-name()='blip']")  # nosec - trusted DOCX XML
                for blip in blips:
                    rid = blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
                    if not rid or rid in seen_rids:
                        continue
                    seen_rids.add(rid)
                    try:
                        part = header.part.related_parts[rid]
                        img_data = part.blob
                    except Exception:
                        continue
                    if not img_data or len(img_data) < 300 or len(img_data) > 5_000_000:
                        continue

                    ext = "png"
                    width, height = 150, 75
                    try:
                        img = Image.open(BytesIO(img_data))
                        width, height = img.size
                        ext = str((img.format or "PNG")).lower()
                        if ext == "jpg":
                            ext = "jpeg"
                        aspect_ratio = width / height if height else 0
                        if aspect_ratio < 0.25 or aspect_ratio > 12:
                            continue
                    except Exception:
                        normalized, ext = self._normalize_image_bytes(img_data, "png")
                        if not normalized:
                            continue
                        img_data = normalized

                    img_data, ext = self._normalize_image_bytes(img_data, ext)
                    if not img_data:
                        continue

                    logo_b64 = base64.b64encode(img_data).decode("utf-8")
                    logos.append(
                        {
                            "data": f"data:image/{ext};base64,{logo_b64}",
                            "position": "header_right",
                            "width": width,
                            "height": height,
                            "source": "docx_header",
                        }
                    )
                    if len(logos) >= 3:
                        return logos
        except Exception as exc:
            logger.warning(f"DOCX header logo extraction failed: {exc}")
        return logos

    def _extract_docx_footer_logos(self, document: Any) -> list[dict]:
        """Extract images from DOCX footer parts (company stamp / signature mark)."""
        logos: list[dict] = []
        try:
            import base64
            from io import BytesIO
            from PIL import Image
        except Exception:
            return logos

        seen_rids: set[str] = set()
        try:
            for section in document.sections:
                footer = section.footer
                if not footer:
                    continue
                blips = footer._element.xpath(".//*[local-name()='blip']")  # nosec - trusted DOCX XML
                for blip in blips:
                    rid = blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
                    if not rid or rid in seen_rids:
                        continue
                    seen_rids.add(rid)
                    try:
                        part = footer.part.related_parts[rid]
                        img_data = part.blob
                    except Exception:
                        try:
                            part = document.part.related_parts[rid]
                            img_data = part.blob
                        except Exception:
                            continue
                    if not img_data or len(img_data) < 300 or len(img_data) > 5_000_000:
                        continue
                    try:
                        img = Image.open(BytesIO(img_data))
                        width, height = img.size
                        aspect = width / height if height else 0
                        if aspect < 0.2 or aspect > 14:
                            continue
                        ext = str((img.format or "PNG")).lower()
                        if ext == "jpg":
                            ext = "jpeg"
                    except Exception:
                        continue
                    img_data, ext = self._normalize_image_bytes(img_data, ext)
                    if not img_data:
                        continue
                    logo_b64 = base64.b64encode(img_data).decode("utf-8")
                    logos.append(
                        {
                            "data": f"data:image/{ext};base64,{logo_b64}",
                            "position": "footer_center",
                            "width": width,
                            "height": height,
                            "source": "docx_footer",
                        }
                    )
                    if len(logos) >= 2:
                        return logos
        except Exception as exc:
            logger.warning(f"DOCX footer logo extraction failed: {exc}")
        return logos

    def _extract_docx_top_body_logos(self, document: Any) -> list[dict]:
        """Fallback: extract images in top body content (header-like area)."""
        logos: list[dict] = []
        try:
            import base64
            from io import BytesIO
            from PIL import Image
        except Exception:
            return logos

        seen_rids: set[str] = set()

        def add_logo_from_blip(blip: Any, source: str) -> bool:
            rid = blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
            if not rid or rid in seen_rids:
                return False
            seen_rids.add(rid)
            try:
                part = document.part.related_parts[rid]
                img_data = part.blob
            except Exception:
                return False
            if not img_data or len(img_data) < 300 or len(img_data) > 5_000_000:
                return False

            try:
                img = Image.open(BytesIO(img_data))
                width, height = img.size
                aspect_ratio = width / height if height else 0
                if aspect_ratio < 0.25 or aspect_ratio > 12:
                    return False
                ext = str((img.format or "PNG")).lower()
                if ext == "jpg":
                    ext = "jpeg"
            except Exception:
                return False

            img_data, ext = self._normalize_image_bytes(img_data, ext)
            if not img_data:
                return False

            logo_b64 = base64.b64encode(img_data).decode("utf-8")
            logos.append(
                {
                    "data": f"data:image/{ext};base64,{logo_b64}",
                    "position": "header_right",
                    "width": width,
                    "height": height,
                    "source": source,
                }
            )
            return len(logos) >= 3

        try:
            for para in list(document.paragraphs)[:12]:
                blips = para._element.xpath(".//*[local-name()='blip']")  # nosec - trusted DOCX XML
                for blip in blips:
                    if add_logo_from_blip(blip, "docx_top_body"):
                        return logos

            for table in list(document.tables)[:4]:
                blips = table._element.xpath(".//*[local-name()='blip']")  # nosec - trusted DOCX XML
                for blip in blips:
                    if add_logo_from_blip(blip, "docx_top_table"):
                        return logos

            if not logos:
                for rel in document.part.related_parts.values():
                    content_type = str(getattr(rel, "content_type", "") or "")
                    if "image" not in content_type:
                        continue
                    img_data = getattr(rel, "blob", None)
                    if not img_data or len(img_data) < 300:
                        continue
                    try:
                        img = Image.open(BytesIO(img_data))
                        width, height = img.size
                        if width < 40 or height < 20 or (width > 1200 and height > 1200):
                            continue
                        aspect = width / height if height else 0
                        if aspect < 0.25 or aspect > 12:
                            continue
                        ext = str((img.format or "PNG")).lower()
                        if ext == "jpg":
                            ext = "jpeg"
                    except Exception:
                        continue
                    img_data, ext = self._normalize_image_bytes(img_data, ext)
                    if not img_data:
                        continue
                    logo_b64 = base64.b64encode(img_data).decode("utf-8")
                    logos.append(
                        {
                            "data": f"data:image/{ext};base64,{logo_b64}",
                            "position": "header_right",
                            "width": width,
                            "height": height,
                            "source": "docx_package_image",
                        }
                    )
                    break
        except Exception as exc:
            logger.warning(f"DOCX top-body logo extraction failed: {exc}")
        return logos

    def _infer_sections(self, text: str) -> list[str]:
        sections, _labels = self._infer_sections_with_labels(text)
        return sections

    def _infer_sections_with_labels(self, text: str) -> tuple[list[str], dict[str, str]]:
        """Detect section order and the exact heading labels used in the template."""
        found: list[str] = []
        labels: dict[str, str] = {}
        seen = set()
        for raw_line in (text or "").splitlines()[:250]:
            line = re.sub(r"\s+", " ", raw_line).strip()
            if not line or len(line) > 90:
                continue

            normalized = re.sub(r"[^a-z0-9 ]+", "", line.lower()).strip()
            for canonical, aliases in SECTION_ALIASES.items():
                if canonical in seen:
                    continue
                if any(self._heading_matches(normalized, alias) for alias in aliases):
                    found.append(canonical)
                    seen.add(canonical)
                    clean_label = re.sub(r"[:：]+$", "", line).strip()
                    if clean_label:
                        labels[canonical] = clean_label.upper()

        if "header" not in seen:
            found.insert(0, "header")
            seen.add("header")

        if not found:
            return list(DEFAULT_SECTIONS), {}
        return found, labels

    def _heading_matches(self, line: str, alias: str) -> bool:
        alias_norm = re.sub(r"[^a-z0-9 ]+", "", alias.lower()).strip()
        return line == alias_norm or line.startswith(f"{alias_norm} ")

    def _build_field_mapping(
        self,
        sections: list[str],
        section_labels: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Map canonical sections to human-readable titles for the generated DOCX."""
        defaults = {
            "summary": "PROFESSIONAL SUMMARY",
            "experience": "PROFESSIONAL EXPERIENCE",
            "education": "EDUCATION",
            "skills": "TECHNICAL SKILLS",
            "projects": "PROJECTS",
            "certifications": "CERTIFICATIONS",
            "achievements": "ACHIEVEMENTS",
            "languages": "LANGUAGES",
        }
        mapping = {
            "name": "Name",
            "email": "Email",
            "phone": "Phone",
            "location": "Location",
        }
        labels = section_labels or {}
        for section in sections:
            if section == "header":
                continue
            label = labels.get(section) or defaults.get(section) or section.replace("_", " ").title()
            if "." in str(label):
                label = defaults.get(section) or section.replace("_", " ").title()
            mapping[section] = label
        return mapping

    def _company_sign_from_text(self, text: str | None) -> dict[str, Any] | None:
        """Build company footer/header sign from extracted header/footer text."""
        raw = (text or "").strip()
        if not raw:
            return None

        parts = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\s*\|\s*|\n+", raw) if p.strip()]
        if not parts:
            return None

        joined = " ".join(parts).lower()
        if any(marker in joined for marker in ("professional summary", "work experience", "education")):
            return None

        company_markers = (
            "inc",
            "llc",
            "ltd",
            "corp",
            "company",
            "pvt",
            "solutions",
            "technologies",
            "consulting",
            "www.",
            "http",
            "@",
            "email",
            "blvd",
            "suite",
            "street",
            "avenue",
            "road",
        )
        looks_branded = any(m in joined for m in company_markers) or len(parts) >= 2
        if not looks_branded:
            return None

        lines = parts[:3]
        return {
            "name": lines[0],
            "address": lines[1] if len(lines) > 1 else "",
            "contact": lines[2] if len(lines) > 2 else "",
            "lines": lines,
        }

    def _normalize_image_bytes(self, image_bytes: bytes, ext: str | None = None) -> tuple[bytes | None, str]:
        """Convert embedded images to PNG/JPEG suitable for python-docx."""
        from io import BytesIO

        try:
            from PIL import Image
        except Exception:
            return image_bytes, (ext or "png").lower().replace("jpg", "jpeg")

        try:
            img = Image.open(BytesIO(image_bytes))
            fmt = str((img.format or ext or "PNG")).upper()
            if fmt == "JPG":
                fmt = "JPEG"
            if fmt in {"PNG", "JPEG"}:
                buffer = BytesIO()
                save_fmt = fmt
                if save_fmt == "JPEG" and img.mode in {"RGBA", "P"}:
                    img = img.convert("RGB")
                img.save(buffer, format=save_fmt)
                return buffer.getvalue(), save_fmt.lower()

            buffer = BytesIO()
            if img.mode not in {"RGB", "RGBA"}:
                img = img.convert("RGBA")
            img.save(buffer, format="PNG")
            return buffer.getvalue(), "png"
        except Exception:
            cleaned_ext = (ext or "png").lower().replace("jpg", "jpeg")
            if cleaned_ext in {"png", "jpeg", "gif"}:
                return image_bytes, cleaned_ext
            return None, "png"

    def _infer_layout(self, text: str) -> str:
        lines = [line for line in (text or "").splitlines() if line.strip()]
        short_line_ratio = 0
        if lines:
            short_line_ratio = len([line for line in lines if len(line.strip()) < 35]) / len(lines)
        return "two_column" if short_line_ratio > 0.55 and len(lines) > 20 else "single_column"

    def _infer_company_header(self, text: str) -> dict[str, Any] | None:
        """Detect company branding lines at the top of an uploaded template."""
        lines = [re.sub(r"\s+", " ", line).strip() for line in (text or "").splitlines()]
        lines = [line for line in lines if line][:12]
        if not lines:
            return None

        company_markers = (
            "inc.",
            "llc",
            "ltd",
            "corp",
            "company",
            "blvd",
            "suite",
            "avenue",
            "street",
            "www.",
            "http",
            "email:",
            "@",
        )
        section_markers = (
            "summary",
            "experience",
            "education",
            "skills",
            "professional",
            "objective",
            "projects",
        )

        selected: list[str] = []
        for line in lines:
            lower = line.lower()
            if any(marker in lower for marker in section_markers):
                break
            # Skip likely candidate contact lines that are only email/phone without company cues.
            looks_company = any(marker in lower for marker in company_markers)
            looks_address = bool(re.search(r"\b\d{5}(?:-\d{4})?\b", line)) or "," in line
            if looks_company or (looks_address and len(selected) > 0):
                selected.append(line)
            elif not selected and len(line.split()) <= 5 and line[0].isupper():
                # Possible company name line before address/contact.
                selected.append(line)
            if len(selected) >= 3:
                break

        if len(selected) < 2:
            # Allow a single strong company line (Inc/LLC/www/@/address cues).
            if len(selected) == 1:
                lower = selected[0].lower()
                strong = any(marker in lower for marker in company_markers) or bool(
                    re.search(r"\b\d{5}(?:-\d{4})?\b", selected[0])
                )
                if not strong:
                    return None
            else:
                return None

        return {
            "name": selected[0],
            "address": selected[1] if len(selected) > 1 else "",
            "contact": selected[2] if len(selected) > 2 else "",
            "lines": selected[:3],
        }

    def _pdf_edge_lines(self, path: Path, pages: list[str]) -> tuple[list[str], list[str]]:
        """Collect short lines from the top and bottom of the first/last PDF pages."""
        first_page_lines: list[str] = []
        last_page_lines: list[str] = []

        try:
            import fitz

            doc = fitz.open(str(path))
            if len(doc) > 0:
                page = doc[0]
                page_h = float(page.rect.height or 1)
                blocks = page.get_text("blocks") or []
                top_blocks = []
                bottom_blocks = []
                for block in blocks:
                    if len(block) < 5:
                        continue
                    _x0, y0, _x1, y1, text = block[:5]
                    text = str(text or "").strip()
                    if not text:
                        continue
                    if float(y0) <= page_h * 0.22:
                        top_blocks.append((float(y0), text))
                    if float(y1) >= page_h * 0.78:
                        bottom_blocks.append((float(y0), text))
                top_blocks.sort(key=lambda item: item[0])
                bottom_blocks.sort(key=lambda item: item[0])
                for _, text in top_blocks:
                    first_page_lines.extend(
                        [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
                    )
                for _, text in bottom_blocks:
                    last_page_lines.extend(
                        [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
                    )
            doc.close()
        except Exception as exc:
            logger.debug("PyMuPDF edge-line extraction unavailable: %s", exc)

        if not first_page_lines and pages:
            first_page_lines = [
                re.sub(r"\s+", " ", line).strip()
                for line in pages[0].splitlines()
                if line.strip()
            ][:8]
        if not last_page_lines and pages:
            source = pages[-1]
            last_page_lines = [
                re.sub(r"\s+", " ", line).strip()
                for line in source.splitlines()
                if line.strip()
            ][-8:]
        return first_page_lines, last_page_lines

    def _pick_branding_lines(self, lines: list[str], region: str = "header") -> str:
        """Keep company-like lines; drop candidate names, section titles, page numbers."""
        if not lines:
            return ""

        section_markers = (
            "summary",
            "experience",
            "education",
            "skills",
            "professional",
            "objective",
            "projects",
            "certification",
            "achievement",
        )
        company_markers = (
            "inc",
            "llc",
            "ltd",
            "corp",
            "company",
            "pvt",
            "solutions",
            "technologies",
            "consulting",
            "www.",
            "http",
            "@",
            "email",
            "blvd",
            "suite",
            "street",
            "avenue",
            "road",
            "confidential",
            "copyright",
            "©",
        )

        selected: list[str] = []
        for line in lines:
            clean = re.sub(r"\s+", " ", line).strip()
            if not clean or len(clean) > 120:
                continue
            lower = clean.lower()
            if clean.isdigit() or re.fullmatch(r"page\s*\d+(\s*of\s*\d+)?", lower):
                continue
            if any(marker in lower for marker in section_markers):
                continue
            looks_company = any(marker in lower for marker in company_markers)
            looks_address = bool(re.search(r"\b\d{5}(?:-\d{4})?\b", clean)) or (
                "," in clean and any(ch.isdigit() for ch in clean)
            )
            short_brand = len(clean.split()) <= 6 and clean[0].isupper()
            if region == "footer":
                if looks_company or looks_address or ("www." in lower or "@" in lower):
                    selected.append(clean)
            else:
                if looks_company or looks_address or short_brand:
                    selected.append(clean)
            if len(selected) >= 3:
                break

        if not selected:
            return ""
        if len(selected) == 1:
            joined = selected[0].lower()
            if not any(marker in joined for marker in company_markers) and not re.search(r"\d", selected[0]):
                return ""
        return " | ".join(selected[:3])

    def _build_format_preview(
        self,
        text: str,
        sections: list[str],
        section_labels: dict[str, str] | None = None,
    ) -> str:
        """Sanitized layout hint for the LLM (headings only — no sample person content)."""
        labels = section_labels or {}
        heading_bits = []
        for section in sections:
            if section == "header":
                continue
            label = labels.get(section) or section.replace("_", " ").upper()
            heading_bits.append(str(label).upper())
        layout_hint = "Section order: " + " → ".join(heading_bits[:10]) if heading_bits else ""

        heading_lines: list[str] = []
        for line in (text or "").splitlines():
            clean = re.sub(r"\s+", " ", line).strip()
            if not clean or len(clean) > 48:
                continue
            letters = re.sub(r"[^A-Za-z]", "", clean)
            if len(letters) < 4:
                continue
            upper_ratio = sum(1 for ch in letters if ch.isupper()) / max(len(letters), 1)
            if upper_ratio >= 0.7 or clean.isupper():
                heading_lines.append(clean.upper())
            if len(heading_lines) >= 10:
                break
        parts = []
        if layout_hint:
            parts.append(layout_hint)
        if heading_lines:
            parts.append("Template headings: " + " | ".join(heading_lines))
        return self._preview(" || ".join(parts))

    def _preview(self, text: str) -> str:
        return re.sub(r"\s+", " ", (text or "").strip())[:700]

    def _clean_font_name(self, font_name: str) -> str:
        cleaned = font_name.split("+")[-1].replace("-", " ").strip()
        return cleaned or "Helvetica"

    def _default_styling(self) -> dict[str, Any]:
        return {
            "font_family": "Calibri",
            "font_size_header": 12,
            "font_size_body": 11,
            "font_size_name": 20,
            "margin_inches": 0.7,
        }
