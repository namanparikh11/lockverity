"""Lockverity backend application package.

Lockverity is an evidence-first software supply-chain assurance tool.
This package implements the v0.2 professional product:

- Typed configuration with safe production defaults
- SQLAlchemy 2 models with PostgreSQL-compatible modelling
- Alembic-managed migrations
- FastAPI service layer with explicit transaction handling
- Provider / analyzer / rule / exporter contracts
- Defensive utilities for path, URL, and archive safety
- A local scan worker for queued scans
- Per-scan intake paths for public GitHub repos and ZIP archives

It is intentionally defensive-only. It does not execute analyzed
code.
"""

from __future__ import annotations

from app import _version

__version__ = _version.__version__

__all__ = ["__version__"]
