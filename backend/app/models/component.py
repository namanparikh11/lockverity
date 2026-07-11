"""Component model.

A *component* is a single package discovered in a manifest, including
its (possibly unresolved) version. The model deliberately separates
``version`` from ``version_source`` so a missing version never gets
confused with a resolved one.
"""

from __future__ import annotations

import enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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


class ComponentVersionSource(str, enum.Enum):
    MANIFEST = "manifest"
    LOCKFILE = "lockfile"
    OVERRIDE = "override"
    UNRESOLVED = "unresolved"
    UNKNOWN = "unknown"


class Component(Base, TimestampMixin):
    __tablename__ = "components"
    __table_args__ = (
        CheckConstraint(
            "length(package_name) > 0",
            name="package_name_not_empty",
        ),
        CheckConstraint(
            "package_name NOT LIKE '%..%'",
            name="package_name_no_traversal",
        ),
        Index(
            "ix_components_scan_run_id_package_name",
            "scan_run_id",
            "package_name",
        ),
        Index(
            "ix_components_ecosystem_package_name",
            "ecosystem",
            "package_name",
        ),
        Index("ix_components_manifest_id", "manifest_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(
        ForeignKey("scan_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    manifest_id: Mapped[int] = mapped_column(
        ForeignKey("manifests.id", ondelete="CASCADE"),
        nullable=False,
    )
    ecosystem: Mapped[str | None] = mapped_column(String(64), nullable=True)
    package_name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    version_source: Mapped[ComponentVersionSource] = mapped_column(
        SAEnum(
            ComponentVersionSource,
            name="component_version_source",
        ),
        nullable=False,
        default=ComponentVersionSource.UNKNOWN,
    )
    package_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    scope: Mapped[str | None] = mapped_column(String(64), nullable=True)
    relationship: Mapped[str | None] = mapped_column(String(64), nullable=True)
    direct: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    development: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    optional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    integrity: Mapped[str | None] = mapped_column(String(255), nullable=True)
