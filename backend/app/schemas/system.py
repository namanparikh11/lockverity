"""System / health API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import SchemaModel


class HealthResponse(SchemaModel):
    status: str
    database: str
    version: str
    environment: str
    timestamp: datetime


class SystemInfoResponse(SchemaModel):
    name: str
    version: str
    tagline: str
    environment: str
    api_prefix: str
    archive_limits: dict[str, int]
    pagination: dict[str, int]
    provider_safety: dict[str, int | float]
    intake: dict[str, int | float | bool | str | None] = Field(default_factory=dict)
