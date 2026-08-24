"""Database engine and session helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .migrations import migrate

_engine = None
_session_factory: sessionmaker | None = None


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _record):
    if dbapi_connection.__class__.__module__.split(".")[0] != "sqlite3":
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.resolved_database_url,
            connect_args={"check_same_thread": False, "timeout": 30},
        )
    return _engine


def init_db() -> None:
    """Create the engine, apply migrations and prepare sessions."""
    global _session_factory
    engine = get_engine()
    migrate(engine)
    _session_factory = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Session:
    if _session_factory is None:
        init_db()
    return _session_factory()


def request_session() -> Iterator[Session]:
    """FastAPI dependency: commits on success, rolls back on error."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager yielding a session and closing it afterwards."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()