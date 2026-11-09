"""Database engine and session handling."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from meditrack import config

_connect_args: dict = {}
_engine_kwargs: dict = {}

if config.DATABASE_URL.startswith("sqlite"):
    # FastAPI serves requests on a threadpool, so the connection must be usable
    # from more than the thread that created it.
    _connect_args["check_same_thread"] = False
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
else:
    # PostgreSQL (RDS). The pool is deliberately small: the application tier is
    # one modest instance, and RDS instance classes cap max_connections low
    # enough that an oversized pool per process is a real risk.
    _engine_kwargs.update(
        pool_size=5,
        max_overflow=5,
        # Recycle below typical idle-timeout cutoffs so a connection that a
        # NAT gateway or RDS has silently dropped is not handed to a request.
        pool_recycle=300,
        # Verify a pooled connection before use; without this, a failover or
        # restart surfaces as one failed request per stale connection.
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5, "application_name": "meditrack"},
    )

if _connect_args:
    _engine_kwargs["connect_args"] = _connect_args

engine = create_engine(config.DATABASE_URL, future=True, **_engine_kwargs)

if config.DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        # SQLite does not enforce foreign keys unless asked to, per connection.
        cursor.execute("PRAGMA foreign_keys=ON")
        # WAL lets reads proceed during a write, which matters even at this
        # scale because a slow page render would otherwise block a save.
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a session that is always closed."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
