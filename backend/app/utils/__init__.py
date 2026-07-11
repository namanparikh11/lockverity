"""Utility subpackage: pure, dependency-light helpers.

These modules must be importable from any other module without pulling
in FastAPI, SQLAlchemy, or HTTP clients. They are the foundation for
the safe-pipeline guarantees documented in :mod:`lockverity`.
"""

from __future__ import annotations

__all__: list[str] = []
