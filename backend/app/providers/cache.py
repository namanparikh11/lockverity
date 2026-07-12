"""Cache contract for outbound provider calls.

The cache is process-local. It is intentionally simple:

- Keys are arbitrary strings (the provider builds them).
- Values are opaque JSON-serializable payloads.
- Each entry has a TTL (default 6 hours). A negative TTL means
  the entry is never used (the cache returns a miss).
- The cache returns ``None`` for misses and never raises.

The contract is *opt-in* per provider. OSV, deps.dev, and
Scorecard decide for themselves which queries to cache and for
how long. The cache is a single source of truth for the
"cache_status" field on :class:`ProviderObservation` records.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

DEFAULT_TTL_SECONDS = 6 * 60 * 60  # 6 hours


@dataclass(frozen=True, slots=True)
class CacheEntry:
    """A single cache entry."""

    key: str
    value: Any
    expires_at: float


class ProviderCache:
    """In-memory provider cache with per-entry TTLs."""

    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        self._store: dict[str, CacheEntry] = {}
        self._clock = clock or time.monotonic

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.expires_at <= self._clock():
            self._store.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: Any, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        if ttl_seconds < 0:
            return
        self._store[key] = CacheEntry(
            key=key,
            value=value,
            expires_at=self._clock() + ttl_seconds,
        )

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    def size(self) -> int:
        return len(self._store)

    def snapshot(self) -> Mapping[str, CacheEntry]:
        return dict(self._store)
