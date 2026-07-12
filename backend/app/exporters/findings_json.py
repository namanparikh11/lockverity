"""Findings JSON exporter.

Exports the full set of findings for a scan as a single JSON
document. The document is intended to be machine-readable; for
the user-facing report use the SARIF or CSV exporter.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.exporters._common import (
    ScanNotFoundError,
    fetch_findings,
    get_scan_or_raise,
)
from app.providers.results import (
    ProviderOutcome,
    ProviderSuccess,
    ProviderUnavailable,
)
from app.utils.datetime import utcnow
from app.utils.json_safe import BoundedJsonError, dump_bounded_json


class FindingsJsonExporter:
    """JSON exporter for scan findings."""

    format = "findings_json"

    def __init__(
        self,
        session_factory: sessionmaker[Session] | Callable[[], Session],
    ) -> None:
        self._session_factory = session_factory

    def export(self, *, scan_run_id: int) -> ProviderSuccess[bytes] | ProviderUnavailable:
        session = self._session_factory()
        try:
            try:
                scan = get_scan_or_raise(session, scan_run_id)
            except ScanNotFoundError:
                return ProviderUnavailable(
                    error_code="export_scan_not_found",
                    error_summary=f"Scan {scan_run_id} not found.",
                    attempted_at=utcnow(),
                    outcome=ProviderOutcome.UNAVAILABLE,
                )
            findings = fetch_findings(session, scan_run_id)
            document = {
                "schema": "lockverity.findings.v1",
                "scan_run_id": scan.id,
                "repository_id": scan.repository_id,
                "status": scan.status.value,
                "fetched_at": utcnow().isoformat().replace("+00:00", "Z"),
                "findings": [self._finding_to_dict(f) for f in findings],
            }
        finally:
            session.close()
        try:
            serialized = dump_bounded_json(document, sort_keys=True)
        except BoundedJsonError as exc:
            return ProviderUnavailable(
                error_code="export_too_large",
                error_summary=str(exc),
                attempted_at=utcnow(),
                outcome=ProviderOutcome.UNAVAILABLE,
            )
        return ProviderSuccess(
            data=serialized.encode("utf-8"),
            fetched_at=utcnow(),
            records_returned=len(findings),
        )

    @staticmethod
    def _finding_to_dict(finding) -> dict[str, Any]:
        return {
            "id": finding.id,
            "rule_id": finding.rule_id,
            "category": finding.category.value if finding.category else None,
            "severity": finding.severity.value if finding.severity else None,
            "confidence": finding.confidence.value if finding.confidence else None,
            "title": finding.title,
            "summary": finding.summary,
            "remediation": finding.remediation,
            "location_path": finding.location_path,
            "location_start_line": finding.location_start_line,
            "location_end_line": finding.location_end_line,
            "stable_key": finding.stable_key,
            "status": finding.status.value if finding.status else None,
            "evidence_json": finding.evidence_json,
        }


__all__ = ["FindingsJsonExporter"]
