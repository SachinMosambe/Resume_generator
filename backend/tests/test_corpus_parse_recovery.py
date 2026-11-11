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
