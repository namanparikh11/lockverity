"""Shared SQLAlchemy mixins.

Keeping the timestamp mixin in one place means every model gets the
same auto-populated ``created_at`` and ``updated_at`` semantics. Both
fields are timezone-aware UTC.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.utils.datetime import utcnow


def _utcnow_factory() -> datetime:
    return utcnow()


class TimestampMixin:
    """Adds ``created_at`` and ``updated_at`` columns to a model.

    Both columns are populated server-side via SQLAlchemy ``default``
    hooks. ``updated_at`` is also touched on update via ``onupdate``.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow_factory,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow_factory,
        onupdate=_utcnow_factory,
    )
