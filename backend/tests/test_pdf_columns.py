from app.services.pdf_parser import extract_text_from_document


def _in_order(text: str, *needles: str) -> bool:
    idx = [text.index(n) for n in needles]
    return idx == sorted(idx)


def test_two_column_sections_not_interleaved(fixtures):
    t = extract_text_from_document(str(fixtures["two_column_pdf"]))
    assert _in_order(t, "SKILLS", "Python, Go, SQL", "EDUCATION", "B.S. Physics", "Tech University 2014")
    assert _in_order(t, "EXPERIENCE", "Data Engineer | Globex", "Built streaming ETL", "Analyst | Initech",
                     "Automated weekly finance")
    assert "SKILLS EXPERIENCE" not in t
    assert "EDUCATION Analyst" not in t
    assert t.index("PUBLICATIONS") > t.index("Automated weekly finance")


def test_sidebar_with_full_width_header_and_footer(fixtures):
    t = extract_text_from_document(str(fixtures["sidebar_pdf"]))
    assert _in_order(t, "PROFESSIONAL SUMMARY", "Data engineer with ten years")
    assert _in_order(t, "Data Engineer | Globex", "Built streaming ETL", "Analyst | Initech", "Automated weekly")
    assert _in_order(t, "SKILLS", "Python", "Spark", "LANGUAGES", "Spanish")
    assert t.index("CERTIFICATIONS") > max(t.index("Spanish"), t.index("Automated weekly"))
    assert _in_order(t, "CERTIFICATIONS", "AWS Certified Data Engineer")


def test_right_aligned_dates_are_not_a_column(tmp_path):
    import pymupdf as fitz

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    rows = [
        ("Data Engineer, Globex", "Mar 2019 - Present"),
        ("Built streaming ETL pipelines for logistics data.", ""),
        ("Analyst, Initech", "Jan 2015 - Feb 2019"),
        ("Automated weekly finance reports for leadership.", ""),
        ("Intern, Umbrella Labs", "Jun 2014 - Aug 2014"),
        ("Wrote test harnesses for lab equipment.", ""),
    ]
    y = 80.0
    for left, right in rows:
        page.insert_text((50, y), left, fontsize=10)
        if right:
            width = fitz.get_text_length(right, fontsize=10)
            page.insert_text((560 - width, y), right, fontsize=10)
        y += 14
    path = tmp_path / "dates.pdf"
    doc.save(path)
    t = extract_text_from_document(str(path))
    assert "Data Engineer, Globex Mar 2019 - Present" in t
    assert "Analyst, Initech Jan 2015 - Feb 2019" in t
