"""Health and system-info endpoints."""

from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import text

from app.api.deps import DBSession, SettingsDep
from app.schemas.system import HealthResponse, SystemInfoResponse
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
    )
