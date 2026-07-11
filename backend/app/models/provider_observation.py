"""Provider observation model.

A *provider observation* is the per-call record of a provider's
availability and behavior. It is the foundation of the provider-
honesty policy: a missing record means we never claimed the
provider was queried, and a record with ``status='unavailable'`` is
the only correct way to represent "we tried and the provider failed".
"""

from __future__ import annotations

import enum
from datetime import datetime

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
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import TimestampMixin


class ProviderStatus(str, enum.Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    NOT_REQUESTED = "not_requested"
    CACHED = "cached"
    UNKNOWN = "unknown"


class ProviderObservation(Base, TimestampMixin):
    __tablename__ = "provider_observations"
    __table_args__ = (
        Index(
            "ix_provider_observations_scan_run_id_provider",
            "scan_run_id",
            "provider",
        ),
        Index("ix_provider_observations_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(
        ForeignKey("scan_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[ProviderStatus] = mapped_column(
        SAEnum(ProviderStatus, name="provider_status"),
        nullable=False,
        default=ProviderStatus.UNKNOWN,
    )
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    records_returned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(String(2048), nullable=True)
