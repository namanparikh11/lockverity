"""Data-access layer.

Each :mod:`app.repositories.<name>` module owns the SQLAlchemy queries
for one domain entity. They are intentionally thin: just queries,
joins, and ordering. Business rules (state transitions, validation,
side effects) live in :mod:`app.services`.

Tests that need a single :class:`Session` should call these helpers
directly rather than going through a service.
"""

from __future__ import annotations

__all__: list[str] = []
