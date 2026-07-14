"""Provider health rollup API schema."""

from __future__ import annotations

from datetime import datetime

from app.schemas.common import SchemaModel


class ProviderHealthEntry(SchemaModel):
    """A single provider's most recent state, aggregated across scans.

    The ``redacted_failure_summary`` is exactly what was persisted
    on the underlying :class:`ProviderObservation`: the backend
    already runs the free-form provider error through the
    redaction utility before writing it. The frontend must not
    re-display this value as trusted HTML.
    """

    provider: str
    status: str
    records_returned: int
    cache_status: str | None = None
    last_retrieved_at: datetime | None = None
    redacted_failure_summary: str | None = None
    last_error_code: str | None = None
    scans_with_observations: int


class ProviderHealthResponse(SchemaModel):
    """The full provider-health rollup."""

    providers: list[str]
    entries: list[ProviderHealthEntry]


__all__ = ["ProviderHealthEntry", "ProviderHealthResponse"]
