"""One-off migration helper for the v0.1 verification step.

Runs ``alembic upgrade head`` -> ``alembic downgrade base`` ->
``alembic upgrade head`` against the configured database, and prints
a short summary of tables after each step.

Usage::

    python -m tests.manual_migration_cycle

The script is intentionally explicit: no fixtures, no in-memory
tricks, no mocking. It exercises the same code path the production
deployment will.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

BACKEND_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"
MIGRATIONS_DIR = BACKEND_ROOT / "alembic"


def _build_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    db_url = os.environ.get("LOCKVERITY_DATABASE_URL")
    if not db_url:
        db_url = "sqlite:///./lockverity.sqlite"
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _db_path_from_url(url: str) -> Path:
    # ``sqlite:///./foo.sqlite`` -> ``./foo.sqlite``
    if not url.startswith("sqlite"):
        raise ValueError(f"Unsupported database URL for the cycle: {url!r}")
    if url.startswith("sqlite:////"):
        return Path(url[len("sqlite:////") :])
    if url.startswith("sqlite:///"):
        return Path(url[len("sqlite:///") :])
    return Path(url)


def _current_version(db_path: Path) -> str | None:
    if not db_path.exists():
        return None
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    return None if row is None else row[0]


def _tables(db_path: Path) -> list[str]:
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        ).fetchall()
    return [r[0] for r in rows]


def main() -> int:
    cfg = _build_config()
    db_path = _db_path_from_url(cfg.get_main_option("sqlalchemy.url"))

    if db_path.exists():
        print(f"Removing existing database at {db_path}")
        db_path.unlink()

    print("\n=== Step 1: alembic upgrade head (from empty) ===")
    command.upgrade(cfg, "head")
    print(f"current version: {_current_version(db_path)}")
    print(f"tables: {_tables(db_path)}")
    assert _current_version(db_path) is not None, "upgrade did not stamp a version"
    assert len(_tables(db_path)) >= 10, "expected at least 10 application tables"

    print("\n=== Step 2: alembic downgrade base ===")
    command.downgrade(cfg, "base")
    assert _current_version(db_path) is None, "downgrade should clear the version"
    # Application tables should be gone; alembic_version may still exist.
    remaining = [t for t in _tables(db_path) if t != "alembic_version"]
    assert not remaining, f"downgrade left tables behind: {remaining}"

    print("\n=== Step 3: alembic upgrade head (re-upgrade) ===")
    command.upgrade(cfg, "head")
    print(f"current version: {_current_version(db_path)}")
    print(f"tables: {_tables(db_path)}")

    print("\nMigration cycle completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
