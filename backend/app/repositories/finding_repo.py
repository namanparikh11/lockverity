"""Finding data-access helpers."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.finding import Finding, FindingCategory, FindingSeverity


def list_findings_for_scan(
    session: Session,
    scan_run_id: int,
    *,
    page: int,
    page_size: int,
    category: FindingCategory | None = None,
    severity: FindingSeverity | None = None,
) -> tuple[Sequence[Finding], int]:
    if page < 1:
        raise ValueError("page must be >= 1")
    if page_size < 1:
        raise ValueError("page_size must be >= 1")
    stmt_total = select(func.count()).select_from(Finding).where(Finding.scan_run_id == scan_run_id)
    stmt = select(Finding).where(Finding.scan_run_id == scan_run_id)
    if category is not None:
        stmt_total = stmt_total.where(Finding.category == category)
        stmt = stmt.where(Finding.category == category)
    if severity is not None:
        stmt_total = stmt_total.where(Finding.severity == severity)
        stmt = stmt.where(Finding.severity == severity)
    total = session.execute(stmt_total).scalar_one()
    stmt = stmt.order_by(Finding.id.asc()).limit(page_size).offset((page - 1) * page_size)
    items = session.execute(stmt).scalars().all()
    return items, int(total or 0)
