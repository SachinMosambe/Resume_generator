import pytest

from tests.fixtures.build_fixtures import build_all


@pytest.fixture(scope="session")
def fixtures(tmp_path_factory):
    return build_all(tmp_path_factory.mktemp("resume_fixtures"))
