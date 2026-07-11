"""SQLAlchemy engine, session, and FastAPI dependency helpers.

A single :data:`engine` is constructed at import time from
:func:`lockverity.core.get_settings`. Tests override the database URL
*before* importing this module, then re-import, to exercise different
SQLite / PostgreSQL configurations.

The :func:`get_db` dependency is the right entry point for FastAPI
route handlers. It yields a :class:`sqlalchemy.orm.Session`, commits
on success, and rolls back on exception. The :func:`session_scope`
context manager is the right entry point for background work and
tests.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.core.config import Settings


def _build_engine(settings: Settings) -> Engine:
    """Construct the SQLAlchemy engine with connection-pool sane defaults."""
    url = settings.database_url
    connect_args: dict = {}
    if url.startswith("sqlite"):
        # SQLite needs ``check_same_thread=False`` because the
        # application serves requests from a thread pool.
        connect_args["check_same_thread"] = False
    return create_engine(
        url,
        future=True,
        connect_args=connect_args,
        pool_pre_ping=True,
    )


_settings = None
try:  # pragma: no cover - exercised via tests
    from app.core.config import get_settings

    _settings = get_settings()
except Exception:
    _settings = None

engine: Engine = (
    _build_engine(_settings)
    if _settings is not None
    else create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
    )
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


def configure_engine(settings: Settings) -> Engine:
    """Reconfigure the global engine. Intended for tests."""
    global engine, SessionLocal
    engine = _build_engine(settings)
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    return engine


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager wrapping a single :class:`Session` in a transaction.

    Commits on clean exit, rolls back on exception, always closes.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a managed :class:`Session`."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
