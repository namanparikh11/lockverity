"""Empty database initialization tests.

The :mod:`app.db` module must produce a usable SQLAlchemy engine on
a fresh import, and the schema must be creatable from the model
metadata without any pre-existing tables. This test runs against an
in-memory SQLite database to keep it hermetic.
"""

from __future__ import annotations

from app.db import Base
from sqlalchemy import create_engine, inspect


def _fresh_engine():
    return create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
    )


def test_schema_is_creatable_from_empty_metadata() -> None:
    """Creating a fresh engine and running ``create_all`` on an empty
    database must produce all ten application tables."""
    engine = _fresh_engine()
    try:
        Base.metadata.create_all(engine)
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        expected = {
            "repositories",
            "scan_runs",
            "scan_stages",
            "manifests",
            "components",
            "dependency_edges",
            "advisories",
            "component_advisories",
            "findings",
            "provider_observations",
        }
        missing = expected - tables
        assert not missing, f"missing tables: {missing}"
    finally:
        engine.dispose()


def test_metadata_lists_all_models() -> None:
    tables = set(Base.metadata.tables.keys())
    expected = {
        "repositories",
        "scan_runs",
        "scan_stages",
        "manifests",
        "components",
        "dependency_edges",
        "advisories",
        "component_advisories",
        "findings",
        "provider_observations",
    }
    assert expected <= tables
