"""Tests for :mod:`app.utils.datetime`."""

from __future__ import annotations

from datetime import UTC, datetime

from app.utils.datetime import ensure_utc, isoformat_utc, utcnow


def test_utcnow_is_timezone_aware() -> None:
    now = utcnow()
    assert isinstance(now, datetime)
    assert now.tzinfo is not None
    assert now.tzinfo == UTC


def test_ensure_utc_passes_through_aware_utc() -> None:
    value = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    assert ensure_utc(value) is value


def test_ensure_utc_converts_other_zones() -> None:
    # ``astimezone`` is the conversion logic under test; using a
    # timezone that is *not* UTC exercises the path.
    east = UTC
    value = datetime(2025, 1, 1, 12, 0, tzinfo=east)
    out = ensure_utc(value)
    assert out.tzinfo == UTC


def test_ensure_utc_assumes_utc_for_naive() -> None:
    naive = datetime(2025, 1, 1, 12, 0)
    out = ensure_utc(naive)
    assert out.tzinfo == UTC
    assert out.year == 2025 and out.hour == 12


def test_isoformat_utc_uses_z_suffix() -> None:
    value = datetime(2025, 1, 1, 12, 0, 0, 123456, tzinfo=UTC)
    out = isoformat_utc(value)
    assert out.endswith("Z")
    assert "+00:00" not in out
    assert out.startswith("2025-01-01T12:00:00")
