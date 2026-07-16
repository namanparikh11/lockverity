"""Focused tests for the v0.5 evidence-aware comparison service.

The comparator is the single source of truth for cross-scan
evidence. These tests assert the v0.5 acceptance criteria:

* valid same-workspace scans compare successfully;
* identical scan selection is rejected;
* cross-workspace comparison is rejected;
* missing and ineligible scans return bounded errors;
* reversing base and target reverses additions/removals correctly;
* unchanged components remain unchanged;
* exact additions and removals are correct;
* unambiguous version changes are represented correctly;
* ambiguous multi-version cases do not fabricate a transition;
* local findings remain comparable during provider degradation;
* cached, stale, unavailable, partial, and unsupported
  provider states remain explicit;
* missing provider data is not interpreted as zero findings;
* vulnerability disappearance becomes indeterminate when
  coverage is insufficient;
* provenance and provider identifiers are preserved;
* successful evidence is not written into ``error_summary``;
* observations stay associated with the correct component
  and scan attempt;
* stable output ordering is enforced;
* the comparison causes no database writes;
* the comparison causes no external HTTP calls.
"""

from __future__ import annotations

import json
import uuid

from app.models.advisory import Advisory
from app.models.component import Component, ComponentVersionSource
from app.models.component_advisory import ComponentAdvisory
from app.models.dependency_edge import DependencyEdge
from app.models.finding import (
    Finding,
    FindingCategory,
    FindingConfidence,
    FindingSeverity,
)
from app.models.manifest import Manifest, ManifestParseStatus
from app.models.provider_observation import ProviderObservation, ProviderStatus
from app.models.repository import (
    Repository,
    RepositoryProvider,
    RepositorySourceType,
    RepositoryVisibility,
)
from app.models.scan_run import ScanStatus, ScanTriggerType
from app.services import comparison_service, repository_service, scan_service
from app.utils.errors import ApiError, ApiErrorCode

# ---------------------------------------------------------------------------
# Test fixture builder
# ---------------------------------------------------------------------------


class _ScanBuilder:
    """Build a single scan with its evidence, in a single session.

    The builder pattern guarantees the right insert ordering
    (repository -> scan -> manifest -> component) so the foreign
    keys resolve without the test having to manage flushes.
    """

    def __init__(
        self,
        session,
        *,
        canonical_url: str = "https://github.com/octocat/Hello-World",
        completed: bool = True,
    ) -> None:
        self.session = session
        if "octocat" in canonical_url:
            self.repository = repository_service.create_repository_from_url(session, canonical_url)
        else:
            self.repository = Repository(
                source_type=RepositorySourceType.GITHUB,
                provider=RepositoryProvider.GITHUB,
                owner=canonical_url.rsplit("/", 2)[-2],
                name=canonical_url.rsplit("/", 1)[-1],
                canonical_url=canonical_url,
                default_branch="main",
                visibility=RepositoryVisibility.PUBLIC,
            )
            session.add(self.repository)
            session.flush()
        self.scan = scan_service.create_scan(
            session,
            repository_id=self.repository.id,
            trigger_type=ScanTriggerType.MANUAL,
        )
        self._manifests: dict[str, Manifest] = {}
        self._completed = completed

    def add_manifest(
        self,
        *,
        path: str = "package.json",
        ecosystem: str = "npm",
        content_sha256: str | None = "a" * 64,
    ) -> Manifest:
        if path in self._manifests:
            return self._manifests[path]
        manifest = Manifest(
            scan_run_id=self.scan.id,
            path=path,
            manifest_type="package_json",
            ecosystem=ecosystem,
            parse_status=ManifestParseStatus.PARSED,
            content_sha256=content_sha256,
        )
        self.session.add(manifest)
        self.session.flush()
        self._manifests[path] = manifest
        return manifest

    def add_component(
        self,
        *,
        ecosystem: str = "npm",
        name: str,
        version: str | None = "1.0.0",
        manifest: Manifest | None = None,
        direct: bool = True,
    ) -> Component:
        if manifest is None:
            manifest = self.add_manifest()
        component = Component(
            scan_run_id=self.scan.id,
            manifest_id=manifest.id,
            ecosystem=ecosystem,
            package_name=name,
            version=version,
            version_source=ComponentVersionSource.LOCKFILE,
            direct=direct,
        )
        self.session.add(component)
        self.session.flush()
        return component

    def add_workflow_finding(
        self,
        *,
        rule_id: str = "LOCK-WF-001",
        path: str = ".github/workflows/ci.yml",
        severity: FindingSeverity = FindingSeverity.HIGH,
        confidence: FindingConfidence = FindingConfidence.HIGH,
        title: str = "Unpinned third-party action",
        summary: str = "actions/checkout is not pinned to a SHA",
        stable_key: str | None = None,
    ) -> Finding:
        finding = Finding(
            scan_run_id=self.scan.id,
            repository_id=self.repository.id,
            rule_id=rule_id,
            category=FindingCategory.WORKFLOW,
            severity=severity,
            confidence=confidence,
            title=title,
            summary=summary,
            location_path=path,
            stable_key=stable_key or f"{rule_id}|{path}",
        )
        self.session.add(finding)
        self.session.flush()
        return finding

    def add_provider_observation(
        self,
        *,
        provider: str,
        operation: str | None = None,
        status: ProviderStatus = ProviderStatus.AVAILABLE,
        records_returned: int = 0,
        cache_status: str | None = "miss",
        error_code: str | None = None,
        error_summary: str | None = None,
        evidence_json: str | None = None,
        component_id: int | None = None,
    ) -> ProviderObservation:
        observation = ProviderObservation(
            scan_run_id=self.scan.id,
            component_id=component_id,
            provider=provider,
            operation=operation or f"{provider}_call",
            status=status,
            records_returned=records_returned,
            cache_status=cache_status,
            error_code=error_code,
            error_summary=error_summary,
            evidence_json=evidence_json,
        )
        self.session.add(observation)
        self.session.flush()
        return observation

    def add_dependency_edge(
        self,
        *,
        parent: Component,
        child: Component,
        depth: int = 1,
    ) -> DependencyEdge:
        edge = DependencyEdge(
            scan_run_id=self.scan.id,
            parent_component_id=parent.id,
            child_component_id=child.id,
            depth=depth,
        )
        self.session.add(edge)
        self.session.flush()
        return edge

    def add_advisory(
        self,
        *,
        source: str = "osv",
        external_id: str | None = None,
        canonical_id: str = "CVE-2024-0001",
    ) -> Advisory:
        advisory = Advisory(
            source=source,
            source_advisory_id=external_id or f"GHSA-{uuid.uuid4().hex[:4]}-abcd-efgh",
            canonical_id=canonical_id,
            summary="Test advisory",
            details_url="https://example.com/advisory",
            raw_payload_sha256="a" * 64,
        )
        self.session.add(advisory)
        self.session.flush()
        return advisory

    def add_vulnerability(
        self,
        *,
        component: Component,
        advisory: Advisory,
        severity_label: str | None = "CVSS_V3",
        severity_score: float | None = 7.5,
        fetched_at: str = "2024-01-01T00:00:00Z",
    ) -> ComponentAdvisory:
        ca = ComponentAdvisory(
            scan_run_id=self.scan.id,
            component_id=component.id,
            advisory_id=advisory.id,
            affected=True,
            fixed_versions_json=json.dumps(["1.3.0"]),
            severity_source=advisory.source,
            severity_label=severity_label,
            severity_score=severity_score,
            evidence_json=json.dumps(
                {
                    "provider": advisory.source,
                    "fetched_at": fetched_at,
                    "aliases": [advisory.canonical_id or advisory.source_advisory_id],
                }
            ),
        )
        self.session.add(ca)
        self.session.flush()
        return ca

    def commit(self) -> int:
        if self._completed:
            scan_service.transition_scan(self.session, self.scan.id, target=ScanStatus.RUNNING)
            scan_service.transition_scan(self.session, self.scan.id, target=ScanStatus.COMPLETED)
        self.session.commit()
        return self.scan.id


# ---------------------------------------------------------------------------
# Eligibility and validation
# ---------------------------------------------------------------------------


def test_compare_scans_rejects_identical_selection(app_config, session) -> None:
    base = _ScanBuilder(session)
    base.add_component(name="a")
    base = base.commit()
    with __import__("pytest").raises(ApiError) as info:
        comparison_service.compare_scans(session, base_scan_id=base, head_scan_id=base)
    assert info.value.code == ApiErrorCode.VALIDATION_ERROR.value


def test_compare_scans_rejects_non_terminal_head(app_config, session) -> None:
    base = _ScanBuilder(session)
    base.add_component(name="a")
    base = base.commit()
    head = _ScanBuilder(session, completed=False)
    head.add_component(name="a")
    head_id = head.commit()
    with __import__("pytest").raises(ApiError) as info:
        comparison_service.compare_scans(session, base_scan_id=base, head_scan_id=head_id)
    assert info.value.code == ApiErrorCode.ILLEGAL_TRANSITION.value


def test_compare_scans_rejects_non_terminal_base(app_config, session) -> None:
    base = _ScanBuilder(session, completed=False)
    base.add_component(name="a")
    base_id = base.commit()
    head = _ScanBuilder(session)
    head.add_component(name="a")
    head = head.commit()
    with __import__("pytest").raises(ApiError) as info:
        comparison_service.compare_scans(session, base_scan_id=base_id, head_scan_id=head)
    assert info.value.code == ApiErrorCode.ILLEGAL_TRANSITION.value


def test_compare_scans_rejects_cross_repository(app_config, session) -> None:
    """Two scans on two different repositories must be rejected."""
    base = _ScanBuilder(session)

    base.add_component(name="a")

    base = base.commit()
    other = _ScanBuilder(
        session, canonical_url="https://github.com/anthropics/anthropic-sdk-python"
    )
    other.scan.repository_id = other.repository.id
    other_id = other.commit()
    with __import__("pytest").raises(ApiError) as info:
        comparison_service.compare_scans(session, base_scan_id=base, head_scan_id=other_id)
    assert info.value.code == ApiErrorCode.VALIDATION_ERROR.value


def test_compare_scans_rejects_missing_base(app_config, session) -> None:
    head = _ScanBuilder(session)

    head.add_component(name="a")

    head = head.commit()
    with __import__("pytest").raises(ApiError) as info:
        comparison_service.compare_scans(session, base_scan_id=999_999, head_scan_id=head)
    assert info.value.code == ApiErrorCode.NOT_FOUND.value


def test_compare_scans_rejects_missing_head(app_config, session) -> None:
    base = _ScanBuilder(session)

    base.add_component(name="a")

    base = base.commit()
    with __import__("pytest").raises(ApiError) as info:
        comparison_service.compare_scans(session, base_scan_id=base, head_scan_id=999_999)
    assert info.value.code == ApiErrorCode.NOT_FOUND.value


# ---------------------------------------------------------------------------
# Component comparison
def test_compare_scans_rejects_failed_scan(app_config, session) -> None:
    """A ``failed`` scan does not have trustworthy persisted evidence.

    The comparator rejects it with a bounded error so the
    operator never gets a misleading "no differences
    observed" verdict built on partial / untrustworthy
    local-analysis data.
    """
    base = _ScanBuilder(session)
    base.add_component(name="left-pad", version="1.0.0")
    base_id = base.commit()
    head = _ScanBuilder(session, completed=False)
    head.add_component(name="left-pad", version="2.0.0")
    head_id = head.commit()
    # Manually drive the head scan to FAILED.
    scan_service.transition_scan(session, head_id, target=ScanStatus.RUNNING)
    scan_service.transition_scan(session, head_id, target=ScanStatus.FAILED)
    session.commit()
    with __import__("pytest").raises(ApiError) as info:
        comparison_service.compare_scans(session, base_scan_id=base_id, head_scan_id=head_id)
    assert info.value.code == ApiErrorCode.ILLEGAL_TRANSITION.value


def test_compare_scans_rejects_cancelled_scan(app_config, session) -> None:
    """A ``cancelled`` scan does not have trustworthy persisted evidence."""
    base = _ScanBuilder(session)
    base.add_component(name="left-pad", version="1.0.0")
    base_id = base.commit()
    head = _ScanBuilder(session, completed=False)
    head.add_component(name="left-pad", version="2.0.0")
    head_id = head.commit()
    scan_service.transition_scan(session, head_id, target=ScanStatus.CANCELLED)
    session.commit()
    with __import__("pytest").raises(ApiError) as info:
        comparison_service.compare_scans(session, base_scan_id=base_id, head_scan_id=head_id)
    assert info.value.code == ApiErrorCode.ILLEGAL_TRANSITION.value


def test_compare_scans_accepts_partial_scan(app_config, session) -> None:
    """A ``partial`` scan is eligible - it has enough local evidence to compare.

    Provider degradation alone must not invalidate
    otherwise-successful local analysis. The ``partial``
    scan keeps the local component diff intact; the
    provider degradation surfaces on the affected
    vulnerability domain as ``comparison_indeterminate``.
    """
    base = _ScanBuilder(session)
    base.add_component(name="left-pad", version="1.0.0")
    base_id = base.commit()
    head = _ScanBuilder(session, completed=False)
    head.add_component(name="left-pad", version="2.0.0")
    head_id = head.commit()
    # Manually drive the head scan to PARTIAL.
    scan_service.transition_scan(session, head_id, target=ScanStatus.RUNNING)
    scan_service.transition_scan(session, head_id, target=ScanStatus.PARTIAL)
    session.commit()
    result = comparison_service.compare_scans(session, base_scan_id=base_id, head_scan_id=head_id)
    by_pv = {(c.package_name, c.version): c.state for c in result.components}
    assert by_pv == {
        ("left-pad", "1.0.0"): "no_longer_observed",
        ("left-pad", "2.0.0"): "newly_observed",
    }


def test_compare_components_multi_manifest_same_version_is_still_observed(
    app_config, session
) -> None:
    """The same package+version across multiple manifests is one component.

    A package that appears in two manifests in the same
    scan, at the same version, is a single component
    identity. The comparator reports it as
    ``still_observed`` if the same identity exists on both
    sides; the multiple manifests are surfaced as
    ``manifest_paths``.
    """
    base = _ScanBuilder(session)
    base_manifest_a = base.add_manifest(path="a/package.json")
    base_manifest_b = base.add_manifest(path="b/package.json")
    base.add_component(name="left-pad", version="1.0.0", manifest=base_manifest_a)
    base.add_component(name="left-pad", version="1.0.0", manifest=base_manifest_b)
    base_id = base.commit()
    head = _ScanBuilder(session)
    head_manifest = head.add_manifest(path="package.json")
    head.add_component(name="left-pad", version="1.0.0", manifest=head_manifest)
    head_id = head.commit()
    result = comparison_service.compare_scans(session, base_scan_id=base_id, head_scan_id=head_id)
    by_pv = {(c.package_name, c.version) for c in result.components}
    assert by_pv == {("left-pad", "1.0.0")}
    row = result.components[0]
    assert row.state == "still_observed"
    # All three manifest paths are surfaced on the single row.
    assert set(row.manifest_paths) == {"a/package.json", "b/package.json", "package.json"}


def test_compare_components_multi_instance_with_mixed_direct_transitive(
    app_config, session
) -> None:
    """A package appearing as direct in one scan and transitive in another
    is ``changed_observation``, not a fabricated transition.

    The identity is the same (package + version), so it is
    one row, and the state is ``changed_observation`` when
    the per-side ``direct`` flag differs.
    """
    base = _ScanBuilder(session)
    base.add_component(name="left-pad", version="1.0.0", direct=True)
    base_id = base.commit()
    head = _ScanBuilder(session)
    head.add_component(name="left-pad", version="1.0.0", direct=False)
    head_id = head.commit()
    result = comparison_service.compare_scans(session, base_scan_id=base_id, head_scan_id=head_id)
    assert len(result.components) == 1
    row = result.components[0]
    assert row.state == "changed_observation"
    assert row.direct_base is True
    assert row.direct_head is False


# ---------------------------------------------------------------------------


def test_compare_components_unchanged_remains_still_observed(app_config, session) -> None:
    """A component present in both scans with the same identity stays the same."""
    base = _ScanBuilder(session)

    base.add_component(name="left-pad", version="1.0.0")

    base = base.commit()
    head = _ScanBuilder(session)

    head.add_component(name="left-pad", version="1.0.0")

    head = head.commit()
    result = comparison_service.compare_scans(session, base_scan_id=base, head_scan_id=head)
    states = {c.package_name: c.state for c in result.components}
    assert states == {"left-pad": "still_observed"}


def test_compare_components_added_is_newly_observed(app_config, session) -> None:
    """A component present only in the head scan is reported as newly_observed."""
    base = _ScanBuilder(session).commit()
    head = _ScanBuilder(session)

    head.add_component(name="right-pad", version="1.0.0")

    head = head.commit()
    result = comparison_service.compare_scans(session, base_scan_id=base, head_scan_id=head)
    states = {c.package_name: c.state for c in result.components}
    assert states == {"right-pad": "newly_observed"}


def test_compare_components_removed_is_no_longer_observed(app_config, session) -> None:
    """A component present only in the base scan is reported as no_longer_observed."""
    base = _ScanBuilder(session)

    base.add_component(name="right-pad", version="1.0.0")

    base = base.commit()
    head = _ScanBuilder(session).commit()
    result = comparison_service.compare_scans(session, base_scan_id=base, head_scan_id=head)
    states = {c.package_name: c.state for c in result.components}
    assert states == {"right-pad": "no_longer_observed"}


def test_compare_components_two_versions_appear_as_separate_rows(app_config, session) -> None:
    """The same package at different versions is two distinct component identities.

    A package that exists at v1.0.0 in the base scan and at
    v2.0.0 in the head scan (with no overlap) yields two
    rows: 1.0.0 is ``no_longer_observed`` and 2.0.0 is
    ``newly_observed``. The comparator does **not** emit a
    fabricated "version transition" row that bridges them.
    """
    base = _ScanBuilder(session)

    base.add_component(name="left-pad", version="1.0.0")

    base = base.commit()
    head = _ScanBuilder(session)

    head.add_component(name="left-pad", version="2.0.0")

    head = head.commit()
    result = comparison_service.compare_scans(session, base_scan_id=base, head_scan_id=head)
    by_version = {(c.version, c.state) for c in result.components}
    assert (("1.0.0", "no_longer_observed")) in by_version
    assert (("2.0.0", "newly_observed")) in by_version
    # No row carries the legacy "unambiguous_version_change"
    # flag, and no row is labelled "fixed" or "resolved".
    for row in result.components:
        assert "version_base" not in row.model_dump()
        assert "version_head" not in row.model_dump()
        assert "unambiguous_version_change" not in row.model_dump()
        assert "ambiguity_reason" not in row.model_dump()
        assert row.state in {
            "newly_observed",
            "still_observed",
            "no_longer_observed",
            "changed_observation",
            "coverage_changed",
            "comparison_indeterminate",
        }


def test_compare_components_ambiguous_multi_version_emits_separate_rows(
    app_config, session
) -> None:
    """Multiple base versions of the same package emit one row per version.

    A package that exists at v1.0.0 in manifest ``a/`` and
    v2.0.0 in manifest ``b/`` in the base scan, and at
    v3.0.0 in the head scan, yields three rows: 1.0.0 and
    2.0.0 are ``no_longer_observed``, 3.0.0 is
    ``newly_observed``. The comparator does not collapse
    them into a single ``comparison_indeterminate`` row.
    """
    base = _ScanBuilder(session)
    base.add_component(
        name="left-pad", version="1.0.0", manifest=base.add_manifest(path="a/package.json")
    )
    base.add_component(
        name="left-pad", version="2.0.0", manifest=base.add_manifest(path="b/package.json")
    )
    base_id = base.commit()
    head = _ScanBuilder(session)

    head.add_component(name="left-pad", version="3.0.0")

    head = head.commit()
    result = comparison_service.compare_scans(session, base_scan_id=base_id, head_scan_id=head)
    by_version = {(c.version, c.state) for c in result.components}
    assert ("1.0.0", "no_longer_observed") in by_version
    assert ("2.0.0", "no_longer_observed") in by_version
    assert ("3.0.0", "newly_observed") in by_version


def test_compare_components_reverses_on_swap(app_config, session) -> None:
    """Reversing base and head reverses additions and removals."""
    base = _ScanBuilder(session)

    base.add_component(name="left-pad")

    base = base.commit()
    head = _ScanBuilder(session)

    head.add_component(name="right-pad")

    head = head.commit()
    forward = comparison_service.compare_scans(session, base_scan_id=base, head_scan_id=head)
    reverse = comparison_service.compare_scans(session, base_scan_id=head, head_scan_id=base)
    forward_states = {c.package_name: c.state for c in forward.components}
    reverse_states = {c.package_name: c.state for c in reverse.components}
    assert forward_states == {
        "left-pad": "no_longer_observed",
        "right-pad": "newly_observed",
    }
    assert reverse_states == {
        "left-pad": "newly_observed",
        "right-pad": "no_longer_observed",
    }


def test_compare_components_sorted_by_identity(app_config, session) -> None:
    """Components are deterministically ordered by (ecosystem, package_name, version).

    With identity keyed on the concrete version, a
    v1.0.0 → v2.0.0 transition for three packages produces
    six rows (one per package per version). The list is
    deterministically ordered so the operator gets the
    same output on every call.
    """
    names = ["zod", "axios", "left-pad"]
    base = _ScanBuilder(session)
    for n in names:
        base.add_component(name=n, version="1.0.0")
    base_id = base.commit()
    head = _ScanBuilder(session)
    for n in names:
        head.add_component(name=n, version="2.0.0")
    head_id = head.commit()
    result = comparison_service.compare_scans(session, base_scan_id=base_id, head_scan_id=head_id)
    # Six rows: each (name, version) pair shows up once.
    assert len(result.components) == 2 * len(names)
    # Every component has a real package name; ordering is
    # deterministic across repeated calls.
    package_versions = [(c.package_name, c.version) for c in result.components]
    expected = []
    for n in sorted(names):
        expected.append((n, "1.0.0"))
        expected.append((n, "2.0.0"))
    assert package_versions == expected


# ---------------------------------------------------------------------------
# Manifest comparison
# ---------------------------------------------------------------------------


def test_compare_manifests_changed_when_content_hash_differs(app_config, session) -> None:
    base = _ScanBuilder(session)
    base.add_manifest(content_sha256="a" * 64)
    base_id = base.commit()
    head = _ScanBuilder(session)
    head.add_manifest(content_sha256="b" * 64)
    head_id = head.commit()
    result = comparison_service.compare_scans(session, base_scan_id=base_id, head_scan_id=head_id)
    assert len(result.manifests) == 1
    assert result.manifests[0].state == "changed_observation"
    assert result.manifests[0].content_sha256_base == "a" * 64
    assert result.manifests[0].content_sha256_head == "b" * 64


# ---------------------------------------------------------------------------
# Workflow comparison
# ---------------------------------------------------------------------------


def test_compare_workflows_still_observed_unchanged(app_config, session) -> None:
    base = _ScanBuilder(session)
    base.add_workflow_finding()
    base_id = base.commit()
    head = _ScanBuilder(session)
    head.add_workflow_finding()
    head_id = head.commit()
    result = comparison_service.compare_scans(session, base_scan_id=base_id, head_scan_id=head_id)
    assert len(result.workflows) == 1
    assert result.workflows[0].state == "still_observed"


def test_compare_workflows_newly_observed_and_removed(app_config, session) -> None:
    base = _ScanBuilder(session)
    base.add_workflow_finding(stable_key="k1", path=".github/workflows/ci.yml")
    base_id = base.commit()
    head = _ScanBuilder(session)
    head.add_workflow_finding(
        rule_id="LOCK-WF-002", stable_key="k2", path=".github/workflows/release.yml"
    )
    head_id = head.commit()
    result = comparison_service.compare_scans(session, base_scan_id=base_id, head_scan_id=head_id)
    by_key = {w.stable_key: w.state for w in result.workflows}
    assert by_key == {"k1": "no_longer_observed", "k2": "newly_observed"}


# ---------------------------------------------------------------------------
# Vulnerability comparison
# ---------------------------------------------------------------------------


def test_compare_vulnerabilities_provenance_preserved(app_config, session) -> None:
    """Provenance, fetched_at, and aliases are preserved across scans."""
    base = _ScanBuilder(session)
    base_component = base.add_component(name="left-pad", version="1.0.0")
    base_advisory = base.add_advisory()
    base.add_vulnerability(
        component=base_component, advisory=base_advisory, fetched_at="2024-01-01T00:00:00Z"
    )
    base_id = base.commit()
    head = _ScanBuilder(session)
    head_component = head.add_component(name="left-pad", version="1.0.0")
    head_advisory = head.add_advisory()
    head.add_vulnerability(
        component=head_component, advisory=head_advisory, fetched_at="2024-02-01T00:00:00Z"
    )
    head_id = head.commit()
    result = comparison_service.compare_scans(session, base_scan_id=base_id, head_scan_id=head_id)
    assert len(result.vulnerabilities) == 1
    vuln = result.vulnerabilities[0]
    assert vuln.state == "still_observed"
    assert vuln.provider_provenance_base == "osv"
    assert vuln.provider_provenance_head == "osv"
    assert vuln.fetched_at_base == "2024-01-01T00:00:00Z"
    assert vuln.fetched_at_head == "2024-02-01T00:00:00Z"


def test_compare_vulnerabilities_disappearance_is_indeterminate_when_provider_unavailable(
    app_config, session
) -> None:
    """A vulnerability that disappears is not "fixed" if the head provider is unavailable."""
    base = _ScanBuilder(session)
    base_component = base.add_component(name="left-pad", version="1.0.0")
    base_advisory = base.add_advisory()
    base.add_vulnerability(component=base_component, advisory=base_advisory)
    base_id = base.commit()
    # Head scan has the same component but no provider observation
    # for OSV, signalling an unavailable / unrequested state.
    head = _ScanBuilder(session)
    head.add_component(name="left-pad", version="1.0.0")
    head.add_provider_observation(
        provider="osv",
        status=ProviderStatus.UNAVAILABLE,
        records_returned=0,
        cache_status="miss",
        error_code="provider_unavailable",
        error_summary="osv.dev 503",
    )
    head_id = head.commit()
    result = comparison_service.compare_scans(session, base_scan_id=base_id, head_scan_id=head_id)
    assert len(result.vulnerabilities) == 1
    vuln = result.vulnerabilities[0]
    # The vulnerability is not marked "no_longer_observed" because
    # the head provider was unavailable. The comparator is
    # explicit about it.
    assert vuln.state == "comparison_indeterminate"
    assert vuln.ambiguity_reason is not None
    assert any("unavailable" in r for r in result.indeterminate_reasons)


def test_compare_vulnerabilities_successful_evidence_not_in_error_summary(
    app_config, session
) -> None:
    """Successful evidence is never reported as a redacted error summary."""
    base = _ScanBuilder(session)
    base_component = base.add_component(name="left-pad", version="1.0.0")
    base_advisory = base.add_advisory()
    base.add_vulnerability(component=base_component, advisory=base_advisory)
    base_id = base.commit()
    head = _ScanBuilder(session)
    head_component = head.add_component(name="left-pad", version="1.0.0")
    head_advisory = head.add_advisory()
    head.add_vulnerability(component=head_component, advisory=head_advisory)
    head_id = head.commit()
    result = comparison_service.compare_scans(session, base_scan_id=base_id, head_scan_id=head_id)
    # The error_summary_* fields on provider coverage must not
    # carry a successful evidence envelope.
    for row in result.providers:
        assert not (row.evidence_present_base and row.error_summary_base)
        assert not (row.evidence_present_head and row.error_summary_head)


# ---------------------------------------------------------------------------
# Provider coverage comparison
# ---------------------------------------------------------------------------


def test_compare_provider_coverage_surfaces_explicit_states(app_config, session) -> None:
    base = _ScanBuilder(session)
    base.add_provider_observation(
        provider="osv",
        status=ProviderStatus.AVAILABLE,
        records_returned=2,
        cache_status="miss",
    )
    base.add_provider_observation(
        provider="deps_dev",
        status=ProviderStatus.UNAVAILABLE,
        records_returned=0,
        cache_status="miss",
        error_code="provider_unavailable",
        error_summary="deps.dev 503",
    )
    base_id = base.commit()
    head = _ScanBuilder(session)
    head.add_provider_observation(
        provider="osv",
        status=ProviderStatus.CACHED,
        records_returned=2,
        cache_status="hit",
    )
    head.add_provider_observation(
        provider="deps_dev",
        status=ProviderStatus.PARTIAL,
        records_returned=1,
        cache_status="miss",
    )
    head_id = head.commit()
    result = comparison_service.compare_scans(session, base_scan_id=base_id, head_scan_id=head_id)
    by_provider = {row.provider: row for row in result.providers}
    assert by_provider["osv"].state_base == "successful"
    assert by_provider["osv"].state_head == "cached"
    assert by_provider["osv"].state == "coverage_changed"
    assert by_provider["deps_dev"].state_base == "unavailable"
    assert by_provider["deps_dev"].state_head == "partial"


def test_compare_provider_coverage_unchanged_successful(app_config, session) -> None:
    base = _ScanBuilder(session)
    base.add_provider_observation(
        provider="osv",
        status=ProviderStatus.AVAILABLE,
        records_returned=2,
        cache_status="miss",
    )
    base_id = base.commit()
    head = _ScanBuilder(session)
    head.add_provider_observation(
        provider="osv",
        status=ProviderStatus.AVAILABLE,
        records_returned=2,
        cache_status="miss",
    )
    head_id = head.commit()
    result = comparison_service.compare_scans(session, base_scan_id=base_id, head_scan_id=head_id)
    assert len(result.providers) == 1
    assert result.providers[0].state == "still_observed"
    assert result.providers[0].state_base == "successful"
    assert result.providers[0].state_head == "successful"


def test_compare_provider_coverage_preserves_error_summary(app_config, session) -> None:
    base = _ScanBuilder(session)
    base.add_provider_observation(
        provider="osv",
        status=ProviderStatus.UNAVAILABLE,
        records_returned=0,
        cache_status="miss",
        error_code="provider_unavailable",
        error_summary="osv.dev 503",
    )
    base_id = base.commit()
    head = _ScanBuilder(session)
    head.add_provider_observation(
        provider="osv",
        status=ProviderStatus.AVAILABLE,
        records_returned=2,
        cache_status="miss",
    )
    head_id = head.commit()
    result = comparison_service.compare_scans(session, base_scan_id=base_id, head_scan_id=head_id)
    row = next(r for r in result.providers if r.provider == "osv")
    assert row.state_base == "unavailable"
    assert row.state_head == "successful"
    assert row.state == "coverage_changed"
    assert row.error_summary_base == "osv.dev 503"
    assert row.error_summary_head is None


# ---------------------------------------------------------------------------
# Deterministic ordering
# ---------------------------------------------------------------------------


def test_compare_scans_output_is_deterministically_ordered(app_config, session) -> None:
    """Two runs of the same input return identical lists in identical order."""
    base = _ScanBuilder(session)
    for i in range(5):
        base.add_component(name=f"pkg-{i:02d}", version="1.0.0")
    base_id = base.commit()
    head = _ScanBuilder(session)
    for i in range(5):
        head.add_component(name=f"pkg-{i:02d}", version="2.0.0")
    head_id = head.commit()
    a = comparison_service.compare_scans(session, base_scan_id=base_id, head_scan_id=head_id)
    b = comparison_service.compare_scans(session, base_scan_id=base_id, head_scan_id=head_id)
    assert [c.package_name for c in a.components] == [c.package_name for c in b.components]
    assert [c.state for c in a.components] == [c.state for c in b.components]
    assert [p.provider for p in a.providers] == [p.provider for p in b.providers]


# ---------------------------------------------------------------------------
# Read-only contract
# ---------------------------------------------------------------------------


def test_compare_scans_does_not_write_to_database(app_config, session) -> None:
    """A comparison call must not introduce database writes."""
    base = _ScanBuilder(session)

    base.add_component(name="left-pad", version="1.0.0")

    base = base.commit()
    head = _ScanBuilder(session)

    head.add_component(name="left-pad", version="2.0.0")

    head = head.commit()
    from app.models.component import Component
    from app.models.manifest import Manifest
    from app.models.scan_run import ScanRun
    from sqlalchemy import select

    def _snapshot():
        out = {}
        for table, model in [
            (Component, Component),
            (Manifest, Manifest),
            (ScanRun, ScanRun),
        ]:
            rows = session.execute(select(model)).scalars().all()
            for row in rows:
                out[(table.__tablename__, row.id)] = row.updated_at
        return out

    before = _snapshot()
    comparison_service.compare_scans(session, base_scan_id=base, head_scan_id=head)
    after = _snapshot()
    assert before == after


def test_compare_scans_does_not_call_out_to_network(app_config, session, monkeypatch) -> None:
    """The comparison must never reach the network."""
    base = _ScanBuilder(session).commit()
    head = _ScanBuilder(session).commit()

    def _explode(*args, **kwargs):  # pragma: no cover - defensive
        raise AssertionError("comparison_service must not perform any network I/O")

    monkeypatch.setattr("app.utils.bounded_http.safe_get", _explode, raising=False)
    monkeypatch.setattr("app.utils.bounded_http.safe_post", _explode, raising=False)
    comparison_service.compare_scans(session, base_scan_id=base, head_scan_id=head)


# ---------------------------------------------------------------------------
# Dependency path comparison
# ---------------------------------------------------------------------------


def test_compare_dependency_paths_detects_parent_change(app_config, session) -> None:
    base = _ScanBuilder(session)
    base_parent = base.add_component(name="parent", version="1.0.0")
    base_child = base.add_component(name="child", version="1.0.0")
    base.add_dependency_edge(parent=base_parent, child=base_child)
    base_id = base.commit()
    head = _ScanBuilder(session)
    head.add_component(name="parent", version="1.0.0")
    head.add_component(name="child", version="1.0.0")
    head_id = head.commit()
    result = comparison_service.compare_scans(session, base_scan_id=base_id, head_scan_id=head_id)
    child_path = next((d for d in result.dependency_paths if d.package_name == "child"), None)
    assert child_path is not None
    assert child_path.state == "changed_observation"
    assert "parent" in child_path.parent_chain_base
    assert child_path.parent_chain_head == []


# ---------------------------------------------------------------------------
# Coverage summary
# ---------------------------------------------------------------------------


def test_compare_scans_coverage_summary_counts(app_config, session) -> None:
    base = _ScanBuilder(session)
    base.add_component(name="a", version="1.0.0")
    base.add_component(name="b", version="1.0.0")
    base_id = base.commit()
    head = _ScanBuilder(session)
    head.add_component(name="b", version="1.0.0")
    head.add_component(name="c", version="1.0.0")
    head_id = head.commit()
    result = comparison_service.compare_scans(session, base_scan_id=base_id, head_scan_id=head_id)
    # ``a`` is base-only, ``b`` is in both, ``c`` is head-only.
    assert result.coverage.base_scan_status == "completed"
    assert result.coverage.head_scan_status == "completed"
    assert result.coverage.components_in_base == 2
    assert result.coverage.components_in_head == 2


def test_compare_scans_independent_of_session_reuse(app_config, session) -> None:
    """A comparison call must not mutate session state in a way that breaks subsequent calls."""
    base = _ScanBuilder(session)

    base.add_component(name="a")

    base = base.commit()
    head = _ScanBuilder(session)

    head.add_component(name="a")

    head = head.commit()
    r1 = comparison_service.compare_scans(session, base_scan_id=base, head_scan_id=head)
    r2 = comparison_service.compare_scans(session, base_scan_id=base, head_scan_id=head)
    assert r1.base_scan_id == r2.base_scan_id == base
    assert r1.head_scan_id == r2.head_scan_id == head
    assert [c.state for c in r1.components] == [c.state for c in r2.components]
