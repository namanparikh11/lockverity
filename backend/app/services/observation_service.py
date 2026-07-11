"""Provider observation service - read-only at v0.1.

Writes are produced by provider implementations in later milestones.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.models.provider_observation import ProviderObservation, ProviderStatus
from app.repositories import observation_repo
from app.services import scan_service


def list_provider_observations(
    session: Session,
    scan_id: int,
    *,
    page: int,
    page_size: int,
    status: ProviderStatus | None = None,
) -> tuple[Sequence[ProviderObservation], int]:
    scan_service.get_scan_or_404(session, scan_id)
    return observation_repo.list_observations_for_scan(
        session,
        scan_id,
        page=page,
        page_size=page_size,
        status=status,
    )
