"""Repository data-access helpers.

Pagination and ordering are baked in here so route handlers and
services have a single, stable contract. ``list_repositories`` does
not eager-load scans; callers that need scan counts can do a separate
aggregate query to avoid N+1 behavior in list endpoints.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.repository import (
    Repository,
    RepositoryProvider,
    RepositorySourceType,
)


def get_repository_by_id(session: Session, repository_id: int) -> Repository | None:
    return session.get(Repository, repository_id)


def get_repository_by_canonical_url(session: Session, canonical_url: str) -> Repository | None:
    stmt = select(Repository).where(Repository.canonical_url == canonical_url)
    return session.execute(stmt).scalar_one_or_none()


def get_repository_by_identity(
    session: Session,
    *,
    provider: RepositoryProvider,
    owner: str,
    name: str,
) -> Repository | None:
    stmt = select(Repository).where(
        Repository.provider == provider,
        Repository.owner == owner,
        Repository.name == name,
    )
    return session.execute(stmt).scalar_one_or_none()


def create_github_repository(
    session: Session,
    *,
    owner: str,
    name: str,
    canonical_url: str,
    description: str | None = None,
    default_branch: str | None = None,
    visibility: str | None = None,
) -> Repository:
    from app.models.repository import RepositoryVisibility

    repo = Repository(
        source_type=RepositorySourceType.GITHUB,
        provider=RepositoryProvider.GITHUB,
        owner=owner,
        name=name,
        canonical_url=canonical_url,
        description=description,
        default_branch=default_branch,
        visibility=(
            RepositoryVisibility(visibility) if visibility else RepositoryVisibility.PUBLIC
        ),
    )
    session.add(repo)
    session.flush()
    return repo


def list_repositories(
    session: Session,
    *,
    page: int,
    page_size: int,
) -> tuple[Sequence[Repository], int]:
    """Return a page of repositories plus the total count."""
    if page < 1:
        raise ValueError("page must be >= 1")
    if page_size < 1:
        raise ValueError("page_size must be >= 1")
    total = session.execute(select(func.count()).select_from(Repository)).scalar_one()
    stmt = (
        select(Repository)
        .order_by(Repository.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    items = session.execute(stmt).scalars().all()
    return items, int(total or 0)
