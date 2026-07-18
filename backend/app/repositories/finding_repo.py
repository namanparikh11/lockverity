"""Finding data-access helpers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.finding import (
    Finding,
    FindingCategory,
    FindingConfidence,
    FindingSeverity,
    FindingStatus,
)

# v1.7: bounded sort options. The default sort is
# ``id`` (insertion order, which matches the orchestrator's
# insertion sequence for reproducible paging). Lockverity
# never invents a "Lockverity risk ranking" - the sort
# vocabulary is restricted to fields that are persisted
# and trustworthy.
SortField = Literal["id", "rule_id", "category", "severity", "confidence", "status", "updated_at"]

# The page-size cap matches the application's
# ``pagination_max_page_size`` default. The route
# handler validates against this cap so an oversized
# page_size is rejected with the stable validation
# envelope.
MAX_PAGE_SIZE = 100


def _normalize_sort_field(value: str | None) -> str:
    """Return a safe sort field name. Invalid values map to ``id``."""
    if value is None:
        return "id"
    if value in ("id", "rule_id", "category", "severity", "confidence", "status", "updated_at"):
        return value
    return "id"


def list_findings_for_scan(
    session: Session,
    scan_run_id: int,
    *,
    page: int,
    page_size: int,
    category: FindingCategory | None = None,
    severity: FindingSeverity | None = None,
    confidence: FindingConfidence | None = None,
    status: FindingStatus | None = None,
    provider: str | None = None,
    rule_id: str | None = None,
    path: str | None = None,
    q: str | None = None,
    sort: str | None = None,
) -> tuple[Sequence[Finding], int]:
    """List findings for a scan with bounded server-side filters.

    The route handler validates enum values and the
    page-size cap. This function expects already-validated
    inputs. The free-text ``q`` is a LIKE search across the
    fields a reviewer is most likely to type:
    ``rule_id``, ``title``, ``summary``, and the raw
    ``evidence_json`` (so package names and PURLs in
    the evidence block are reachable). ``provider`` and
    ``path`` are filterable separately because they
    appear in the evidence payload, not as top-level
    columns.
    """
    if page < 1:
        raise ValueError("page must be >= 1")
    if page_size < 1:
        raise ValueError("page_size must be >= 1")
    if page_size > MAX_PAGE_SIZE:
        raise ValueError(f"page_size must be <= {MAX_PAGE_SIZE}")

    sort_field = _normalize_sort_field(sort)
    stmt_total = select(func.count()).select_from(Finding).where(Finding.scan_run_id == scan_run_id)
    stmt = select(Finding).where(Finding.scan_run_id == scan_run_id)
    if category is not None:
        stmt_total = stmt_total.where(Finding.category == category)
        stmt = stmt.where(Finding.category == category)
    if severity is not None:
        stmt_total = stmt_total.where(Finding.severity == severity)
        stmt = stmt.where(Finding.severity == severity)
    if confidence is not None:
        stmt_total = stmt_total.where(Finding.confidence == confidence)
        stmt = stmt.where(Finding.confidence == confidence)
    if status is not None:
        stmt_total = stmt_total.where(Finding.status == status)
        stmt = stmt.where(Finding.status == status)
    if rule_id:
        stmt_total = stmt_total.where(Finding.rule_id == rule_id)
        stmt = stmt.where(Finding.rule_id == rule_id)
    if path:
        # Path is a free-text substring match. The
        # front end is expected to escape percent /
        # underscore before sending.
        stmt_total = stmt_total.where(Finding.location_path.contains(path))
        stmt = stmt.where(Finding.location_path.contains(path))
    if provider:
        # Provider is a free-text substring match on
        # the raw evidence JSON because it lives in
        # the payload, not as a top-level column.
        evidence_match = Finding.evidence_json.contains(provider)
        stmt_total = stmt_total.where(evidence_match)
        stmt = stmt.where(evidence_match)
    if q:
        # The q query splits into a free-text match
        # across the columns a reviewer is most likely
        # to type into. SQL injection is prevented by
        # the parameter binding on each LIKE clause
        # (SQLAlchemy ``.contains`` emits ``LIKE ?``
        # with the value bound, not interpolated).
        match = or_(
            Finding.title.contains(q),
            Finding.summary.contains(q),
            Finding.rule_id.contains(q),
            Finding.evidence_json.contains(q),
        )
        stmt_total = stmt_total.where(match)
        stmt = stmt.where(match)

    total = session.execute(stmt_total).scalar_one()

    # Apply the requested sort. The default is ``id``
    # (insertion order, deterministic) with a secondary
    # ``id`` tiebreaker so paging is stable when many
    # findings share a sort key.
    sort_col = getattr(Finding, sort_field)
    stmt = (
        stmt.order_by(sort_col.asc(), Finding.id.asc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    items = session.execute(stmt).scalars().all()
    return items, int(total or 0)


def get_finding_by_id(session: Session, finding_id: int) -> Finding | None:
    return session.get(Finding, finding_id)


__all__ = [
    "MAX_PAGE_SIZE",
    "SortField",
    "get_finding_by_id",
    "list_findings_for_scan",
]
