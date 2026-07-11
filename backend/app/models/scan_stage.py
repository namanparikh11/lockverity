"""Scan stage model.

Every scan has an ordered list of *stages* (intake, parsing,
vulnerability query, etc.). Stages make provider availability and
data completeness observable at scan time, not just after the fact.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.models.scan_run import ScanRun


class StageType(str, enum.Enum):
    REPOSITORY_INTAKE = "repository_intake"
    ARCHIVE_VALIDATION = "archive_validation"
    MANIFEST_DISCOVERY = "manifest_discovery"
    DEPENDENCY_PARSING = "dependency_parsing"
    DEPENDENCY_ENRICHMENT = "dependency_enrichment"
    VULNERABILITY_QUERY = "vulnerability_query"
    WORKFLOW_ANALYSIS = "workflow_analysis"
    REPOSITORY_POSTURE = "repository_posture"
    FINDING_RECONCILIATION = "finding_reconciliation"
    EXPORT_GENERATION = "export_generation"


class StageStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


TERMINAL_STAGE_STATUSES: frozenset[StageStatus] = frozenset(
    {
        StageStatus.COMPLETED,
        StageStatus.PARTIAL,
        StageStatus.FAILED,
        StageStatus.SKIPPED,
    }
)


class ScanStage(Base, TimestampMixin):
    __tablename__ = "scan_stages"
    __table_args__ = (
        Index("ix_scan_stages_scan_run_id", "scan_run_id"),
        Index("ix_scan_stages_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(
        ForeignKey("scan_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    stage_type: Mapped[StageType] = mapped_column(
        SAEnum(StageType, name="stage_type"),
        nullable=False,
    )
    status: Mapped[StageStatus] = mapped_column(
        SAEnum(StageStatus, name="stage_status"),
        nullable=False,
        default=StageStatus.PENDING,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    records_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_summary: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    scan_run: Mapped[ScanRun] = relationship(back_populates="stages")
