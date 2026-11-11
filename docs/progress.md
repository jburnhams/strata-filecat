# strata-filecat progress

## 2026-11-07: created
Extracted from the `exports-catalog` script that was written the same day for a large Google Takeout (multi-TiB, with the same file in several zips, nested earlier exports and several versions per path). First as `exports-catalog` for one collection, then generalised in a few hours into collections + roots + profiles in one DB, so that duplicates can be found across services.

Decisions:
- One DB, not one per collection: the value is cross-collection duplicates.
- SQLite, standard library only. Keep it on fast storage (small random writes are slow on archive disks).
- CRC32 from archive indexes is free but 32 bits: candidates only. SHA-256 is the proof, computed lazily and resumably.
- Keep every version of a path (`current` flag) instead of overwriting: the exports overwrite each other on disk, the history is the point.
- Service-specific path rules are not here. `takeout` is a plugin from strata-takeout (entry point group `filecat.profiles`).
- It never extracts, moves or deletes. Acting on duplicates (hard links, deletion) would be a separate, reviewed step.

Found by the first unit tests: scan generations were `int(time.time())`, so two scans in the same second could not tell which files had been seen (a vanished file was not marked missing). Now a counter. The same bug was in the original script (harmless there: scans are minutes apart).

Open: a `filecat verify` pass (re-hash a sample, flag changed files), a schema migration helper for the next schema change, an `--exclude` option for `scan`, and a streaming SHA-256 option while extracting (the extractor currently hashes from disk afterwards).

## 2026-11-07: PostgreSQL
- The catalogue can live in PostgreSQL: schema `filecat` of a shared database (see jburnhams/database), through omarchy_db (SQLAlchemy Core + Alembic). Same tables (BIGINT for sizes, mtimes, CRC32; BYTEA for SHA-256); the queries keep sqlite3 style via `db.Conn`. SQLite still works (tests, other machines); an old SQLite catalogue (user_version 2) is adopted by stamping it at revision 0001.
- Where: `FILECAT_DB`, else `~/.config/filecat/database` (so the timer, the Takeout inbox and a shell all agree), else the SQLite file.
- Ported for Postgres: `RETURNING id` instead of `lastrowid`, no aliases in HAVING/ORDER BY, `COUNT(sha256)` instead of a boolean sum, typed COALESCE, hex of a BLOB per dialect, Decimal sums. scan_root reads a root's rows once and marks unchanged files in batches (a query per file is slow against a server). Hashing ends its read transaction before hashing a file.
- Measured on a snapshot of the real catalogue (438,681 file rows): import + verify 18 s (163 MB in Postgres); report 0.8 s (SQLite 1.3 s); dups 0.02 s; re-ingesting a 10,824-entry Takeout part 4.7 s (SQLite 2.1 s: a round trip per entry).
- A one-off SQLite-to-PostgreSQL import/cutover script existed for the first deployment; removed once done (2026-11-11).
