"""The database: schema, connection. One DB for every collection so identical content can be found across them."""
import os, sqlite3

DB_ENV = 'FILECAT_DB'
DEFAULT_DB = '~/.local/share/filecat/catalog.db'
SCHEMA_VERSION = 2
SCHEMA = """
CREATE TABLE IF NOT EXISTS collections(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, profile TEXT NOT NULL DEFAULT 'plain', note TEXT, config TEXT NOT NULL DEFAULT '{}', created_at INTEGER);
CREATE TABLE IF NOT EXISTS roots(id INTEGER PRIMARY KEY, collection_id INTEGER NOT NULL REFERENCES collections(id), label TEXT NOT NULL, path TEXT NOT NULL, autoscan INTEGER NOT NULL DEFAULT 0, UNIQUE(collection_id, label));
CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY, collection_id INTEGER NOT NULL REFERENCES collections(id), name TEXT NOT NULL, kind TEXT NOT NULL, export_ts TEXT, size INTEGER, mtime INTEGER, entries INTEGER, ingested_at INTEGER, UNIQUE(collection_id, name));
CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY, collection_id INTEGER NOT NULL, root TEXT NOT NULL, path TEXT NOT NULL, size INTEGER NOT NULL, crc32 INTEGER, sha256 BLOB,
  mtime INTEGER, source_id INTEGER NOT NULL, export_ts TEXT, state TEXT NOT NULL DEFAULT 'ok', current INTEGER NOT NULL DEFAULT 1, orig_path TEXT, seen_gen INTEGER);
CREATE INDEX IF NOT EXISTS files_path ON files(collection_id, root, path, current);
CREATE INDEX IF NOT EXISTS files_sizecrc ON files(size, crc32) WHERE current=1;
CREATE INDEX IF NOT EXISTS files_sha ON files(sha256) WHERE sha256 IS NOT NULL AND current=1;
CREATE INDEX IF NOT EXISTS files_pending ON files(id) WHERE sha256 IS NULL AND current=1 AND state='ok';
"""

def db_path():
    return os.path.expanduser(os.environ.get(DB_ENV, DEFAULT_DB))

def connect(path=None):
    path = path or db_path()
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    c = sqlite3.connect(path, timeout=120)
    c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA synchronous=NORMAL')
    if c.execute('PRAGMA user_version').fetchone()[0] < SCHEMA_VERSION:       # only write when the schema needs creating: a long-running writer (hashing) must not block every other invocation
        c.executescript(SCHEMA); c.execute(f'PRAGMA user_version={SCHEMA_VERSION}'); c.commit()
    return c
