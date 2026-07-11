"""Repository model.

A *repository* is the abstract target of analysis. It can come from
GitHub or from an uploaded archive. The model captures the
minimum-needed identity, source, and metadata, plus a small cache of
``last_provider_sync_at`` for the GitHub case.

We deliberately do not store any repository code or repository
filesystem paths. The scanner resolves archive contents to a private
workspace that the API never serves.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import TimestampMixin


class RepositorySourceType(str, enum.Enum):
    GITHUB = "github"
    UPLOADED_ARCHIVE = "uploaded_archive"


class RepositoryProvider(str, enum.Enum):
    GITHUB = "github"
    LOCAL_UPLOAD = "local_upload"


class RepositoryVisibility(str, enum.Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    UNKNOWN = "unknown"


class Repository(Base, TimestampMixin):
    __tablename__ = "repositories"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "owner",
            "name",
            name="uq_repositories_provider_owner_name",
        ),
        UniqueConstraint(
            "canonical_url",
            name="uq_repositories_canonical_url",
        ),
        Index("ix_repositories_source_type", "source_type"),
        Index("ix_repositories_provider_owner", "provider", "owner"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_type: Mapped[RepositorySourceType] = mapped_column(
        SAEnum(RepositorySourceType, name="repository_source_type"),
        nullable=False,
    )
    provider: Mapped[RepositoryProvider] = mapped_column(
        SAEnum(RepositoryProvider, name="repository_provider"),
        nullable=False,
    )
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    default_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    visibility: Mapped[RepositoryVisibility] = mapped_column(
        SAEnum(RepositoryVisibility, name="repository_visibility"),
        nullable=False,
        default=RepositoryVisibility.UNKNOWN,
    )
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_provider_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    scans: Mapped[list[app.models.scan_run.ScanRun]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="repository",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
