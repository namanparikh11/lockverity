"""Dependency edge model.

An edge represents "parent depends on child". The database enforces
that parent and child live in the same scan and that an edge is not
self-referential. The service layer re-validates this on every write.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import TimestampMixin


class DependencyEdge(Base, TimestampMixin):
    __tablename__ = "dependency_edges"
    __table_args__ = (
        CheckConstraint(
            "parent_component_id <> child_component_id",
            name="no_self_reference",
        ),
        CheckConstraint(
            "depth >= 0",
            name="depth_non_negative",
        ),
        UniqueConstraint(
            "scan_run_id",
            "parent_component_id",
            "child_component_id",
            name="uq_dependency_edges_parent_child",
        ),
        Index("ix_dependency_edges_scan_run_id", "scan_run_id"),
        Index("ix_dependency_edges_parent", "parent_component_id"),
        Index("ix_dependency_edges_child", "child_component_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(
        ForeignKey("scan_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_component_id: Mapped[int] = mapped_column(
        ForeignKey("components.id", ondelete="CASCADE"),
        nullable=False,
    )
    child_component_id: Mapped[int] = mapped_column(
        ForeignKey("components.id", ondelete="CASCADE"),
        nullable=False,
    )
    relationship: Mapped[str] = mapped_column(String(64), nullable=False, default="runtime")
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
