# Changelog

Newest first, grouped by day. One entry per change, in the same commit or PR as the change.

## 2026-11-15

**File labels from a profile (branch `file-labels`).** Exports often carry labels next to the file (a sidecar listing the people in a photo, say). filecat stays service-neutral: a profile opts in with `label_exts` and `labels(rel_path)`; filecat reads each current file once and stores the result.

- `models.py`, migrations `8c561a25a69a` (tables) and `83083cb708ae` (`source` joins the primary key; existing rows kept): **new tables** `file_labels` (file_id, source, kind, value; index on kind, value) and `label_scans` (file_id, source, state ok / none / error: what has been looked at).
- `labels.py`: **new**. `read_pending` (time-boxed, resumable; profiles without `labels` skipped), `summary`, `find`.
- `cli.py`: `filecat labels [--seconds N] [--collection C]` reads; `filecat labels --find KIND=VALUE` lists files. `filecat run` also reads labels. `report` shows label counts per collection.
- Callers can attach their own labels: `filecat labels --import FILE --source NAME` (JSON lines `{collection, root, path, labels: [[kind, value]]}`, `-` is stdin) or `labels.put(...)`; a re-import replaces that source's labels of the file, labels from other sources (the profile's own) stay; files not in the catalogue are counted, not added (scan first). Labels go next to the hashes: `file_labels` joins `files` and `visual_hashes`.
- `profiles.py` docstring: the optional `labels` hook.
- Review fixes: the time budget is checked per file, and results are collected with no write transaction open and written in batches of 50, so a slow label source (network mount) cannot lock the catalogue for other writers.

## 2026-11-14 (later)

**Visual hashes: reuse and workers (branch `visual-hash-reuse-workers`).** The first full run over a real photo library would decode every file row, including every byte-identical copy.

- `visual.py`: a file with the same SHA-256 as one already hashed copies that row instead of decoding again (also between files of one batch). Decoding runs in `--workers` processes (default 2, niced by 10, spawn context); only the parent process touches the database. `--workers 1` stays in-process.
- `cli.py`: `--workers` on `visual-hash` and `run`. The output reports how many hashes were reused.
- Review fixes: decoding is bounded to a small chunk in flight (workers x 4) and the time budget and `--stop-when` are rechecked between chunks, so a slice ends promptly; a same-SHA twin of a file that hit an I/O error is decoded from its own path instead of inheriting the error.
- Tests: reuse across and within a batch, pool results equal in-process results.

## 2026-11-14

**Perceptual hashes of image files (branch `visual-hash`).** To find the same picture across different files (resized, recompressed, another format) and visually similar ones, e.g. to attach metadata from one export to your own copy of a photo.

- `src/filecat/visual.py`: **new**. 64-bit pHash (greyscale 32x32, DCT, 8x8 low frequencies vs the median), pure Python on top of Pillow (about 1.6 ms for the DCT; decoding dominates). EXIF orientation is applied first. JPEG, PNG, GIF, BMP, TIFF and WebP through Pillow; HEIC/HEIF/AVIF with pillow-heif. Animated files: first frame. Unreadable files are recorded once as `unsupported`/`error`, not retried.
- `models.py`, migration `e9abb7519e6d`: **new table `visual_hashes`** (file_id, algo, state, hash as signed BIGINT, width, height), one row per file version.
- `cli.py`: `filecat visual-hash [--seconds N] [--collection C]` and `filecat similar [--distance 6] [--across] [--collection C]` (groups of byte-different images within a Hamming distance; exact copies are left to `dups`). `filecat run` also runs the visual pass when Pillow is installed. `report` shows the visual-hash count per collection.
- `pyproject.toml`: optional extra `visual` (pillow, pillow-heif), also in the dev group so the tests cover it. Without the extra everything else works as before.
- Review fixes: the visual pass pages by id so images not on disk yet cannot stall a slice, honours `--stop-when`, and `similar` keeps matches inside crowded bands (identical hashes joined, distinct ones compared; a warning if a band is too crowded to compare).
- Not covered: camera RAW (needs the embedded preview), video (see `docs/progress.md`), crops and rotations by other than EXIF (pHash is not invariant to them).

## 2026-11-10

**Move to uv, ruff, pyright and the shared strata-python gate (branch `claude/project-thread-iw7199`)**
Every Python project should use the same tooling as [python-app-template](https://github.com/jburnhams/python-app-template): uv, ruff with `ruff format`, pyright and ty, one `scripts/check` gate, and dependencies kept current. Behaviour of the program is unchanged.

- `pyproject.toml`, `uv.lock`: hatchling instead of setuptools; a `dev` group (pytest tooling, ruff, pyright, ty, strata-python for its gate); git sources for `omarchy-db` and `strata-python`; ruff `E,F,I,B,UP,SIM,RUF,C4,PT,S,TID` with `pytest.importorskip` banned, line length 120 (was 400), pyright strict ratchet starting at `__init__.py`, ty, coverage floor 90 (92% measured). `requirements.txt` and `requirements-test.txt`: **removed**. `scripts/check`: **new**.
- `src/`, `tests/`: `ruff format` and import sorting (mechanical). `core.py`: `--stop-when` runs the user's own shell command, marked `noqa: S602` with that reason.
- `.github/workflows/unit.yml`: uv, current action versions, the gate once on Linux 3.13, tests on three operating systems; the `database` job installs with `uv pip install -e . --group dev`. `upgrade-strata-python.yml`: **new**, weekly PR that moves the library pin after the gate. `.github/dependabot.yml`: ecosystem `uv` instead of `pip`.
- `README.md`, `AGENTS.md`: commands for uv. The one-off SQLite-to-PostgreSQL migration scripts (`scripts/cutover.sh`, `scripts/import-sqlite`) and the test for the latter are removed.

## 2026-11-11

**Public-readiness scrub.** `AGENTS.md` now states the repo is public and must stay generic; hostnames, machine paths and personal names removed from docs, comments and tests; the project description no longer mentions a specific machine.
