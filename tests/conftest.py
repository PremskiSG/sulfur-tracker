import pytest


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    """Point every test at an isolated home dir so it uses DEFAULT scoring config
    (no config.yaml present) and never touches the real DB."""
    monkeypatch.setenv("SULFUR_TRACKER_HOME", str(tmp_path))
    from sulfur_tracker import config, secrets
    config.load_config.cache_clear()
    secrets.load_secrets.cache_clear()
    yield
    config.load_config.cache_clear()
    secrets.load_secrets.cache_clear()


@pytest.fixture
def conn(tmp_path):
    from sulfur_tracker import db
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()
