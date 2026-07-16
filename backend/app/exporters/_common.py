"""Shared exporter utilities.

A common problem when serializing a scan to an external format
is that some scan rows are simply not interesting to a given
format (for example, SARIF cannot represent a finding without a
file location). The helpers here keep the per-format exporters
small by centralising the database lookups and the
component-to-format adapters.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.component import Component
from app.models.finding import Finding
from app.models.manifest import Manifest
from app.models.provider_observation import ProviderObservation
from app.models.scan_run import ScanRun, ScanStatus

# Reasonable hard caps. The defaults match the v0.1 configuration
# limits. An exporter can lower them.
DEFAULT_EXPORT_COMPONENT_LIMIT = 100_000
DEFAULT_EXPORT_FINDING_LIMIT = 100_000
DEFAULT_EXPORT_OBSERVATION_LIMIT = 10_000


class ScanNotFoundError(ValueError):
    """Raised when an exporter is asked to export an unknown scan."""


def get_scan_or_raise(session: Session, scan_run_id: int) -> ScanRun:
    scan = session.get(ScanRun, scan_run_id)
    if scan is None:
        raise ScanNotFoundError(f"Scan {scan_run_id} not found.")
    return scan


def fetch_components(
    session: Session,
    scan_run_id: int,
    *,
    limit: int = DEFAULT_EXPORT_COMPONENT_LIMIT,
) -> Sequence[Component]:
    stmt = (
        session.query(Component)
        .filter(Component.scan_run_id == scan_run_id)
        .order_by(Component.id.asc())
        .limit(limit)
    )
    return stmt.all()


def fetch_findings(
    session: Session,
    scan_run_id: int,
    *,
    limit: int = DEFAULT_EXPORT_FINDING_LIMIT,
) -> Sequence[Finding]:
    stmt = (
        session.query(Finding)
        .filter(Finding.scan_run_id == scan_run_id)
        .order_by(Finding.id.asc())
        .limit(limit)
    )
    return stmt.all()


def fetch_observations(
    session: Session,
    scan_run_id: int,
    *,
    limit: int = DEFAULT_EXPORT_OBSERVATION_LIMIT,
) -> Sequence[ProviderObservation]:
    stmt = (
        session.query(ProviderObservation)
        .filter(ProviderObservation.scan_run_id == scan_run_id)
        .order_by(ProviderObservation.id.asc())
        .limit(limit)
    )
    return stmt.all()


def _component_to_purl(component: Component) -> str | None:
    if component.package_url:
        return component.package_url
    if not component.package_name or not component.ecosystem:
        return None
    if component.ecosystem == "npm":
        return (
            f"pkg:npm/{component.package_name}@{component.version}"
            if component.version
            else f"pkg:npm/{component.package_name}"
        )
    if component.ecosystem == "pypi":
        return (
            f"pkg:pypi/{component.package_name}@{component.version}"
            if component.version
            else f"pkg:pypi/{component.package_name}"
        )
    return None


def component_purl(component: Component) -> str | None:
    return _component_to_purl(component)


def format_iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone().isoformat().replace("+00:00", "Z")


def serialize_findings_jsonl(findings: Iterable[Finding]) -> str:
    """Return a JSON-Lines serialization of the findings.

    Used by the Findings JSON exporter for the streaming variant.
    The function is intentionally simple; it never raises on
    individual findings - any unparseable record is skipped.
    """
    import json

    out: list[str] = []
    for finding in findings:
        try:
            out.append(json.dumps(_finding_to_dict(finding), sort_keys=True, default=str))
        except (TypeError, ValueError):
            continue
    return "\n".join(out)


def _finding_to_dict(finding: Finding) -> dict[str, Any]:
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


def map_observations(
    observations: Iterable[ProviderObservation],
    fn: Callable[[ProviderObservation], dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for obs in observations:
        out.append(fn(obs))
    return out


# ---------------------------------------------------------------------
# v0.6 CycloneDX 1.7 SBOM export eligibility
# ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExportEligibility:
    """The single authoritative export-eligibility verdict for one scan.

    v0.6 introduces a strict eligibility rule: a scan is only
    eligible for a standards-compliant SBOM when its persisted
    local-analysis evidence is sufficient to faithfully represent
    the analyzed inventory. A failed, cancelled, queued, or
    running scan never qualifies, even if a few rows exist; a
    partial scan only qualifies when it has at least one parsed
    manifest and at least one observed component. Every other
    partial scan is rejected as "locally incomplete".
    """

    eligible: bool
    reason: str
    # The machine-readable reason code mirrors the API error code
    # so the API layer can map it without duplicating the string.
    code: str
    # The set of explicit limitations the consumer should surface.
    # Empty for ineligible scans.
    limitations: tuple[str, ...] = ()


_INELIGIBLE_TERMINAL: dict[ScanStatus, tuple[str, str]] = {
    ScanStatus.FAILED: ("scan_failed", "Scan terminated in a failed state."),
    ScanStatus.CANCELLED: ("scan_cancelled", "Scan was cancelled before completion."),
}

_INELIGIBLE_INFLIGHT: dict[ScanStatus, tuple[str, str]] = {
    ScanStatus.QUEUED: ("scan_not_started", "Scan is queued; no inventory has been observed yet."),
    ScanStatus.RUNNING: ("scan_in_progress", "Scan is still running; inventory may be partial."),
}


def evaluate_export_eligibility(
    scan: ScanRun,
    *,
    component_count: int,
    manifest_count: int,
) -> ExportEligibility:
    """Return the v0.6 export-eligibility verdict for ``scan``.

    The function is the single authoritative backend rule. The
    v0.6 SBOM exporter, the API layer, and the frontend must all
    reach the same verdict for the same scan state.
    """
    if scan.status in _INELIGIBLE_TERMINAL:
        code, reason = _INELIGIBLE_TERMINAL[scan.status]
        return ExportEligibility(eligible=False, reason=reason, code=code)
    if scan.status in _INELIGIBLE_INFLIGHT:
        code, reason = _INELIGIBLE_INFLIGHT[scan.status]
        return ExportEligibility(eligible=False, reason=reason, code=code)
    if scan.status == ScanStatus.COMPLETED:
        return ExportEligibility(
            eligible=True,
            reason="Scan completed with persisted local-analysis evidence.",
            code="eligible",
        )
    # ScanStatus.PARTIAL - the only partial path that qualifies.
    if component_count == 0 or manifest_count == 0:
        return ExportEligibility(
            eligible=False,
            reason=(
                "Scan is partial and no persisted local-analysis evidence is "
                "complete enough to derive an inventory."
            ),
            code="partial_incomplete",
        )
    return ExportEligibility(
        eligible=True,
        reason="Scan is partial due to provider degradation; local inventory is complete.",
        code="eligible_with_provider_degradation",
        limitations=("provider_degraded",),
    )


def fetch_manifests(
    session: Session,
    scan_run_id: int,
    *,
    limit: int = DEFAULT_EXPORT_COMPONENT_LIMIT,
) -> Sequence[Manifest]:
    """Return all manifests for ``scan_run_id`` in stable order."""
    stmt = (
        session.query(Manifest)
        .filter(Manifest.scan_run_id == scan_run_id)
        .order_by(Manifest.id.asc())
        .limit(limit)
    )
    return stmt.all()


def fetch_dependency_edges(
    session: Session,
    scan_run_id: int,
    *,
    limit: int = DEFAULT_EXPORT_COMPONENT_LIMIT,
) -> Sequence[Any]:
    """Return all dependency edges for ``scan_run_id`` in stable order.

    The edges table is imported lazily so this module does not
    create an import cycle with the model package.
    """
    from app.models.dependency_edge import DependencyEdge

    stmt = (
        session.query(DependencyEdge)
        .filter(DependencyEdge.scan_run_id == scan_run_id)
        .order_by(DependencyEdge.id.asc())
        .limit(limit)
    )
    return stmt.all()
