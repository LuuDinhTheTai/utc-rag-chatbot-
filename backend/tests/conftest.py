"""Never let HTTP tests read or mutate the developer's configured database."""
import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    settings.cache_clear()
    yield
    settings.cache_clear()
