"""Scan data-access helpers."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.scan_run import ScanRun, ScanStatus, ScanTriggerType


def get_scan_by_id(session: Session, scan_id: int) -> ScanRun | None:
    return session.get(ScanRun, scan_id)


def list_scans_for_repository(
    session: Session,
    repository_id: int,
    *,
    page: int,
    page_size: int,
) -> tuple[Sequence[ScanRun], int]:
    if page < 1:
        raise ValueError("page must be >= 1")
    if page_size < 1:
        raise ValueError("page_size must be >= 1")
    total = session.execute(
        select(func.count()).select_from(ScanRun).where(ScanRun.repository_id == repository_id)
    ).scalar_one()
    stmt = (
        select(ScanRun)
        .where(ScanRun.repository_id == repository_id)
        .order_by(ScanRun.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    items = session.execute(stmt).scalars().all()
    return items, int(total or 0)


def create_scan(
    session: Session,
    *,
    repository_id: int,
    trigger_type: ScanTriggerType,
    requested_ref: str | None = None,
) -> ScanRun:
    scan = ScanRun(
        repository_id=repository_id,
        trigger_type=trigger_type,
        status=ScanStatus.QUEUED,
        requested_ref=requested_ref,
    )
    session.add(scan)
    session.flush()
    return scan
