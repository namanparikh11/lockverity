"""Manifest model.

A *manifest* is a discovered dependency manifest inside a scan
(``package.json``, ``requirements.txt``, ``Pipfile.lock``, etc.). The
content of the manifest is **not** stored in v0.1; the scan only keeps
a content hash and provenance.
"""

from __future__ import annotations

import enum

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import TimestampMixin


class ManifestParseStatus(str, enum.Enum):
    NOT_PARSED = "not_parsed"
    PARSED = "parsed"
    PARTIAL = "partial"
    FAILED = "failed"


class Manifest(Base, TimestampMixin):
    __tablename__ = "manifests"
    __table_args__ = (
        UniqueConstraint(
            "scan_run_id",
            "path",
            name="uq_manifests_scan_run_id_path",
        ),
        # Database-portable safety checks. The service layer is the
        # authoritative validator; these are defence in depth.
        CheckConstraint(
            "length(path) > 0",
            name="path_not_empty",
        ),
        CheckConstraint(
            "path NOT LIKE '/%'",
            name="path_no_leading_slash",
        ),
        Index("ix_manifests_scan_run_id", "scan_run_id"),
        Index("ix_manifests_ecosystem", "ecosystem"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(
        ForeignKey("scan_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    manifest_type: Mapped[str] = mapped_column(String(64), nullable=False)
    ecosystem: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parse_status: Mapped[ManifestParseStatus] = mapped_column(
        SAEnum(ManifestParseStatus, name="manifest_parse_status"),
        nullable=False,
        default=ManifestParseStatus.NOT_PARSED,
    )
    parse_warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
