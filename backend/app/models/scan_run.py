"""Scan run model.

A *scan run* is one attempt to analyze a repository. It has a strict
lifecycle enforced both in the database (CHECK constraint) and in the
service layer (transition validation). Terminal statuses are
immutable except for explicit human intervention paths we do not yet
expose.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.models.repository import Repository


class ScanStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScanTriggerType(str, enum.Enum):
    MANUAL = "manual"
    UPLOAD = "upload"
    SCHEDULED = "scheduled"
    API = "api"


TERMINAL_SCAN_STATUSES: frozenset[ScanStatus] = frozenset(
    {ScanStatus.COMPLETED, ScanStatus.PARTIAL, ScanStatus.FAILED, ScanStatus.CANCELLED}
)


class ScanRun(Base, TimestampMixin):
    __tablename__ = "scan_runs"
    __table_args__ = (
        CheckConstraint(
            "(resolved_commit_sha IS NULL) OR (length(resolved_commit_sha) >= 7)",
            name="resolved_sha_length",
        ),
        Index("ix_scan_runs_repository_id", "repository_id"),
        Index("ix_scan_runs_status", "status"),
        Index(
            "ix_scan_runs_repository_id_created_at",
            "repository_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[ScanStatus] = mapped_column(
        SAEnum(ScanStatus, name="scan_status"),
        nullable=False,
        default=ScanStatus.QUEUED,
    )
    trigger_type: Mapped[ScanTriggerType] = mapped_column(
        SAEnum(ScanTriggerType, name="scan_trigger_type"),
        nullable=False,
    )
    requested_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    analyzer_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_summary: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    repository: Mapped[Repository] = relationship(back_populates="scans")
    stages: Mapped[list[app.models.scan_stage.ScanStage]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="scan_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ScanStage.id",
    )
