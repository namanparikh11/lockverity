"""Advisory model.

An *advisory* is a single record from a vulnerability provider
(OSV, GHSA, NVD, ...). The model stores the minimum stable identity
plus a hash of the raw payload. The raw payload itself is **not**
persisted in v0.1 - we keep only its hash to prove provenance
without retaining unbounded provider responses.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import TimestampMixin


class Advisory(Base, TimestampMixin):
    __tablename__ = "advisories"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "source_advisory_id",
            name="uq_advisories_source_source_id",
        ),
        Index("ix_advisories_canonical_id", "canonical_id"),
        Index("ix_advisories_published_at", "published_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_advisory_id: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    details_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_payload_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
