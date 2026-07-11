"""Scan stage data-access helpers."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.scan_stage import ScanStage, StageStatus, StageType


def list_stages_for_scan(session: Session, scan_run_id: int) -> Sequence[ScanStage]:
    stmt = (
        select(ScanStage).where(ScanStage.scan_run_id == scan_run_id).order_by(ScanStage.id.asc())
    )
    return session.execute(stmt).scalars().all()


def get_stage(session: Session, scan_run_id: int, stage_type: StageType) -> ScanStage | None:
    stmt = select(ScanStage).where(
        ScanStage.scan_run_id == scan_run_id,
        ScanStage.stage_type == stage_type,
    )
    return session.execute(stmt).scalar_one_or_none()


def create_stage(
    session: Session,
    *,
    scan_run_id: int,
    stage_type: StageType,
) -> ScanStage:
    stage = ScanStage(
        scan_run_id=scan_run_id,
        stage_type=stage_type,
        status=StageStatus.PENDING,
    )
    session.add(stage)
    session.flush()
    return stage
