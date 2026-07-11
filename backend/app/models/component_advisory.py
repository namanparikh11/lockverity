"""Component-advisory association.

A row says "this component, in this scan, is affected by this
advisory". The association carries the severity *as reported by the
provider* (``severity_source`` / ``severity_label`` / ``severity_score``)
plus bounded evidence for debugging. If a provider does not supply a
score, the score column is NULL - we never invent one.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import TimestampMixin


class ComponentAdvisory(Base, TimestampMixin):
    __tablename__ = "component_advisories"
    __table_args__ = (
        UniqueConstraint(
            "scan_run_id",
            "component_id",
            "advisory_id",
            name="uq_component_advisories_scan_component_advisory",
        ),
        CheckConstraint(
            "severity_score IS NULL OR (severity_score >= 0 AND severity_score <= 10)",
            name="severity_range",
        ),
        CheckConstraint(
            "length(evidence_json) <= 65536",
            name="evidence_bounded",
        ),
        Index("ix_component_advisories_scan_run_id", "scan_run_id"),
        Index("ix_component_advisories_component_id", "component_id"),
        Index("ix_component_advisories_advisory_id", "advisory_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(
        ForeignKey("scan_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    component_id: Mapped[int] = mapped_column(
        ForeignKey("components.id", ondelete="CASCADE"),
        nullable=False,
    )
    advisory_id: Mapped[int] = mapped_column(
        ForeignKey("advisories.id", ondelete="CASCADE"),
        nullable=False,
    )
    affected: Mapped[bool] = mapped_column(Integer, nullable=False, default=1)
    fixed_versions_json: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    severity_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    severity_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    severity_score: Mapped[float | None] = mapped_column(Integer, nullable=True)
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
