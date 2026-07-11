"""Finding service - read-only at v0.1.

Writing findings is the job of analyzers and rules, which arrive in
later milestones. For v0.1 we only expose the read path so the
frontend can already render empty finding tables.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.models.finding import Finding, FindingCategory, FindingSeverity
from app.repositories import finding_repo
from app.services import scan_service


def list_findings_for_scan(
    session: Session,
    scan_id: int,
    *,
    page: int,
    page_size: int,
    category: FindingCategory | None = None,
    severity: FindingSeverity | None = None,
) -> tuple[Sequence[Finding], int]:
    scan_service.get_scan_or_404(session, scan_id)
    return finding_repo.list_findings_for_scan(
        session,
        scan_id,
        page=page,
        page_size=page_size,
        category=category,
        severity=severity,
    )
