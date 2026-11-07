# strata-filecat

One SQLite catalogue and SHA-256 index for many file collections. Point it at the folders and archives from your online-service exports, photo libraries and backups and it answers: *what is where, which files are exact duplicates (inside one collection or across several), which paths changed between exports, what has vanished from disk.* Standard library only; it catalogues, it never extracts, moves or deletes anything.

Built for [strata-takeout](https://github.com/jburnhams/strata-takeout) (Google Takeout and other cloud-platform exports), usable on its own.

## Why one database
The same photo can sit in Google Photos, Flickr and a phone backup. One SHA-256 index across all collections shows it as one duplicate group; a database per collection cannot. SQLite copes with tens of millions of rows (about 200 bytes per row with indexes).

## Quick start
```bash
pip install -e .                     # or: uv tool install --editable .
filecat collection add flickr --root photos=/data/flickr,autoscan --note "Flickr export"
filecat scan flickr                  # incremental: new / changed (new version row) / gone (state=missing)
filecat ingest-archive amazon export.zip --strip 1 --skip Junk     # index an archive from its index; nothing is extracted
filecat run                          # profile ingest + autoscan roots + SHA-256 (put this on a timer)
filecat report                       # per collection, then duplicates inside and across collections
filecat dups --across --min-size 1000000     # biggest identical-content sets present in more than one collection
```
The database is `~/.local/share/filecat/catalog.db` (`FILECAT_DB` to change it). Everything else is plain SQL:
```sql
select c.name, f.root, f.path from files f join collections c on c.id = f.collection_id
where hex(f.sha256) like '41EF49%' and f.current = 1;
```

## How it works
- **Collections** have named **roots** (label -> directory, optional `autoscan`) and a **profile**.
- **Two hash tiers.** Archive indexes already hold size, CRC32 and mtime per entry, so `ingest-archive` records them without reading data; size + CRC32 only ever gives *candidates*. `filecat hash` computes SHA-256 for files on disk that have none, in time-boxed, resumable slices (so it can run at low priority next to downloads). A new version with the same size and CRC32 as the one it replaces inherits its hash.
- **Versions.** `files` keeps one row per path per source; `current=1` is the version on disk now, older rows stay, so "this path changed between exports" and "which export is this from" stay answerable. `state` is `ok`, `missing`, `size-mismatch`, `skipped-nested` (skipped by the profile) or `error`.
- **Scans** treat a file as unchanged when its size matches and (it has a CRC32 from an archive, or its mtime matches). Hidden files and directories, `*.partial`, `*.part` and symlinks are ignored.
- **Profiles** map an archive entry name to the stored path. `plain` ships here (`--strip N`, `--skip PREFIX`). Others are plugins in the entry point group `filecat.profiles`, e.g. `takeout` from strata-takeout (drops the leading `Takeout/`, cuts over-long names, skips nested earlier exports). A profile may also provide `pending_archives(cfg)` so `filecat run` ingests new archives by itself. See `src/filecat/profiles.py`.

## Develop
```bash
pip install -r requirements-test.txt && pip install -e .
pytest            # hermetic: every test uses a temporary database
ruff check src tests
```
See [AGENTS.md](AGENTS.md) for conventions and [docs/progress.md](docs/progress.md) for the log.
