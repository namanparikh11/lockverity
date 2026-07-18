"""Finding service - read-only.

v1.7 extends the read path with bounded server-side
filters (search, confidence, status, provider, rule id,
path, sort) so the analyst review workbench can scale
to real-world result sets. Writing findings remains
the job of analyzers and rules.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.models.finding import (
    Finding,
    FindingCategory,
    FindingConfidence,
    FindingSeverity,
    FindingStatus,
)
from app.repositories import finding_repo
from app.services import scan_service
from app.utils.errors import ApiError, ApiErrorCode


def list_findings_for_scan(
    session: Session,
    scan_id: int,
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
    scan_service.get_scan_or_404(session, scan_id)
    return finding_repo.list_findings_for_scan(
        session,
        scan_id,
        page=page,
        page_size=page_size,
        category=category,
        severity=severity,
        confidence=confidence,
        status=status,
        provider=provider,
        rule_id=rule_id,
        path=path,
        q=q,
        sort=sort,
    )


def get_finding_for_scan_or_404(session: Session, scan_id: int, finding_id: int) -> Finding:
    """Fetch a single finding scoped to a scan.

    The route handler enforces scan-scoped isolation
    so a finding from one scan cannot be read
    through another scan's URL. Missing findings or
    cross-scan lookups both return 404.
    """
    scan_service.get_scan_or_404(session, scan_id)
    finding = finding_repo.get_finding_by_id(session, finding_id)
    if finding is None or finding.scan_run_id != scan_id:
        raise ApiError(
            ApiErrorCode.NOT_FOUND,
            "Finding not found for this scan.",
            details={"scan_id": scan_id, "finding_id": finding_id},
        )
    return finding
