"""Tests for the provider cache service."""

from __future__ import annotations

from datetime import timedelta

from app.services.cache_service import (
    CacheDescriptor,
    CacheService,
    CacheStatus,
)


def test_build_key_is_deterministic_and_redacts(session) -> None:
    cache = CacheService(session)
    descriptor_a = CacheDescriptor(
        provider="github",
        operation="repo_metadata",
        parameters={
            "canonical_url": "https://github.com/octocat/Hello-World",
            "authorization": "Bearer secret",
        },
    )
    descriptor_b = CacheDescriptor(
        provider="github",
        operation="repo_metadata",
        parameters={
            "authorization": "Bearer secret",
            "canonical_url": "https://github.com/octocat/Hello-World",
        },
    )
    key_a = cache.build_key(descriptor_a)
    key_b = cache.build_key(descriptor_b)
    assert key_a == key_b
    assert len(key_a) == 64
    # ``authorization`` must not appear in the key.
    assert "secret" not in key_a
    assert "Bearer" not in key_a


def test_get_returns_miss_when_no_entry(session) -> None:
    cache = CacheService(session)
    descriptor = CacheDescriptor(
        provider="github",
        operation="repo_metadata",
        parameters={"url": "https://github.com/octocat/Hello-World"},
    )
    lookup = cache.get(descriptor)
    assert lookup.status == CacheStatus.MISS
    assert lookup.payload is None


def test_put_then_get_returns_hit(session) -> None:
    cache = CacheService(session)
    descriptor = CacheDescriptor(
        provider="github",
        operation="repo_metadata",
        parameters={"url": "https://github.com/octocat/Hello-World"},
    )
    cache.put(descriptor, payload=b'{"ok":true}', etag='"abc"', last_modified="today")
    lookup = cache.get(descriptor)
    assert lookup.status == CacheStatus.HIT
    assert lookup.payload == b'{"ok":true}'
    assert lookup.etag == '"abc"'
    assert lookup.last_modified == "today"


def test_get_returns_stale_when_expired(session) -> None:
    cache = CacheService(session)
    descriptor = CacheDescriptor(
        provider="github",
        operation="repo_metadata",
        parameters={"url": "https://github.com/octocat/x"},
    )
    cache.put(
        descriptor,
        payload=b"{}",
        etag=None,
        last_modified=None,
        ttl=timedelta(seconds=-1),
    )
    lookup = cache.get(descriptor)
    assert lookup.status == CacheStatus.STALE
    assert lookup.payload == b"{}"


def test_put_rejects_oversized_payload(session) -> None:
    cache = CacheService(session)
    descriptor = CacheDescriptor(
        provider="github",
        operation="repo_metadata",
        parameters={"url": "https://github.com/octocat/y"},
    )
    entry = cache.put(
        descriptor,
        payload=b"x" * (cache.max_payload_bytes + 1),
        etag=None,
        last_modified=None,
    )
    assert entry.status == CacheStatus.ERROR


def test_invalidate_removes_entry(session) -> None:
    cache = CacheService(session)
    descriptor = CacheDescriptor(
        provider="github",
        operation="repo_metadata",
        parameters={"url": "https://github.com/octocat/z"},
    )
    cache.put(descriptor, payload=b"{}", etag=None, last_modified=None)
    assert cache.invalidate(descriptor) is True
    assert cache.invalidate(descriptor) is False
    lookup = cache.get(descriptor)
    assert lookup.status == CacheStatus.MISS


def test_hit_count_increments(session) -> None:
    cache = CacheService(session)
    descriptor = CacheDescriptor(
        provider="github",
        operation="repo_metadata",
        parameters={"url": "https://github.com/octocat/w"},
    )
    cache.put(descriptor, payload=b"{}", etag=None, last_modified=None)
    cache.get(descriptor)
    cache.get(descriptor)
    lookup = cache.get(descriptor)
    assert lookup.status == CacheStatus.HIT
    assert lookup.entry is not None
    assert lookup.entry.hit_count >= 2
