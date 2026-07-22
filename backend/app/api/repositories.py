"""Repository endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.api.deps import DBSession, PageParamsDep
from app.api.mappers import pagination
from app.repositories import repository_repo
from app.schemas.common import SchemaModel
from app.schemas.repository import (
    RepositoryCreate,
    RepositoryLatestScan,
    RepositoryRead,
    RepositorySummary,
    RepositoryWithSummary,
)
from app.services import repository_service

router = APIRouter(prefix="/repositories", tags=["repositories"])


class PaginatedRepositories(SchemaModel):
    items: list[RepositoryWithSummary]
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
    return RepositoryRead.model_validate(repo)


def _upload_fallback_label(repo) -> str:
    """Return the bounded opaque fallback label for an uploaded row."""
    short = (repo.canonical_url or "").removeprefix("upload://").strip()
    if not short:
        return "Uploaded archive"
    return f"Uploaded archive · upload/{short}"


def _display_name(
    repo,
    *,
    historical_archive_filename: str | None = None,
) -> str:
    """Return the primary human-readable label for a repository row.

    Precedence (v2.0.6):

    1. GitHub rows: ``owner/name``.
    2. Uploaded rows with ``Repository.original_filename``:
       the persisted filename (basename-only, sanitised at
       intake).
    3. Uploaded rows with a non-null
       ``Workspace.archive_filename`` from a single agreed
       historical basename: that historical filename.
       The helper is called with a value already resolved by
       ``repository_repo.get_repository_historical_filenames``
       so a conflict returns ``None`` here (the bounded
       fallback is used instead).
    4. Uploaded rows with no filename metadata at all: the
       bounded opaque fallback
       ``Uploaded archive · upload/<short-key>``.

    The function never exposes a local absolute path. The
    short key is the part of ``canonical_url`` after
    ``upload://`` (the upload marker is a 16-character
    hex string).
    """
    if repo.source_type.value == "github":
        return f"{repo.owner}/{repo.name}"
    if repo.original_filename:
        return repo.original_filename
    if historical_archive_filename:
        return historical_archive_filename
    return _upload_fallback_label(repo)


def _canonical_identity(repo) -> str:
    """Return the secondary technical identifier for a repository row."""
    if repo.source_type.value == "github":
        return repo.canonical_url or f"{repo.owner}/{repo.name}"
    short = (repo.canonical_url or "").removeprefix("upload://").strip()
    if not short:
        return "upload://unknown"
    return f"upload/{short}"


def _summary_to_dict(summary) -> RepositorySummary:
    """Convert a ``RepositorySummary`` row to the schema."""
    latest_scan: RepositoryLatestScan | None = None
    if summary.latest_scan_id is not None and summary.latest_scan_status is not None:
        latest_scan = RepositoryLatestScan(
            id=summary.latest_scan_id,
            status=summary.latest_scan_status,
            trigger_type=summary.latest_scan_trigger_type or "manual",
            created_at=summary.latest_scan_created_at,
            completed_at=summary.latest_scan_completed_at,
        )
    return RepositorySummary(
        scan_count=summary.scan_count,
        eligible_comparison_scan_count=summary.eligible_comparison_scan_count,
        latest_scan=latest_scan,
    )


@router.get(
    "",
    response_model=PaginatedRepositories,
    summary="List registered repositories.",
)
def list_repositories(
    session: DBSession,
    page_params: PageParamsDep,
    search: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    archived: str | None = Query(default=None, pattern="^(all|active|archived)$"),
) -> PaginatedRepositories:
    items, total = repository_service.list_repositories(
        session,
        page=page_params.page,
        page_size=page_params.page_size,
        search=search,
        provider=provider,
        source_type=source_type,
        archived=archived,
    )
    # Single batched summary read; never one query per row.
    summaries = repository_repo.get_repository_summaries(session, [r.id for r in items])
    # v2.0.6: single batched historical-filename read; never
    # one query per row. The two batched reads are issued
    # back-to-back so the list endpoint still produces a
    # bounded query count (one paginated list query, one
    # summary aggregate, one historical-filename read).
    historical = repository_repo.get_repository_historical_filenames(session, [r.id for r in items])
    enriched: list[RepositoryWithSummary] = []
    for repo in items:
        base = RepositoryRead.model_validate(repo)
        summary = summaries.get(repo.id)
        if summary is None:
            # Defensive: a row that disappeared between the
            # list query and the summary read. Render a
            # bounded zero-summary rather than crashing.
            summary = repository_repo.RepositorySummary(
                repository_id=repo.id,
                scan_count=0,
                latest_scan_id=None,
                latest_scan_status=None,
                latest_scan_created_at=None,
                latest_scan_completed_at=None,
                latest_scan_trigger_type=None,
                eligible_comparison_scan_count=0,
            )
        # v2.0.6: pass the historical archive filename
        # into the display-name helper so an uploaded row
        # whose ``original_filename`` is null (a v2.0.4 or
        # earlier row) still surfaces a human-readable
        # label derived from a trustworthy persisted
        # ``Workspace.archive_filename``. A conflict
        # surfaces as ``None`` and the helper falls back
        # to the bounded opaque label.
        hist = historical.get(repo.id)
        historical_filename = hist.historical_archive_filename if hist is not None else None
        enriched.append(
            RepositoryWithSummary(
                **base.model_dump(),
                summary=_summary_to_dict(summary),
                display_name=_display_name(repo, historical_archive_filename=historical_filename),
                canonical_identity=_canonical_identity(repo),
            )
        )
    return PaginatedRepositories(
        items=enriched,
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
    return RepositoryRead.model_validate(repo)
