"""Core subpackage: cross-cutting application concerns.

Modules here are kept dependency-light so they can be imported from
tests, scripts, and Alembic env without triggering heavy imports.
"""

from __future__ import annotations

from app.core.config import Settings, get_settings

__all__ = ["Settings", "get_settings"]
