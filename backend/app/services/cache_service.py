"""Provider cache service.

A thin, SQL-backed cache for provider responses. The cache is
deliberately narrow: it stores the raw response bytes, the
SHA-256 of those bytes, the ETag and Last-Modified headers, and
an expiry timestamp. The cache does not interpret the response.

The :class:`CacheService` API is:

- :meth:`get` returns a :class:`CacheLookup` with hit / miss /
  stale / error status;
- :meth:`put` stores a payload after a successful call.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.provider_cache import ProviderCacheEntry
from app.repositories import cache_repo
from app.utils.datetime import utcnow
from app.utils.json_safe import dump_bounded_json
from app.utils.redaction import redact_payload


# Cache status returned to the caller. The values map to the
# existing :class:`ProviderStatus` enum so they are easy to
# surface as observations.
class CacheStatus(str, Enum):
    HIT = "hit"
    MISS = "miss"
    STALE = "stale"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class CacheLookup:
    status: CacheStatus
    entry: ProviderCacheEntry | None
    etag: str | None
    last_modified: str | None
    payload: bytes | None
    response_sha256: str | None


@dataclass(frozen=True, slots=True)
class CacheDescriptor:
    """Inputs to a cache key."""

    provider: str
    operation: str
    parameters: dict[str, Any]


class CacheService:
    """A small, safe provider cache."""

    def __init__(self, session: Session, *, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()

    @property
    def max_payload_bytes(self) -> int:
        return self._settings.provider_cache_max_payload_bytes

    @property
    def default_ttl(self) -> timedelta:
        return timedelta(seconds=self._settings.provider_cache_default_ttl_seconds)

    def build_key(self, descriptor: CacheDescriptor) -> str:
        """Return a normalized, deterministic cache key.

        The parameters are recursively redacted, then serialized
        with deterministic key ordering, then hashed.
        """
        redacted = redact_payload(descriptor.parameters)
        serialized = dump_bounded_json(
            {
                "provider": descriptor.provider,
                "operation": descriptor.operation,
                "parameters": redacted,
            }
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def get(self, descriptor: CacheDescriptor) -> CacheLookup:
        cache_key = self.build_key(descriptor)
        try:
            entry = cache_repo.get(
                self._session,
                provider=descriptor.provider,
                operation=descriptor.operation,
                cache_key=cache_key,
            )
        except Exception:  # pragma: no cover - DB error
            return CacheLookup(
                status=CacheStatus.ERROR,
                entry=None,
                etag=None,
                last_modified=None,
                payload=None,
                response_sha256=None,
            )
        if entry is None:
            return CacheLookup(
                status=CacheStatus.MISS,
                entry=None,
                etag=None,
                last_modified=None,
                payload=None,
                response_sha256=None,
            )
        # SQLite may strip timezone info on read; the
        # application always stores UTC-aware datetimes, so we
        # # ensure the comparison is UTC-aware.
        expires_at = entry.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=utcnow().tzinfo)
        if expires_at <= utcnow():
            return CacheLookup(
                status=CacheStatus.STALE,
                entry=entry,
                etag=entry.etag,
                last_modified=entry.last_modified,
                payload=entry.payload,
                response_sha256=entry.response_sha256,
            )
        # Hit: bump counter and return the payload.
        entry.hit_count += 1
        self._session.flush()
        return CacheLookup(
            status=CacheStatus.HIT,
            entry=entry,
            etag=entry.etag,
            last_modified=entry.last_modified,
            payload=entry.payload,
            response_sha256=entry.response_sha256,
        )

    def put(
        self,
        descriptor: CacheDescriptor,
        *,
        payload: bytes,
        etag: str | None,
        last_modified: str | None,
        ttl: timedelta | None = None,
    ) -> CacheEntry:
        """Store ``payload`` for ``descriptor``."""
        if len(payload) > self.max_payload_bytes:
            return CacheEntry(
                status=CacheStatus.ERROR,
                cache_key=self.build_key(descriptor),
                response_sha256=None,
            )
        cache_key = self.build_key(descriptor)
        retrieved_at = utcnow()
        expires_at = retrieved_at + (ttl or self.default_ttl)
        sha = hashlib.sha256(payload).hexdigest()
        entry = cache_repo.upsert(
            self._session,
            provider=descriptor.provider,
            operation=descriptor.operation,
            cache_key=cache_key,
            response_sha256=sha,
            payload=payload,
            etag=etag,
            last_modified=last_modified,
            retrieved_at=retrieved_at,
            expires_at=expires_at,
        )
        return CacheEntry(
            status=CacheStatus.HIT,
            cache_key=cache_key,
            response_sha256=entry.response_sha256,
        )

    def invalidate(self, descriptor: CacheDescriptor) -> bool:
        cache_key = self.build_key(descriptor)
        return cache_repo.delete(
            self._session,
            provider=descriptor.provider,
            operation=descriptor.operation,
            cache_key=cache_key,
        )


@dataclass(frozen=True, slots=True)
class CacheEntry:
    status: CacheStatus
    cache_key: str
    response_sha256: str | None


__all__ = [
    "CacheDescriptor",
    "CacheEntry",
    "CacheLookup",
    "CacheService",
    "CacheStatus",
]
