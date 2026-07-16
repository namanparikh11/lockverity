"""v0.5 evidence-aware scan comparison service.

This service is the *only* place that decides how two terminal
scans of the same repository/workspace should be diffed. It is
read-only: it never writes to the database, never triggers a
rescan, never downloads a repository, never extracts an
archive, never calls an external provider, and never executes
repository code.

The state vocabulary is the one defined in
:mod:`app.schemas.comparison`:

* ``newly_observed``
* ``still_observed``
* ``no_longer_observed``
* ``changed_observation``
* ``coverage_changed``
* ``comparison_indeterminate``

Successful provider evidence is never placed in
``error_summary``. Missing provider data is never interpreted
as a clean bill of health. When a comparison cannot be made
truthfully for a given row, the row is marked
``comparison_indeterminate`` and a short reason is added to the
top-level ``indeterminate_reasons`` list.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

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
from app.models.provider_observation import (
    ProviderObservation,
    ProviderStatus,
)
from app.models.scan_run import ScanRun, ScanStatus
from app.schemas.comparison import (
    ComponentObservation,
    CoverageSummary,
    DependencyPathChange,
    LicenceObservation,
    ManifestObservation,
    OpenSSFObservation,
    ProviderCoverage,
    ProviderStateName,
    ScanComparisonResponse,
    VulnerabilityObservation,
    WorkflowObservation,
)
from app.services import scan_service
from app.utils.datetime import utcnow
from app.utils.errors import ApiError, ApiErrorCode

# Terminal scan statuses that are eligible for comparison.
# Only ``completed`` and ``partial`` qualify: a ``failed``
# or ``cancelled`` scan did not finish its work, so its
# persisted evidence is untrustworthy. The comparator
# rejects those two with a bounded error rather than
# building a comparison on partial, untrustworthy data.
_TERMINAL_SCAN_STATUSES: frozenset[ScanStatus] = frozenset(
    {ScanStatus.COMPLETED, ScanStatus.PARTIAL}
)

# Provider state names that mean "we cannot trust the
# comparison for the affected ecosystem" on the head side.
# These mirror the v0.4 ``ProviderStatus`` enum: a missing,
# unavailable, partial, rate-limited, unsupported,
# not_requested, or unknown head provider is treated as
# evidence-insufficient for the affected domain.
_INDETERMINATE_HEAD_PROVIDER_STATES: frozenset[ProviderStateName] = frozenset(
    {"unavailable", "partial", "unsupported", "not_requested", "unknown"}
)

# The v0.4 backend does not maintain a "stale" provider
# classification based on the wall-clock age of a cached
# observation. The authoritative freshness signal is the
# ``cache_status`` column on :class:`ProviderObservation`
# (``hit`` / ``miss`` / ``stale`` / ``error``), set by
# :class:`app.services.cache_service.CacheService` when an
# entry's ``expires_at`` is in the past. The comparator
# therefore treats an ``AVAILABLE`` provider as
# ``successful`` regardless of how long ago the observation
# was recorded, and surfaces ``cache_status`` as raw freshness
# metadata on the response so the operator can see what the
# underlying record says. Inventing a cross-scan "stale"
# classification would be a fabricated severity claim.

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def compare_scans(
    session: Session,
    *,
    base_scan_id: int,
    head_scan_id: int,
) -> ScanComparisonResponse:
    """Return a deterministic, read-only comparison of two terminal scans.

    The two scans must:

    * exist;
    * be distinct;
    * belong to the same repository (cross-workspace
      comparison is out of scope for v0.5);
    * both be in a terminal state.

    The comparator does not perform any external I/O. It only
    reads persisted data from the database.
    """
    if base_scan_id == head_scan_id:
        raise ApiError(
            ApiErrorCode.VALIDATION_ERROR,
            "Base and head scans must be distinct.",
            details={"base_scan_id": base_scan_id, "head_scan_id": head_scan_id},
        )
    base = scan_service.get_scan_or_404(session, base_scan_id)
    head = scan_service.get_scan_or_404(session, head_scan_id)
    if base.repository_id != head.repository_id:
        raise ApiError(
            ApiErrorCode.VALIDATION_ERROR,
            "Scans must belong to the same repository.",
            details={
                "base_repository_id": base.repository_id,
                "head_repository_id": head.repository_id,
            },
        )
    if base.status not in _TERMINAL_SCAN_STATUSES or head.status not in _TERMINAL_SCAN_STATUSES:
        raise ApiError(
            ApiErrorCode.ILLEGAL_TRANSITION,
            "Both scans must be in a terminal state.",
            details={
                "base_scan_id": base.id,
                "base_status": base.status.value,
                "head_scan_id": head.id,
                "head_status": head.status.value,
            },
        )

    components = _compare_components(session, base.id, head.id)
    manifests = _compare_manifests(session, base.id, head.id)
    dependency_paths = _compare_dependency_paths(session, base.id, head.id)
    workflows = _compare_workflows(session, base.id, head.id)
    vulnerabilities, vuln_indeterminate = _compare_vulnerabilities(session, base.id, head.id)
    licences = _compare_licences(session, base.id, head.id)
    openssf = _compare_openssf(session, base.id, head.id)
    providers, providers_indeterminate = _compare_providers(session, base.id, head.id)
    coverage = _coverage_summary(
        base=base,
        head=head,
        components_base=sum(1 for c in components if _present_in_scan(c, "base")),
        components_head=sum(1 for c in components if _present_in_scan(c, "head")),
        findings_base=_count_in_scan(
            _findings_by_category(session, base.id, FindingCategory.WORKFLOW)
        ),
        findings_head=_count_in_scan(
            _findings_by_category(session, head.id, FindingCategory.WORKFLOW)
        ),
        vulnerabilities_base=len(_component_advisories(session, base.id)),
        vulnerabilities_head=len(_component_advisories(session, head.id)),
        workflows_base=len(_findings_by_category(session, base.id, FindingCategory.WORKFLOW)),
        workflows_head=len(_findings_by_category(session, head.id, FindingCategory.WORKFLOW)),
        manifests_base=len(manifests),
        manifests_head=len(manifests),
        licence_assertions_base=sum(1 for row in licences if row.provider_base is not None),
        licence_assertions_head=sum(1 for row in licences if row.provider_head is not None),
        openssf_checks_in_base=len(
            _findings_by_category(session, base.id, FindingCategory.REPOSITORY_POSTURE)
        ),
        openssf_checks_in_head=len(
            _findings_by_category(session, head.id, FindingCategory.REPOSITORY_POSTURE)
        ),
        providers=providers,
    )
    indeterminate_reasons: list[str] = []
    indeterminate_reasons.extend(vuln_indeterminate)
    indeterminate_reasons.extend(providers_indeterminate)
    # Deterministic sort + dedupe.
    indeterminate_reasons = sorted(dict.fromkeys(indeterminate_reasons))
    return ScanComparisonResponse(
        base_scan_id=base.id,
        head_scan_id=head.id,
        repository_id=head.repository_id,
        base_trigger_type=base.trigger_type.value if base.trigger_type else None,
        head_trigger_type=head.trigger_type.value if head.trigger_type else None,
        base_resolved_commit_sha=base.resolved_commit_sha,
        head_resolved_commit_sha=head.resolved_commit_sha,
        base_analyzer_version=base.analyzer_version,
        head_analyzer_version=head.analyzer_version,
        base_completed_at=base.completed_at,
        head_completed_at=head.completed_at,
        generated_at=utcnow(),
        coverage=coverage,
        components=components,
        manifests=manifests,
        dependency_paths=dependency_paths,
        workflows=workflows,
        vulnerabilities=vulnerabilities,
        licences=licences,
        openssf=openssf,
        providers=providers,
        indeterminate_reasons=indeterminate_reasons,
    )


# ---------------------------------------------------------------------------
# Component comparison
# ---------------------------------------------------------------------------


def _compare_components(session: Session, base_id: int, head_id: int) -> list[ComponentObservation]:
    """Compare components discovered in the two scans.

    Component identity is the v0.5 tuple
    ``(ecosystem, package_name, version)``: the concrete
    version is part of the identity, not a derived attribute.
    The comparator therefore emits one row per
    ``(ecosystem, package_name, version)`` it observes on
    either side.

    * A version present in only the base scan is
      ``no_longer_observed``.
    * A version present in only the head scan is
      ``newly_observed``.
    * A version present in both scans is
      ``still_observed``; the row records the manifest
      paths and the direct/transitive flag observed on
      each side.
    * A version present on both sides whose direct /
      transitive scope differs is ``changed_observation``.

    Where the *same package* appears with several versions
    in either scan (across manifests or as multiple
    dependency instances), the comparator does **not**
    collapse them into a single row and does **not**
    fabricate a transition. Each version gets its own
    row, and an umbrella "the package identity was
    ambiguous" reason is never emitted - the spec is
    explicit that the concrete version is part of the
    identity. ``comparison_indeterminate`` is reserved
    for cases where the data is genuinely insufficient
    (e.g. the underlying record is corrupt); it is not a
    catch-all for "there are several versions".
    """
    base_components = (
        session.execute(select(Component).where(Component.scan_run_id == base_id)).scalars().all()
    )
    head_components = (
        session.execute(select(Component).where(Component.scan_run_id == head_id)).scalars().all()
    )
    base_manifest_ids = _scan_manifest_ids(session, base_id)
    head_manifest_ids = _scan_manifest_ids(session, head_id)
    manifest_paths_by_id = _manifest_paths_by_id(session, base_manifest_ids | head_manifest_ids)
    base_index = _index_components_by_version(base_components)
    head_index = _index_components_by_version(head_components)
    all_keys = sorted(set(base_index) | set(head_index))
    rows: list[ComponentObservation] = []
    for key in all_keys:
        ecosystem, package_name, version = key
        base_rows = base_index.get(key, [])
        head_rows = head_index.get(key, [])
        manifest_paths = sorted(
            {manifest_paths_by_id[c.manifest_id] for c in base_rows + head_rows}
        )
        direct_base = _bool_or_none([c.direct for c in base_rows]) if base_rows else None
        direct_head = _bool_or_none([c.direct for c in head_rows]) if head_rows else None
        if base_rows and not head_rows:
            rows.append(
                ComponentObservation(
                    ecosystem=ecosystem,
                    package_name=package_name,
                    version=version,
                    manifest_paths=manifest_paths,
                    direct_base=direct_base,
                    direct_head=None,
                    state="no_longer_observed",
                )
            )
            continue
        if head_rows and not base_rows:
            rows.append(
                ComponentObservation(
                    ecosystem=ecosystem,
                    package_name=package_name,
                    version=version,
                    manifest_paths=manifest_paths,
                    direct_base=None,
                    direct_head=direct_head,
                    state="newly_observed",
                )
            )
            continue
        # Both sides have the same concrete version. The row
        # is "still_observed" unless the direct / transitive
        # scope actually changed on a per-instance basis.
        state = "still_observed" if direct_base == direct_head else "changed_observation"
        rows.append(
            ComponentObservation(
                ecosystem=ecosystem,
                package_name=package_name,
                version=version,
                manifest_paths=manifest_paths,
                direct_base=direct_base,
                direct_head=direct_head,
                state=state,
            )
        )
    return rows


def _index_components_by_version(
    components: Iterable[Component],
) -> dict[tuple[str | None, str, str | None], list[Component]]:
    """Group components by ``(ecosystem, package_name, version)``.

    The concrete version is part of the identity, so multiple
    versions of the same package (or a mix of resolved and
    unresolved entries) end up in separate buckets. Within a
    bucket, every row shares the same identity and the
    comparator treats them as duplicate observations of the
    same component, not as separate components.
    """
    out: dict[tuple[str | None, str, str | None], list[Component]] = defaultdict(list)
    for component in components:
        out[(component.ecosystem, component.package_name, component.version)].append(component)
    return out


def _bool_or_none(values: Iterable[bool]) -> bool | None:
    """Return the value if all observed values agree, else ``None``."""
    distinct = set(values)
    if len(distinct) == 1:
        return next(iter(distinct))
    return None


# ---------------------------------------------------------------------------
# Manifest comparison
# ---------------------------------------------------------------------------


def _compare_manifests(session: Session, base_id: int, head_id: int) -> list[ManifestObservation]:
    base_manifests = _manifests_by_scan(session, base_id)
    head_manifests = _manifests_by_scan(session, head_id)
    all_paths = sorted(set(base_manifests) | set(head_manifests))
    rows: list[ManifestObservation] = []
    for path in all_paths:
        base = base_manifests.get(path)
        head = head_manifests.get(path)
        if base and not head:
            state = "no_longer_observed"
        elif head and not base:
            state = "newly_observed"
        elif base and head and base.content_sha256 != head.content_sha256:
            state = "changed_observation"
        else:
            state = "still_observed"
        rows.append(
            ManifestObservation(
                manifest_path=path,
                manifest_type=(head or base).manifest_type if (head or base) else None,
                ecosystem=(head or base).ecosystem if (head or base) else None,
                parse_status_base=base.parse_status.value
                if base and hasattr(base.parse_status, "value")
                else None,
                parse_status_head=head.parse_status.value
                if head and hasattr(head.parse_status, "value")
                else None,
                content_sha256_base=base.content_sha256 if base else None,
                content_sha256_head=head.content_sha256 if head else None,
                state=state,
            )
        )
    return rows


def _manifests_by_scan(session: Session, scan_id: int) -> dict[str, Manifest]:
    rows = session.execute(select(Manifest).where(Manifest.scan_run_id == scan_id)).scalars().all()
    return {row.path: row for row in rows}


def _scan_manifest_ids(session: Session, scan_id: int) -> set[int]:
    return {
        row
        for (row,) in session.execute(
            select(Manifest.id).where(Manifest.scan_run_id == scan_id)
        ).all()
    }


def _manifest_paths_by_id(session: Session, manifest_ids: set[int]) -> dict[int, str]:
    if not manifest_ids:
        return {}
    rows = session.execute(
        select(Manifest.id, Manifest.path).where(Manifest.id.in_(manifest_ids))
    ).all()
    return {row[0]: row[1] for row in rows}


# ---------------------------------------------------------------------------
# Dependency path comparison
# ---------------------------------------------------------------------------


def _compare_dependency_paths(
    session: Session, base_id: int, head_id: int
) -> list[DependencyPathChange]:
    """Compare parent chains for components present in both scans.

    The comparator only emits a row when the component's
    *identity* (ecosystem, package_name, version) is unchanged
    in both scans and a parent chain difference is detected.
    Other component-level changes belong on the
    ``ComponentObservation`` list, not here.
    """
    base_components = _components_by_package_version(session, base_id)
    head_components = _components_by_package_version(session, head_id)
    shared = sorted(set(base_components) & set(head_components))
    rows: list[DependencyPathChange] = []
    for key in shared:
        ecosystem, package_name, version = key
        base_chain = _parent_chain(session, base_id, base_components[key])
        head_chain = _parent_chain(session, head_id, head_components[key])
        if base_chain == head_chain:
            continue
        rows.append(
            DependencyPathChange(
                ecosystem=ecosystem,
                package_name=package_name,
                version=version,
                parent_chain_base=base_chain,
                parent_chain_head=head_chain,
                state="changed_observation",
            )
        )
    return rows


def _components_by_package_version(
    session: Session, scan_id: int
) -> dict[tuple[str | None, str, str | None], int]:
    rows = (
        session.execute(select(Component).where(Component.scan_run_id == scan_id)).scalars().all()
    )
    out: dict[tuple[str | None, str, str | None], int] = {}
    for row in rows:
        key = (row.ecosystem, row.package_name, row.version)
        if key in out:
            continue
        out[key] = row.id
    return out


def _parent_chain(session: Session, scan_id: int, component_id: int) -> list[str]:
    """Return the sorted list of direct-parent package names."""
    rows = session.execute(
        select(Component.package_name)
        .join(DependencyEdge, DependencyEdge.parent_component_id == Component.id)
        .where(
            DependencyEdge.scan_run_id == scan_id,
            DependencyEdge.child_component_id == component_id,
        )
    ).all()
    return sorted(name for (name,) in rows if name is not None)


# ---------------------------------------------------------------------------
# Workflow (GitHub Actions) comparison
# ---------------------------------------------------------------------------


def _compare_workflows(session: Session, base_id: int, head_id: int) -> list[WorkflowObservation]:
    """Compare workflow findings between two scans.

    The comparator deduplicates on ``stable_key`` so a finding
    is treated as the same row even if the title or
    workflow_path evolved slightly. Severity and confidence
    deltas are surfaced, not summarised.
    """
    base_rows = _findings_by_category(session, base_id, FindingCategory.WORKFLOW)
    head_rows = _findings_by_category(session, head_id, FindingCategory.WORKFLOW)
    base_index = {row.stable_key: row for row in base_rows}
    head_index = {row.stable_key: row for row in head_rows}
    all_keys = sorted(set(base_index) | set(head_index))
    rows: list[WorkflowObservation] = []
    for key in all_keys:
        b = base_index.get(key)
        h = head_index.get(key)
        if b and not h:
            state = "no_longer_observed"
        elif h and not b:
            state = "newly_observed"
        elif b and h and (b.severity != h.severity or b.confidence != h.confidence):
            state = "changed_observation"
        else:
            state = "still_observed"
        rows.append(
            WorkflowObservation(
                rule_id=(b or h).rule_id if (b or h) else "",
                workflow_path=(b or h).location_path or "" if (b or h) else "",
                title=(b or h).title if (b or h) else "",
                severity_base=b.severity.value if b and hasattr(b.severity, "value") else None,
                severity_head=h.severity.value if h and hasattr(h.severity, "value") else None,
                confidence_base=b.confidence.value
                if b and hasattr(b.confidence, "value")
                else None,
                confidence_head=h.confidence.value
                if h and hasattr(h.confidence, "value")
                else None,
                stable_key=key,
                state=state,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Vulnerability comparison
# ---------------------------------------------------------------------------


def _compare_vulnerabilities(
    session: Session, base_id: int, head_id: int
) -> tuple[list[VulnerabilityObservation], list[str]]:
    """Compare component x advisory rows between two scans.

    Rows that disappear from the head scan are not marked
    ``no_longer_observed`` when the head's provider coverage
    for the affected ecosystem is insufficient; the comparator
    marks them ``comparison_indeterminate`` and adds a reason
    to the top-level ``indeterminate_reasons`` list.
    """
    base_rows = _component_advisories_with_joins(session, base_id)
    head_rows = _component_advisories_with_joins(session, head_id)
    head_provider_state = _provider_state_by_name(session, head_id)
    base_provider_state = _provider_state_by_name(session, base_id)
    base_index: dict[tuple[str | None, str | None, str, str], list[_VulnRow]] = defaultdict(list)
    head_index: dict[tuple[str | None, str | None, str, str], list[_VulnRow]] = defaultdict(list)
    for row in base_rows:
        base_index[_vuln_key(row)].append(row)
    for row in head_rows:
        head_index[_vuln_key(row)].append(row)
    all_keys = sorted(set(base_index) | set(head_index))
    rows: list[VulnerabilityObservation] = []
    indeterminate_reasons: list[str] = []
    for key in all_keys:
        b_list = base_index.get(key, [])
        h_list = head_index.get(key, [])
        b = b_list[0] if b_list else None
        h = h_list[0] if h_list else None
        if b and not h:
            ecosystem = b.ecosystem
            provider_state = head_provider_state.get(
                _provider_name_for_ecosystem(ecosystem), "not_requested"
            )
            if provider_state in _INDETERMINATE_HEAD_PROVIDER_STATES:
                state = "comparison_indeterminate"
                reason = (
                    "head provider state for "
                    f"{b.advisory_source or 'unknown'} was {provider_state}; "
                    "the comparison cannot determine whether the advisory still applies"
                )
                indeterminate_reasons.append(reason)
            else:
                state = "no_longer_observed"
                reason = None
            rows.append(
                VulnerabilityObservation(
                    component_id_base=b.component_id,
                    component_id_head=None,
                    ecosystem=ecosystem,
                    package_name=b.package_name,
                    package_version_base=b.package_version,
                    package_version_head=None,
                    advisory_source=b.advisory_source,
                    advisory_external_id=b.advisory_external_id,
                    advisory_canonical_id=b.advisory_canonical_id,
                    severity_label_base=b.severity_label,
                    severity_score_base=b.severity_score,
                    severity_label_head=None,
                    severity_score_head=None,
                    state=state,
                    provider_provenance_base=b.advisory_source,
                    provider_provenance_head=None,
                    fetched_at_base=b.fetched_at,
                    fetched_at_head=None,
                    ambiguity_reason=reason,
                )
            )
            continue
        if h and not b:
            ecosystem = h.ecosystem
            base_state = base_provider_state.get(
                _provider_name_for_ecosystem(ecosystem), "not_requested"
            )
            # A newly observed vulnerability in the head is
            # reported as ``newly_observed`` even when the
            # base had no provider data; the comparator does
            # not call it "newly introduced" because we
            # cannot know whether the base was simply
            # missing the data.
            if base_state in _INDETERMINATE_HEAD_PROVIDER_STATES:
                state = "comparison_indeterminate"
                reason = (
                    "base provider state for "
                    f"{h.advisory_source or 'unknown'} was {base_state}; "
                    "the head observation may be a coverage change rather than a new finding"
                )
                indeterminate_reasons.append(reason)
            else:
                state = "newly_observed"
                reason = None
            rows.append(
                VulnerabilityObservation(
                    component_id_base=None,
                    component_id_head=h.component_id,
                    ecosystem=ecosystem,
                    package_name=h.package_name,
                    package_version_base=None,
                    package_version_head=h.package_version,
                    advisory_source=h.advisory_source,
                    advisory_external_id=h.advisory_external_id,
                    advisory_canonical_id=h.advisory_canonical_id,
                    severity_label_base=None,
                    severity_score_base=None,
                    severity_label_head=h.severity_label,
                    severity_score_head=h.severity_score,
                    state=state,
                    provider_provenance_base=None,
                    provider_provenance_head=h.advisory_source,
                    fetched_at_base=None,
                    fetched_at_head=h.fetched_at,
                    ambiguity_reason=reason,
                )
            )
            continue
        if (
            b
            and h
            and (b.severity_label != h.severity_label or b.severity_score != h.severity_score)
        ):
            state = "changed_observation"
        else:
            state = "still_observed"
        rows.append(
            VulnerabilityObservation(
                component_id_base=b.component_id,
                component_id_head=h.component_id,
                ecosystem=(b or h).ecosystem,
                package_name=(b or h).package_name,
                package_version_base=b.package_version,
                package_version_head=h.package_version,
                advisory_source=(b or h).advisory_source,
                advisory_external_id=(b or h).advisory_external_id,
                advisory_canonical_id=(b or h).advisory_canonical_id,
                severity_label_base=b.severity_label,
                severity_score_base=b.severity_score,
                severity_label_head=h.severity_label,
                severity_score_head=h.severity_score,
                state=state,
                provider_provenance_base=b.advisory_source,
                provider_provenance_head=h.advisory_source,
                fetched_at_base=b.fetched_at,
                fetched_at_head=h.fetched_at,
                ambiguity_reason=None,
            )
        )
    return rows, indeterminate_reasons


class _VulnRow:
    """In-memory join of ``ComponentAdvisory`` + ``Component`` + ``Advisory``."""

    __slots__ = (
        "advisory_canonical_id",
        "advisory_external_id",
        "advisory_source",
        "component_id",
        "ecosystem",
        "fetched_at",
        "package_name",
        "package_version",
        "severity_label",
        "severity_score",
    )

    def __init__(
        self,
        *,
        component_id: int,
        ecosystem: str | None,
        package_name: str | None,
        package_version: str | None,
        advisory_source: str | None,
        advisory_external_id: str | None,
        advisory_canonical_id: str | None,
        severity_label: str | None,
        severity_score: float | None,
        fetched_at: str | None,
    ) -> None:
        self.component_id = component_id
        self.ecosystem = ecosystem
        self.package_name = package_name
        self.package_version = package_version
        self.advisory_source = advisory_source
        self.advisory_external_id = advisory_external_id
        self.advisory_canonical_id = advisory_canonical_id
        self.severity_label = severity_label
        self.severity_score = severity_score
        self.fetched_at = fetched_at


def _component_advisories_with_joins(session: Session, scan_id: int) -> list[_VulnRow]:
    rows = session.execute(
        select(ComponentAdvisory, Component, Advisory)
        .join(Component, Component.id == ComponentAdvisory.component_id)
        .join(Advisory, Advisory.id == ComponentAdvisory.advisory_id)
        .where(ComponentAdvisory.scan_run_id == scan_id)
    ).all()
    out: list[_VulnRow] = []
    for ca, component, advisory in rows:
        evidence = _parse_evidence(ca.evidence_json)
        fetched_at = None
        if evidence is not None:
            value = evidence.get("fetched_at")
            if isinstance(value, str):
                fetched_at = value
        out.append(
            _VulnRow(
                component_id=ca.component_id,
                ecosystem=component.ecosystem,
                package_name=component.package_name,
                package_version=component.version,
                advisory_source=advisory.source,
                advisory_external_id=advisory.source_advisory_id,
                advisory_canonical_id=advisory.canonical_id,
                severity_label=ca.severity_label,
                severity_score=ca.severity_score,
                fetched_at=fetched_at,
            )
        )
    return out


def _component_advisories(session: Session, scan_id: int) -> list[int]:
    rows = session.execute(
        select(ComponentAdvisory.id).where(ComponentAdvisory.scan_run_id == scan_id)
    ).all()
    return [row[0] for row in rows]


def _vuln_key(row: _VulnRow) -> tuple[str | None, str | None, str, str]:
    """Cross-scan join key for vulnerability observations.

    The key is ``(ecosystem, package_version, advisory_source,
    advisory_canonical_id or source_advisory_id)``. We never
    join on the database id (which is per-scan) and never on
    the package name alone (which is not unique across
    versions).
    """
    canonical = row.advisory_canonical_id or row.advisory_external_id or ""
    return (
        row.ecosystem,
        row.package_version,
        row.advisory_source or "",
        canonical,
    )


def _parse_evidence(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _provider_name_for_ecosystem(ecosystem: str | None) -> str:
    # The v0.4 product uses OSV as the canonical vulnerability
    # provider. The ecosystem string is informational; the
    # provider name is the value that the provider_observations
    # table uses.
    return "osv"


# ---------------------------------------------------------------------------
# Licence comparison
# ---------------------------------------------------------------------------


def _compare_licences(session: Session, base_id: int, head_id: int) -> list[LicenceObservation]:
    """Compare licence assertions between two scans.

    A licence assertion is keyed on
    ``(package_name, version, licence, provider)``. The
    comparator preserves the rule-engine ``provider`` and any
    deps.dev attribution separately so the operator can see
    the upstream identity.
    """
    base_index = _licence_index(session, base_id)
    head_index = _licence_index(session, head_id)
    all_keys = sorted(set(base_index) | set(head_index))
    rows: list[LicenceObservation] = []
    for key in all_keys:
        b = base_index.get(key)
        h = head_index.get(key)
        if b and not h:
            state = "no_longer_observed"
        elif h and not b:
            state = "newly_observed"
        elif b and h and (b["licence"] != h["licence"] or b["provider"] != h["provider"]):
            state = "changed_observation"
        else:
            state = "still_observed"
        rows.append(
            LicenceObservation(
                ecosystem=(b or h)["ecosystem"] if (b or h) else None,
                package_name=(b or h)["package_name"] if (b or h) else key[0],
                package_version_base=b["version"] if b else None,
                package_version_head=h["version"] if h else None,
                licence_base=b["licence"] if b else None,
                licence_head=h["licence"] if h else None,
                provider_base=b["provider"] if b else None,
                provider_head=h["provider"] if h else None,
                review_status_base=b["review_status"] if b else None,
                review_status_head=h["review_status"] if h else None,
                state=state,
            )
        )
    return rows


def _licence_index(
    session: Session, scan_id: int
) -> dict[tuple[str, str | None, str, str], dict[str, Any]]:
    findings = _findings_by_category(session, scan_id, FindingCategory.LICENCE)
    components_by_id = _components_by_id(session, scan_id)
    out: dict[tuple[str, str | None, str, str], dict[str, Any]] = {}
    for finding in findings:
        evidence = _parse_evidence(finding.evidence_json) or {}
        evidence_inner = (
            evidence.get("evidence") if isinstance(evidence.get("evidence"), dict) else {}
        )
        package_name = evidence_inner.get("package_name") or _component_package_name(
            finding, components_by_id
        )
        version = evidence_inner.get("version") or _component_version(finding, components_by_id)
        licences = evidence_inner.get("licences") or []
        licence_value = (
            ", ".join(licences) if isinstance(licences, list) and licences else "unknown"
        )
        provider = "rule_engine"
        review_status = _licence_review_status(finding)
        if not package_name:
            continue
        key = (package_name, version, licence_value, provider)
        out[key] = {
            "package_name": package_name,
            "version": version,
            "licence": licence_value,
            "provider": provider,
            "review_status": review_status,
            "ecosystem": _component_ecosystem(finding, components_by_id),
        }
    return out


def _components_by_id(session: Session, scan_id: int) -> dict[int, Component]:
    rows = (
        session.execute(select(Component).where(Component.scan_run_id == scan_id)).scalars().all()
    )
    return {row.id: row for row in rows}


def _component_package_name(finding: Finding, components_by_id: dict[int, Component]) -> str | None:
    evidence = _parse_evidence(finding.evidence_json) or {}
    evidence_inner = evidence.get("evidence") if isinstance(evidence.get("evidence"), dict) else {}
    candidate = evidence_inner.get("package_name")
    if isinstance(candidate, str):
        return candidate
    return finding.title or None


def _component_version(finding: Finding, components_by_id: dict[int, Component]) -> str | None:
    evidence = _parse_evidence(finding.evidence_json) or {}
    evidence_inner = evidence.get("evidence") if isinstance(evidence.get("evidence"), dict) else {}
    candidate = evidence_inner.get("version")
    if isinstance(candidate, str):
        return candidate
    return None


def _component_ecosystem(finding: Finding, components_by_id: dict[int, Component]) -> str | None:
    return None


def _licence_review_status(finding: Finding) -> str:
    rule_id = finding.rule_id or ""
    if rule_id == "LOCK-LIC-003":
        return "review_required"
    if rule_id == "LOCK-LIC-INV":
        return "approved"
    if rule_id in {"LOCK-LIC-001", "LOCK-LIC-002", "LOCK-LIC-004"}:
        return "unreviewed"
    return "unknown"


# ---------------------------------------------------------------------------
# OpenSSF comparison
# ---------------------------------------------------------------------------


def _compare_openssf(session: Session, base_id: int, head_id: int) -> list[OpenSSFObservation]:
    base_rows = _findings_by_category(session, base_id, FindingCategory.REPOSITORY_POSTURE)
    head_rows = _findings_by_category(session, head_id, FindingCategory.REPOSITORY_POSTURE)
    base_index = {row.rule_id: row for row in base_rows}
    head_index = {row.rule_id: row for row in head_rows}
    all_keys = sorted(set(base_index) | set(head_index))
    rows: list[OpenSSFObservation] = []
    for key in all_keys:
        b = base_index.get(key)
        h = head_index.get(key)
        if b and not h:
            state = "no_longer_observed"
        elif h and not b:
            state = "newly_observed"
        elif b and h and (b.severity != h.severity):
            state = "changed_observation"
        else:
            state = "still_observed"
        score_b = _score_from_severity(b.severity) if b else None
        score_h = _score_from_severity(h.severity) if h else None
        rows.append(
            OpenSSFObservation(
                check_id=key,
                name=(h or b).title if (h or b) else key,
                score_base=score_b,
                score_head=score_h,
                reason_base=b.summary if b else None,
                reason_head=h.summary if h else None,
                details_url=None,
                source="rule_engine",
                state=state,
            )
        )
    return rows


def _score_from_severity(severity: FindingSeverity | None) -> int | None:
    if severity is None:
        return None
    if not hasattr(severity, "value"):
        return None
    return {
        FindingSeverity.INFORMATIONAL: 10,
        FindingSeverity.LOW: 7,
        FindingSeverity.MEDIUM: 5,
        FindingSeverity.HIGH: 3,
        FindingSeverity.CRITICAL: 1,
    }.get(severity)


# ---------------------------------------------------------------------------
# Provider coverage comparison
# ---------------------------------------------------------------------------


def _compare_providers(
    session: Session, base_id: int, head_id: int
) -> tuple[list[ProviderCoverage], list[str]]:
    base_obs = _provider_obs_by_provider(session, base_id)
    head_obs = _provider_obs_by_provider(session, head_id)
    all_providers = sorted(set(base_obs) | set(head_obs))
    rows: list[ProviderCoverage] = []
    indeterminate_reasons: list[str] = []
    for provider in all_providers:
        b = base_obs.get(provider)
        h = head_obs.get(provider)
        state_b = _normalise_provider_state(b)
        state_h = _normalise_provider_state(h)
        # The cross-scan state. A change in any of state /
        # last_completed_at / records_returned is reported as
        # ``coverage_changed``; an unchanged successful
        # pair is ``still_observed``. The ``cache_status``
        # column carries the v0.4 freshness signal and is
        # surfaced verbatim on the row so the operator can
        # see what the underlying record said.
        if (
            state_b == state_h
            and (b is None) == (h is None)
            and (b is None or _same_provider_record(b, h))
        ):
            row_state = "still_observed"
        else:
            row_state = "coverage_changed"
        if state_h in _INDETERMINATE_HEAD_PROVIDER_STATES:
            cache_label = (
                f" (cache_status={h.cache_status!r})" if h is not None and h.cache_status else ""
            )
            indeterminate_reasons.append(
                f"head provider {provider!r} state is {state_h}{cache_label}"
            )
        rows.append(
            ProviderCoverage(
                provider=provider,
                state_base=state_b,
                state_head=state_h,
                last_completed_at_base=b.completed_at if b else None,
                last_completed_at_head=h.completed_at if h else None,
                records_returned_base=b.records_returned if b else None,
                records_returned_head=h.records_returned if h else None,
                cache_status_base=b.cache_status if b else None,
                cache_status_head=h.cache_status if h else None,
                error_code_base=b.error_code if b else None,
                error_summary_base=b.error_summary if b else None,
                error_code_head=h.error_code if h else None,
                error_summary_head=h.error_summary if h else None,
                evidence_present_base=bool(b is not None and b.evidence_json),
                evidence_present_head=bool(h is not None and h.evidence_json),
                state=row_state,
            )
        )
    return rows, sorted(set(indeterminate_reasons))


def _same_provider_record(a: ProviderObservation, b: ProviderObservation) -> bool:
    return (
        a.completed_at == b.completed_at
        and a.records_returned == b.records_returned
        and a.cache_status == b.cache_status
        and a.error_code == b.error_code
    )


def _provider_obs_by_provider(session: Session, scan_id: int) -> dict[str, ProviderObservation]:
    """Return the most recent observation per provider for a scan.

    The comparator surfaces the *latest* observation per
    provider because the per-call records are an audit trail,
    not a state machine; the state we want to compare is
    "what was the last thing this provider did for the
    scan?".
    """
    rows = (
        session.execute(
            select(ProviderObservation)
            .where(ProviderObservation.scan_run_id == scan_id)
            .order_by(ProviderObservation.id.asc())
        )
        .scalars()
        .all()
    )
    by_id: dict[str, ProviderObservation] = {}
    for row in rows:
        existing = by_id.get(row.provider)
        if (
            existing is None
            or (row.completed_at or datetime.min.replace(tzinfo=UTC))
            > (existing.completed_at or datetime.min.replace(tzinfo=UTC))
            or row.id > existing.id
        ):
            by_id[row.provider] = row
    return by_id


def _normalise_provider_state(
    observation: ProviderObservation | None,
) -> ProviderStateName:
    """Map a v0.4 ``ProviderStatus`` to the v0.5 vocabulary.

    The mapping is a one-to-one rename of the v0.4 enum
    values; the comparator does not invent a "stale" state
    out of wall-clock age. The persisted ``cache_status``
    column carries the authoritative freshness signal and is
    surfaced separately on the response so the operator can
    audit what the underlying record said.
    """
    if observation is None:
        return "not_requested"
    raw = observation.status
    name: str = str(raw.value) if hasattr(raw, "value") else str(raw)
    if name == ProviderStatus.AVAILABLE.value:
        return "successful"
    if name == ProviderStatus.CACHED.value:
        return "cached"
    if name == ProviderStatus.PARTIAL.value:
        return "partial"
    if name == ProviderStatus.RATE_LIMITED.value:
        return "partial"
    if name == ProviderStatus.UNAVAILABLE.value:
        return "unavailable"
    if name == ProviderStatus.NOT_REQUESTED.value:
        return "not_requested"
    if name == ProviderStatus.UNKNOWN.value:
        return "unknown"
    return "unknown"


def _provider_state_by_name(session: Session, scan_id: int) -> dict[str, ProviderStateName]:
    obs = _provider_obs_by_provider(session, scan_id)
    return {provider: _normalise_provider_state(o) for provider, o in obs.items()}


def _scan_completed_at(session: Session, scan_id: int) -> datetime | None:
    row = session.get(ScanRun, scan_id)
    if row is None:
        return None
    return row.completed_at


# ---------------------------------------------------------------------------
# Coverage summary
# ---------------------------------------------------------------------------


def _coverage_summary(
    *,
    base: ScanRun,
    head: ScanRun,
    components_base: int,
    components_head: int,
    findings_base: int,
    findings_head: int,
    vulnerabilities_base: int,
    vulnerabilities_head: int,
    workflows_base: int,
    workflows_head: int,
    manifests_base: int,
    manifests_head: int,
    licence_assertions_base: int,
    licence_assertions_head: int,
    openssf_checks_in_base: int,
    openssf_checks_in_head: int,
    providers: list[ProviderCoverage],
) -> CoverageSummary:
    changed = sum(1 for row in providers if row.state == "coverage_changed")
    indeterminate = sum(
        1 for row in providers if row.state_head in _INDETERMINATE_HEAD_PROVIDER_STATES
    )
    return CoverageSummary(
        base_scan_status=base.status.value if hasattr(base.status, "value") else str(base.status),
        head_scan_status=head.status.value if hasattr(head.status, "value") else str(head.status),
        components_in_base=components_base,
        components_in_head=components_head,
        findings_in_base=findings_base,
        findings_in_head=findings_head,
        vulnerabilities_in_base=vulnerabilities_base,
        vulnerabilities_in_head=vulnerabilities_head,
        workflows_in_base=workflows_base,
        workflows_in_head=workflows_head,
        manifests_in_base=manifests_base,
        manifests_in_head=manifests_head,
        licence_assertions_in_base=licence_assertions_base,
        licence_assertions_in_head=licence_assertions_head,
        openssf_checks_in_base=openssf_checks_in_base,
        openssf_checks_in_head=openssf_checks_in_head,
        providers_with_changed_state=changed,
        providers_with_indeterminate_head=indeterminate,
    )


def _present_in_scan(row: ComponentObservation, side: str) -> bool:
    # A row is "present" in a side when the per-side
    # ``direct_*`` flag is set. Every row carries a
    # ``version``; the per-side presence signal is the
    # direct/transitive scope.
    if side == "base":
        return row.direct_base is not None
    return row.direct_head is not None


def _count_in_scan(rows: Iterable[Finding]) -> int:
    return sum(1 for _ in rows)


def _findings_by_category(
    session: Session, scan_id: int, category: FindingCategory
) -> list[Finding]:
    return list(
        session.execute(
            select(Finding).where(
                Finding.scan_run_id == scan_id,
                Finding.category == category,
            )
        ).scalars()
    )


__all__ = ["compare_scans"]
