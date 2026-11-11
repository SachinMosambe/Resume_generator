from pathlib import Path

from app.services.detailed_resume_parser import parse_resume_detailed

CASES = Path(__file__).parent / "fixtures" / "golden" / "cases"


def _load(name: str) -> str:
    return (CASES / name).read_text(encoding="utf-8")


def test_dice_wrapper_recovers_roles_and_bullets():
    data = parse_resume_detailed(None, _load("dice_wrapper.txt"))
    assert len(data["experience"]) >= 1
    companies = " ".join(r.get("company") or "" for r in data["experience"])
    assert "amazon" in companies.lower()
    bullets = " ".join(b for r in data["experience"] for b in (r.get("description") or []))
    assert "onboarding" in bullets.lower()
    assert data.get("parse_meta", {}).get("confidence", 0) >= 0.55


def test_paren_title_split_header():
    data = parse_resume_detailed(None, _load("paren_title.txt"))
    assert len(data["experience"]) >= 1
    role = data["experience"][0]
    assert "Northwind" in (role.get("company") or "")
    assert (role.get("title") or "") == "Platform Engineer"
    assert "billing service" in " ".join(role.get("description") or [])
    assert data["name"] == "Jordan Hale"


def test_bullet_only_preserves_text():
    data = parse_resume_detailed(None, _load("bullet_only.txt"))
    assigned = [b for r in data["experience"] for b in (r.get("description") or [])]
    unassigned = data.get("unassigned_experience_bullets") or []
    assert assigned or unassigned
    blob = " ".join(assigned + unassigned).lower()
    assert "onboarding checklist" in blob and "weekly finance close" in blob
    if not data["experience"]:
        assert "expected_experience_missing" in (data.get("parse_meta") or {}).get("reasons", []) or (
            "ambiguous_role_assignment" in (data.get("parse_meta") or {}).get("reasons", [])
        )


def test_education_only_ok_without_roles():
    data = parse_resume_detailed(None, _load("education_only.txt"))
    assert data["experience"] == []
    assert data.get("education")
    reasons = (data.get("parse_meta") or {}).get("reasons") or []
    assert "expected_experience_missing" not in reasons


def test_clean_conventional_control():
    data = parse_resume_detailed(None, _load("clean_conventional.txt"))
    assert len(data["experience"]) == 1
    assert data["experience"][0].get("company")
    assert data["name"] == "Alex Example"
    assert data["parse_meta"]["confidence"] >= 0.9


def test_tech_token_name_rejected():
    text = "React Native.\nEXPERIENCE\nAcme Inc\nEngineer 2020 - Present\n• built apps\nSKILLS\nReact Native, Python\n"
    data = parse_resume_detailed(None, text)
    assert (data.get("name") or "").lower().strip(". ") != "react native"


def test_emdash_company_title_dates_header():
    data = parse_resume_detailed(None, _load("emdash_header.txt"))
    assert len(data["experience"]) == 1
    role = data["experience"][0]
    assert role["company"] == "Fabrikam Studio"
    assert role["title"] == "Designer"
    assert "settings screens" in " ".join(role["description"])


def test_date_only_headers_keep_bullets_for_review():
    data = parse_resume_detailed(None, _load("bullet_only_dated.txt"))
    assert data["experience"] == []
    unassigned = " ".join(data.get("unassigned_experience_bullets") or []).lower()
    assert "weekly sales report" in unassigned and "monthly books" in unassigned
    assert "ambiguous_role_assignment" in data["parse_meta"]["reasons"]


def test_bullet_only_flags_review_reason():
    data = parse_resume_detailed(None, _load("bullet_only.txt"))
    assert data["experience"] == []
    assert len(data["unassigned_experience_bullets"]) == 3
    assert "ambiguous_role_assignment" in data["parse_meta"]["reasons"]


def test_title_only_experience_role_recovered():
    data = parse_resume_detailed(None, _load("title_only.txt"))
    assert len(data["experience"]) >= 1
    role = data["experience"][0]
    assert role["title"] == "Product Designer"
    # No employer is stated in the source, so none may be invented.
    assert (role.get("company") or "") == ""
    assert "settings screens" in " ".join(role["description"])
    assert not data.get("unassigned_experience_bullets")


def test_title_only_requires_following_bullet():
    text = "Casey Example\nEXPERIENCE\nProduct Designer\nSome free text without bullets here.\nEDUCATION\nB.A. Design\n"
    data = parse_resume_detailed(None, text)
    assert data["experience"] == []


def test_sentence_line_before_bullets_is_not_a_title():
    text = (
        "Riley Quinn\nEXPERIENCE\nManaged a team of analysts and led the close process.\n"
        "• Documented the weekly finance close.\nSKILLS\nExcel\n"
    )
    data = parse_resume_detailed(None, text)
    assert data["experience"] == []


# ─── Task 3: additional zero-role layouts ────────────────────────────────


def _roles_text(data):
    return " ".join(
        f"{r.get('company') or ''} {r.get('title') or ''} {r.get('duration') or ''} "
        + " ".join(r.get("description") or [])
        for r in data["experience"]
    )


def test_dice_work_history_list_recovers_title_and_employer():
    data = parse_resume_detailed(None, _load("dice_work_history_list.txt"))
    pairs = {(r["title"], r["company"]) for r in data["experience"]}
    assert ("Senior ERP Consultant", "Contoso Logistics") in pairs
    assert ("Applications Manager", "Fabrikam Gardening") in pairs
    # A PDF line wrap ("Holdings,\nLlc") is rejoined.
    assert ("Business Systems Analyst", "Adatum Holdings, Llc") in pairs
    first = next(r for r in data["experience"] if r["company"] == "Contoso Logistics")
    assert "2019" in first["duration"]
    # Nothing is invented: no bullets, no technologies.
    assert all(not r.get("description") for r in data["experience"])


def test_dice_work_history_list_does_not_guess_ambiguous_split():
    data = parse_resume_detailed(None, _load("dice_work_history_list.txt"))
    # "Director Of Sales & Marketing Northwind Plastics" has no safe title/employer split.
    for role in data["experience"]:
        assert "Northwind" not in (role.get("title") or "")
        assert "Director" not in (role.get("company") or "")
    unassigned = " ".join(data.get("unassigned_experience_bullets") or [])
    assert "Northwind Plastics" in unassigned
    assert "ambiguous_role_assignment" in data["parse_meta"]["reasons"]


def test_work_history_skill_list_is_not_experience():
    text = (
        "Pat Doe\npat@example.com\nWork History\n• Python\n• SQL\n• Kubernetes\nSkills\n• Python\n"
    )
    data = parse_resume_detailed(None, text)
    assert data["experience"] == []


def test_portfolio_client_engagements_heading_maps_to_experience():
    data = parse_resume_detailed(None, _load("portfolio_client_engagements.txt"))
    assert len(data["experience"]) == 2
    first, second = data["experience"]
    assert first["company"] == "Contoso Media"
    assert first["title"] == "Content Strategy Lead"
    assert "Present" in first["duration"]
    assert "editorial calendar" in " ".join(first["description"])
    assert second["company"] == "Fabrikam Learning"
    assert "Content Strategist" in second["title"]
    # The mapped section is not rendered a second time.
    assert not data.get("projects")
    assert not any("engagement" in (s.get("title") or "").lower() for s in data["additional_sections"])


def test_portfolio_content_experience_heading_with_split_lines():
    data = parse_resume_detailed(None, _load("portfolio_content_experience.txt"))
    assert len(data["experience"]) == 2
    first = data["experience"][0]
    assert first["company"] == "Adatum Studios"
    assert first["title"] == "Head of Content Programs"
    assert "executive event recap" in " ".join(first["description"])
    assert data["experience"][1]["company"] == "Litware Events"
    # Skills block above the heading is not swallowed into a role.
    assert "Storytelling" not in _roles_text(data)


def test_projects_heading_without_job_history_stays_projects():
    data = parse_resume_detailed(None, _load("clean_with_projects.txt"))
    assert len(data["experience"]) == 1
    assert data["projects"]


def test_projects_heading_with_dated_employers_is_job_history():
    text = (
        "Lee Park\nlee@example.com\nSKILLS\nPython\n"
        "PROJECT EXPERIENCE\nAcme Cloud — Platform Engineer | Jan 2020 - Dec 2022\n"
        "• Built the deploy pipeline.\n"
        "Beta Works — Developer | Feb 2017 - Dec 2019\n• Wrote the billing API.\n"
        "EDUCATION\nB.S. Example State\n"
    )
    data = parse_resume_detailed(None, text)
    assert [r["company"] for r in data["experience"]] == ["Acme Cloud", "Beta Works"]
    assert not data["projects"]


def test_dense_bullet_prefixed_headers_become_roles():
    data = parse_resume_detailed(None, _load("dense_bullet_headers.txt"))
    assert len(data["experience"]) == 2
    first, second = data["experience"]
    assert first["company"] == "Globex Retail"
    assert first["title"] == "Lead Database Administrator"
    assert "Present" in first["duration"]
    assert "maintenance plans" in " ".join(first["description"])
    assert second["company"] == "Initech Systems"
    assert second["location"] == "Dallas, TX"
    assert first["location"] == "Austin, TX"
    assert second["title"] == "Database Administrator"
    # Opening intro bullets (no heading above them) become the summary, not the headline.
    assert "backup design" in data["summary"] and "ten years" in data["summary"]
    assert not data["headline"].startswith("•")
    # The title line is not repeated as a bullet.
    assert "Database Administrator" not in first["description"]
    assert "Database Administrator" not in second["description"]


def test_bullet_with_year_range_is_not_a_header():
    text = (
        "Sam Roe\nEXPERIENCE\nAcme Corp | Engineer | 2019 - Present\n"
        "• Led the migration from 2017 - 2019 across three teams and many services.\n"
        "• Built the audit tooling.\nEDUCATION\nB.S. Example\n"
    )
    data = parse_resume_detailed(None, text)
    assert len(data["experience"]) == 1
    assert len(data["experience"][0]["description"]) == 2


def test_company_client_role_duration_labels_with_apostrophe_years():
    data = parse_resume_detailed(None, _load("labeled_company_role_duration.txt"))
    assert len(data["experience"]) == 2
    first, second = data["experience"]
    assert first["company"].startswith("Contoso Consulting")
    assert first["title"] == "Senior Software Architect"
    assert "23" in first["duration"] and "24" in first["duration"]
    assert "Wells Example Bank" in (first.get("project") or "")
    assert "payments microservice" in " ".join(first["description"])
    assert second["company"].startswith("Fabrikam Systems")
    assert second["title"] == "Software Engineer"
    assert "REST services" in " ".join(second["description"])


def test_bullet_company_designation_duration_without_colons():
    data = parse_resume_detailed(None, _load("labeled_bullet_company_designation.txt"))
    assert len(data["experience"]) == 2
    first, second = data["experience"]
    assert first["company"].startswith("Photon Example Inc")
    assert first["title"] == "Technical Lead"
    assert "Till" in first["duration"] or "Present" in first["duration"]
    assert second["company"].startswith("Mundio Example")
    assert second["title"] == "Senior Android Developer"


def test_role_line_with_inline_date_and_project_line():
    data = parse_resume_detailed(None, _load("role_line_date_project.txt"))
    assert len(data["experience"]) == 2
    first, second = data["experience"]
    assert first["title"] == "Senior Full Stack Engineer"
    assert "24" in first["duration"] and "Present" in first["duration"]
    assert "Example Freight" in (first.get("project") or "")
    # Nothing is invented: a project/client line is not promoted to the employer.
    assert (first.get("company") or "") == ""
    assert "microservices" in " ".join(first["description"])
    assert second["title"] == "Software Engineer"


def test_apostrophe_and_till_date_ranges_in_conventional_header():
    text = (
        "Kim Lau\nEXPERIENCE\nQA ANALYST Peoples Group APRIL’22 – DEC’23\n"
        "• Automated the loan workflow regression suite.\n"
        "Test Engineer, Globex Corp Jan'18 – Till Date\n• Wrote the API tests.\n"
        "EDUCATION\nB.S. Example\n"
    )
    data = parse_resume_detailed(None, text)
    assert len(data["experience"]) == 2
    assert "22" in data["experience"][0]["duration"]
    assert "Till" in data["experience"][1]["duration"]


def test_prose_apostrophe_year_is_not_a_date_range():
    text = "Sam Roe\nEXPERIENCE\nAcme Corp\nEngineer 2020 - Present\n• Shipped the '19 launch plan to 40 teams.\nEDUCATION\nB.S. X\n"
    data = parse_resume_detailed(None, text)
    assert len(data["experience"]) == 1
    assert "launch plan" in " ".join(data["experience"][0]["description"])


def test_projects_sublist_does_not_replace_employers_found_elsewhere():
    text = (
        "Vic Jay\nvic@example.com\nSKILLS\nJava\n"
        "Acme Cloud, Austin, TX\nSenior Developer Jan 2020 - Present\n• Built the billing service.\n"
        "Beta Works, Dallas, TX\nDeveloper Feb 2016 - Dec 2019\n• Wrote the claims API.\n"
        "Projects:\n"
        "Gamma Retail — Developer | Jan 2012 - Dec 2015\n• Built the storefront.\n"
        "EDUCATION\nB.S. Example State\n"
    )
    data = parse_resume_detailed(None, text)
    companies = [r["company"] for r in data["experience"]]
    assert "Acme Cloud" in " ".join(companies) and "Beta Works" in " ".join(companies)


def test_date_only_line_after_company_and_title_lines():
    text = (
        "Al Bo\nEXPERIENCE\nAcme Corp\nSenior Engineer\n2020 - Present\n• Built the thing.\n"
        "Beta Inc\nAnalyst\n2017 - 2020\n• Closed the books.\nEDUCATION\nB.S. Example\n"
    )
    data = parse_resume_detailed(None, text)
    pairs = [(r["company"], r["title"], r["duration"]) for r in data["experience"]]
    assert pairs == [("Acme Corp", "Senior Engineer", "2020 - Present"), ("Beta Inc", "Analyst", "2017 - 2020")]


def test_title_date_company_order_with_date_only_line():
    text = "Al Bo\nEXPERIENCE\nSenior Engineer\n2020 - Present\nAcme Corp\n• Built the thing.\nEDUCATION\nB.S. Example\n"
    data = parse_resume_detailed(None, text)
    role = data["experience"][0]
    assert (role["company"], role["title"]) == ("Acme Corp", "Senior Engineer")
    assert "Acme Corp" not in role["description"]


def test_date_only_line_never_becomes_the_employer():
    text = "Al Bo\nEXPERIENCE\nAcme Corp\n2020 - Present\n• Built the thing.\nEDUCATION\nB.S. Example\n"
    data = parse_resume_detailed(None, text)
    assert data["experience"][0]["company"] == "Acme Corp"


def test_pipe_separated_labels_and_bracketed_dates():
    text = (
        "Bo Li\nbo@example.com\nEXPERIENCE\n"
        "Company: Acme Tech | Role: Senior Java Developer\nDuration: May 2023 – Present\n"
        "• Built the billing service.\n"
        "Company: Beta Soft (Feb 2020 to Oct 2022)\nRole: Business Analyst [Nov 2019 to Oct 2022]\n"
        "• Wrote the specs.\nEDUCATION\nB.S. Example\n"
    )
    data = parse_resume_detailed(None, text)
    first, second = data["experience"]
    assert (first["company"], first["title"]) == ("Acme Tech", "Senior Java Developer")
    assert "Present" in first["duration"]
    assert second["company"] == "Beta Soft"
    assert second["title"] == "Business Analyst"


def test_parenthesised_gap_note_does_not_swallow_next_employer():
    text = (
        "Hal Sid\nWork Experience\nOctober 2023 - Feb2024 (Personal Time off)\nCanada Life\n"
        "Business System Analyst (March 2023- September2023)\nPublic Service Health Care Plan\n"
        "• Analyzed API needs.\nBank Of Montreal, Toronto\nBusiness Analyst (March2021- February 2023)\n"
        "• Documented requirements.\nEDUCATION\nB.S. Example\n"
    )
    data = parse_resume_detailed(None, text)
    titles = [r["title"] for r in data["experience"]]
    assert "Business Analyst" in titles and "Business System Analyst" in titles


# --- Safe zero-role edge wave ---


def test_letter_spaced_dates_become_recoverable_durations():
    data = parse_resume_detailed(None, _load("letter_spaced_dates.txt"))
    assert len(data["experience"]) == 2
    first, second = data["experience"]
    assert first["company"] == "Northwind Analytics"
    assert first["title"] == "Senior Data Analyst"
    assert "2023" in first["duration"] and "PRESENT" in first["duration"].upper()
    assert "weekly revenue dashboard" in " ".join(first["description"])
    assert second["company"] == "Globex Insights"
    assert "2020" in second["duration"] and "2023" in second["duration"]


def test_letter_spaced_dates_single_space_word_gaps():
    text = (
        "Al Bo\nEXPERIENCE\nAcme Corp\nEngineer A U G U S T 2 0 2 3 - P R E S E N T\n"
        "• Built the thing.\nEDUCATION\nB.S. Example\n"
    )
    data = parse_resume_detailed(None, text)
    assert len(data["experience"]) == 1
    assert "2023" in data["experience"][0]["duration"]


def test_letter_spaced_normalizer_leaves_ordinary_spaced_text_alone():
    text = (
        "Al Bo\nEXPERIENCE\nAcme Corp\nEngineer 2020 - Present\n"
        "• Documented the A B C rollout and the P R E S E N T plan.\nEDUCATION\nB.S. Example\n"
    )
    data = parse_resume_detailed(None, text)
    blob = " ".join(data["experience"][0]["description"])
    assert "A B C rollout" in blob and "P R E S E N T plan" in blob


def test_role_company_labels_without_dates_recover_roles():
    data = parse_resume_detailed(None, _load("role_label_no_dates.txt"))
    assert len(data["experience"]) == 2
    first, second = data["experience"]
    assert first["company"] == "Acme Retail Group"
    assert first["title"] == "Senior Analyst"
    # No dates are stated in the source, so none may be invented.
    assert (first.get("duration") or "") == ""
    assert (second.get("duration") or "") == ""
    assert "weekly margin report" in " ".join(first["description"])
    assert second["company"] == "Globex Services"
    assert second["title"] == "Business Analyst"
    assert "order-tracking portal" in " ".join(second["description"])
    assert not data.get("unassigned_experience_bullets")


def test_client_role_labels_without_dates_use_client_as_employer():
    text = (
        "Zed Qu\nEXPERIENCE\nClient: Contoso Bank\nRole: Test Lead\n"
        "• Led the regression suite.\nEDUCATION\nB.S. Example\n"
    )
    data = parse_resume_detailed(None, text)
    assert len(data["experience"]) == 1
    role = data["experience"][0]
    assert role["company"] == "Contoso Bank" and role["title"] == "Test Lead"
    assert (role.get("duration") or "") == ""


def test_role_label_without_company_or_dates_needs_following_bullets():
    text = "Zed Qu\nEXPERIENCE\nRole: Test Lead\nSome plain sentence here.\nEDUCATION\nB.S. Example\n"
    data = parse_resume_detailed(None, text)
    assert data["experience"] == []


def test_portfolio_clients_heading_with_client_and_role_label_without_dates():
    data = parse_resume_detailed(None, _load("portfolio_engagements.txt"))
    assert len(data["experience"]) == 2
    first, second = data["experience"]
    assert first["company"] == "Contoso Media"
    assert first["title"] == "Content Strategy Lead"
    assert (first.get("duration") or "") == ""
    assert "editorial calendar" in " ".join(first["description"])
    assert second["company"] == "Fabrikam Learning"
    assert second["title"] == "Senior Content Strategist"
    assert "learning-content program" in " ".join(second["description"])
    # Skills above the heading are not swallowed, and the mapped section is not repeated.
    assert "Editorial Planning" not in _roles_text(data)
    assert not any("client" in (s.get("title") or "").lower() for s in data["additional_sections"])


def test_engagements_heading_without_role_labels_stays_additional_section():
    text = (
        "Mara L\nmara@example.com\nENGAGEMENTS\nContoso Media\n• Wrote the editorial calendar.\n"
        "Fabrikam Learning\n• Launched a program.\nEDUCATION\nB.A. Example\n"
    )
    data = parse_resume_detailed(None, text)
    assert data["experience"] == []


def test_engagements_client_without_role_label_does_not_become_role():
    text = (
        "Mara L\nmara@example.com\nENGAGEMENTS\nContoso Media\nRole: Strategy Lead\n• Wrote the calendar.\n"
        "Fabrikam Learning\n• Launched a program.\nEDUCATION\nB.A. Example\n"
    )
    data = parse_resume_detailed(None, text)
    # One entry has no Role evidence, so the heading is not trusted as job history.
    assert all(r["company"] != "Fabrikam Learning" for r in data["experience"])


def test_labels_outside_experience_section_are_not_roles():
    text = (
        "Zed Qu\nPROJECTS\nClient: Contoso Bank\nRole: Test Lead\n• Led the suite.\n"
        "EXPERIENCE\nAcme Corp\nEngineer 2020 - Present\n• Built it.\nEDUCATION\nB.S. Example\n"
    )
    data = parse_resume_detailed(None, text)
    assert [r["company"] for r in data["experience"]] == ["Acme Corp"]


def test_company_date_header_with_role_and_project_lines():
    data = parse_resume_detailed(None, _load("company_date_role_project_lines.txt"))
    assert len(data["experience"]) == 2
    first, second = data["experience"]
    assert first["company"] == "Northwind Traders"
    assert first["title"] == "Senior BPM Developer"
    assert first["duration"] == "Jan 2020 - Present"
    assert first.get("project") == "Claims Workflow Modernization"
    assert "case-management workflows" in " ".join(first["description"])
    assert second["company"] == "Contoso Insurance"
    assert second["title"] == "BPM Developer"
    assert second.get("project") == "Underwriting Automation"
    assert "underwriting approval" in " ".join(second["description"])
    assert not data.get("unassigned_experience_bullets")


def test_labels_after_dated_header_never_replace_a_real_title():
    text = (
        "Zed Qu\nEXPERIENCE\nLead Engineer | Acme Corp | Jan 2020 - Present\n"
        "Project: Billing Rewrite\n• Shipped the billing rewrite.\nEDUCATION\nB.S. Example\n"
    )
    data = parse_resume_detailed(None, text)
    role = data["experience"][0]
    assert role["title"] == "Lead Engineer" and role["company"] == "Acme Corp"
    assert role.get("project") == "Billing Rewrite"


def test_dates_first_layout_reads_company_and_title_lines():
    data = parse_resume_detailed(None, _load("dates_first_company_title.txt"))
    assert len(data["experience"]) == 2
    first, second = data["experience"]
    assert first["company"].startswith("Northwind Traders")
    assert first["title"] == "Senior Data Engineer"
    assert first["duration"] == "Jan 2020 - Present"
    assert "ingestion pipelines" in " ".join(first["description"])
    assert second["company"].startswith("Contoso Insurance")
    assert second["title"] == "Data Engineer"
    assert second["duration"] == "Mar 2017 - Dec 2019"
    assert "nightly batch jobs" in " ".join(second["description"])
    assert not data.get("unassigned_experience_bullets")


def test_dates_first_layout_without_bullets_does_not_cross_pair_dates():
    text = (
        "Zed Qu\nEXPERIENCE\nJan 2020 - Present\nNorthwind Traders\nSenior Data Engineer\n"
        "Mar 2017 - Dec 2019\nContoso Insurance\nData Engineer\nEDUCATION\nB.S. Example\n"
    )
    roles = parse_resume_detailed(None, text)["experience"]
    assert [(r["company"], r["title"], r["duration"]) for r in roles] == [
        ("Northwind Traders", "Senior Data Engineer", "Jan 2020 - Present"),
        ("Contoso Insurance", "Data Engineer", "Mar 2017 - Dec 2019"),
    ]


def test_company_first_layout_is_not_treated_as_dates_first():
    text = (
        "Zed Qu\nEXPERIENCE\nNorthwind Traders\nSenior Data Engineer\nJan 2020 - Present\n"
        "Contoso Insurance\nData Engineer\nMar 2017 - Dec 2019\nEDUCATION\nB.S. Example\n"
    )
    roles = parse_resume_detailed(None, text)["experience"]
    assert [(r["company"], r["title"], r["duration"]) for r in roles] == [
        ("Northwind Traders", "Senior Data Engineer", "Jan 2020 - Present"),
        ("Contoso Insurance", "Data Engineer", "Mar 2017 - Dec 2019"),
    ]


def test_dice_work_history_list_with_separators():
    data = parse_resume_detailed(None, _load("dice_work_history_separators.txt"))
    pairs = [(r["company"], r["title"]) for r in data["experience"]]
    assert pairs == [
        ("Northwind Traders", "Senior Java Developer"),
        ("Contoso Insurance", "Java Developer"),
        ("Fabrikam Systems", "Software Engineer"),
        ("Adatum Holdings", "Technical Lead"),
    ]
    # No dates or bullets are stated in the source, so none may be invented.
    assert all(not r.get("duration") and not r.get("description") for r in data["experience"])


def test_work_history_plain_title_employer_lines():
    data = parse_resume_detailed(None, _load("work_history_plain_list.txt"))
    assert [(r["company"], r["title"]) for r in data["experience"]] == [
        ("Northwind Traders", "Senior QA Analyst"),
        ("Contoso Insurance", "QA Analyst"),
        ("Fabrikam Systems", "Test Engineer"),
    ]


def test_work_history_separator_with_roles_on_both_sides_is_not_split():
    text = (
        "Zed Qu\nWork History\n• Lead Engineer - Senior Consultant\n"
        "• Project Manager - Program Director\nEducation\nB.S. Example\n"
    )
    assert parse_resume_detailed(None, text)["experience"] == []


def test_work_history_plain_lines_with_prose_stay_unparsed():
    text = (
        "Zed Qu\nWork History\nSenior QA Analyst Northwind Traders\n"
        "Responsible for the quality of every release across the portfolio.\n"
        "Education\nB.S. Example\n"
    )
    assert parse_resume_detailed(None, text)["experience"] == []
