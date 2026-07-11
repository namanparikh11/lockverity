"""Repository API schemas."""

from __future__ import annotations

from datetime import datetime

from app.models.repository import (
    RepositoryProvider,
    RepositorySourceType,
    RepositoryVisibility,
)
from app.schemas.common import NonEmptyStr, SchemaModel, TimestampMixin


class RepositoryCreate(SchemaModel):
    """Payload for ``POST /api/v1/repositories``.

    For now only public GitHub repositories are accepted. Uploaded
    archives are a separate, archive-specific endpoint that arrives in
    a later milestone.
    """

    canonical_url: NonEmptyStr


class RepositoryRead(TimestampMixin):
    id: int
    source_type: RepositorySourceType
    provider: RepositoryProvider
    owner: str
    name: str
    canonical_url: str | None = None
    default_branch: str | None = None
    description: str | None = None
    visibility: RepositoryVisibility
    archived: bool
    last_provider_sync_at: datetime | None = None
