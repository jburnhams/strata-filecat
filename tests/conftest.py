import pytest
from filecat.db import connect

@pytest.fixture
def db(tmp_path, monkeypatch, request):
    """A fresh catalogue, never the real one: a SQLite file in tmp_path, or with `pytest --pg` a throwaway PostgreSQL
    database (omarchy_db's pytest plugin; the catalogue goes into its schema `filecat`, as on omarchy)."""
    if request.config.getoption('--pg'):
        url = request.getfixturevalue('db_url')
        monkeypatch.setenv('FILECAT_DB', url)
    else:
        monkeypatch.setenv('FILECAT_DB', str(tmp_path / 'cat.db'))
    c = connect()
    yield c
    c.close()


def pytest_collection_modifyitems(config, items):
    if config.getoption('--pg'):
        for it in items:
            if 'sqlite_only' in it.keywords: it.add_marker(pytest.mark.skip(reason='SQLite locking behaviour; not applicable on PostgreSQL'))


def pytest_configure(config):
    config.addinivalue_line('markers', 'sqlite_only: tests of SQLite-specific behaviour (file locking)')

@pytest.fixture
def tree(tmp_path):
    def make(name, files):
        root = tmp_path / name
        for rel, data in files.items():
            p = root / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
        return root
    return make
