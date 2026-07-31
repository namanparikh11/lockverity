"""Alembic environment for Lockverity.

The script URL is read from :func:`app.core.get_settings` so the same
``LOCKVERITY_DATABASE_URL`` value drives the application and the
migrations. We also import the application metadata to enable
``--autogenerate`` in later revisions, but the first migration is
written by hand so it is fully reviewable.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make the ``app`` package importable. The script location is
# ``backend/alembic/env.py`` in source mode, so the project
# root is one level up. In frozen mode the script location
# is ``<frozen_root>/alembic/env.py`` and the project root
# is the frozen root; the application package is unpacked
# by PyInstaller under ``sys._MEIPASS`` and is on
# ``sys.path`` automatically. The ``app.runtime_paths``
# helper resolves the script's parent directory in a
# mode-aware way so the same env script works in both
# build flavours without an operator-set env var.
try:
    from app.runtime_paths import is_frozen, frozen_root, source_root
except ImportError:  # pragma: no cover - source-only fallback
    is_frozen = lambda: False  # type: ignore[assignment]
    frozen_root = lambda: Path(__file__).resolve().parents[1]  # type: ignore[assignment]
    source_root = lambda: Path(__file__).resolve().parents[1]  # type: ignore[assignment]

if is_frozen():
    # In frozen mode the ``app`` package is unpacked by
    # PyInstaller under ``sys._MEIPASS`` and the frozen
    # bundle already contains ``alembic/versions/``.
    # The application package import works because
    # PyInstaller adds ``sys._MEIPASS`` to ``sys.path``.
    BACKEND_ROOT = frozen_root()
else:
    # Source mode: the script location is
    # ``backend/alembic/env.py`` so the project root is
    # one level up.
    BACKEND_ROOT = source_root()
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import app.models
from app.core.config import get_settings
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the database URL from application settings so the same value
# is used for application and migration runs.
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without a live database connection."""
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("sqlalchemy.url is not configured.")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with a live database connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
