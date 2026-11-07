import pytest
from filecat.db import connect

@pytest.fixture
def db(tmp_path, monkeypatch):
    """A fresh catalogue in tmp_path (never the real one)."""
    monkeypatch.setenv('FILECAT_DB', str(tmp_path / 'cat.db'))
    return connect()

@pytest.fixture
def tree(tmp_path):
    def make(name, files):
        root = tmp_path / name
        for rel, data in files.items():
            p = root / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
        return root
    return make
