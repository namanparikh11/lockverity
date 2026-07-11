"""Repository endpoints."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import DBSession, PageParamsDep
from app.api.mappers import pagination, repository_to_read
from app.schemas.common import SchemaModel
from app.schemas.repository import RepositoryCreate, RepositoryRead
from app.services import repository_service

router = APIRouter(prefix="/repositories", tags=["repositories"])


class PaginatedRepositories(SchemaModel):
    items: list[RepositoryRead]
    pagination: dict


@router.post(
    "",
    response_model=RepositoryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a public GitHub repository for analysis.",
)
def create_repository(
    payload: RepositoryCreate,
    session: DBSession,
) -> RepositoryRead:
    repo = repository_service.create_repository_from_url(session, payload.canonical_url)
    return repository_to_read(repo)


@router.get(
    "",
    response_model=PaginatedRepositories,
    summary="List registered repositories.",
)
def list_repositories(
    session: DBSession,
    page_params: PageParamsDep,
) -> PaginatedRepositories:
    items, total = repository_service.list_repositories(
        session,
        page=page_params.page,
        page_size=page_params.page_size,
    )
    return PaginatedRepositories(
        items=[repository_to_read(item) for item in items],
        pagination=pagination(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ).model_dump(),
    )


@router.get(
    "/{repository_id}",
    response_model=RepositoryRead,
    summary="Get one repository by id.",
)
def get_repository(repository_id: int, session: DBSession) -> RepositoryRead:
    repo = repository_service.get_repository_or_404(session, repository_id)
    return repository_to_read(repo)
