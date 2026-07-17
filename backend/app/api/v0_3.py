"""v0.3 end-to-end scan flow API endpoints.

This module is the single source of truth for the read endpoints
the v0.3 frontend pages use. The endpoints are read-only views
over the existing schema; the orchestrator populates the
underlying tables when it runs.

The shapes are designed to be consumed directly by the
TypeScript types in :file:`frontend/src/api/types.ts`. Adding a
new column to a row keeps the existing field list intact.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Query, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import DBSession, PageParamsDep
from app.api.mappers import pagination
from app.exporters import (
    CycloneDxExporter,
    FindingsCsvExporter,
    FindingsJsonExporter,
    SarifStaticFindingsExporter,
)
from app.exporters._common import evaluate_export_eligibility
from app.exporters.cyclonedx_v17 import (
    CYCLONEDX_FORMAT_KEY,
    CYCLONEDX_MEDIA_TYPE,
)
from app.models.advisory import Advisory
from app.models.component import Component
from app.models.component_advisory import ComponentAdvisory
from app.models.dependency_edge import DependencyEdge
from app.models.finding import (
    Finding,
    FindingCategory,
    FindingSeverity,
)
from app.models.manifest import Manifest
from app.models.scan_run import ScanRun
from app.providers.results import ProviderSuccess
from app.schemas.common import SchemaModel
from app.schemas.comparison import ScanComparisonResponse
from app.schemas.intake import ScanRunRequest
from app.schemas.scan import (
    AdvisoryRead,
    ComponentAdvisoryRead,
    ComponentEnrichment,
    ComponentRead,
    DependencyPathEntry,
    DependencyPathRead,
    WorkflowFindingRead,
)
from app.services import comparison_service, scan_service
from app.utils.errors import ApiError, ApiErrorCode

logger = logging.getLogger("lockverity.api.v0_3")

router = APIRouter(prefix="/scans", tags=["v0.3"])


# ----------------------------------------------------------------------
# Pagination / read models
# ----------------------------------------------------------------------
class PaginatedComponents(SchemaModel):
    items: list[ComponentRead]
    pagination: dict


class PaginatedAdvisories(SchemaModel):
    items: list[AdvisoryRead]
    pagination: dict


class PaginatedVulnerabilities(SchemaModel):
    items: list[ComponentAdvisoryRead]
    pagination: dict


class PaginatedWorkflowFindings(SchemaModel):
    items: list[WorkflowFindingRead]
    pagination: dict


class PaginatedOpenSSF(SchemaModel):
    items: list[dict[str, Any]]
    pagination: dict


class PaginatedLicences(SchemaModel):
    items: list[dict[str, Any]]
    pagination: dict


class PaginatedEnrichments(SchemaModel):
    items: list[ComponentEnrichment]
    pagination: dict


class ExportFormatDescriptor(SchemaModel):
    format: str
    label: str
    description: str
    supported: bool
    not_supported_reason: str | None = None
    content_type: str
    filename_hint: str


class ExportListResponse(SchemaModel):
    items: list[ExportFormatDescriptor]


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _get_scan_or_404(session: Session, scan_id: int) -> ScanRun:
    return scan_service.get_scan_or_404(session, scan_id)


def _finding_to_workflow_finding(finding: Finding) -> WorkflowFindingRead:
    """Project a workflow-category finding into the workflow schema."""
    location_path = finding.location_path or ""
    workflow_name = location_path.rsplit("/", 1)[-1] if location_path else "workflow"
    extras = _parse_extras(finding.evidence_json)
    return WorkflowFindingRead(
        id=finding.id,
        scan_run_id=finding.scan_run_id,
        repository_id=finding.repository_id,
        rule_id=finding.rule_id,
        severity=finding.severity,
        confidence=finding.confidence,
        workflow_path=location_path,
        workflow_name=workflow_name,
        title=finding.title,
        summary=finding.summary,
        remediation=finding.remediation,
        permissions=extras.get("permissions", []),
        triggers=extras.get("triggers", []),
        unpinned_actions=extras.get("unpinned_actions", []),
        yaml_path=extras.get("yaml_path"),
        start_line=finding.location_start_line,
        end_line=finding.location_end_line,
        stable_key=finding.stable_key,
        limitations=extras.get("limitations", []),
    )


def _finding_to_licence_assertion(finding: Finding) -> dict[str, Any]:
    extras = _parse_extras(finding.evidence_json)
    payload = extras.get("evidence", {}) or {}
    return {
        "id": finding.id,
        "scan_run_id": finding.scan_run_id,
        "package_name": payload.get("package_name") or "",
        "version": payload.get("version"),
        "licence": ", ".join(payload.get("licences") or []) or "unknown",
        "direct": True,
        "provider": "rule_engine",
        "review_status": _licence_review_status(finding),
        "unknown_licence": bool(
            finding.rule_id == "LOCK-LIC-001"
            or "no licence assertion" in (finding.title or "").lower()
        ),
        "finding_id": finding.id,
        "stable_key": finding.stable_key,
    }


def _licence_review_status(finding: Finding) -> str:
    rule_id = finding.rule_id or ""
    if rule_id == "LOCK-LIC-003":
        return "review_required"
    if rule_id == "LOCK-LIC-INV":
        return "approved"
    if rule_id in {"LOCK-LIC-001", "LOCK-LIC-002", "LOCK-LIC-004"}:
        return "unreviewed"
    return "unknown"


def _finding_to_openssf_check(finding: Finding) -> dict[str, Any]:
    """Project a posture-category finding into an OpenSSF-shaped record."""
    _extras = _parse_extras(finding.evidence_json)
    return {
        "id": finding.id,
        "scan_run_id": finding.scan_run_id,
        "repository_id": finding.repository_id,
        "check_id": finding.rule_id,
        "name": finding.title,
        "score": _score_from_severity(finding.severity),
        "reason": finding.summary,
        "details_url": None,
        "source": "rule_engine",
        "finding_id": finding.id,
    }


def _score_from_severity(severity: FindingSeverity) -> int | None:
    return {
        FindingSeverity.INFORMATIONAL: 10,
        FindingSeverity.LOW: 7,
        FindingSeverity.MEDIUM: 5,
        FindingSeverity.HIGH: 3,
        FindingSeverity.CRITICAL: 1,
    }.get(severity)


def _parse_extras(evidence_json: str | None) -> dict[str, Any]:
    if not evidence_json:
        return {}
    try:
        data = json.loads(evidence_json)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _parse_observation_evidence(
    raw: str | None,
) -> dict[str, Any] | None:
    """Parse the structured evidence envelope on a ProviderObservation.

    v0.4 stores successful provider payload metadata
    (licence observations, dependency counts, package
    identity, fetched_at) in a dedicated bounded JSON column
    on ``provider_observations``. The endpoint never has to
    parse ``error_summary`` to recover it; ``error_summary``
    is reserved for redacted error text on failed calls.

    Returns the parsed envelope (or ``None`` when the column
    is empty, malformed, or unparseable). Malformed values
    are reported as a parse failure to the caller; we never
    guess the contents of a corrupt envelope.
    """
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


# ----------------------------------------------------------------------
# Components
# ----------------------------------------------------------------------
@router.get(
    "/{scan_id}/components",
    response_model=PaginatedComponents,
    summary="List components discovered in a scan.",
)
def list_components(
    scan_id: int,
    session: DBSession,
    page_params: PageParamsDep,
    ecosystem: str | None = Query(default=None),
    scope: str | None = Query(default=None, pattern="^(all|direct|transitive)$"),
    vulnerable_only: str | None = Query(default=None, pattern="^(all|vulnerable)$"),
    development: str | None = Query(default=None, pattern="^(all|production|development)$"),
    search: str | None = Query(default=None),
) -> PaginatedComponents:
    _get_scan_or_404(session, scan_id)
    stmt = select(Component).where(Component.scan_run_id == scan_id)
    count_stmt = select(func.count()).select_from(Component).where(Component.scan_run_id == scan_id)
    if ecosystem is not None:
        stmt = stmt.where(Component.ecosystem == ecosystem)
        count_stmt = count_stmt.where(Component.ecosystem == ecosystem)
    if scope == "direct":
        stmt = stmt.where(Component.direct.is_(True))
        count_stmt = count_stmt.where(Component.direct.is_(True))
    elif scope == "transitive":
        stmt = stmt.where(Component.direct.is_(False))
        count_stmt = count_stmt.where(Component.direct.is_(False))
    if development == "development":
        stmt = stmt.where(Component.development.is_(True))
        count_stmt = count_stmt.where(Component.development.is_(True))
    elif development == "production":
        stmt = stmt.where(Component.development.is_(False))
        count_stmt = count_stmt.where(Component.development.is_(False))
    if search is not None and search:
        pattern = f"%{search}%"
        stmt = stmt.where(Component.package_name.ilike(pattern))
        count_stmt = count_stmt.where(Component.package_name.ilike(pattern))
    if vulnerable_only == "vulnerable":
        vuln_subquery = (
            select(ComponentAdvisory.component_id)
            .where(ComponentAdvisory.scan_run_id == scan_id)
            .distinct()
        )
        stmt = stmt.where(Component.id.in_(vuln_subquery))
        count_stmt = count_stmt.where(Component.id.in_(vuln_subquery))
    total = session.execute(count_stmt).scalar_one() or 0
    stmt = (
        stmt.order_by(Component.id.asc())
        .limit(page_params.page_size)
        .offset((page_params.page - 1) * page_params.page_size)
    )
    rows = session.execute(stmt).scalars().all()
    items = [
        ComponentRead(
            id=row.id,
            scan_run_id=row.scan_run_id,
            manifest_id=row.manifest_id,
            ecosystem=row.ecosystem,
            package_name=row.package_name,
            version=row.version,
            version_source=row.version_source,
            package_url=row.package_url,
            scope=row.scope,
            relationship=row.relationship,
            direct=row.direct,
            development=row.development,
            optional=row.optional,
            integrity=row.integrity,
        )
        for row in rows
    ]
    return PaginatedComponents(
        items=items,
        pagination=pagination(
            page=page_params.page,
            page_size=page_params.page_size,
            total=int(total),
        ).model_dump(),
    )


# ----------------------------------------------------------------------
# Dependency path
# ----------------------------------------------------------------------
@router.get(
    "/{scan_id}/components/{component_id}/path",
    response_model=DependencyPathRead,
    summary="Return the dependency path leading to a component.",
)
def get_dependency_path(
    scan_id: int,
    component_id: int,
    session: DBSession,
) -> DependencyPathRead:
    _get_scan_or_404(session, scan_id)
    component = session.get(Component, component_id)
    if component is None or component.scan_run_id != scan_id:
        raise ApiError(
            ApiErrorCode.NOT_FOUND,
            "Component not found for this scan.",
            details={"scan_id": scan_id, "component_id": component_id},
        )
    # BFS from the component to the root. We follow the
    # ``child -> parents`` direction; a component with no
    # incoming edge is a direct root.
    visited: set[int] = set()
    chain_components: list[Component] = []
    chain_edges: list[DependencyEdge] = []
    current_ids: set[int] = {component.id}
    truncated = False
    depth = 0
    max_depth = 32
    while current_ids and depth < max_depth:
        next_parents: set[int] = set()
        rows = session.execute(
            select(DependencyEdge, Component)
            .join(
                Component,
                Component.id == DependencyEdge.parent_component_id,
            )
            .where(
                DependencyEdge.scan_run_id == scan_id,
                DependencyEdge.child_component_id.in_(current_ids),
            )
        ).all()
        for edge, parent in rows:
            if parent.id in visited:
                continue
            visited.add(parent.id)
            next_parents.add(parent.id)
            chain_edges.append(edge)
            chain_components.append(parent)
        if not next_parents:
            break
        current_ids = next_parents
        depth += 1
    if depth >= max_depth and current_ids:
        truncated = True
    chain_components.append(component)
    return DependencyPathRead(
        components=[
            DependencyPathEntry(
                id=c.id,
                package_name=c.package_name,
                version=c.version,
                version_source=c.version_source,
                ecosystem=c.ecosystem,
                direct=c.direct,
                development=c.development,
            )
            for c in chain_components
        ],
        edges=[
            {
                "parent_component_id": e.parent_component_id,
                "child_component_id": e.child_component_id,
                "relationship": e.relationship,
                "depth": e.depth,
            }
            for e in chain_edges
        ],
        truncated=truncated,
    )


# v0.8 component evidence drilldown.
#
# Declared after the existing ``/components/{component_id}/path``
# route so the path-bfs handler wins for the dedicated
# ``/path`` path. The evidence endpoint is a sibling surface
# for the same component: read-only, deterministic, never
# generates a BOM, never calls a provider, never writes to
# the database. A 404 is returned only when the scan id or
# the component id does not exist (or the component belongs
# to a different scan); every other scan state returns 200
# with the appropriate evidence block.
@router.get(
    "/{scan_id}/components/{component_id}/evidence",
    summary=(
        "Return the v0.8 component evidence drilldown for a "
        "component in a scan. Read-only summary of identity, "
        "manifest, licence, provider, dependency, and "
        "CycloneDX 1.7 export implications."
    ),
)
def get_component_evidence(
    scan_id: int,
    component_id: int,
    session: DBSession,
) -> dict[str, Any]:
    """Return the v0.8 component evidence drilldown.

    The endpoint is the single authoritative backend
    surface for component-level audit. It never calls a
    provider, never downloads a repository, never executes
    analyzed code, and never writes to the database. The
    response is bounded: scan identity, component
    identity, manifest evidence, licence evidence, provider
    evidence, dependency evidence, export implications,
    and the explicit omissions list.

    The route returns 404 when the scan id does not exist
    or when the component id is unknown to the scan. Every
    other scan state returns 200; the evidence surface is
    informational, and the consumer renders the response
    from a single source of truth."""
    from app.db import session as _db_session
    from app.evidence import ComponentEvidenceService

    _get_scan_or_404(session, scan_id)
    service = ComponentEvidenceService(_db_session.SessionLocal)
    evidence = service.fetch(scan_run_id=scan_id, component_id=component_id)
    if evidence is None:
        raise ApiError(
            ApiErrorCode.NOT_FOUND,
            "Component not found for this scan.",
            details={"scan_id": scan_id, "component_id": component_id},
        )
    return evidence


# v0.9 evidence-aware search and filtering.
#
# Declared after the v0.8 evidence detail route so the
# detail route keeps the more specific path component.
# The summary endpoint is the v0.9 read-only surface that
# surfaces the persisted evidence flags the consumer
# needs to filter / sort / facet the dependency table.
# The endpoint reuses the same v0.6 CycloneDX helpers the
# v0.8 detail endpoint uses, so the summary cannot
# disagree with the per-row drawer.
@router.get(
    "/{scan_id}/components/evidence-summary",
    summary=(
        "Read-only evidence-aware component search and "
        "filtering surface for a scan. Returns a filtered, "
        "sorted, paginated list of components with their "
        "evidence flags and aggregate facet counts."
    ),
)
def get_components_evidence_summary(
    scan_id: int,
    session: DBSession,
    search: str | None = Query(default=None),
    ecosystem: str | None = Query(default=None),
    direct: str = Query(default="all", pattern="^(all|yes|no)$"),
    version: str = Query(default="all", pattern="^(all|present|missing)$"),
    licence_evidence: str = Query(default="all", pattern="^(all|present|missing)$"),
    provider_evidence: str = Query(default="all", pattern="^(all|present|missing)$"),
    purl: str = Query(default="all", pattern="^(all|persisted|constructible|omitted)$"),
    dependency_edges: str = Query(default="all", pattern="^(all|present|none_observed)$"),
    cyclonedx_appears: str = Query(default="all", pattern="^(all|yes|no)$"),
    cyclonedx_version_omitted: str = Query(default="all", pattern="^(all|yes|no)$"),
    cyclonedx_relationships_emitted: str = Query(default="all", pattern="^(all|yes|no)$"),
    sort: str = Query(
        default="package_name",
        pattern="^(package_name|ecosystem|version_missing_first|"
        "licence_missing_first|provider_missing_first|"
        "dependency_edges_missing_first)$",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """Return the v0.9 evidence summary for ``scan_id``.

    The route is the v0.9 search / filter / sort / paginate
    surface for the components table. The endpoint never
    generates a full BOM, never calls a provider, never
    downloads a repository, never executes analyzed code,
    and never writes to the database.

    A 404 is returned only when the scan id does not
    exist. Every other scan state (including queued,
    running, failed, cancelled, partial, completed) returns
    200 with the filtered summary; the consumer renders
    the response as a discovery surface, not a verdict.
    """
    from app.db import session as _db_session
    from app.evidence.summary import ComponentEvidenceSummaryService

    _get_scan_or_404(session, scan_id)
    service = ComponentEvidenceSummaryService(_db_session.SessionLocal)
    summary = service.fetch(
        scan_run_id=scan_id,
        search=search,
        ecosystem=ecosystem,
        direct=direct,
        version=version,
        licence_evidence=licence_evidence,
        provider_evidence=provider_evidence,
        purl=purl,
        dependency_edges=dependency_edges,
        cyclonedx_appears=cyclonedx_appears,
        cyclonedx_version_omitted=cyclonedx_version_omitted,
        cyclonedx_relationships_emitted=cyclonedx_relationships_emitted,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    if summary is None:
        # The scan row was deleted between the 404 check
        # and the service call. The bounded 404 envelope
        # is the right answer; the consumer never sees a
        # half-built summary.
        raise ApiError(
            ApiErrorCode.NOT_FOUND,
            f"Scan {scan_id} not found.",
            details={"scan_id": scan_id},
        )
    return summary


# ----------------------------------------------------------------------
# Vulnerabilities
# ----------------------------------------------------------------------
@router.get(
    "/{scan_id}/vulnerabilities",
    response_model=PaginatedVulnerabilities,
    summary="List vulnerability rows (component x advisory) for a scan.",
)
def list_vulnerabilities(
    scan_id: int,
    session: DBSession,
    page_params: PageParamsDep,
    ecosystem: str | None = Query(default=None),
    direct_transitive: str | None = Query(default=None, pattern="^(all|direct|transitive)$"),
    search: str | None = Query(default=None),
) -> PaginatedVulnerabilities:
    _get_scan_or_404(session, scan_id)
    stmt = (
        select(ComponentAdvisory, Component, Advisory)
        .join(Component, Component.id == ComponentAdvisory.component_id)
        .join(Advisory, Advisory.id == ComponentAdvisory.advisory_id)
        .where(ComponentAdvisory.scan_run_id == scan_id)
    )
    count_stmt = (
        select(func.count())
        .select_from(ComponentAdvisory)
        .where(ComponentAdvisory.scan_run_id == scan_id)
    )
    if ecosystem is not None:
        stmt = stmt.where(Component.ecosystem == ecosystem)
        count_stmt = count_stmt.where(
            ComponentAdvisory.component_id.in_(
                select(Component.id).where(Component.ecosystem == ecosystem)
            )
        )
    if direct_transitive == "direct":
        stmt = stmt.where(Component.direct.is_(True))
        count_stmt = count_stmt.where(
            ComponentAdvisory.component_id.in_(
                select(Component.id).where(Component.direct.is_(True))
            )
        )
    elif direct_transitive == "transitive":
        stmt = stmt.where(Component.direct.is_(False))
        count_stmt = count_stmt.where(
            ComponentAdvisory.component_id.in_(
                select(Component.id).where(Component.direct.is_(False))
            )
        )
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(Component.package_name.ilike(pattern), Advisory.summary.ilike(pattern))
        )
        count_stmt = count_stmt.where(
            ComponentAdvisory.component_id.in_(
                select(Component.id).where(Component.package_name.ilike(pattern))
            )
        )
    total = session.execute(count_stmt).scalar_one() or 0
    stmt = (
        stmt.order_by(ComponentAdvisory.id.asc())
        .limit(page_params.page_size)
        .offset((page_params.page - 1) * page_params.page_size)
    )
    rows = session.execute(stmt).all()
    items = [
        _component_advisory_to_read(ca, component, advisory) for ca, component, advisory in rows
    ]
    return PaginatedVulnerabilities(
        items=items,
        pagination=pagination(
            page=page_params.page,
            page_size=page_params.page_size,
            total=int(total),
        ).model_dump(),
    )


def _component_advisory_to_read(
    ca: ComponentAdvisory,
    component: Component,
    advisory: Advisory,
) -> ComponentAdvisoryRead:
    fixed = ca.fixed_versions_json
    if fixed:
        try:
            parsed = json.loads(fixed)
        except (ValueError, TypeError):
            parsed = [fixed]
    else:
        parsed = []
    # v0.4: pull aliases + fetched_at from the evidence_json
    # payload the provider service attached when it persisted
    # the row. The evidence envelope is a small JSON document;
    # a missing field is treated as a missing record, never
    # as a fabricated value.
    aliases: list[str] = []
    fetched_at: str | None = None
    if ca.evidence_json:
        try:
            evidence = json.loads(ca.evidence_json)
        except (ValueError, TypeError):
            evidence = None
        if isinstance(evidence, dict):
            raw_aliases = evidence.get("aliases")
            if isinstance(raw_aliases, list):
                aliases = [a for a in raw_aliases if isinstance(a, str)]
            fetched_at_value = evidence.get("fetched_at")
            if isinstance(fetched_at_value, str):
                fetched_at = fetched_at_value
    return ComponentAdvisoryRead(
        id=ca.id,
        component_id=ca.component_id,
        advisory_id=advisory.id,
        fixed_versions=parsed if isinstance(parsed, list) else [],
        severity_source=ca.severity_source,
        # v0.4 honesty fix: ComponentAdvisory does not carry a
        # confidence field, and we must never infer one from
        # the severity score, the upstream provider, or the
        # existence of the advisory. OSV does not supply a
        # confidence value, so the response carries ``None``
        # and the frontend renders "Not supplied" / "Unknown".
        confidence=None,
        dependency_paths=[],
        withdrawn=False,
        # Enriched from the joined row:
        package_name=component.package_name,
        package_version=component.version,
        ecosystem=component.ecosystem,
        direct=component.direct,
        advisory_source=advisory.source,
        advisory_external_id=advisory.source_advisory_id,
        advisory_canonical_id=advisory.canonical_id,
        advisory_summary=advisory.summary,
        advisory_details_url=advisory.details_url,
        affected=ca.affected,
        severity_label=ca.severity_label,
        severity_score=ca.severity_score,
        # v0.4 additions
        provider_provenance=advisory.source,
        aliases=aliases,
        fetched_at=fetched_at,
    )


# ----------------------------------------------------------------------
# Advisories
# ----------------------------------------------------------------------
@router.get(
    "/{scan_id}/advisories",
    response_model=PaginatedAdvisories,
    summary="List advisories referenced by a scan.",
)
def list_advisories(
    scan_id: int,
    session: DBSession,
    page_params: PageParamsDep,
) -> PaginatedAdvisories:
    _get_scan_or_404(session, scan_id)
    stmt = (
        select(Advisory)
        .join(ComponentAdvisory, ComponentAdvisory.advisory_id == Advisory.id)
        .where(ComponentAdvisory.scan_run_id == scan_id)
        .distinct()
        .order_by(Advisory.id.asc())
    )
    count_stmt = (
        select(func.count(func.distinct(Advisory.id)))
        .join(ComponentAdvisory, ComponentAdvisory.advisory_id == Advisory.id)
        .where(ComponentAdvisory.scan_run_id == scan_id)
    )
    total = session.execute(count_stmt).scalar_one() or 0
    stmt = stmt.limit(page_params.page_size).offset((page_params.page - 1) * page_params.page_size)
    rows = session.execute(stmt).scalars().all()
    items = [
        AdvisoryRead(
            id=row.id,
            source=row.source,
            source_advisory_id=row.source_advisory_id,
            canonical_id=row.canonical_id,
            summary=row.summary,
            details_url=row.details_url,
            published_at=row.published_at,
            modified_at=row.modified_at,
            withdrawn_at=row.withdrawn_at,
            raw_payload_sha256=row.raw_payload_sha256,
        )
        for row in rows
    ]
    return PaginatedAdvisories(
        items=items,
        pagination=pagination(
            page=page_params.page,
            page_size=page_params.page_size,
            total=int(total),
        ).model_dump(),
    )


# ----------------------------------------------------------------------
# Workflow findings
# ----------------------------------------------------------------------
@router.get(
    "/{scan_id}/workflows",
    response_model=PaginatedWorkflowFindings,
    summary="List workflow (GitHub Actions) findings for a scan.",
)
def list_workflow_findings(
    scan_id: int,
    session: DBSession,
    page_params: PageParamsDep,
    rule_id: str | None = Query(default=None),
    severity: FindingSeverity | None = Query(default=None),
) -> PaginatedWorkflowFindings:
    _get_scan_or_404(session, scan_id)
    stmt = select(Finding).where(
        Finding.scan_run_id == scan_id,
        Finding.category == FindingCategory.WORKFLOW,
    )
    count_stmt = (
        select(func.count())
        .select_from(Finding)
        .where(
            Finding.scan_run_id == scan_id,
            Finding.category == FindingCategory.WORKFLOW,
        )
    )
    if rule_id is not None:
        stmt = stmt.where(Finding.rule_id == rule_id)
        count_stmt = count_stmt.where(Finding.rule_id == rule_id)
    if severity is not None:
        stmt = stmt.where(Finding.severity == severity)
        count_stmt = count_stmt.where(Finding.severity == severity)
    total = session.execute(count_stmt).scalar_one() or 0
    stmt = (
        stmt.order_by(Finding.id.asc())
        .limit(page_params.page_size)
        .offset((page_params.page - 1) * page_params.page_size)
    )
    rows = session.execute(stmt).scalars().all()
    items = [_finding_to_workflow_finding(row) for row in rows]
    return PaginatedWorkflowFindings(
        items=items,
        pagination=pagination(
            page=page_params.page,
            page_size=page_params.page_size,
            total=int(total),
        ).model_dump(),
    )


# ----------------------------------------------------------------------
# OpenSSF posture
# ----------------------------------------------------------------------
@router.get(
    "/{scan_id}/openssf",
    response_model=PaginatedOpenSSF,
    summary="List OpenSSF posture checks for a scan.",
)
def list_openssf_checks(
    scan_id: int,
    session: DBSession,
    page_params: PageParamsDep,
    check_id: str | None = Query(default=None),
) -> PaginatedOpenSSF:
    _get_scan_or_404(session, scan_id)
    stmt = select(Finding).where(
        Finding.scan_run_id == scan_id,
        Finding.category == FindingCategory.REPOSITORY_POSTURE,
    )
    count_stmt = (
        select(func.count())
        .select_from(Finding)
        .where(
            Finding.scan_run_id == scan_id,
            Finding.category == FindingCategory.REPOSITORY_POSTURE,
        )
    )
    if check_id is not None:
        stmt = stmt.where(Finding.rule_id == check_id)
        count_stmt = count_stmt.where(Finding.rule_id == check_id)
    total = session.execute(count_stmt).scalar_one() or 0
    stmt = (
        stmt.order_by(Finding.id.asc())
        .limit(page_params.page_size)
        .offset((page_params.page - 1) * page_params.page_size)
    )
    rows = session.execute(stmt).scalars().all()
    items = [_finding_to_openssf_check(row) for row in rows]
    return PaginatedOpenSSF(
        items=items,
        pagination=pagination(
            page=page_params.page,
            page_size=page_params.page_size,
            total=int(total),
        ).model_dump(),
    )


# ----------------------------------------------------------------------
# Licences
# ----------------------------------------------------------------------
@router.get(
    "/{scan_id}/licences",
    response_model=PaginatedLicences,
    summary="List licence assertions for a scan.",
)
def list_licences(
    scan_id: int,
    session: DBSession,
    page_params: PageParamsDep,
    review_status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    direct_transitive: str | None = Query(default=None, pattern="^(all|direct|transitive)$"),
) -> PaginatedLicences:
    _get_scan_or_404(session, scan_id)
    stmt = select(Finding).where(
        Finding.scan_run_id == scan_id,
        Finding.category == FindingCategory.LICENCE,
    )
    count_stmt = (
        select(func.count())
        .select_from(Finding)
        .where(
            Finding.scan_run_id == scan_id,
            Finding.category == FindingCategory.LICENCE,
        )
    )
    if review_status and review_status != "all":
        # The licence review status is encoded in the rule_id
        # we wrote. We translate the request into a rule_id
        # filter; "unreviewed" is the absence of a specific
        # rule_id.
        rule_filter = _rule_filter_for_licence_review(review_status)
        if rule_filter is not None:
            stmt = stmt.where(Finding.rule_id.in_(rule_filter))
            count_stmt = count_stmt.where(Finding.rule_id.in_(rule_filter))
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(Finding.title.ilike(pattern))
        count_stmt = count_stmt.where(Finding.title.ilike(pattern))
    total = session.execute(count_stmt).scalar_one() or 0
    stmt = (
        stmt.order_by(Finding.id.asc())
        .limit(page_params.page_size)
        .offset((page_params.page - 1) * page_params.page_size)
    )
    rows = session.execute(stmt).scalars().all()
    items = [_finding_to_licence_assertion(row) for row in rows]
    return PaginatedLicences(
        items=items,
        pagination=pagination(
            page=page_params.page,
            page_size=page_params.page_size,
            total=int(total),
        ).model_dump(),
    )


def _rule_filter_for_licence_review(status: str) -> tuple[str, ...] | None:
    if status == "review_required":
        return ("LOCK-LIC-003",)
    if status == "approved":
        return ("LOCK-LIC-INV",)
    if status == "unreviewed":
        return ("LOCK-LIC-001", "LOCK-LIC-002", "LOCK-LIC-004")
    return None


# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# Component enrichments (deps.dev / v0.4)
# ----------------------------------------------------------------------
@router.get(
    "/{scan_id}/enrichments",
    response_model=PaginatedEnrichments,
    summary="Per-component enrichment observations for a scan.",
)
def list_enrichments(
    scan_id: int,
    session: DBSession,
    page_params: PageParamsDep,
    ecosystem: str | None = Query(default=None),
    source_provenance: str | None = Query(default=None),
) -> PaginatedEnrichments:
    """List the per-component enrichment observations recorded for a scan.

    The endpoint surfaces the v0.4 deps.dev-backed enrichments
    and pairs them with their ``provider_observations`` row
    (status, fetched_at, cache_status, unavailable_reason).
    Components that were never enriched (e.g. unsupported
    ecosystem, no concrete version) are still included with
    ``provider_status=null`` and ``unavailable_reason``
    describing why; the frontend renders them as honest
    empty states, not as fabricated results.
    """
    _get_scan_or_404(session, scan_id)
    stmt = select(Component).where(Component.scan_run_id == scan_id).order_by(Component.id.asc())
    count_stmt = select(func.count()).select_from(Component).where(Component.scan_run_id == scan_id)
    if ecosystem is not None:
        stmt = stmt.where(Component.ecosystem == ecosystem)
        count_stmt = count_stmt.where(Component.ecosystem == ecosystem)
    total = session.execute(count_stmt).scalar_one() or 0
    stmt = stmt.limit(page_params.page_size).offset((page_params.page - 1) * page_params.page_size)
    components = session.execute(stmt).scalars().all()
    items = [_component_to_enrichment(session, c) for c in components]
    if source_provenance is not None:
        items = [i for i in items if (i.source_provenance or "") == source_provenance]
    return PaginatedEnrichments(
        items=items,
        pagination=pagination(
            page=page_params.page,
            page_size=page_params.page_size,
            total=int(total),
        ).model_dump(),
    )


def _component_to_enrichment(session: Session, component: Component) -> ComponentEnrichment:
    """Project a Component into its enrichment view.

    The shape is intentionally narrow: the frontend uses it
    to render the freshness indicator and the licence
    provenance, not the full component record.
    """
    # The latest ``deps_dev`` observation **for this
    # component** is the canonical enrichment record.
    # Earlier versions of the read path selected the
    # latest per-(scan, provider) row, which leaked
    # per-component error reasons to other components in
    # the same scan (a component with a concrete normalised
    # version would receive the "missing concrete version"
    # reason from a different component whose deps.dev
    # lookup failed). The v0.4 fix binds every per-component
    # ``ProviderObservation`` to ``component_id`` and the
    # endpoint filters on that key.
    from app.models.provider_observation import ProviderObservation

    obs = (
        session.query(ProviderObservation)
        .filter(
            ProviderObservation.scan_run_id == component.scan_run_id,
            ProviderObservation.provider == "deps_dev",
            ProviderObservation.component_id == component.id,
        )
        .order_by(ProviderObservation.id.desc())
        .first()
    )
    license_observations: list[str] = []
    dependency_count: int | None = None
    fetched_at: str | None = None
    cache_status = "miss"
    provider_status: str | None = None
    unavailable_reason: str | None = None
    provider_url: str | None = None
    source_provenance: str | None = None
    if obs is not None:
        provider_status = obs.status.value if hasattr(obs.status, "value") else str(obs.status)
        cache_status = obs.cache_status or "miss"
        if obs.completed_at is not None:
            fetched_at = obs.completed_at.isoformat().replace("+00:00", "Z")
        # v0.4 honesty fix: read the structured evidence
        # envelope from the dedicated ``evidence_json``
        # column. ``error_summary`` is for redacted error
        # text only; we never recover a successful payload
        # by parsing it. When the column is empty (legacy
        # rows, or an unconfigured observation) the
        # licence / dependency count simply stay empty.
        if obs.evidence_json:
            envelope = _parse_observation_evidence(obs.evidence_json)
            if envelope is not None:
                raw_licences = envelope.get("licences")
                if isinstance(raw_licences, list):
                    license_observations = [str(x) for x in raw_licences if x is not None]
                raw_dep = envelope.get("dependency_count")
                if isinstance(raw_dep, int):
                    dependency_count = raw_dep
        if obs.error_summary:
            unavailable_reason = obs.error_summary
        # The provider URL we *would* have queried. The
        # frontend uses it to surface a "View at provider"
        # link, never as evidence of a successful call.
        if component.ecosystem and component.package_name:
            provider_url = (
                f"https://api.deps.dev/v3/systems/{component.ecosystem}"
                f"/packages/{component.package_name}/versions/"
                f"{component.version or ''}"
            )
        if obs.status.value in {"available", "partial", "cached"}:
            source_provenance = "deps.dev"
    return ComponentEnrichment(
        component_id=component.id,
        ecosystem=component.ecosystem,
        package_name=component.package_name,
        version=component.version,
        fetched_at=fetched_at,
        cache_status=cache_status,
        provider_url=provider_url,
        source_provenance=source_provenance,
        license_observations=license_observations,
        dependency_count=dependency_count,
        provider_status=provider_status,
        unavailable_reason=unavailable_reason,
        # The structured evidence envelope from the
        # ``provider_observations.evidence_json`` column.
        # ``None`` for failed / never-queried rows; a JSON
        # object with ``licences`` and ``dependency_count``
        # for successful rows. The endpoint never fabricates
        # values.
        evidence=(_parse_observation_evidence(obs.evidence_json) if obs is not None else None),
    )


# ----------------------------------------------------------------------
# Scan comparison
# ----------------------------------------------------------------------
@router.get(
    "/{head_scan_id}/compare/{base_scan_id}",
    response_model=ScanComparisonResponse,
    summary="Compare two scans of the same repository.",
)
def compare_scans(
    head_scan_id: int,
    base_scan_id: int,
    session: DBSession,
) -> ScanComparisonResponse:
    """Read-only, evidence-aware comparison of two terminal scans.

    The comparator is the single source of truth for
    cross-scan evidence. It never triggers a rescan, never
    downloads a repository, never extracts an archive, never
    calls an external provider, and never writes to the
    database. The response carries the v0.5 evidence-honest
    state vocabulary (``newly_observed``,
    ``still_observed``, ``no_longer_observed``,
    ``changed_observation``, ``coverage_changed``,
    ``comparison_indeterminate``) and a coverage summary so
    the frontend can render "no differences observed"
    without conflating it with "all clear".
    """
    return comparison_service.compare_scans(
        session,
        base_scan_id=base_scan_id,
        head_scan_id=head_scan_id,
    )


# ----------------------------------------------------------------------
# Exports
# ----------------------------------------------------------------------
@router.get(
    "/{scan_id}/exports",
    response_model=ExportListResponse,
    summary="List the export formats the backend supports for this scan.",
)
def list_exports(
    scan_id: int,
    session: DBSession,
) -> ExportListResponse:
    """Return the export descriptors for ``scan_id``.

    Most descriptors are unconditional: the legacy v0.5 1.5
    CycloneDX SBOM, the findings JSON/CSV exports, and the
    SARIF export all produce empty-but-valid output for a
    failed, cancelled, queued, or running scan. The v0.6
    ``cyclonedx_1_7`` descriptor is the single exception: it
    applies the authoritative
    :func:`app.exporters._common.evaluate_export_eligibility`
    rule so the UI never offers a download the actual
    download endpoint would reject with 422.

    The list endpoint never weakens backend validation. The
    per-descriptor ``supported`` flag is the same answer the
    download endpoint would return (200 vs 422), so the
    frontend cannot offer a button that the backend would
    reject. The ``not_supported_reason`` carries the bounded
    eligibility reason so the UI can render a precise
    "Unavailable" tooltip and the operator log can
    reproduce the decision without re-querying."""
    scan = _get_scan_or_404(session, scan_id)
    # Count the persisted inventory so the eligibility
    # helper can decide whether a partial scan has enough
    # local evidence to qualify for a CycloneDX 1.7 export.
    # The two COUNT queries are bounded and indexed; the
    # ``list_exports`` endpoint is read-only and never
    # mutates state.
    component_count = int(
        session.execute(
            select(func.count()).select_from(Component).where(Component.scan_run_id == scan.id)
        ).scalar_one()
        or 0
    )
    manifest_count = int(
        session.execute(
            select(func.count()).select_from(Manifest).where(Manifest.scan_run_id == scan.id)
        ).scalar_one()
        or 0
    )
    cdx_17_eligibility = evaluate_export_eligibility(
        scan,
        component_count=component_count,
        manifest_count=manifest_count,
    )
    if cdx_17_eligibility.eligible:
        cdx_17_supported = True
        cdx_17_not_supported_reason: str | None = None
        if "provider_degraded" in cdx_17_eligibility.limitations:
            # Provider-degraded partial scan: the local
            # inventory is complete, but vulnerability /
            # enrichment evidence is partial. The descriptor
            # is still ``supported: true`` (the download
            # would return 200), but the description text
            # surfaces the limitation so the consumer never
            # mistakes a degraded SBOM for a complete one.
            cdx_17_description = (
                "CycloneDX 1.7 software bill of materials as JSON. "
                "Generated against the official 1.7 schema. "
                "Provider-degraded scan: local inventory is "
                "complete, but vulnerability / enrichment "
                "evidence may be partial. The BOM does not "
                "assert a complete dependency graph."
            )
        else:
            cdx_17_description = (
                "CycloneDX 1.7 software bill of materials as JSON. "
                "Generated against the official 1.7 schema."
            )
    else:
        cdx_17_supported = False
        cdx_17_not_supported_reason = cdx_17_eligibility.reason
        cdx_17_description = (
            "CycloneDX 1.7 software bill of materials as JSON. "
            "Generated against the official 1.7 schema. This "
            "scan is not eligible for the 1.7 export; the "
            "download endpoint would return 422 for this scan "
            "state."
        )
    descriptors = [
        ExportFormatDescriptor(
            format="cyclonedx_json",
            label="CycloneDX 1.5 SBOM (JSON)",
            description=(
                "CycloneDX 1.5 software bill of materials as "
                "JSON. Produces an empty-but-valid SBOM for a "
                "scan with no persisted evidence."
            ),
            supported=True,
            content_type="application/json",
            filename_hint="lockverity-sbom.cdx.json",
        ),
        ExportFormatDescriptor(
            format=CYCLONEDX_FORMAT_KEY,
            label="CycloneDX 1.7 SBOM (JSON)",
            description=cdx_17_description,
            supported=cdx_17_supported,
            not_supported_reason=cdx_17_not_supported_reason,
            content_type=CYCLONEDX_MEDIA_TYPE,
            filename_hint="lockverity-scan.cdx.json",
        ),
        ExportFormatDescriptor(
            format="findings_json",
            label="Findings (JSON)",
            description=(
                "Every finding, with evidence and location. "
                "Empty-but-valid for a scan with no findings."
            ),
            supported=True,
            content_type="application/json",
            filename_hint="lockverity-findings.json",
        ),
        ExportFormatDescriptor(
            format="findings_csv",
            label="Findings (CSV)",
            description=("One finding per row. Empty-but-valid for a scan with no findings."),
            supported=True,
            content_type="text/csv",
            filename_hint="lockverity-findings.csv",
        ),
        ExportFormatDescriptor(
            format="sarif_json",
            label="SARIF 2.1.0 (JSON)",
            description=(
                "Static analysis results in SARIF 2.1.0 "
                "format. Empty-but-valid for a scan with no "
                "static findings."
            ),
            supported=True,
            content_type="application/sarif+json",
            filename_hint="lockverity.sarif.json",
        ),
    ]
    return ExportListResponse(items=descriptors)


# v0.7 CycloneDX 1.7 preview / readiness summary.
#
# Declared *before* the format-dispatching
# ``/{scan_id}/exports/{format}`` route so FastAPI matches
# the more specific path first. The preview is a read-only
# JSON summary that reuses the same eligibility helper the
# download endpoint uses. It never generates a full BOM,
# never validates against the official JSON schema, and
# never writes to the database. The endpoint always returns
# 200 with a JSON body; the ``eligibility`` block in the
# body carries the bounded verdict (the API does not raise
# on eligibility because the consumer wants the verdict
# to render an "ineligible, here is why" panel rather
# than a 4xx error).
@router.get(
    "/{scan_id}/exports/cyclonedx_1_7/preview",
    summary=(
        "Preview the CycloneDX 1.7 SBOM for a scan. "
        "Returns a read-only JSON summary: scan identity, "
        "eligibility, inventory summary, evidence coverage, "
        "SBOM output facts, omissions, and the legacy-export "
        "relationship note."
    ),
)
def preview_cyclonedx_v17_sbom(
    scan_id: int,
    session: DBSession,
) -> dict[str, Any]:
    """Return the v0.7 preview / readiness summary for ``scan_id``.

    The route is informational. The ``eligibility`` block in
    the response carries the same verdict the download
    endpoint enforces, so the consumer can render the
    "eligible / disabled" state from a single source of
    truth. The route is read-only, deterministic, and
    performs no provider / network call.

    A 404 is returned only when the scan id does not exist
    in the database; every other scan state (queued,
    running, completed, partial, failed, cancelled)
    returns 200 with the appropriate ``eligibility``
    verdict.
    """
    from app.db import session as _db_session
    from app.exporters.cyclonedx_v17 import CycloneDxV17Exporter

    _get_scan_or_404(session, scan_id)
    exporter = CycloneDxV17Exporter(_db_session.SessionLocal)
    preview = exporter.preview(scan_run_id=scan_id)
    if preview is None:
        # The scan was deleted between the 404 check and
        # the preview call. The bounded 404 envelope is
        # the right answer; the consumer never sees a
        # half-built preview.
        raise ApiError(
            ApiErrorCode.NOT_FOUND,
            f"Scan {scan_id} not found.",
            details={"scan_id": scan_id},
        )
    return preview


# v0.6 CycloneDX 1.7 dedicated route.
#
# Declared *before* the format-dispatching
# ``/{scan_id}/exports/{format}`` route so FastAPI matches the
# more specific path first. Otherwise the dispatcher would
# treat ``cyclonedx_1_7`` as a format identifier and return
# the legacy 1.5-style ``filename_hint`` without the scan id.
@router.get(
    "/{scan_id}/exports/cyclonedx_1_7",
    summary=(
        "Download a CycloneDX 1.7 SBOM for the scan. "
        "Read-only, deterministic, validated against the official 1.7 schema."
    ),
    response_class=Response,
)
def download_cyclonedx_v17_sbom(
    scan_id: int,
    session: DBSession,
) -> Response:
    """Return the v0.6 CycloneDX 1.7 SBOM for ``scan_id``.

    The route is the v0.6 entry point. It deliberately lives
    alongside the existing ``/{scan_id}/exports/{format}``
    route so the legacy 1.5 export and the new 1.7 export are
    both available, with no behaviour change to the legacy
    route. The 1.7 endpoint:

    - Returns the BOM with the correct CycloneDX 1.7 JSON
      media type (``application/vnd.cyclonedx+json; version=1.7``).
    - Uses a deterministic ``Content-Disposition`` filename that
      includes the scan id, so two different scans never collide
      on the same downloaded file.
    - Maps the exporter's bounded :class:`ProviderUnavailable`
      codes to 4xx/5xx responses with no internal paths or
      validator internals leaked.
    - Performs no database writes and no external HTTP requests.
    """
    from app.db import session as _db_session
    from app.exporters.cyclonedx_v17 import (
        CYCLONEDX_MEDIA_TYPE,
        CycloneDxV17Exporter,
    )

    _get_scan_or_404(session, scan_id)
    exporter = CycloneDxV17Exporter(_db_session.SessionLocal)
    result = exporter.export(scan_run_id=scan_id)
    if not isinstance(result, ProviderSuccess):
        code = getattr(result, "error_code", "export_failed")
        summary = getattr(result, "error_summary", "Export is not currently available.")
        # The exporter's bounded code map. The API layer never
        # returns the internal exception, the stack trace, or
        # the validator internals; only the bounded summary.
        if code == "export_scan_not_found":
            raise ApiError(
                ApiErrorCode.NOT_FOUND,
                summary,
                details={"scan_id": scan_id, "code": code},
            )
        # scan_failed, scan_cancelled, scan_not_started,
        # scan_in_progress, partial_incomplete: a state-based
        # rejection that the consumer should treat as a 409
        # (state conflict).
        state_codes = {
            "scan_failed",
            "scan_cancelled",
            "scan_not_started",
            "scan_in_progress",
            "partial_incomplete",
            "cyclonedx_validation_failed",
        }
        if code in state_codes:
            raise ApiError(
                ApiErrorCode.VALIDATION_ERROR,
                summary,
                details={"scan_id": scan_id, "code": code},
            )
        raise ApiError(
            ApiErrorCode.PROVIDER_UNAVAILABLE,
            summary,
            details={"scan_id": scan_id, "code": code},
        )
    payload = result.data
    filename = f"lockverity-scan-{scan_id}.cdx.json"
    return Response(
        content=payload,
        # FastAPI's ``media_type`` does not accept media-type
        # parameters, so the parameter is appended manually via
        # the ``Content-Type`` header. The base type remains
        # ``application/vnd.cyclonedx+json``.
        headers={
            "Content-Type": CYCLONEDX_MEDIA_TYPE,
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get(
    "/{scan_id}/exports/{format}",
    summary="Download a generated export for the scan.",
    response_class=PlainTextResponse,
)
def download_export(
    scan_id: int,
    format: str,
    session: DBSession,
) -> Response:
    _get_scan_or_404(session, scan_id)
    exporter = _exporter_for_format(format)
    if exporter is None:
        raise ApiError(
            ApiErrorCode.NOT_FOUND,
            "Export format is not implemented.",
            details={
                "format": format,
                "supported": [
                    "cyclonedx_json",
                    "findings_json",
                    "findings_csv",
                    "sarif_json",
                ],
            },
        )
    from app.exporters._common import ScanNotFoundError

    try:
        result = exporter.export(scan_run_id=scan_id)
    except ScanNotFoundError as exc:
        raise ApiError(
            ApiErrorCode.NOT_FOUND,
            "Scan not found for export.",
            details={"scan_id": scan_id},
        ) from exc
    if not isinstance(result, ProviderSuccess):
        # The exporter contract returns ProviderUnavailable for
        # the failure case. Surface as a 503 so the UI can show
        # "transient" instead of "permanent".
        raise ApiError(
            ApiErrorCode.PROVIDER_UNAVAILABLE,
            "Export is not currently available.",
            details={"format": format, "reason": getattr(result, "error_summary", "unavailable")},
        )
    payload = result.data
    descriptor = next(d for d in list_exports(scan_id, session).items if d.format == format)
    return Response(
        content=payload,
        media_type=descriptor.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{descriptor.filename_hint}"',
        },
    )


def _exporter_for_format(format: str):
    # The ``cyclonedx_1_7`` format is served by the dedicated
    # ``/{scan_id}/exports/cyclonedx_1_7`` route above so the
    # 1.7 download can carry the per-scan filename and the
    # media-type parameter. The dispatcher never sees it.
    if format == "cyclonedx_json":
        from app.db import session as _db_session

        return CycloneDxExporter(_db_session.SessionLocal)
    if format == "findings_json":
        from app.db import session as _db_session

        return FindingsJsonExporter(_db_session.SessionLocal)
    if format == "findings_csv":
        from app.db import session as _db_session

        return FindingsCsvExporter(_db_session.SessionLocal)
    if format == "sarif_json":
        from app.db import session as _db_session

        return SarifStaticFindingsExporter(_db_session.SessionLocal)
    return None


# ----------------------------------------------------------------------
# Auto-run on intake (v0.3 product outcome)
# ----------------------------------------------------------------------
@router.post(
    "/{scan_id}/auto-run",
    response_model=None,
    summary="Local convenience: run a queued scan synchronously and return the final state.",
)
def auto_run(
    scan_id: int,
    session: DBSession,
    payload: ScanRunRequest | None = None,
) -> dict[str, Any]:
    """Run ``scan_id`` synchronously and return the terminal state.

    This endpoint exists for **local development and smoke
    verification only**. It blocks the HTTP worker thread
    until the orchestrator reaches a terminal state. The
    duration is bounded by the per-scan and per-file limits
    in :class:`app.core.config.Settings` (the orchestrator
    never executes repository code, never makes a network
    call to an upstream provider, and never exceeds the
    configured archive limits), but the request itself can
    take seconds to a few minutes depending on the size of
    the workspace.

    The **production frontend flow** is the asynchronous
    pattern: ``POST /api/v1/scans/{id}/run`` to enqueue the
    scan on the local executor, then poll
    ``GET /api/v1/scans/{id}`` until a terminal state. The
    frontend already wires this up in
    :file:`frontend/src/pages/RepositoryDetailsPage.tsx` and
    :file:`frontend/src/pages/ScanDetailsPage.tsx`.

    ``auto-run`` is a thin convenience: it accepts the same
    ``force`` payload as ``/run`` so a re-run can be
    requested. It cannot silently replace the asynchronous
    flow because it is documented here as a local-only
    convenience, it shares the same orchestrator code path,
    and the only consumer in this repository is the
    development smoke test.
    """
    from app.services.orchestrator_service import ScanOrchestrator

    scan_service.get_scan_or_404(session, scan_id)
    orchestrator = ScanOrchestrator(_orchestrator_session_factory())
    outcome = orchestrator.run(scan_id)
    return {
        "scan_id": outcome.scan_id,
        "final_status": outcome.final_status.value,
        "failure_code": outcome.failure_code,
        "failure_summary": outcome.failure_summary,
    }


def _orchestrator_session_factory():
    from app.db import session as _db_session

    return _db_session.SessionLocal


__all__ = [
    "auto_run",
    "compare_scans",
    "download_export",
    "get_dependency_path",
    "list_advisories",
    "list_components",
    "list_exports",
    "list_licences",
    "list_openssf_checks",
    "list_vulnerabilities",
    "list_workflow_findings",
    "router",
]
