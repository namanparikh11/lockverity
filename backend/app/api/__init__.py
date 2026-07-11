"""API package - mounts every router under the configured API prefix."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import repositories, scans, system

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(repositories.router)
api_router.include_router(scans.repository_scans)
api_router.include_router(scans.scans)

__all__ = ["api_router"]
