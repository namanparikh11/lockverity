"""Health and system-info endpoints."""

from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import text

from app.api.deps import DBSession, SettingsDep
from app.core.config import get_settings
from app.models.workspace import Workspace, WorkspaceState
from app.schemas.intake import (
    ProviderLimit,
    SystemProviderLimitsResponse,
    SystemWorkspaceCleanupResponse,
    WorkspaceRead,
)
from app.schemas.system import HealthResponse, SystemInfoResponse
from app.services import cache_service
from app.services.workspace_service import WorkspaceService
from app.utils.datetime import utcnow

router = APIRouter(tags=["system"])


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Lightweight health check.",
    description=(
        "Returns the application name, environment, and database "
        "connectivity status. No provider calls, no scans, no "
        "external state."
    ),
)
def health(session: DBSession, settings: SettingsDep) -> HealthResponse:
    db_status = "ok"
    try:
        session.execute(text("SELECT 1"))
    except Exception:
        db_status = "unavailable"
    return HealthResponse(
        status="ok" if db_status == "ok" else "degraded",
        database=db_status,
        version=settings.app_version,
        environment=settings.environment,
        timestamp=utcnow(),
    )


@router.get(
    "/system/info",
    response_model=SystemInfoResponse,
    summary="Build and configuration metadata.",
)
def system_info(settings: SettingsDep) -> SystemInfoResponse:
    return SystemInfoResponse(
        name=settings.app_name,
        version=settings.app_version,
        tagline=settings.app_tagline,
        environment=settings.environment,
        api_prefix=settings.api_prefix,
        archive_limits={
            "max_compressed_bytes": settings.archive_max_compressed_bytes,
            "max_uncompressed_bytes": settings.archive_max_uncompressed_bytes,
            "max_file_count": settings.archive_max_file_count,
            "max_file_bytes": settings.archive_max_file_bytes,
            "max_depth": settings.archive_max_depth,
            "suspicious_ratio": settings.archive_suspicious_ratio,
        },
        pagination={
            "default_page_size": settings.pagination_default_page_size,
            "max_page_size": settings.pagination_max_page_size,
        },
        provider_safety={
            "timeout_seconds": settings.provider_timeout_seconds,
            "max_response_bytes": settings.provider_max_response_bytes,
            "retry_limit": settings.provider_retry_limit,
        },
        intake={
            "github_api_url": settings.github_api_url,
            "github_max_download_bytes": settings.github_max_download_bytes,
            "github_timeout_seconds": settings.github_timeout_seconds,
            "github_token_configured": settings.github_token is not None,
            "scan_worker_concurrency": settings.scan_worker_concurrency,
            "scan_heartbeat_seconds": settings.scan_heartbeat_seconds,
            "scan_heartbeat_timeout_seconds": settings.scan_heartbeat_timeout_seconds,
            "provider_cache_max_payload_bytes": settings.provider_cache_max_payload_bytes,
            "provider_cache_default_ttl_seconds": settings.provider_cache_default_ttl_seconds,
        },
    )


@router.get(
    "/system/provider-limits",
    response_model=SystemProviderLimitsResponse,
    summary="Provider rate-limit and cache snapshot.",
)
def system_provider_limits(session: DBSession) -> SystemProviderLimitsResponse:
    # v0.2 only knows about the GitHub intake path. The
    # endpoint reports a single placeholder so the frontend
    # has a stable shape.
    settings = get_settings()
    return SystemProviderLimitsResponse(
        github=[
            ProviderLimit(
                provider="github",
                operation="api",
                status="available",
                cache_status=None,
                retry_after=None,
                rate_limit_remaining=None,
                rate_limit_reset=None,
            ),
        ],
        overall_cache_size=cache_service.CacheService(
            session, settings=settings
        )._settings.provider_cache_max_payload_bytes,  # type: ignore[attr-defined]
    )


@router.post(
    "/system/workspaces/cleanup",
    response_model=SystemWorkspaceCleanupResponse,
    summary="Remove stale workspaces (administrative).",
    description=(
        "Removes workspaces whose owning scan is in a terminal "
        "state, plus workspaces that are stuck in "
        "``quarantined`` or ``validating`` for longer than the "
        "configured heartbeat timeout. Intended for local "
        "administration; protect with an authenticating reverse "
        "proxy in production."
    ),
)
def system_workspaces_cleanup(
    session: DBSession,
    settings: SettingsDep,
) -> SystemWorkspaceCleanupResponse:
    workspaces_service = WorkspaceService(session, settings=settings)
    stale_removed = workspaces_service.cleanup_stale()
    failed_removed = workspaces_service.cleanup_failed_scans()
    total = stale_removed + failed_removed
    # Return the (now-cleaned) workspaces for diagnostic
    # purposes. The ``to_read`` projection hides the on-disk
    # path.
    from app.repositories import workspace_repo

    cleaned = workspace_repo.list_states(
        session,
        states=[WorkspaceState.CLEANED_UP],
    )
    return SystemWorkspaceCleanupResponse(
        removed=total,
        removed_workspaces=[_workspace_to_read(w) for w in cleaned[-total:]],
    )


def _workspace_to_read(workspace: Workspace) -> WorkspaceRead:
    return WorkspaceRead.model_validate(workspace)
