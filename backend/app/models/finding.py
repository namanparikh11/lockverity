"""Finding model.

A *finding* is a single observable security observation in a scan.
Findings are *evidence-based*, not score-based. Every finding has a
deterministic ``stable_key`` per scan, plus bounded ``evidence_json``
that the API can return to the client.

Severity and confidence are independent dimensions. A critical-
severity finding may still have low confidence, and the UI must show
both.
"""

from __future__ import annotations

import enum

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import TimestampMixin


class FindingCategory(str, enum.Enum):
    DEPENDENCY = "dependency"
    VULNERABILITY = "vulnerability"
    WORKFLOW = "workflow"
    REPOSITORY_POSTURE = "repository_posture"
    LICENCE = "licence"
    PROVIDER = "provider"
    DATA_QUALITY = "data_quality"


class FindingSeverity(str, enum.Enum):
    INFORMATIONAL = "informational"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class FindingConfidence(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CONFIRMED = "confirmed"
    UNKNOWN = "unknown"


class FindingStatus(str, enum.Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    ACCEPTED = "accepted"
    SUPPRESSED = "suppressed"


class Finding(Base, TimestampMixin):
    __tablename__ = "findings"
    __table_args__ = (
        UniqueConstraint(
            "scan_run_id",
            "stable_key",
            name="uq_findings_scan_run_id_stable_key",
        ),
        CheckConstraint(
            "length(evidence_json) <= 65536",
            name="evidence_bounded",
        ),
        CheckConstraint(
            "location_start_line IS NULL OR location_start_line > 0",
            name="start_line_positive",
        ),
        CheckConstraint(
            "location_end_line IS NULL OR location_end_line > 0",
            name="end_line_positive",
        ),
        CheckConstraint(
            "(location_start_line IS NULL) OR "
            "(location_end_line IS NULL) OR "
            "(location_end_line >= location_start_line)",
            name="range_consistent",
        ),
        Index("ix_findings_scan_run_id", "scan_run_id"),
        Index("ix_findings_repository_id", "repository_id"),
        Index("ix_findings_category", "category"),
        Index("ix_findings_severity", "severity"),
        Index("ix_findings_rule_id", "rule_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(
        ForeignKey("scan_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    repository_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    rule_id: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[FindingCategory] = mapped_column(
        SAEnum(FindingCategory, name="finding_category"),
        nullable=False,
    )
    severity: Mapped[FindingSeverity] = mapped_column(
        SAEnum(FindingSeverity, name="finding_severity"),
        nullable=False,
    )
    confidence: Mapped[FindingConfidence] = mapped_column(
        SAEnum(FindingConfidence, name="finding_confidence"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[str] = mapped_column(String(2048), nullable=False)
    remediation: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    location_start_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location_end_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stable_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[FindingStatus] = mapped_column(
        SAEnum(FindingStatus, name="finding_status"),
        nullable=False,
        default=FindingStatus.OPEN,
    )
