"""Repository service tests."""

from __future__ import annotations

import pytest
from app.models.repository import (
    RepositoryProvider,
    RepositorySourceType,
)
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
