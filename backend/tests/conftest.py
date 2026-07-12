"""Shared pytest fixtures.

Strategy: a single in-memory SQLite database is held open for the
whole test session via :class:`sqlalchemy.pool.StaticPool`. Each test
function gets a fresh :class:`Session` bound to a fresh transaction,
which is rolled back at teardown. The schema is created once at
session start.

This pattern is the documented SQLAlchemy recipe for fast, isolated
in-memory tests. It also lets the service layer call
``session.commit()`` freely, because the per-test transaction is a
savepoint-style nested transaction.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# Configure environment *before* importing the application, otherwise
# :func:`app.core.get_settings` would have already cached a value.
os.environ.setdefault("LOCKVERITY_ENV", "test")
os.environ.setdefault("LOCKVERITY_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("LOCKVERITY_WORKSPACE_ROOT", "./var/workspace-test")

import app.models  # noqa: F401  - ensures every model is registered on Base.metadata
from app.core.config import get_settings
from app.db.base import Base


@pytest.fixture(scope="session")
def settings():
    """Return the cached :class:`Settings` instance for tests."""
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture(scope="session")
def engine(settings, tmp_path_factory):
    """Build a session-wide SQLite engine.

    We use a temp-file-backed SQLite database so the FastAPI
    TestClient, which may run in a worker thread, sees the same
    schema as the test thread.
    """
    db_path = tmp_path_factory.mktemp("lockverity-db") / "test.sqlite"
    test_engine = create_engine(
        f"sqlite:///{db_path}",
        future=True,
        connect_args={"check_same_thread": False},
        pool_pre_ping=False,
    )
    Base.metadata.create_all(test_engine)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def session_factory(engine):
    """Return a session factory bound to the shared engine."""
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )


@pytest.fixture
def session(engine, session_factory) -> Iterator[Session]:
    """Yield a clean SQLAlchemy session per test, rolling back at teardown.

    Uses an outer transaction with a nested savepoint, the standard
    recipe from the SQLAlchemy docs. The service layer's
    ``session.commit()`` calls commit the inner savepoint; the outer
    transaction is rolled back at teardown so the next test starts
    with a clean schema.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session_testing = sessionmaker(bind=connection, autoflush=False, autocommit=False, future=True)
    session_ = session_testing()
    try:
        yield session_
    finally:
        session_.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture
def app_config(settings, engine):
    """Reconfigure the global engine to use the test engine.

    The FastAPI ``get_db`` dependency opens sessions against
    :data:`app.db.session.engine`. For tests we want it to open
    against the test engine. This fixture keeps a reference to
    the original engine and restores it at teardown.

    Both :mod:`app.db.session` and the re-exports in
    :mod:`app.db` are rebound. The ``__init__`` re-export happens
    at import time, so without the second rebind any code that
    does ``from app.db import SessionLocal`` would still talk to
    the original engine - which is exactly the gap the scan
    executor used to fall into.
    """
    import app.db as db_pkg
    from app.db import session as db_session

    original_engine = db_session.engine
    original_sessionlocal = db_session.SessionLocal
    original_pkg_sessionlocal = db_pkg.SessionLocal
    original_pkg_engine = db_pkg.engine

    new_sessionlocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )

    db_session.engine = engine
    db_session.SessionLocal = new_sessionlocal
    db_pkg.SessionLocal = new_sessionlocal
    db_pkg.engine = engine
    try:
        yield settings
    finally:
        db_session.engine = original_engine
        db_session.SessionLocal = original_sessionlocal
        db_pkg.SessionLocal = original_pkg_sessionlocal
        db_pkg.engine = original_pkg_engine


@pytest.fixture
def workspace_root(tmp_path):
    """Return a per-test workspace root under pytest's tmp_path."""
    root = tmp_path / "workspace"
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture(autouse=True)
def _reset_db_state(engine):
    """Truncate every table before each test that uses the global engine.

    API tests bind :data:`app.db.session.engine` to the in-memory test
    engine for their duration. The transaction in the ``session``
    fixture covers the per-session case. For API tests that use
    :data:`app.db.session.SessionLocal`` directly (which talks to the
    global engine), we additionally truncate between tests so that
    state from a previous test cannot leak.
    """
    yield
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            table_name = table.name
            # ``table_name`` is sourced from SQLAlchemy metadata at
            # import time, not from user input. The string-format is
            # intentional and the rule below documents the exception.
            conn.execute(text("DELETE FROM " + table_name))  # noqa: S608
