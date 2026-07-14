"""Pydantic v2 schemas for the public API.

Schemas are deliberately separated from the ORM models:

- ORM models capture persistence concerns (relationships, enums,
  indexes, cascade behavior).
- API schemas capture wire format (validation, defaults, examples,
  documentation).

Never return an ORM instance directly from a route handler.
"""

from __future__ import annotations

from app.schemas.provider_health import ProviderHealthEntry, ProviderHealthResponse

__all__ = ["ProviderHealthEntry", "ProviderHealthResponse"]
