"""FastAPI dependency providers.

Centralizing the dependencies here keeps the route modules small and
makes it easy to override behavior in tests via ``app.dependency_overrides``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db import get_db

__all__ = [
    "DBSession",
    "PageParams",
    "SettingsDep",
    "page_params",
]


def page_params(
    page: int = Query(1, ge=1, description="1-indexed page number"),
    page_size: int = Query(
        None,
        ge=1,
        description="Page size; defaults to server-configured value.",
    ),
    settings: Settings = Depends(get_settings),
) -> PageParams:
    """Resolve effective pagination parameters.

    ``page_size`` defaults to the configured default and is capped at
    the configured maximum. This is the single place that knows about
    the pagination policy.
    """
    effective_size = page_size or settings.pagination_default_page_size
    if effective_size > settings.pagination_max_page_size:
        effective_size = settings.pagination_max_page_size
    return PageParams(page=page, page_size=effective_size)


class PageParams:
    """Materialized pagination parameters."""

    __slots__ = ("page", "page_size")

    def __init__(self, *, page: int, page_size: int) -> None:
        self.page = page
        self.page_size = page_size

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"PageParams(page={self.page}, page_size={self.page_size})"


DBSession = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
PageParamsDep = Annotated[PageParams, Depends(page_params)]
