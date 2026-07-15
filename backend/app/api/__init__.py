"""API package - mounts every router under the configured API prefix."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import intake, repositories, scans, system, v0_3

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(repositories.router)
api_router.include_router(intake.router)
api_router.include_router(scans.repository_scans)
api_router.include_router(scans.scans)
api_router.include_router(v0_3.router)

__all__ = ["api_router"]
