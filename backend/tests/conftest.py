import pytest

from tests.fixtures.build_fixtures import build_all


@pytest.fixture(scope="session")
def fixtures(tmp_path_factory):
    return build_all(tmp_path_factory.mktemp("resume_fixtures"))


@pytest.fixture(autouse=True)
def _no_live_line_extract(monkeypatch):
    """Tests never call Bedrock for line extraction; extractor tests inject a fake client."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "RESUME_LLM_LINE_EXTRACT", False)
