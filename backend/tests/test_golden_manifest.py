import json
from pathlib import Path

REQUIRED_IDS = {
    "clean_guillermo_pattern",
    "dice_wrapper_full_resume",
    "paren_title_split_header",
    "bullet_only_experience",
    "education_only_complete",
}
REQUIRED_PATTERNS = {
    "conventional_clean",
    "dice_wrapper",
    "paren_title",
    "bullet_only",
    "education_only",
    "two_column",
    "table_docx",
    "long_history",
    "missing_optional",
    "scanned",
    "legacy_doc",
    "sparse_profile",
    "ambiguous",
}
GATE_KEYS = {
    "passed_pct_min",
    "zero_role_pct_max",
    "empty_title_pct_max",
    "bad_name_pct_max",
    "scanned_recovery_pct_min",
    "doc_conversion_pct_min",
    "style_assert_pct_min",
    "failed_pct_max",
}


def _load():
    path = Path(__file__).parent / "fixtures" / "golden" / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return path, data


def test_golden_manifest_loads_and_has_scored_fixtures():
    _path, data = _load()
    assert data["version"] == 1
    scored = [f for f in data["fixtures"] if f.get("scored")]
    assert len(scored) >= 5
    for f in scored:
        assert "id" in f and "expects_work_history" in f


def test_golden_manifest_covers_pattern_families_and_sources():
    path, data = _load()
    assert data["baseline_run"] == "corpus_eval_20261111_135025"
    fixtures = data["fixtures"]
    assert len(fixtures) >= 50
    ids = [f["id"] for f in fixtures]
    assert len(ids) == len(set(ids))
    assert REQUIRED_IDS <= set(ids)
    assert REQUIRED_PATTERNS <= {f["pattern"] for f in fixtures}
    assert any(f.get("expected_status") for f in fixtures if f["pattern"] == "ambiguous")
    assert GATE_KEYS <= set(data["gates"])
    root = path.parent
    for fixture in fixtures:
        assert (root / fixture["source"]).is_file(), fixture["id"]
        if fixture.get("scored"):
            assert isinstance(fixture["expects_work_history"], bool)
