"""v0.5 evidence-aware scan comparison schemas.

A *scan comparison* is a read-only, deterministic diff of two
terminal scans that belong to the same repository/workspace. It
never claims that software became secure, that a vulnerability was
fixed, or that a repository is clean. The state vocabulary is
narrow and explicit:

    newly_observed           - present in the head scan only
    still_observed           - present in both scans with no material change
    no_longer_observed       - present in the base scan only
    changed_observation      - present in both scans with a material change
    coverage_changed         - the provider/state changed, content uncertain
    comparison_indeterminate - one or both scans are missing the data
                              needed to make a determination

Successful provider evidence is never placed in ``error_summary``,
and a missing provider row is never interpreted as a clean bill of
health. Where a row is missing or degraded, the comparison is
explicitly indeterminate for the affected domain.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import SchemaModel

# ---------------------------------------------------------------------------
# State vocabulary (public API surface area)
# ---------------------------------------------------------------------------

ObservationState = Literal[
    "newly_observed",
    "still_observed",
    "no_longer_observed",
    "changed_observation",
    "coverage_changed",
    "comparison_indeterminate",
]

# These labels are the only words we use to describe a single row's
# outcome in the comparison. They are *not* conclusions about the
# software's security posture; the response shape also surfaces
# provenance and freshness so the operator can interpret them.
OBSERVATION_STATE_LABELS: dict[str, str] = {
    "newly_observed": "Newly observed",
    "still_observed": "Still observed",
    "no_longer_observed": "No longer observed",
    "changed_observation": "Changed observation",
    "coverage_changed": "Coverage changed",
    "comparison_indeterminate": "Comparison indeterminate",
}

# Provider state vocabulary (per-call availability). The values
# match :class:`app.models.provider_observation.ProviderStatus`
# and the typed-status list returned by the read API.
ProviderStateName = Literal[
    "successful",
    "cached",
    "stale",
    "partial",
    "unavailable",
    "unsupported",
    "not_requested",
    "unknown",
]

# Terminal scan statuses that are eligible for comparison.
# ``completed`` and ``partial`` both have meaningful persisted
# local-analysis evidence (a partial scan finished most or
# all of its stages and recorded what it could). ``failed``
# and ``cancelled`` did not; their persisted evidence is
# untrustworthy and a comparison built on it would risk
# misleading "no differences observed" verdicts. The
# comparator therefore rejects those two states with a
# bounded error and asks the operator to wait for a scan
# that finished the work. Provider degradation alone
# (e.g. a scan finished ``completed`` but with OSV
# unavailable) does **not** invalidate the comparison - the
# comparator surfaces the affected domains as
# ``comparison_indeterminate`` so the operator can still
# trust the rest of the diff.
ELIGIBLE_SCAN_STATUSES: tuple[str, ...] = (
    "completed",
    "partial",
)


# ---------------------------------------------------------------------------
# Local / rule-engine observation rows
# ---------------------------------------------------------------------------


class ComponentObservation(SchemaModel):
    """A single ``(ecosystem, package_name, version)`` observation.

    The concrete version is part of the component identity.
    The comparator therefore emits one row per
    ``(ecosystem, package_name, version)`` it observes on
    either side. Where the *same package* appears with
    several versions in either scan (across manifests or as
    multiple dependency instances), each version gets its
    own row. The comparator never collapses a multi-version
    package into a single ``comparison_indeterminate`` row;
    such a row is reserved for cases where the data is
    genuinely insufficient.
    """

    # Stable identity: ecosystem + package name + concrete
    # version. ``version=None`` means the component was
    # observed without a resolved version in that scan; the
    # comparator never fabricates a transition out of a
    # missing version - it emits a row for the unresolved
    # identity instead.
    ecosystem: str | None
    package_name: str
    version: str | None
    # ``manifest_paths`` is the sorted list of manifests the
    # observation was sourced from. It is preserved so the
    # operator can audit exactly which files contributed
    # to the row.
    manifest_paths: list[str] = Field(default_factory=list)
    direct_base: bool | None = None
    direct_head: bool | None = None
    state: ObservationState


class ManifestObservation(SchemaModel):
    """A single manifest's presence/absence in the comparison."""

    manifest_path: str
    manifest_type: str | None = None
    ecosystem: str | None = None
    parse_status_base: str | None = None
    parse_status_head: str | None = None
    content_sha256_base: str | None = None
    content_sha256_head: str | None = None
    state: ObservationState


class DependencyPathChange(SchemaModel):
    """A change in a component's parent chain between scans.

    The comparator only emits this row when a component's
    *identity* (ecosystem, package_name, version) is unchanged
    and a path difference is detected. A change in identity
    belongs on a ``ComponentObservation`` row instead.
    """

    ecosystem: str | None
    package_name: str
    version: str | None
    parent_chain_base: list[str] = Field(default_factory=list)
    parent_chain_head: list[str] = Field(default_factory=list)
    state: ObservationState


class WorkflowObservation(SchemaModel):
    """A workflow (GitHub Actions) rule observation in the comparison.

    The comparator deduplicates on ``stable_key`` (the rule
    engine's deterministic per-row key). Severity and confidence
    can change between scans; the comparator only marks the row
    as ``changed_observation`` when one or both dimensions
    changed material-ly. The base/head severity and confidence
    are preserved so the UI never has to guess which way they
    moved.
    """

    rule_id: str
    workflow_path: str
    title: str
    severity_base: str | None = None
    severity_head: str | None = None
    confidence_base: str | None = None
    confidence_head: str | None = None
    stable_key: str
    state: ObservationState


class VulnerabilityObservation(SchemaModel):
    """A component x advisory row in the comparison.

    The comparator is keyed on the (component_id, advisory_id)
    pair *within* each scan. The cross-scan pairing is by
    (ecosystem, package_name, version, advisory_canonical_id
    or source_advisory_id). When the same component matches a
    different advisory on each side, the comparator reports
    them as distinct rows.

    A vulnerability absent from the head scan is reported as
    ``no_longer_observed``; the comparator never claims the
    advisory was resolved. If the head scan's provider
    coverage for the affected ecosystem was unavailable /
    partial / stale, the comparator marks the row
    ``comparison_indeterminate`` instead of ``no_longer_observed``
    so a degraded provider cannot be misread as a fix.
    """

    component_id_base: int | None = None
    component_id_head: int | None = None
    ecosystem: str | None = None
    package_name: str | None = None
    package_version_base: str | None = None
    package_version_head: str | None = None
    advisory_source: str | None = None
    advisory_external_id: str | None = None
    advisory_canonical_id: str | None = None
    severity_label_base: str | None = None
    severity_score_base: float | None = None
    severity_label_head: str | None = None
    severity_score_head: float | None = None
    state: ObservationState
    # Provenance is preserved as the upstream provider name.
    # ``null`` means the row was synthesized by a rule engine
    # and the comparator will not pretend otherwise.
    provider_provenance_base: str | None = None
    provider_provenance_head: str | None = None
    # Coverage / freshness timestamps for the underlying
    # provider call, when available.
    fetched_at_base: str | None = None
    fetched_at_head: str | None = None
    # When ``state`` is ``comparison_indeterminate`` because
    # provider coverage was insufficient, this short string
    # explains why. Examples: "head provider unavailable",
    # "head provider stale".
    ambiguity_reason: str | None = None


class LicenceObservation(SchemaModel):
    """A licence assertion observation in the comparison.

    A licence assertion is a (component_id, licence, provider)
    triple. The comparator surfaces a row per such triple so
    the operator can see whether the same component is reported
    under a different licence, or by a different provider,
    between scans.
    """

    ecosystem: str | None = None
    package_name: str | None = None
    package_version_base: str | None = None
    package_version_head: str | None = None
    licence_base: str | None = None
    licence_head: str | None = None
    provider_base: str | None = None
    provider_head: str | None = None
    review_status_base: str | None = None
    review_status_head: str | None = None
    state: ObservationState


class OpenSSFObservation(SchemaModel):
    """An OpenSSF Scorecard / posture check observation.

    A posture check is keyed on ``check_id`` (a stable string
    like ``Binary-Artifacts``). The comparator surfaces the
    base and head scores; a missing score is preserved as
    ``None`` and never converted into a Lockverity score.
    """

    check_id: str
    name: str
    score_base: int | None = None
    score_head: int | None = None
    reason_base: str | None = None
    reason_head: str | None = None
    details_url: str | None = None
    source: str
    state: ObservationState


# ---------------------------------------------------------------------------
# Provider coverage rows
# ---------------------------------------------------------------------------


class ProviderCoverage(SchemaModel):
    """Per-provider availability and freshness for a scan.

    The ``state_base`` / ``state_head`` values are the
    normalized provider states. A successful provider that
    finished its last call long before the scan is marked
    ``stale``. A provider that returned a partial response
    (some components, but not all) is marked ``partial``. A
    provider that was never queried for the scan is marked
    ``not_requested``. A provider the system does not
    understand is marked ``unsupported``.
    """

    provider: str
    state_base: ProviderStateName
    state_head: ProviderStateName
    last_completed_at_base: datetime | None = None
    last_completed_at_head: datetime | None = None
    records_returned_base: int | None = None
    records_returned_head: int | None = None
    cache_status_base: str | None = None
    cache_status_head: str | None = None
    error_code_base: str | None = None
    error_summary_base: str | None = None
    error_code_head: str | None = None
    error_summary_head: str | None = None
    # True iff the underlying provider call returned a
    # successful structured evidence envelope. The frontend
    # uses this to qualify "no differences observed" so the
    # operator knows the comparison is bounded by the data
    # the provider actually returned, not by an empty diff.
    evidence_present_base: bool = False
    evidence_present_head: bool = False
    state: ObservationState


# ---------------------------------------------------------------------------
# Coverage and provenance summary
# ---------------------------------------------------------------------------


class CoverageSummary(SchemaModel):
    """Honest evidence-coverage summary for the comparison.

    Every field is a count, not a verdict. The frontend shows
    this block prominently so the operator knows what the
    comparison is bounded by.
    """

    base_scan_status: str
    head_scan_status: str
    components_in_base: int
    components_in_head: int
    findings_in_base: int
    findings_in_head: int
    vulnerabilities_in_base: int
    vulnerabilities_in_head: int
    workflows_in_base: int
    workflows_in_head: int
    manifests_in_base: int
    manifests_in_head: int
    licence_assertions_in_base: int
    licence_assertions_in_head: int
    openssf_checks_in_base: int
    openssf_checks_in_head: int
    # The number of providers whose state changed between
    # the two scans. A non-zero value does *not* mean data
    # was lost; it means the availability or freshness
    # signal changed.
    providers_with_changed_state: int
    # The number of providers whose head state is
    # unavailable / partial / stale / unsupported. The
    # comparison for those providers is indeterminate.
    providers_with_indeterminate_head: int


# ---------------------------------------------------------------------------
# The top-level comparison response
# ---------------------------------------------------------------------------


class ScanComparisonResponse(SchemaModel):
    """Read-only, deterministic comparison of two scans.

    The response is shaped for the v0.5 frontend: each
    domain has its own typed list of observations, all
    deterministically ordered. The endpoint is bounded:
    it never triggers a rescan, never downloads a
    repository, never extracts an archive, never calls an
    external provider, never writes to the database, and
    never executes repository code.
    """

    base_scan_id: int
    head_scan_id: int
    repository_id: int
    base_trigger_type: str | None = None
    head_trigger_type: str | None = None
    base_resolved_commit_sha: str | None = None
    head_resolved_commit_sha: str | None = None
    base_analyzer_version: str | None = None
    head_analyzer_version: str | None = None
    base_completed_at: datetime | None = None
    head_completed_at: datetime | None = None
    generated_at: datetime
    coverage: CoverageSummary
    components: list[ComponentObservation]
    manifests: list[ManifestObservation]
    dependency_paths: list[DependencyPathChange]
    workflows: list[WorkflowObservation]
    vulnerabilities: list[VulnerabilityObservation]
    licences: list[LicenceObservation]
    openssf: list[OpenSSFObservation]
    providers: list[ProviderCoverage]
    # A list of human-readable explanations for rows that
    # were reported as ``comparison_indeterminate`` because
    # the underlying evidence was insufficient. The frontend
    # surfaces these in the prominent "evidence-coverage
    # and provenance" summary. The list is deterministically
    # sorted.
    indeterminate_reasons: list[str]


__all__ = [
    "ELIGIBLE_SCAN_STATUSES",
    "OBSERVATION_STATE_LABELS",
    "ComponentObservation",
    "CoverageSummary",
    "DependencyPathChange",
    "LicenceObservation",
    "ManifestObservation",
    "ObservationState",
    "OpenSSFObservation",
    "ProviderCoverage",
    "ProviderStateName",
    "ScanComparisonResponse",
    "VulnerabilityObservation",
    "WorkflowObservation",
]
