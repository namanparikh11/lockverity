"""Tests for the provider cache contract."""

from __future__ import annotations

from app.providers.cache import DEFAULT_TTL_SECONDS, ProviderCache


def test_get_returns_none_on_miss() -> None:
    cache = ProviderCache()
    assert cache.get("missing") is None


def test_set_then_get_returns_value() -> None:
    cache = ProviderCache()
    cache.set("k", {"x": 1})
    assert cache.get("k") == {"x": 1}


def test_negative_ttl_skips_storage() -> None:
    cache = ProviderCache()
    cache.set("k", "v", ttl_seconds=-1)
    assert cache.get("k") is None


def test_default_ttl_is_documented() -> None:
    assert DEFAULT_TTL_SECONDS > 0


def test_expiry_uses_clock() -> None:
    clock_value = [0.0]

    def fake_clock() -> float:
        return clock_value[0]

    cache = ProviderCache(clock=fake_clock)
    cache.set("k", "v", ttl_seconds=10)
    assert cache.get("k") == "v"
    clock_value[0] = 11.0
    assert cache.get("k") is None


def test_invalidate_removes_entry() -> None:
    cache = ProviderCache()
    cache.set("k", "v")
    cache.invalidate("k")
    assert cache.get("k") is None


def test_clear_removes_all() -> None:
    cache = ProviderCache()
    cache.set("a", 1)
    cache.set("b", 2)
    cache.clear()
    assert cache.size() == 0


def test_size_reflects_stored_entries() -> None:
    cache = ProviderCache()
    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.size() == 2
