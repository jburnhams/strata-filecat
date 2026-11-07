#!/usr/bin/env bash
# One-time move of the catalogue from ~/.local/share/filecat/catalog.db to the shared PostgreSQL on omarchy
# (schema filecat of the database omarchy). No sudo. Stops on the first problem; prints how to undo.
#   scripts/cutover.sh            do it
#
# Order matters: the venv must have omarchy-db BEFORE the live clone runs the new code, or every filecat call
# (timer, Takeout inbox) fails on `import omarchy_db`.
#  1. refuse while a Takeout extraction (bsdtar) or a filecat run is going; pause filecat.timer
#  2. install omarchy-db (../database/python) into the strata venv, then update the live clone to this code
#  3. role + schema filecat (dbtool new-app), migrations
#  4. copy and verify (scripts/import-sqlite: one transaction, row counts + SHA-256 per table, rolled back on mismatch)
#  5. ~/.config/filecat/database -> the Postgres URL (every caller reads it), catalog.db read-only (kept 30 days)
#  6. one report and one `filecat run`, then the timer again
# Undo: rm ~/.config/filecat/database; chmod 600 ~/.local/share/filecat/catalog.db (filecat uses SQLite again).
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
LIVE="${FILECAT_REPO:-$HOME/code/github/strata-filecat}"
VENV="${STRATA_VENV:-$HOME/.local/share/strata/venv}"
SQLITE="$HOME/.local/share/filecat/catalog.db"
URL='postgresql:///omarchy?options=-csearch_path%3Dfilecat'
CONF="$HOME/.config/filecat/database"
PY="$VENV/bin/python"

[ -x "$PY" ] || { echo "no strata venv at $VENV (strata-takeout scripts/install.sh)" >&2; exit 1; }
pg_isready -q || { echo "postgresql not running" >&2; exit 1; }
[ -f "$SQLITE" ] || { echo "$SQLITE not found" >&2; exit 1; }
[ ! -s "$CONF" ] || { echo "$CONF already exists: moved before?" >&2; exit 1; }
if pgrep -f '[b]sdtar -xf' >/dev/null; then echo "a Takeout extraction (bsdtar) is running: it adds files every 5 minutes; try again when it is done" >&2; exit 1; fi

echo "== pause filecat.timer and wait for a running filecat"
systemctl --user stop filecat.timer
trap 'echo "stopped before the end; filecat.timer is paused (systemctl --user start filecat.timer). Undo: rm -f $CONF; chmod 600 $SQLITE" >&2' ERR
while [[ "$(systemctl --user show -p ActiveState --value filecat.service)" =~ ^(active|activating|deactivating)$ ]]; do echo "waiting for the running filecat"; sleep 10; done
if fuser "$SQLITE" >/dev/null 2>&1; then echo "something still has $SQLITE open (a manual filecat?)" >&2; false; fi

echo "== omarchy-db into the venv, then this code into the live clone"
# from GitHub main, not the shared ~/code/github/database clone (other sessions switch its branches)
uv pip install -q --python "$PY" "omarchy-db @ git+https://github.com/jburnhams/database@main#subdirectory=python"
git -C "$LIVE" fetch -q origin main && git -C "$LIVE" merge -q --ff-only origin/main
uv pip install -q --python "$PY" -e "$LIVE"
"$PY" -c 'import omarchy_db, filecat.models'

echo "== role + schema filecat in omarchy"
"$VENV/bin/dbtool" new-app filecat

echo "== copy and verify"
"$PY" "$LIVE/scripts/import-sqlite" --src "$SQLITE" --dst "$URL"

echo "== point every caller at Postgres; the SQLite file becomes read-only (delete after $(date -d '+30 days' +%F))"
mkdir -p "$(dirname "$CONF")"
printf '%s\n# since %s (strata-filecat scripts/cutover.sh); remove this file to go back to %s\n' "$URL" "$(date +%F)" "$SQLITE" > "$CONF"
chmod 400 "$SQLITE"

echo "== first runs on Postgres"
"$VENV/bin/filecat" report | tail -4
systemctl --user start filecat.service
journalctl --user -u filecat -n 3 --no-pager -o cat

trap - ERR
systemctl --user start filecat.timer
systemctl --user list-timers filecat.timer --no-pager
echo "done: the catalogue is omarchy.filecat ($URL)"
