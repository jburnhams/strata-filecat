# strata-filecat progress

## 2026-11-07: created
Extracted from the `exports-catalog` script that was written the same day for a Google Takeout on a home Linux box (3+ TiB with the same file in several zips, nested earlier exports and several versions per path). First as `exports-catalog` for one collection, then generalised in a few hours into collections + roots + profiles in one DB, so that duplicates can be found across services.

Decisions:
- One DB, not one per collection: the value is cross-collection duplicates.
- SQLite, standard library only. On an SSD (small random writes are slow on the SMR archive disk the exports live on).
- CRC32 from archive indexes is free but 32 bits: candidates only. SHA-256 is the proof, computed lazily and resumably.
- Keep every version of a path (`current` flag) instead of overwriting: the exports overwrite each other on disk, the history is the point.
- Service-specific path rules are not here. `takeout` is a plugin from strata-takeout (entry point group `filecat.profiles`).
- It never extracts, moves or deletes. Acting on duplicates (hard links, deletion) would be a separate, reviewed step.

Found by the first unit tests: scan generations were `int(time.time())`, so two scans in the same second could not tell which files had been seen (a vanished file was not marked missing). Now a counter. The same bug was in the original script (harmless there: scans are minutes apart).

Open: a `filecat verify` pass (re-hash a sample, flag changed files), a schema migration helper for the next schema change, an `--exclude` option for `scan`, and a streaming SHA-256 option while extracting (the extractor currently hashes from disk afterwards).
