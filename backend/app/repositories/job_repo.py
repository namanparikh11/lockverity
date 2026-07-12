"""Scan job data-access helpers."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.scan_job import ScanJob, ScanJobState


def get_for_scan(session: Session, scan_run_id: int) -> ScanJob | None:
    stmt = select(ScanJob).where(ScanJob.scan_run_id == scan_run_id)
    return session.execute(stmt).scalar_one_or_none()


def create(
    session: Session,
    *,
    scan_run_id: int,
    executor_id: str,
) -> ScanJob:
    job = ScanJob(
        scan_run_id=scan_run_id,
        executor_id=executor_id,
        state=ScanJobState.IDLE,
    )
    session.add(job)
    session.flush()
    return job


def get_by_id(session: Session, job_id: int) -> ScanJob | None:
    return session.get(ScanJob, job_id)


def list_stale(
    session: Session,
    *,
    state: ScanJobState,
    heartbeat_threshold: datetime,
) -> Sequence[ScanJob]:
    stmt = select(ScanJob).where(
        ScanJob.state == state,
        ScanJob.last_heartbeat_at < heartbeat_threshold,
    )
    return session.execute(stmt.order_by(ScanJob.id.asc())).scalars().all()
