"""Repository service tests."""

from __future__ import annotations

import re

import pytest
from app.models.repository import (
    RepositoryProvider,
    RepositorySourceType,
)
from app.repositories import repository_repo
from app.services import repository_service
from app.utils.errors import ApiError, ApiErrorCode


def test_create_repository_normalizes_url(session) -> None:
    repo = repository_service.create_repository_from_url(
        session, "https://github.com/OctoCat/Hello-World.git"
    )
    assert repo.owner == "OctoCat"
    assert repo.name == "Hello-World"
    assert repo.canonical_url == "https://github.com/OctoCat/Hello-World"
    assert repo.source_type == RepositorySourceType.GITHUB
    assert repo.provider == RepositoryProvider.GITHUB


def test_create_repository_is_idempotent(session) -> None:
    a = repository_service.create_repository_from_url(
        session, "https://github.com/octocat/Hello-World"
    )
    b = repository_service.create_repository_from_url(
        session, "https://github.com/octocat/Hello-World"
    )
    assert a.id == b.id


def test_create_repository_rejects_non_github(session) -> None:
    with pytest.raises(ApiError) as exc:
        repository_service.create_repository_from_url(
            session, "https://example.com/octocat/Hello-World"
        )
    assert exc.value.code == ApiErrorCode.VALIDATION_ERROR.value


def test_create_repository_rejects_extra_path(session) -> None:
    with pytest.raises(ApiError):
        repository_service.create_repository_from_url(
            session, "https://github.com/octocat/Hello-World/tree/main"
        )


def test_get_repository_or_404(session) -> None:
    repo = repository_service.create_repository_from_url(
        session, "https://github.com/octocat/Hello-World"
    )
    found = repository_service.get_repository_or_404(session, repo.id)
    assert found.id == repo.id

    with pytest.raises(ApiError) as exc:
        repository_service.get_repository_or_404(session, 99_999)
    assert exc.value.code == ApiErrorCode.NOT_FOUND.value


def test_list_repositories_pagination(session) -> None:
    for i in range(5):
        repository_service.create_repository_from_url(
            session, f"https://github.com/owner{i}/repo{i}"
        )
    items, total = repository_service.list_repositories(session, page=1, page_size=2)
    assert total == 5
    assert len(items) == 2
    items2, _ = repository_service.list_repositories(session, page=3, page_size=2)
    assert len(items2) == 1


# ---------------------------------------------------------------------------
# v2.1.1: defence-in-depth safe wrapper for the legacy
# ``POST /repositories`` endpoint. The primary bundled-UI path is
# the v1.5 guided intake endpoint ``POST /repositories/github``;
# the legacy endpoint is retained for backwards compatibility and
# must never leak a raw traceback or a half-committed row.
# ---------------------------------------------------------------------------


def test_safe_wrapper_sanitises_unexpected_exception_into_internal_unexpected(
    session, monkeypatch, caplog
) -> None:
    """A non-ApiError exception that escapes the inner
    service call is mapped to ``INTERNAL_UNEXPECTED`` with a
    16-character lowercase hex ``correlation_id`` and
    ``kind=repository``. The full traceback is logged with
    the same id; the response carries no exception class
    name, no simulated message, and no path.
    """

    def _raise_db_error(*_args, **_kwargs) -> None:
        raise RuntimeError("simulated db write failure from the legacy path")

    # Patch the inner service call so the failure happens
    # AFTER the URL normalisation (a classified
    # ``validation_error``) succeeds. This is the same
    # pattern the legacy endpoint would see if a database
    # write failed: a valid URL that fails to persist.
    monkeypatch.setattr(
        repository_service,
        "create_repository_from_url",
        _raise_db_error,
    )

    with (
        caplog.at_level("ERROR", logger="lockverity.repository_service"),
        pytest.raises(ApiError) as exc,
    ):
        repository_service.safe_create_repository_from_url(
            session, "https://github.com/octocat/Hello-World"
        )

    # The outer handler must sanitise the non-ApiError
    # exception into the documented ``INTERNAL_UNEXPECTED``
    # envelope, not the legacy ``INTERNAL`` envelope.
    assert exc.value.code == ApiErrorCode.INTERNAL_UNEXPECTED.value

    # The response ``details`` carries a 16-character
    # lowercase hex ``correlation_id`` and ``kind=repository``.
    assert exc.value.details is not None
    cid = exc.value.details.get("correlation_id")
    assert isinstance(cid, str)
    assert re.fullmatch(r"[0-9a-f]{16}", cid) is not None
    assert exc.value.details.get("kind") == "repository"

    # The response message is the bounded safe message; the
    # exception class name and the simulated message are NOT
    # in the response.
    assert "RuntimeError" not in exc.value.message
    assert "simulated" not in exc.value.message
    assert "Traceback" not in exc.value.message

    # The full traceback is chained so the log has the
    # complete information.
    assert exc.value.__cause__ is not None

    # The same correlation id appears in the log record so
    # the operator can cross-reference the response and the
    # log without parsing the response body.
    log_records = [r for r in caplog.records if r.name == "lockverity.repository_service"]
    assert any(cid in r.getMessage() for r in log_records), (
        f"correlation id {cid!r} not found in log records: {[r.getMessage() for r in log_records]}"
    )


def test_safe_wrapper_preserves_classified_errors(session) -> None:
    """The safe wrapper does NOT swallow classified
    ``ApiError`` instances. A ``validation_error`` from URL
    normalisation surfaces as the original ``validation_error``
    envelope, not as ``INTERNAL_UNEXPECTED``.
    """
    with pytest.raises(ApiError) as exc:
        repository_service.safe_create_repository_from_url(
            session, "https://example.com/octocat/Hello-World"
        )
    assert exc.value.code == ApiErrorCode.VALIDATION_ERROR.value
    assert "is not a valid public GitHub URL" in exc.value.message
    # The classified envelope does NOT carry a correlation
    # id because the failure was classified by the inner
    # service call, not by the top-level wrapper.
    assert "correlation_id" not in (exc.value.details or {})


def test_safe_wrapper_rolls_back_on_unexpected_failure(session, monkeypatch) -> None:
    """A non-ApiError exception that escapes the inner
    service call leaves no orphan repository row. The
    session is rolled back best-effort so the
    ``repositories`` table is empty after the failure.
    """

    def _raise_db_error(*_args, **_kwargs) -> None:
        raise RuntimeError("simulated db write failure")

    monkeypatch.setattr(
        repository_service,
        "create_repository_from_url",
        _raise_db_error,
    )

    with pytest.raises(ApiError):
        repository_service.safe_create_repository_from_url(
            session, "https://github.com/octocat/Hello-World"
        )

    # The session was rolled back by the wrapper; no
    # repository row should exist for the canonical URL
    # that the inner call would have created.
    found = repository_repo.get_repository_by_canonical_url(
        session, "https://github.com/octocat/Hello-World"
    )
    assert found is None, (
        "safe wrapper must roll back the session so a "
        "failed write does not leave a half-committed row"
    )
