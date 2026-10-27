import pymupdf as fitz

from app.services.pdf_parser import _strip_repeated_header_footer, extract_text_from_document


def test_repeated_header_kept_on_first_page():
    header = "Jordan Rivera | jordan@example.com"
    pages = [f"{header}\nExperience\nA", f"{header}\nB", f"{header}\nC"]
    out = _strip_repeated_header_footer(pages)
    assert out[0].startswith("Jordan Rivera")
    assert "Jordan Rivera" not in out[1]
    assert "Jordan Rivera" not in out[2]


def test_link_annotations_extracted(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 60), "Jordan Rivera", fontsize=14)
    page.insert_text((50, 80), "LinkedIn | GitHub", fontsize=10)
    page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(48, 70, 95, 84), "uri": "https://linkedin.com/in/jrivera"})
    page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(100, 70, 140, 84), "uri": "https://github.com/jrivera"})
    path = tmp_path / "links.pdf"
    doc.save(path)
    text = extract_text_from_document(str(path))
    assert "linkedin.com/in/jrivera" in text
    assert "github.com/jrivera" in text


def test_repair_keeps_mixed_case_names_and_urls():
    from app.services.pdf_parser import repair_collapsed_spaces

    line = (
        "Optimized cloud infrastructure on AWS SageMaker with StoreKit, HealthKit, DeepLearning.AI, "
        "RetrieveIQ and LinkedIn https://github.com/jrivera"
    )
    out = repair_collapsed_spaces(line)
    for word in ("SageMaker", "StoreKit", "HealthKit", "DeepLearning.AI", "RetrieveIQ", "LinkedIn",
                 "https://github.com/jrivera"):
        assert word in out


def test_repair_still_splits_long_jams():
    from app.services.pdf_parser import repair_collapsed_spaces

    out = repair_collapsed_spaces("ExperiencedSoftwareEngineerBuildingScalableSystems for retail customers today")
    assert "Experienced Software Engineer" in out


def test_mailto_links_not_duplicated(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 60), "jordan.rivera@example.com", fontsize=10)
    page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(48, 50, 200, 64), "uri": "mailto:jordan.rivera@example.com"})
    path = tmp_path / "mail.pdf"
    doc.save(path)
    text = extract_text_from_document(str(path))
    assert text.count("jordan.rivera@example.com") == 1
