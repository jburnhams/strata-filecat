"""The database: connection and schema. One DB for every collection so identical content can be found across them.

Where: FILECAT_DB, else the first line of ~/.config/filecat/database, else ~/.local/share/filecat/catalog.db. Each is
a SQLite path or a PostgreSQL URL. The file is how every caller agrees without its own environment (the timer, the
Takeout inbox, a shell); on omarchy it holds postgresql:///omarchy?options=-csearch_path%3Dfilecat (schema filecat
of the shared database).
Schema: SQLAlchemy models (models.py) with Alembic migrations (migrations/), through omarchy_db; pending migrations
are applied on connect. A SQLite catalogue from before Alembic (PRAGMA user_version 2, same tables) is adopted by
stamping it at the first revision, so nothing is rewritten.

The code keeps sqlite3-style calls (`c.execute(sql, params)` with `?` placeholders, `with c:` for a transaction,
`c.commit()`): `Conn` turns them into SQLAlchemy text() statements, so one set of queries runs on both engines.
"""
import os, re
from pathlib import Path

from sqlalchemy import bindparam, inspect, text

import omarchy_db
from omarchy_db.config import with_search_path

DB_ENV = 'FILECAT_DB'
DB_FILE = '~/.config/filecat/database'
DEFAULT_DB = '~/.local/share/filecat/catalog.db'
SCHEMA = 'filecat'                                   # its schema in the shared Postgres
MIGRATIONS = Path(__file__).resolve().parent / 'migrations'
FIRST_REVISION = '0001'                              # the original user_version 2 schema


def configured():
    if os.environ.get(DB_ENV): return os.environ[DB_ENV]
    f = os.path.expanduser(DB_FILE)
    if os.path.isfile(f):
        with open(f) as fh:
            line = fh.readline().strip()
        if line: return line
    return DEFAULT_DB

def db_url():
    v = configured()
    if v.startswith(('postgresql:', 'postgres:', 'postgresql+psycopg:')):
        return with_search_path(omarchy_db.normalise_url(v), SCHEMA)
    return 'sqlite:///' + os.path.abspath(os.path.expanduser(v))

def db_path():                                       # for messages; the URL for Postgres
    return db_url().removeprefix('sqlite:///')

_PARAM = re.compile(r"\?")

def _named(sql, params):
    """sqlite3 style (`?`, a tuple) -> SQLAlchemy style (`:p0`, a dict). The queries have no literal '?'."""
    if isinstance(params, dict): return sql, params
    params = tuple(params); n = iter(range(len(params)))
    return _PARAM.sub(lambda _: f':p{next(n)}', sql), {f'p{i}': v for i, v in enumerate(params)}


class Conn:
    """A sqlite3.Connection look-alike over one SQLAlchemy connection."""
    def __init__(s, engine):
        s.engine = engine; s.dialect = engine.dialect.name; s.conn = engine.connect()

    def execute(s, sql, params=()):
        q, p = _named(sql, params)
        return s.conn.execute(text(q), p)

    def execute_ids(s, sql, ids, **params):
        """`sql` with `:ids` expanded to a list (UPDATE ... WHERE id IN :ids), in chunks."""
        st = text(sql).bindparams(bindparam('ids', expanding=True)); n = 0; ids = list(ids)
        for i in range(0, len(ids), 5000):
            n += s.conn.execute(st, {'ids': ids[i:i + 5000], **params}).rowcount
        return n

    def commit(s): s.conn.commit()
    def rollback(s): s.conn.rollback()
    def close(s): s.conn.close(); s.engine.dispose()

    def __enter__(s): return s
    def __exit__(s, exc, *_):
        if exc is None: s.conn.commit()
        else: s.conn.rollback()

    # The few expressions that differ between the engines
    def hex6(s, col):
        """First 6 bytes of a BLOB as upper-case hex (a short, readable hash prefix)."""
        return f"upper(encode(substring({col} from 1 for 6), 'hex'))" if s.dialect == 'postgresql' else f'hex(substr({col},1,6))'

    def as_text(s, col):
        """Any column as comparable text (COALESCE over columns of different types needs one type)."""
        return f"upper(encode({col}, 'hex'))" if s.dialect == 'postgresql' and col == 'sha256' else (f'hex({col})' if col == 'sha256' else f'CAST({col} AS TEXT)')


def _adopt_pre_alembic(engine):
    """An existing SQLite catalogue made by the old hand-written schema (PRAGMA user_version 2): same tables, so mark
    it as being at the first revision instead of creating them again."""
    if engine.dialect.name != 'sqlite': return
    names = inspect(engine).get_table_names()
    if 'files' in names and 'alembic_version' not in names:
        from alembic import command
        from omarchy_db.migrations import make_config
        from .models import Base
        with engine.begin() as conn:
            command.stamp(make_config(MIGRATIONS, Base.metadata, conn), FIRST_REVISION)


def connect(path=None):
    """The catalogue, migrated to the newest schema. `path` (tests): a SQLite path or a URL."""
    from .models import Base
    url = db_url() if path is None else (path if '://' in path else 'sqlite:///' + os.path.abspath(path))
    if url.startswith('sqlite:///'):
        os.makedirs(os.path.dirname(url.removeprefix('sqlite:///')) or '.', exist_ok=True)
    engine = omarchy_db.connect(url, **({} if url.startswith('sqlite') else {'pool_size': 2}))
    if engine.dialect.name == 'sqlite':
        from sqlalchemy import event
        @event.listens_for(engine, 'connect')
        def _sqlite(dbapi_conn, _):                    # as before: WAL, a long busy timeout, cheap fsyncs
            cur = dbapi_conn.cursor(); cur.execute('PRAGMA synchronous=NORMAL'); cur.execute('PRAGMA busy_timeout=120000'); cur.close()
    _adopt_pre_alembic(engine)
    omarchy_db.upgrade(engine, MIGRATIONS, Base.metadata, owner_role=SCHEMA, schema=SCHEMA)
    return Conn(engine)
