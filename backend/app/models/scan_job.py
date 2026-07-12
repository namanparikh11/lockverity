"""Scan executor state model.

A *scan_job* is the per-scan row that drives the executor. It
records the executor's current state, its last heartbeat, and the
worker that owns it. After a process crash, the recovery routine
finds ``scan_jobs`` whose ``state == 'running'`` and whose
``last_heartbeat_at`` is older than the configured threshold and
marks them failed with the code ``lost_heartbeat``.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import TimestampMixin


class ScanJobState(str, enum.Enum):
    IDLE = "idle"
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ScanJob(Base, TimestampMixin):
    __tablename__ = "scan_jobs"
    __table_args__ = (
        CheckConstraint(
            "length(executor_id) >= 8",
            name="scan_job_executor_id_min_length",
        ),
        Index("ix_scan_jobs_scan_run_id", "scan_run_id"),
        Index("ix_scan_jobs_state", "state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(
        ForeignKey("scan_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    state: Mapped[ScanJobState] = mapped_column(
        SAEnum(ScanJobState, name="scan_job_state"),
        nullable=False,
        default=ScanJobState.IDLE,
    )
    executor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_summary: Mapped[str | None] = mapped_column(String(2048), nullable=True)
