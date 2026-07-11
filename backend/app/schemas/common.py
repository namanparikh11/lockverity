"""Shared schema building blocks.

A single :class:`SchemaModel` base keeps :func:`model_config` consistent
across the public API and provides a stable place to register global
hooks (for example, future JSON Schema customizations).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ShortStr = Annotated[str, StringConstraints(strip_whitespace=True, max_length=512)]
LongStr = Annotated[str, StringConstraints(max_length=4096)]


class SchemaModel(BaseModel):
    """Common configuration for every public API schema."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        populate_by_name=True,
        use_enum_values=False,
        ser_json_timedelta="iso8601",
        from_attributes=True,
    )


class TimestampMixin(SchemaModel):
    """Adds ``created_at`` / ``updated_at`` ISO 8601 fields."""

    created_at: datetime
    updated_at: datetime


class PageMeta(SchemaModel):
    """Pagination metadata returned with every paginated response."""

    page: int
    page_size: int
    total: int
    total_pages: int


def page_meta(page: int, page_size: int, total: int) -> PageMeta:
    """Return a :class:`PageMeta` from the raw page inputs and total."""
    if total < 0:
        raise ValueError("total must be non-negative")
    if page < 1:
        raise ValueError("page must be >= 1")
    if page_size < 1:
        raise ValueError("page_size must be >= 1")
    total_pages = (total + page_size - 1) // page_size if total else 0
    return PageMeta(
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
    )
