"""Timezone-aware UTC datetime helpers.

Lockverity never stores naive datetimes. Every persisted timestamp is
timezone-aware UTC. Callers should use :func:`utcnow` instead of
:func:`datetime.utcnow` to get the same semantics without the deprecation
warning, and to be explicit about the timezone.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Return a timezone-aware ``datetime`` for the current UTC instant."""
    return datetime.now(tz=UTC)


def ensure_utc(value: datetime) -> datetime:
    """Return ``value`` as a timezone-aware UTC datetime.

    Naive datetimes are assumed to already be in UTC. Aware datetimes
    in other zones are converted. The result is always UTC and always
    timezone-aware.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def isoformat_utc(value: datetime) -> str:
    """Return an RFC 3339 / ISO 8601 UTC string with ``Z`` suffix."""
    return ensure_utc(value).isoformat().replace("+00:00", "Z")
