"""Provider cache data-access helpers."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.provider_cache import ProviderCacheEntry


def get(
    session: Session,
    *,
    provider: str,
    operation: str,
    cache_key: str,
) -> ProviderCacheEntry | None:
    stmt = select(ProviderCacheEntry).where(
        ProviderCacheEntry.provider == provider,
        ProviderCacheEntry.operation == operation,
        ProviderCacheEntry.cache_key == cache_key,
    )
    return session.execute(stmt).scalar_one_or_none()


def upsert(
    session: Session,
    *,
    provider: str,
    operation: str,
    cache_key: str,
    response_sha256: str,
    payload: bytes,
    etag: str | None,
    last_modified: str | None,
    retrieved_at: datetime,
    expires_at: datetime,
) -> ProviderCacheEntry:
    existing = get(session, provider=provider, operation=operation, cache_key=cache_key)
    if existing is not None:
        existing.response_sha256 = response_sha256
        existing.payload = payload
        existing.payload_size = len(payload)
        existing.etag = etag
        existing.last_modified = last_modified
        existing.retrieved_at = retrieved_at
        existing.expires_at = expires_at
        existing.hit_count = existing.hit_count
        session.flush()
        return existing
    entry = ProviderCacheEntry(
        provider=provider,
        operation=operation,
        cache_key=cache_key,
        response_sha256=response_sha256,
        payload=payload,
        payload_size=len(payload),
        etag=etag,
        last_modified=last_modified,
        retrieved_at=retrieved_at,
        expires_at=expires_at,
        hit_count=0,
    )
    session.add(entry)
    session.flush()
    return entry


def delete(
    session: Session,
    *,
    provider: str,
    operation: str,
    cache_key: str,
) -> bool:
    existing = get(session, provider=provider, operation=operation, cache_key=cache_key)
    if existing is None:
        return False
    session.delete(existing)
    session.flush()
    return True


def count(session: Session) -> int:
    from sqlalchemy import func

    return int(
        session.execute(select(func.count()).select_from(ProviderCacheEntry)).scalar_one() or 0
    )
