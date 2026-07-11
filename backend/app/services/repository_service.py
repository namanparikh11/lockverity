"""Repository service.

Wraps the GitHub URL normalization, uniqueness checks, and the small
amount of default-state the application holds per repository.

This service does *not* call any external provider - in v0.1 there is
no GitHub authentication, no metadata fetch, and no archive
introspection. Creating a repository is a pure database operation
that records the user's intent to analyze a given public URL.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.repository import (
    Repository,
)
from app.repositories import repository_repo
from app.utils.errors import ApiError, ApiErrorCode
from app.utils.repo_url import (
    NormalizedRepositoryUrl,
    RepositoryUrlError,
    normalize_github_url,
)


def normalize_input_url(url: str) -> NormalizedRepositoryUrl:
    """Normalize a user-supplied GitHub URL.

    Raises :class:`ApiError` with code ``validation_error`` for any
    input that does not match the accepted public-GitHub shape.
    """
    try:
        return normalize_github_url(url)
    except RepositoryUrlError as exc:
        raise ApiError(
            ApiErrorCode.VALIDATION_ERROR,
            "Repository URL is not a valid public GitHub URL.",
            details={"reason": str(exc)},
        ) from exc


def create_repository_from_url(session: Session, url: str) -> Repository:
    """Create a repository record from a GitHub URL.

    The function is idempotent on the canonical URL: if a repository
    with the same normalized URL already exists, that record is
    returned. Otherwise a new repository is created and committed.
    """
    normalized = normalize_input_url(url)
    existing = repository_repo.get_repository_by_canonical_url(session, normalized.canonical_url)
    if existing is not None:
        return existing

    repo = repository_repo.create_github_repository(
        session,
        owner=normalized.owner,
        name=normalized.name,
        canonical_url=normalized.canonical_url,
    )
    try:
        session.commit()
    except IntegrityError as exc:
        # A concurrent insert won the race; fall back to the
        # canonical-URL lookup so the API is still idempotent.
        session.rollback()
        existing = repository_repo.get_repository_by_canonical_url(
            session, normalized.canonical_url
        )
        if existing is not None:
            return existing
        raise ApiError(
            ApiErrorCode.DUPLICATE,
            "Repository already exists with conflicting identity.",
            details={"canonical_url": normalized.canonical_url},
        ) from exc
    return repo


def get_repository_or_404(session: Session, repository_id: int) -> Repository:
    repo = repository_repo.get_repository_by_id(session, repository_id)
    if repo is None:
        raise ApiError(
            ApiErrorCode.NOT_FOUND,
            "Repository not found.",
            details={"repository_id": repository_id},
        )
    return repo


def list_repositories(
    session: Session, *, page: int, page_size: int
) -> tuple[Sequence[Repository], int]:
    return repository_repo.list_repositories(session, page=page, page_size=page_size)
