# Repository Guidelines

strata-filecat: one SQLite catalogue and SHA-256 index for many file collections (Google Takeout and other service exports, photo libraries, backups), so duplicates and changed files can be found inside a collection and across them. Standard library only. Sister of [strata-takeout](https://github.com/jburnhams/strata-takeout), which supplies the `takeout` profile.

- Code lives in `src/filecat/`: `db.py` (schema, connection), `profiles.py` (`plain` and plugin loading), `core.py` (collections, archive indexes, incremental scans, hashing), `report.py`, `cli.py`. Tests: `tests/unit/` (pytest, hermetic: every test uses a temporary DB through the `db` fixture in `tests/conftest.py`, never `~/.local/share/filecat`).
- Commands: `pip install -r requirements-test.txt && pip install -e .`, `pytest`, `ruff check src tests`.
- Model: a collection has root directories and a profile; `files` keeps one row per path per source and `current=1` is the version on disk; SHA-256 is computed in time-boxed resumable slices. CRC32 from archive indexes only makes *candidates*. It catalogues; it never extracts, moves or deletes files.
- Profiles are plugins: classes registered in the entry point group `filecat.profiles` (see the docstring in `profiles.py`). Keep service-specific rules out of this repo.
- Style: dense, comment-the-why, long lines are fine (ruff line-length 400). Keep it dependency-free.
- Changing the schema: bump `SCHEMA_VERSION` and add a migration step in `db.connect`; the default DB is `~/.local/share/filecat/catalog.db`, back it up first (`sqlite3 .backup`).
- Notes and decisions go in `docs/progress.md`.
