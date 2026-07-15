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
from datetime import UTC, datetime
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
from app.models.scan_run import ScanRun, ScanStatus
from app.providers.results import ProviderSuccess
from app.schemas.common import SchemaModel
from app.schemas.intake import ScanRunRequest
from app.schemas.scan import (
    AdvisoryRead,
    ComponentAdvisoryRead,
    ComponentRead,
    DependencyPathEntry,
    DependencyPathRead,
    ScanComparisonRead,
    WorkflowFindingRead,
)
from app.services import scan_service
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
    return ComponentAdvisoryRead(
        id=ca.id,
        component_id=ca.component_id,
        advisory_id=ca.advisory_id,
        fixed_versions=parsed if isinstance(parsed, list) else [],
        severity_source=ca.severity_source,
        confidence=ca.confidence,
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
# Scan comparison
# ----------------------------------------------------------------------
@router.get(
    "/{head_scan_id}/compare/{base_scan_id}",
    response_model=ScanComparisonRead,
    summary="Compare two scans of the same repository.",
)
def compare_scans(
    head_scan_id: int,
    base_scan_id: int,
    session: DBSession,
) -> ScanComparisonRead:
    base = _get_scan_or_404(session, base_scan_id)
    head = _get_scan_or_404(session, head_scan_id)
    if base.repository_id != head.repository_id:
        raise ApiError(
            ApiErrorCode.VALIDATION_ERROR,
            "Scans must belong to the same repository.",
            details={
                "base_repository_id": base.repository_id,
                "head_repository_id": head.repository_id,
            },
        )
    base_components = _components_by_name(session, base_scan_id)
    head_components = _components_by_name(session, head_scan_id)
    component_rows = _build_component_comparison(base_components, head_components)
    base_findings = _findings_by_key(session, base_scan_id)
    head_findings = _findings_by_key(session, head_scan_id)
    finding_rows = _build_finding_comparison(base_findings, head_findings)
    base_manifests = _manifests_by_path(session, base_scan_id)
    head_manifests = _manifests_by_path(session, head_scan_id)
    manifest_rows = _build_manifest_comparison(base_manifests, head_manifests)
    unable: list[str] = []
    if head.status == ScanStatus.FAILED:
        unable.append("head scan failed")
    if base.status == ScanStatus.FAILED:
        unable.append("base scan failed")
    return ScanComparisonRead(
        base_scan_id=base.id,
        head_scan_id=head.id,
        repository_id=head.repository_id,
        generated_at=datetime.now(UTC),
        components=component_rows,
        findings=finding_rows,
        manifests=manifest_rows,
        workflows=[],
        providers=[],
        unable_to_determine=unable,
    )


def _components_by_name(session: Session, scan_id: int) -> dict[str, Component]:
    rows = (
        session.execute(select(Component).where(Component.scan_run_id == scan_id)).scalars().all()
    )
    out: dict[str, Component] = {}
    for row in rows:
        # When the same package appears multiple times (one per
        # manifest), prefer the lockfile-resolved version.
        existing = out.get(row.package_name)
        if existing is None or (row.version and not existing.version):
            out[row.package_name] = row
    return out


def _findings_by_key(session: Session, scan_id: int) -> dict[str, Finding]:
    rows = session.execute(select(Finding).where(Finding.scan_run_id == scan_id)).scalars().all()
    return {row.stable_key: row for row in rows}


def _manifests_by_path(session: Session, scan_id: int) -> dict[str, Manifest]:
    rows = session.execute(select(Manifest).where(Manifest.scan_run_id == scan_id)).scalars().all()
    return {row.path: row for row in rows}


def _build_component_comparison(
    base: dict[str, Component],
    head: dict[str, Component],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in sorted(set(base) | set(head)):
        b = base.get(name)
        h = head.get(name)
        if b and not h:
            verdict = "removed"
        elif h and not b:
            verdict = "added"
        elif b and h and b.version != h.version:
            verdict = "updated"
        else:
            verdict = "persisting"
        rows.append(
            {
                "package_name": name,
                "ecosystem": (b or h).ecosystem if (b or h) else None,
                "verdict": verdict,
                "version_base": b.version if b else None,
                "version_head": h.version if h else None,
                "direct_base": b.direct if b else None,
                "direct_head": h.direct if h else None,
                "dependency_path_changed": bool(b and h and b.version != h.version),
            }
        )
    return rows


def _build_finding_comparison(
    base: dict[str, Finding],
    head: dict[str, Finding],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in sorted(set(base) | set(head)):
        b = base.get(key)
        h = head.get(key)
        if b and not h:
            verdict = "resolved"
        elif h and not b:
            verdict = "added"
        elif b and h and (b.severity != h.severity or b.confidence != h.confidence):
            verdict = "updated"
        else:
            verdict = "persisting"
        rows.append(
            {
                "stable_key": key,
                "rule_id": (b or h).rule_id if (b or h) else "",
                "title": (b or h).title if (b or h) else "",
                "verdict": verdict,
                "severity_base": b.severity if b else None,
                "severity_head": h.severity if h else None,
                "confidence_base": b.confidence if b else None,
                "confidence_head": h.confidence if h else None,
                "provider_attribution_base": [],
                "provider_attribution_head": [],
                "unable_to_determine": False,
            }
        )
    return rows


def _build_manifest_comparison(
    base: dict[str, Manifest],
    head: dict[str, Manifest],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(set(base) | set(head)):
        b = base.get(path)
        h = head.get(path)
        if b and not h:
            change = "removed"
        elif h and not b:
            change = "added"
        elif b and h and b.content_sha256 != h.content_sha256:
            change = "updated"
        else:
            change = "unchanged"
        rows.append(
            {
                "manifest_path": path,
                "base_hash": b.content_sha256 if b else None,
                "head_hash": h.content_sha256 if h else None,
                "change": change,
            }
        )
    return rows


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
    _get_scan_or_404(session, scan_id)
    descriptors = [
        ExportFormatDescriptor(
            format="cyclonedx_json",
            label="CycloneDX 1.5 SBOM (JSON)",
            description="CycloneDX 1.5 software bill of materials as JSON.",
            supported=True,
            content_type="application/json",
            filename_hint="lockverity-sbom.cdx.json",
        ),
        ExportFormatDescriptor(
            format="findings_json",
            label="Findings (JSON)",
            description="Every finding, with evidence and location.",
            supported=True,
            content_type="application/json",
            filename_hint="lockverity-findings.json",
        ),
        ExportFormatDescriptor(
            format="findings_csv",
            label="Findings (CSV)",
            description="One finding per row.",
            supported=True,
            content_type="text/csv",
            filename_hint="lockverity-findings.csv",
        ),
        ExportFormatDescriptor(
            format="sarif_json",
            label="SARIF 2.1.0 (JSON)",
            description="Static analysis results in SARIF 2.1.0 format.",
            supported=True,
            content_type="application/sarif+json",
            filename_hint="lockverity.sarif.json",
        ),
    ]
    return ExportListResponse(items=descriptors)


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
                "supported": ["cyclonedx_json", "findings_json", "findings_csv", "sarif_json"],
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
