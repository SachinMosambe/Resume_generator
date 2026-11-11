"""The golden CI gate must fail loudly: injected regressions flip the exit code.

Loads ``scripts/corpus_quality_eval.py`` in-process so a regression can be injected
(a dropped bullet, a crashing generator) and the real ``--golden`` exit code asserted.
"""

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest
from docx import Document

BACKEND = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND / "scripts" / "corpus_quality_eval.py"
MANIFEST = BACKEND / "tests" / "fixtures" / "golden" / "manifest.json"

# Ten fixtures that pass cleanly today: one dropped bullet is 1/10 runs, so the aggregate
# passed_pct (90%) still clears the 85% bar -- only the zero-tolerance gate can catch it.
CLEAN_IDS = [
    "clean_guillermo_pattern",
    "clean_one_role",
    "emdash_role_header",
    "title_only_under_experience",
    "numeric_date_history",
    "promotion_same_employer",
    "two_column_body",
    "long_history_twelve_roles",
    "pipe_delimited_headers",
    "unicode_bullet_markers",
]
VICTIM = "clean_guillermo_pattern"


@pytest.fixture(scope="module")
def runner(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    # The script sets these at import; register them so the originals are restored.
    for key in (
        "RESUME_LLM_CONDENSE",
        "RESUME_AGENT_PIPELINE",
        "RESUME_LLM_POLISH",
        "RESUME_LLM_PARSE_FALLBACK",
        "UPLOAD_DIR",
    ):
        mp.setenv(key, "false")
    mp.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
    spec = importlib.util.spec_from_file_location("corpus_quality_eval_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    mp.undo()
    sys.modules.pop(spec.name, None)


def _run(runner, tmp_path, ids=CLEAN_IDS, formats="aptino"):
    return runner.main(
        ["--golden", "--formats", formats, "--fixtures", ",".join(ids), "--out", str(tmp_path)]
    )


def _drop_paragraphs(data: bytes, needle: str) -> bytes:
    doc = Document(io.BytesIO(data))
    for paragraph in list(doc.paragraphs):
        if needle in paragraph.text.lower():
            paragraph._element.getparent().remove(paragraph._element)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def test_clean_subset_exits_zero(runner, tmp_path, capsys):
    assert _run(runner, tmp_path) == 0
    out = capsys.readouterr().out
    assert "GOLDEN PASS" in out
    assert "passed_pct" in out and "10/10" in out


def test_injected_bullet_omission_exits_nonzero_even_when_aggregate_passes(runner, tmp_path, monkeypatch, capsys):
    real_generate = runner.ResumeGenerationService.generate

    def lossy(self, candidate, client_format):
        data = real_generate(self, candidate, client_format)
        if VICTIM in candidate.resume_path:
            data = _drop_paragraphs(data, "shipped")  # the manifest's expected bullet
        return data

    monkeypatch.setattr(runner.ResumeGenerationService, "generate", lossy)
    code = _run(runner, tmp_path)
    out = capsys.readouterr().out
    assert code != 0
    report = json.loads((tmp_path / "golden_latest.json").read_text(encoding="utf-8"))
    gates = {g["gate"]: g for g in report["gates"]}
    # 9/10 = 90% >= 85%: the rate gate alone would pass...
    assert gates["passed_pct"]["met"] is True
    assert gates["passed_pct"]["numerator"] == 9 and gates["passed_pct"]["denominator"] == 10
    # ...the zero-tolerance gate is what fails, and it names the fixture and the lost fact.
    assert gates["silent_omission_pct"]["met"] is False
    assert gates["silent_omission_pct"]["failing_ids"] == [f"{VICTIM}@aptino"]
    assert f"{VICTIM}@aptino" in out and "bullet:shipped" in out
    assert "GOLDEN FAIL" in out


def test_generation_error_stays_in_denominator_and_fails(runner, tmp_path, monkeypatch, capsys):
    real_generate = runner.ResumeGenerationService.generate

    def boom(self, candidate, client_format):
        if VICTIM in candidate.resume_path:
            raise RuntimeError("renderer exploded")
        return real_generate(self, candidate, client_format)

    monkeypatch.setattr(runner.ResumeGenerationService, "generate", boom)
    assert _run(runner, tmp_path, ids=CLEAN_IDS[:2]) != 0
    out = capsys.readouterr().out
    report = json.loads((tmp_path / "golden_latest.json").read_text(encoding="utf-8"))
    failed = next(g for g in report["gates"] if g["gate"] == "failed_pct")
    assert failed["denominator"] == 2 and failed["failing_ids"] == [f"{VICTIM}@aptino"]
    assert "renderer exploded" in out


def test_llm_parse_fallback_must_stay_off(runner, tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "RESUME_LLM_PARSE_FALLBACK", True)
    assert _run(runner, tmp_path, ids=CLEAN_IDS[:1]) == 2


def test_unknown_fixture_or_missing_format_is_a_setup_error(runner, tmp_path):
    assert _run(runner, tmp_path, ids=["no_such_fixture"]) == 2
    assert _run(runner, tmp_path, ids=CLEAN_IDS[:1], formats="aptino,nonsense") == 2


def test_stub_binary_fixtures_are_not_scored(runner, tmp_path):
    assert _run(runner, tmp_path, ids=CLEAN_IDS[:1]) == 0
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    stubs = [f["id"] for f in manifest["fixtures"] if f.get("builder")]
    assert stubs and all(not f["scored"] for f in manifest["fixtures"] if f.get("builder"))
    # Asking for a stub explicitly still scores nothing: it is unscored, not a pass.
    assert _run(runner, tmp_path, ids=[stubs[0]]) == 1  # zero runs is never a vacuous pass


def test_gate_math_reports_numerator_denominator_and_ids(runner):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    fixtures = {
        "a": {"id": "a", "expects_work_history": True, "expected_roles": [{"company": "X", "title": "T"}],
              "expected_name": "N"},
        "b": {"id": "b", "expects_work_history": True, "expected_roles": [{"company": "Y", "title": "T"}],
              "expected_name": "N"},
    }
    ok = {"status": "passed", "expectation_failures": [], "style_failures": None}
    lost = {"status": "needs_review", "expectation_failures": ["bullet:x"], "style_failures": None}
    results = [
        {"id": "a", "runs": {"aptino": ok}, "parse": {"roles": 1, "bad_name": False, "annotated_titled_roles": 1,
                                                         "untitled_source_titled_roles": []}},
        {"id": "b", "runs": {"aptino": lost}, "parse": {"roles": 0, "bad_name": True, "annotated_titled_roles": 1,
                                                          "untitled_source_titled_roles": ["Y"]}},
    ]
    gates = {g["gate"]: g for g in runner.compute_golden_gates(manifest, results, fixtures)}
    assert (gates["passed_pct"]["numerator"], gates["passed_pct"]["denominator"]) == (1, 2)
    assert gates["passed_pct"]["failing_ids"] == ["b@aptino"] and gates["passed_pct"]["met"] is False
    assert gates["zero_role_pct"]["failing_ids"] == ["b"] and gates["zero_role_pct"]["met"] is False
    assert gates["empty_title_pct"]["failing_ids"] == ["b:Y"]
    assert gates["bad_name_pct"]["failing_ids"] == ["b"]
    # No scored OCR / DOC fixtures: reported as not enforced, never silently green.
    assert gates["scanned_recovery_pct"]["met"] is None and gates["doc_conversion_pct"]["met"] is None
    assert runner.golden_exit_code(list(gates.values()), 2) == 1
    assert runner.golden_exit_code(list(gates.values()), 0) == 1


def test_unassigned_bullets_missing_from_docx_and_incorrectly_passed_fail_gate(runner):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    fixture = next(f for f in manifest["fixtures"] if f["id"] == "bullet_only_experience")
    preserved = list(fixture["expected_bullet_substrings"])
    missing = runner.golden_expectation_failures(fixture, fixture["expected_name"], preserved)

    assert missing == [f"bullet:{bullet}" for bullet in preserved]

    result = {
        "id": fixture["id"],
        "runs": {
            "aptino": {
                "status": "passed",
                "expectation_failures": missing,
                "style_failures": None,
            }
        },
        "parse": {
            "roles": 0,
            "bad_name": False,
            "annotated_titled_roles": 0,
            "untitled_source_titled_roles": [],
        },
    }
    gates = {
        gate["gate"]: gate
        for gate in runner.compute_golden_gates(manifest, [result], {fixture["id"]: fixture})
    }
    assert gates["passed_pct"]["met"] is False
    assert gates["silent_omission_pct"]["met"] is False
    assert runner.golden_exit_code(list(gates.values()), 1) == 1


def test_unassigned_bullet_fixture_requires_needs_review_even_when_rendered(runner):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    fixture = next(f for f in manifest["fixtures"] if f["id"] == "bullet_only_experience")
    result = {
        "id": fixture["id"],
        "runs": {
            "aptino": {
                "status": "passed",
                "expectation_failures": [],
                "style_failures": None,
            }
        },
        "parse": {
            "roles": 0,
            "bad_name": False,
            "annotated_titled_roles": 0,
            "untitled_source_titled_roles": [],
        },
    }
    gates = {
        gate["gate"]: gate
        for gate in runner.compute_golden_gates(manifest, [result], {fixture["id"]: fixture})
    }
    assert gates["passed_pct"]["met"] is False
    assert runner.golden_exit_code(list(gates.values()), 1) == 1


def test_numeric_level_suffix_stays_in_the_title():
    """Regression found by the golden gate: 'Engineer II | dates' parsed as title 'Engineer', company 'II'."""
    from app.services.detailed_resume_parser import parse_resume_detailed

    text = (BACKEND / "tests" / "fixtures" / "golden" / "cases" / "promotion_ladder.txt").read_text(encoding="utf-8")
    roles = parse_resume_detailed(None, text)["experience"]
    assert [(r["title"], r["company"]) for r in roles] == [
        ("Engineer I", "ExampleCorp"),
        ("Engineer II", "ExampleCorp"),
    ]
