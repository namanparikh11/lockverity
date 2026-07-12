"""Provider cache model.

A *provider_cache_entry* stores one provider response. The
:attr:`cache_key` is a SHA-256 of a normalized request descriptor
that never contains credentials. The response payload is stored as
a bounded blob.

The cache is intentionally narrow: it does not interpret the
payload, it just records that a request with key ``cache_key``
returned a payload with ``response_sha256`` under headers
``etag`` / ``last_modified``. Concrete providers consult the
cache and may honour the saved ``expires_at``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.base import TimestampMixin


class ProviderCacheEntry(Base, TimestampMixin):
    __tablename__ = "provider_cache_entries"
    __table_args__ = (
        UniqueConstraint("provider", "operation", "cache_key", name="uq_provider_cache_key"),
        Index("ix_provider_cache_provider_operation", "provider", "operation"),
        Index("ix_provider_cache_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    cache_key: Mapped[str] = mapped_column(String(128), nullable=False)
    response_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    payload_size: Mapped[int] = mapped_column(Integer, nullable=False)
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(255), nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
