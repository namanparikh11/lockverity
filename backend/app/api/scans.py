"""Scan, stage, finding, and provider-observation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query, status
from sqlalchemy.orm import Session

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
from app.models.scan_job import ScanJobState
from app.models.scan_run import ScanStatus, ScanTriggerType
from app.schemas.common import SchemaModel
from app.schemas.intake import ScanCancelRequest, ScanRunRequest
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
from app.services.executor_service import ScanTask, new_executor_id
from app.services.orchestrator_service import ScanOrchestrator, _CancellationToken
from app.services.rescan_service import RescanService
from app.singletons import get_executor
from app.utils.datetime import utcnow
from app.utils.errors import ApiError, ApiErrorCode

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

    The scan starts in ``queued`` state. The worker picks it up
    when the caller invokes ``POST /scans/{id}/run``.

    The v1.6.1 "Retry as new scan" / "Run another scan"
    flow uses the dedicated
    ``POST /repositories/{id}/rescan`` route, which
    creates a fresh workspace and re-materialises
    the source before returning. This route stays
    as the low-level scan-record creator used by the
    orchestrator tests and by callers that need to
    create a queued scan without a workspace.
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


@repository_scans.post(
    "/{repository_id}/rescan",
    response_model=ScanRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a runnable new scan for the repository with a prepared workspace.",
)
def rescan_repository(
    repository_id: int,
    session: DBSession,
    payload: ScanCreate | None = None,
) -> ScanRead:
    """Workspace-preserving rescan for an existing repository.

    v1.6.1: the route performs the full rescan
    semantics — it creates a fresh scan row, a
    fresh workspace, and re-materialises the source
    evidence (re-download the GitHub tarball, or
    safely copy the previous upload workspace). The
    historical scan and workspace are never mutated.

    When the original source evidence is no longer
    available, the route returns a bounded
    ``rescan_source_unavailable`` error before any
    queued row is persisted.
    """
    if payload is None:
        payload = ScanCreate.model_validate({})
    rescan = RescanService(session)
    result = rescan.rescan_repository(
        repository_id,
        trigger_type=payload.trigger_type or ScanTriggerType.MANUAL,
        requested_ref=payload.requested_ref,
    )
    return scan_to_read(result.scan)


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
    "",
    response_model=PaginatedScans,
    summary="List scans across all repositories (cross-repo rollup).",
)
def list_scans(
    session: DBSession,
    page_params: PageParamsDep,
    status_filter: ScanStatus | None = Query(
        default=None,
        alias="status",
        description="Filter by scan status.",
    ),
    trigger_type: ScanTriggerType | None = Query(default=None),
) -> PaginatedScans:
    """Cross-repository scan listing for the dashboard rollup.

    The per-repository listing on ``/repositories/{id}/scans`` is
    unchanged. This endpoint exists for product surfaces that need
    a global view, such as the dashboard "scans" summary card and
    the operator's "all scans" panel.
    """
    items, total = scan_service.list_all_scans(
        session,
        page=page_params.page,
        page_size=page_params.page_size,
        status=status_filter,
        trigger_type=trigger_type,
    )
    return PaginatedScans(
        items=[scan_to_read(item) for item in items],
        pagination=pagination(
            page=page_params.page,
            page_size=page_params.page_size,
            total=total,
        ).model_dump(),
    )


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


@scans.post(
    "/{scan_id}/cancel",
    response_model=ScanRead,
    summary="Request cancellation of a running or queued scan.",
)
def cancel_scan(
    scan_id: int,
    session: DBSession,
    payload: ScanCancelRequest | None = None,
) -> ScanRead:
    """Mark a scan for cancellation.

    A scan that is still ``queued`` is cancelled immediately. A
    scan that is ``running`` is allowed to finish its current
    stage, then marked ``cancelled``. Terminal scans return
    409 because the operation is illegal.
    """
    scan = scan_service.get_scan_or_404(session, scan_id)
    if scan.status in {
        ScanStatus.COMPLETED,
        ScanStatus.PARTIAL,
        ScanStatus.FAILED,
        ScanStatus.CANCELLED,
    }:
        raise ApiError(
            ApiErrorCode.ILLEGAL_TRANSITION,
            "Scan is in a terminal state and cannot be cancelled.",
            details={"current_status": scan.status.value},
        )
    orchestrator = _orchestrator_for_session(session)
    orchestrator.cancel(scan_id)
    if payload is not None and payload.reason:
        scan.failure_summary = (scan.failure_summary or "") + f" reason={payload.reason}"
        session.commit()
    return scan_to_read(scan_service.get_scan_or_404(session, scan_id))


@scans.post(
    "/{scan_id}/run",
    response_model=ScanRead,
    summary="Start a queued scan on the local worker.",
)
def run_scan(
    scan_id: int,
    session: DBSession,
    payload: ScanRunRequest | None = None,
) -> ScanRead:
    """Run ``scan_id`` synchronously on the local worker.

    The endpoint is idempotent for already-running scans (the
    request returns 409). For terminal scans, the run is
    rejected with 409. For queued scans, the scan is moved to
    ``running`` and the worker schedules the orchestration.
    """
    from app.repositories import job_repo

    scan = scan_service.get_scan_or_404(session, scan_id)
    force = bool(payload and payload.force)
    if scan.status == ScanStatus.RUNNING and not force:
        raise ApiError(
            ApiErrorCode.ILLEGAL_TRANSITION,
            "Scan is already running.",
            details={"current_status": scan.status.value},
        )
    if scan.status in {
        ScanStatus.COMPLETED,
        ScanStatus.PARTIAL,
        ScanStatus.FAILED,
        ScanStatus.CANCELLED,
    }:
        raise ApiError(
            ApiErrorCode.ILLEGAL_TRANSITION,
            "Scan is in a terminal state and cannot be re-run.",
            details={"current_status": scan.status.value},
        )

    executor = get_executor()
    # Record the executor job row before scheduling the work.
    job = job_repo.get_for_scan(session, scan_id)
    executor_id = new_executor_id()
    if job is None:
        job = job_repo.create(
            session,
            scan_run_id=scan_id,
            executor_id=executor_id,
        )
    else:
        job.executor_id = executor_id
        job.state = ScanJobState.QUEUED
        job.queued_at = utcnow()
        job.failure_code = None
        job.failure_summary = None
    session.commit()

    # The orchestrator needs a session factory. We provide one
    # that opens a fresh session per call. The test suite can
    # override the session factory via dependency_overrides on
    # the application instance.
    orchestrator = _orchestrator_for_session(session)
    cancellation = _CancellationToken()

    def _run() -> None:
        try:
            orchestrator.run(scan_id, cancellation=cancellation)
        except Exception:
            logger.exception("scan %s failed in worker", scan_id)
        finally:
            _finalize_job(scan_id, executor_id)

    task = ScanTask(
        scan_id=scan_id,
        task_key=executor_id,
        callback=_run,
        description=f"scan {scan_id}",
    )
    executor.submit(task)
    return scan_to_read(scan_service.get_scan_or_404(session, scan_id))


def _orchestrator_for_session(session: Session) -> ScanOrchestrator:
    """Build a fresh orchestrator bound to a session factory.

    Each call opens a new session. This is the right shape for
    a small in-process worker.
    """
    from app.db import session as _db_session

    return ScanOrchestrator(_db_session.SessionLocal)


def _finalize_job(scan_id: int, executor_id: str) -> None:
    # Use ``app.db.session`` rather than ``app.db`` to honour the
    # test-time rebind of the engine and session factory. The
    # ``app.db`` package re-exports ``SessionLocal`` at import time
    # and that binding is *not* updated by the conftest, so a
    # plain ``from app.db import SessionLocal`` here would silently
    # talk to the wrong engine.
    from app.db import session as _db_session
    from app.repositories import job_repo

    with _db_session.SessionLocal() as session:
        job = job_repo.get_for_scan(session, scan_id)
        if job is None or job.executor_id != executor_id:
            return
        scan = scan_service.get_scan_or_404(session, scan_id)
        if scan.status == ScanStatus.COMPLETED:
            job.state = ScanJobState.IDLE
        elif scan.status in {ScanStatus.FAILED, ScanStatus.CANCELLED}:
            job.state = (
                ScanJobState.FAILED if scan.status == ScanStatus.FAILED else ScanJobState.CANCELLED
            )
            job.failure_code = scan.failure_code
            job.failure_summary = scan.failure_summary
        job.completed_at = utcnow()
        session.commit()


import logging  # noqa: E402

logger = logging.getLogger("lockverity.api.scans")


__all__ = [
    "PaginatedFindings",
    "PaginatedObservations",
    "PaginatedScans",
    "PaginatedStages",
    "repository_scans",
    "scans",
]
