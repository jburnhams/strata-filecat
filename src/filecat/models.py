"""The catalogue's tables as SQLAlchemy models (omarchy_db). Alembic generates the migrations from these
(`dbtool revision -m ...` in this repo); the same tables work on SQLite (tests, other machines) and on the shared
PostgreSQL (schema `filecat` of the configured database).

Same columns as the original hand-written SQLite schema (user_version 2). Sizes, mtimes and CRC32 are BIGINT: files
over 2 GB and unsigned 32-bit CRCs do not fit a Postgres INTEGER. Flags stay integers (current=1) so the queries
read the same on both engines.
"""

from omarchy_db import make_base
from sqlalchemy import BigInteger, ForeignKey, Index, Integer, LargeBinary, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

Base = make_base()


class Collection(Base):
    __tablename__ = "collections"
    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    name: Mapped[str] = mapped_column(String, unique=True)
    profile: Mapped[str] = mapped_column(String, server_default="plain")
    note: Mapped[str | None] = mapped_column(String)
    config: Mapped[str] = mapped_column(String, server_default="{}")
    created_at: Mapped[int | None] = mapped_column(BigInteger)


class Root(Base):
    __tablename__ = "roots"
    __table_args__ = (UniqueConstraint("collection_id", "label"),)
    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id"))
    label: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String)
    autoscan: Mapped[int] = mapped_column(Integer, server_default="0")


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("collection_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id"))
    name: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    export_ts: Mapped[str | None] = mapped_column(String)
    size: Mapped[int | None] = mapped_column(BigInteger)
    mtime: Mapped[int | None] = mapped_column(BigInteger)
    entries: Mapped[int | None] = mapped_column(Integer)
    ingested_at: Mapped[int | None] = mapped_column(BigInteger)


PENDING = text("sha256 IS NULL AND current = 1 AND state = 'ok'")


class File(Base):
    __tablename__ = "files"
    __table_args__ = (
        Index("files_path", "collection_id", "root", "path", "current"),
        Index("files_sizecrc", "size", "crc32", sqlite_where=text("current = 1"), postgresql_where=text("current = 1")),
        Index(
            "files_sha",
            "sha256",
            sqlite_where=text("sha256 IS NOT NULL AND current = 1"),
            postgresql_where=text("sha256 IS NOT NULL AND current = 1"),
        ),
        Index("files_pending", "id", sqlite_where=PENDING, postgresql_where=PENDING),
    )
    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    collection_id: Mapped[int] = mapped_column(Integer)
    root: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String)
    size: Mapped[int] = mapped_column(BigInteger)
    source_id: Mapped[int] = mapped_column(Integer)
    crc32: Mapped[int | None] = mapped_column(BigInteger, default=None)
    sha256: Mapped[bytes | None] = mapped_column(LargeBinary, default=None)
    mtime: Mapped[int | None] = mapped_column(BigInteger, default=None)
    export_ts: Mapped[str | None] = mapped_column(String, default=None)
    state: Mapped[str] = mapped_column(String, server_default="ok", default="ok")
    current: Mapped[int] = mapped_column(Integer, server_default="1", default=1)
    orig_path: Mapped[str | None] = mapped_column(String, default=None)
    seen_gen: Mapped[int | None] = mapped_column(Integer, default=None)
