"""Tests for the Settings class."""

from __future__ import annotations

import pytest
from app.core.config import Settings, get_settings
from pydantic import ValidationError


def test_default_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    # Strip every LOCKVERITY_* env var so the test sees
    # the documented default. ``Settings(_env_file=None)``
    # only disables the ``.env`` file; explicit env
    # variables override the field defaults and would
    # otherwise leak from the test infrastructure.
    for name in (
        "LOCKVERITY_ENVIRONMENT",
        "LOCKVERITY_DATABASE_URL",
        "LOCKVERITY_WORKSPACE_ROOT",
        "LOCKVERITY_SERVE_FRONTEND",
        "LOCKVERITY_FRONTEND_DIST",
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.environment == "development"
    assert s.api_prefix == "/api/v1"
    assert s.pagination_default_page_size > 0
    assert s.pagination_default_page_size <= s.pagination_max_page_size


def test_cors_origins_accepts_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "LOCKVERITY_ENVIRONMENT",
        "LOCKVERITY_DATABASE_URL",
        "LOCKVERITY_WORKSPACE_ROOT",
        "LOCKVERITY_SERVE_FRONTEND",
        "LOCKVERITY_FRONTEND_DIST",
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    s = Settings(_env_file=None, cors_origins="a.com,b.com,c.com")  # type: ignore[call-arg]
    assert s.cors_origins == ["a.com", "b.com", "c.com"]


def test_cors_origins_rejects_wildcard_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "LOCKVERITY_ENVIRONMENT",
        "LOCKVERITY_DATABASE_URL",
        "LOCKVERITY_WORKSPACE_ROOT",
        "LOCKVERITY_SERVE_FRONTEND",
        "LOCKVERITY_FRONTEND_DIST",
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="production", cors_origins="*")  # type: ignore[call-arg]


def test_cors_origins_allows_wildcard_in_development() -> None:
    # Production is the only restricted environment. Development
    # can be permissive so local tools work.
    s = Settings(_env_file=None, environment="development", cors_origins="*")  # type: ignore[call-arg]
    assert s.cors_origins == ["*"]


def test_pagination_max_size_is_bounded() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, pagination_max_page_size=2000)  # type: ignore[call-arg]


def test_archive_suspicious_ratio_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, archive_suspicious_ratio=0)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        Settings(_env_file=None, archive_suspicious_ratio=-10)  # type: ignore[call-arg]


def test_pagination_default_size_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, pagination_default_page_size=0)  # type: ignore[call-arg]
