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
    Text,
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
        Index(
            "ix_provider_observations_scan_run_id_provider_component_id",
            "scan_run_id",
            "provider",
            "component_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(
        ForeignKey("scan_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    # v0.4: nullable FK to the component this observation
    # belongs to. Per-component observations (OSV lookups,
    # deps.dev enrichments) set this; scan-level
    # observations (Scorecard) leave it ``null``. The
    # endpoint that joins observations to components
    # filters on this column so a per-component
    # "missing version" reason cannot leak to a different
    # component in the same scan.
    component_id: Mapped[int | None] = mapped_column(
        ForeignKey("components.id", ondelete="CASCADE"),
        nullable=True,
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
    # v0.4: structured evidence envelope for successful
    # provider responses. Bounded at 8 KiB; the application
    # validator rejects oversized payloads and the column is
    # always ``null`` for error / unavailable observations.
    # ``error_summary`` continues to carry redacted error
    # text; the two columns are independent and are never
    # mixed.
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
