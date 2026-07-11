"""Database package.

This package owns the SQLAlchemy engine, session factory, and the
declarative base used by :mod:`lockverity.models`. It must remain
dependency-light so it can be imported from Alembic env scripts.
"""

from __future__ import annotations

from app.db.base import Base
from app.db.session import (
    SessionLocal,
    engine,
    get_db,
    session_scope,
)

__all__ = ["Base", "SessionLocal", "engine", "get_db", "session_scope"]
