"""Scan, stage, finding, and provider-observation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.api.deps import DBSession, PageParamsDep
from app.api.mappers import (
    finding_to_read,
    observation_to_read,
    pagination,
    scan_to_read,
    stage_to_read,
)
from app.models.finding import FindingCategory, FindingSeverity
from app.models.provider_observation import ProviderStatus
from app.schemas.common import SchemaModel
from app.schemas.scan import (
    FindingRead,
    ProviderObservationRead,
    ScanCreate,
    ScanRead,
    ScanStageRead,
)
from app.services import (
    finding_service,
    observation_service,
    scan_service,
)

# Two routers share the URL space but live in separate modules for
# readability. ``scans`` is mounted at /api/v1/scans, ``repository_scans``
# is mounted at /api/v1/repositories/{repository_id}/scans.
repository_scans = APIRouter(prefix="/repositories", tags=["scans"])
scans = APIRouter(prefix="/scans", tags=["scans"])


class PaginatedScans(SchemaModel):
    items: list[ScanRead]
    pagination: dict


class PaginatedStages(SchemaModel):
    items: list[ScanStageRead]


class PaginatedFindings(SchemaModel):
    items: list[FindingRead]
    pagination: dict


class PaginatedObservations(SchemaModel):
    items: list[ProviderObservationRead]
    pagination: dict


# ---- nested under repositories ----
@repository_scans.post(
    "/{repository_id}/scans",
    response_model=ScanRead,
    status_code=status.HTTP_201_CREATED,
    summary="Queue a new scan for the repository.",
)
def create_scan(
    repository_id: int,
    session: DBSession,
    payload: ScanCreate | None = None,
) -> ScanRead:
    """Create a queued scan and seed its default stage pipeline.

    The scan starts in ``queued`` state. v0.1 does not run an
    executor; the scan is observable but stays queued until a worker
    arrives in a later milestone.
    """
    if payload is None:
        payload = ScanCreate.model_validate({})
    scan = scan_service.create_scan(
        session,
        repository_id=repository_id,
        trigger_type=payload.trigger_type,
        requested_ref=payload.requested_ref,
    )
    return scan_to_read(scan)


@repository_scans.get(
    "/{repository_id}/scans",
    response_model=PaginatedScans,
    summary="List scans for one repository.",
)
def list_scans_for_repository(
    repository_id: int,
    session: DBSession,
    page_params: PageParamsDep,
) -> PaginatedScans:
    items, total = scan_service.list_scans_for_repository(
        session,
        repository_id,
        page=page_params.page,
        page_size=page_params.page_size,
    )
    return PaginatedScans(
        items=[scan_to_read(item) for item in items],
        pagination=pagination(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ).model_dump(),
    )


# ---- top-level scans endpoints ----
@scans.get(
    "/{scan_id}",
    response_model=ScanRead,
    summary="Get one scan by id.",
)
def get_scan(scan_id: int, session: DBSession) -> ScanRead:
    scan = scan_service.get_scan_or_404(session, scan_id)
    return scan_to_read(scan)


@scans.get(
    "/{scan_id}/stages",
    response_model=PaginatedStages,
    summary="List the stages of a scan in pipeline order.",
)
def list_stages(scan_id: int, session: DBSession) -> PaginatedStages:
    items = scan_service.list_stages_for_scan(session, scan_id)
    return PaginatedStages(items=[stage_to_read(item) for item in items])


@scans.get(
    "/{scan_id}/findings",
    response_model=PaginatedFindings,
    summary="List findings produced by a scan.",
)
def list_findings(
    scan_id: int,
    session: DBSession,
    page_params: PageParamsDep,
    category: FindingCategory | None = Query(default=None),
    severity: FindingSeverity | None = Query(default=None),
) -> PaginatedFindings:
    items, total = finding_service.list_findings_for_scan(
        session,
        scan_id,
        page=page_params.page,
        page_size=page_params.page_size,
        category=category,
        severity=severity,
    )
    return PaginatedFindings(
        items=[finding_to_read(item) for item in items],
        pagination=pagination(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ).model_dump(),
    )


@scans.get(
    "/{scan_id}/providers",
    response_model=PaginatedObservations,
    summary="List provider availability observations for a scan.",
)
def list_providers(
    scan_id: int,
    session: DBSession,
    page_params: PageParamsDep,
    status_filter: ProviderStatus | None = Query(
        default=None,
        alias="status",
        description="Filter by provider status.",
    ),
) -> PaginatedObservations:
    items, total = observation_service.list_provider_observations(
        session,
        scan_id,
        page=page_params.page,
        page_size=page_params.page_size,
        status=status_filter,
    )
    return PaginatedObservations(
        items=[observation_to_read(item) for item in items],
        pagination=pagination(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ).model_dump(),
    )
