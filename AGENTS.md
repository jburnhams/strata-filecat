# Repository Guidelines

strata-filecat: one catalogue and SHA-256 index for many file collections (Google Takeout and other service exports, photo libraries, backups), so duplicates and changed files can be found inside a collection and across them. The catalogue is SQLite or PostgreSQL (on omarchy: schema `filecat` of the shared database `omarchy`), through omarchy_db (SQLAlchemy + Alembic, from the private repo jburnhams/database). Sister of [strata-takeout](https://github.com/jburnhams/strata-takeout), which supplies the `takeout` profile.

- Code lives in `src/filecat/`: `db.py` (connection; sqlite3-style `Conn` over SQLAlchemy so the same `?` queries run on both engines), `models.py` (tables), `migrations/` (Alembic), `profiles.py` (`plain` and plugin loading), `core.py` (collections, archive indexes, incremental scans, hashing), `report.py`, `cli.py`. Tests: `tests/unit/` (pytest, hermetic: every test uses a temporary DB through the `db` fixture in `tests/conftest.py`, never the real catalogue). `pytest --pg` runs them on a throwaway PostgreSQL database.
- Commands: `pip install -r requirements-test.txt && pip install -e ../database/python && pip install -e .`, `pytest`, `pytest --pg`, `ruff check src tests`.
- Model: a collection has root directories and a profile; `files` keeps one row per path per source and `current=1` is the version on disk; SHA-256 is computed in time-boxed resumable slices. CRC32 from archive indexes only makes *candidates*. It catalogues; it never extracts, moves or deletes files.
- Profiles are plugins: classes registered in the entry point group `filecat.profiles` (see the docstring in `profiles.py`). Keep service-specific rules out of this repo.
- Style: dense, comment-the-why, long lines are fine (ruff line-length 400). Dependencies: only omarchy-db (and what it brings).
- SQL must run on SQLite and PostgreSQL: no aliases in HAVING / ORDER BY expressions, single-quoted strings, no `X'..'` literals, no boolean sums; dialect-specific bits go through `Conn` helpers (`hex6`, `as_text`).
- Changing the schema: edit `models.py`, then `dbtool revision -m "..."` (review the file), `dbtool check` (SQLite and Postgres); migrations run on connect. Where the catalogue is: `FILECAT_DB`, else `~/.config/filecat/database`, else `~/.local/share/filecat/catalog.db`.
- Notes and decisions go in `docs/progress.md`.
