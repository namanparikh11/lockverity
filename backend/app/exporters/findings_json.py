"""Findings JSON exporter.

Exports the full set of findings for a scan as a single JSON
document. The document is intended to be machine-readable; for
the user-facing report use the SARIF or CSV exporter.
"""

from __future__ import annotations

import json
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
            observations = _fetch_observations(session, scan_run_id)
            document = {
                "schema": "lockverity.findings.v1",
                "scan_run_id": scan.id,
                "repository_id": scan.repository_id,
                "status": scan.status.value,
                "fetched_at": utcnow().isoformat().replace("+00:00", "Z"),
                "providers": [_observation_to_dict(o) for o in observations],
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
        # v0.4: extract the provider name from the
        # ``evidence_json`` envelope when present. A
        # finding without an envelope is local (rule
        # engine).
        provider = "local"
        if finding.evidence_json:
            try:
                envelope = json.loads(finding.evidence_json)
            except (ValueError, TypeError):
                envelope = None
            if isinstance(envelope, dict):
                raw_provider = envelope.get("provider")
                if isinstance(raw_provider, str) and raw_provider:
                    provider = raw_provider
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
            "provider": provider,
        }


def _fetch_observations(session, scan_run_id: int):
    from app.models.provider_observation import ProviderObservation

    return (
        session.query(ProviderObservation)
        .filter(ProviderObservation.scan_run_id == scan_run_id)
        .order_by(ProviderObservation.id.asc())
        .all()
    )


def _observation_to_dict(observation) -> dict[str, Any]:
    return {
        "provider": observation.provider,
        "operation": observation.operation,
        "status": observation.status.value if observation.status else None,
        "http_status": observation.http_status,
        "records_returned": observation.records_returned,
        "cache_status": observation.cache_status,
        "error_code": observation.error_code,
        "error_summary": observation.error_summary,
        "completed_at": observation.completed_at.isoformat().replace("+00:00", "Z")
        if observation.completed_at
        else None,
    }


__all__ = ["FindingsJsonExporter"]
