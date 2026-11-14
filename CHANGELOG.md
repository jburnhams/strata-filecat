# Changelog

Newest first, grouped by day. One entry per change, in the same commit or PR as the change.

## 2026-11-14

**Perceptual hashes of image files (branch `visual-hash`).** To find the same picture across different files (resized, recompressed, another format) and visually similar ones, e.g. to attach metadata from one export to your own copy of a photo.

- `src/filecat/visual.py`: **new**. 64-bit pHash (greyscale 32x32, DCT, 8x8 low frequencies vs the median), pure Python on top of Pillow (about 1.6 ms for the DCT; decoding dominates). EXIF orientation is applied first. JPEG, PNG, GIF, BMP, TIFF and WebP through Pillow; HEIC/HEIF/AVIF with pillow-heif. Animated files: first frame. Unreadable files are recorded once as `unsupported`/`error`, not retried.
- `models.py`, migration `e9abb7519e6d`: **new table `visual_hashes`** (file_id, algo, state, hash as signed BIGINT, width, height), one row per file version.
- `cli.py`: `filecat visual-hash [--seconds N] [--collection C]` and `filecat similar [--distance 6] [--across] [--collection C]` (groups of byte-different images within a Hamming distance; exact copies are left to `dups`). `filecat run` also runs the visual pass when Pillow is installed. `report` shows the visual-hash count per collection.
- `pyproject.toml`: optional extra `visual` (pillow, pillow-heif), also in the dev group so the tests cover it. Without the extra everything else works as before.
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
