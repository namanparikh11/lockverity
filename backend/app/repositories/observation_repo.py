"""Provider observation data-access helpers."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.provider_observation import ProviderObservation, ProviderStatus


def list_observations_for_scan(
    session: Session,
    scan_run_id: int,
    *,
    page: int,
    page_size: int,
    status: ProviderStatus | None = None,
) -> tuple[Sequence[ProviderObservation], int]:
    if page < 1:
        raise ValueError("page must be >= 1")
    if page_size < 1:
        raise ValueError("page_size must be >= 1")
    stmt_total = (
        select(func.count())
        .select_from(ProviderObservation)
        .where(ProviderObservation.scan_run_id == scan_run_id)
    )
    stmt = select(ProviderObservation).where(ProviderObservation.scan_run_id == scan_run_id)
    if status is not None:
        stmt_total = stmt_total.where(ProviderObservation.status == status)
        stmt = stmt.where(ProviderObservation.status == status)
    total = session.execute(stmt_total).scalar_one()
    stmt = (
        stmt.order_by(ProviderObservation.id.asc()).limit(page_size).offset((page - 1) * page_size)
    )
    items = session.execute(stmt).scalars().all()
    return items, int(total or 0)
