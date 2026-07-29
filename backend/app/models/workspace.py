"""Workspace model.

A *workspace* is the on-disk boundary around one scan's extracted
content. The database row holds the *safe* metadata that the rest of
the application is allowed to see; the on-disk path is stored as
an opaque key that we can resolve at runtime. The API never
returns an absolute filesystem path.
"""

from __future__ import annotations

import enum

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


class WorkspaceKind(str, enum.Enum):
    GITHUB = "github"
    UPLOADED_ARCHIVE = "uploaded_archive"


class WorkspaceState(str, enum.Enum):
    QUARANTINED = "quarantined"
    VALIDATING = "validating"
    READY = "ready"
    FAILED = "failed"
    CLEANED_UP = "cleaned_up"


class Workspace(Base, TimestampMixin):
    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint(
            "length(workspace_key) >= 16",
            name="workspace_key_min_length",
        ),
        Index("ix_workspaces_scan_run_id", "scan_run_id"),
        Index("ix_workspaces_state", "state"),
        Index("ix_workspaces_kind", "kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(
        ForeignKey("scan_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    kind: Mapped[WorkspaceKind] = mapped_column(
        SAEnum(WorkspaceKind, name="workspace_kind"),
        nullable=False,
    )
    state: Mapped[WorkspaceState] = mapped_column(
        SAEnum(WorkspaceState, name="workspace_state"),
        nullable=False,
        default=WorkspaceState.QUARANTINED,
    )
    archive_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # ``safe_archive_filename`` is the basename-only form
    # of ``archive_filename`` (always run through
    # :func:`app.utils.paths.basename_safely`). It is what
    # the public search predicate matches against, so a
    # search for a parent-directory component (``Users``,
    # ``home``, ``..``) cannot match a row whose
    # ``archive_filename`` happens to contain such a
    # component in its raw form (e.g. a legacy
    # ``C:\\Users\\me\\secret.zip`` value). For trusted
    # GitHub provenance (``github/owner/repo@sha.tar.gz``)
    # the safe basename is ``repo@sha.tar.gz``.
    safe_archive_filename: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        index=True,
    )
    archive_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    archive_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uncompressed_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_summary: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    ready_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cleaned_up_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
