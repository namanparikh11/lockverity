"""Lockverity backend application package.

Lockverity is an evidence-first software supply-chain assurance tool.
This package implements the v0.1 architecture baseline:

- Typed configuration with safe production defaults
- SQLAlchemy 2 models with PostgreSQL-compatible modelling
- Alembic-managed migrations
- FastAPI service layer with explicit transaction handling
- Provider / analyzer / rule / exporter contracts
- Defensive utilities for path, URL, and archive safety

It is intentionally defensive-only. It does not execute analyzed code.
"""

from __future__ import annotations

__version__ = "0.1.0"
