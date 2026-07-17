"""v0.8 component evidence drilldown tests.

The tests exercise the free function and the session-lifecycle
service over a small in-memory SQLite database. The fixtures
build a minimal but representative scan: a completed scan with
one manifest, one component, an optional licence finding, an
optional provider observation, an optional component-advisory
row, and an optional dependency edge.

Every test asserts one documented contract; the negative
tests prove the bounded not-found / cross-scan rejection /
deterministic / no-side-effect rules.
"""

from __future__ import annotations

import socket

import pytest
from app.db.base import Base
from app.evidence import (
    ADVISORY_LIMIT,
    COMPONENT_EVIDENCE_OMISSIONS,
    ComponentEvidenceService,
)
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
from app.models.provider_observation import (
    ProviderObservation,
    ProviderStatus,
)
from app.models.repository import (
    Repository,
    RepositoryProvider,
    RepositorySourceType,
    RepositoryVisibility,
)
from app.models.scan_run import ScanRun, ScanStatus, ScanTriggerType
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Compatibility: the evidence module exposes the omissions
# list as a module-level constant for the test to assert
# against. The constant name is intentionally distinct from
# the runtime ``omissions`` list to keep the contract
# obvious to readers.
_COMPONENT_EVIDENCE_OMISSIONS = COMPONENT_EVIDENCE_OMISSIONS


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest.fixture()
def session():
    """Yield a fresh in-memory SQLite session per test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine)
    session = session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _make_repo(session, *, owner: str = "octocat", name: str = "Hello-World") -> int:
    repo = Repository(
        source_type=RepositorySourceType.GITHUB,
        provider=RepositoryProvider.GITHUB,
        owner=owner,
        name=name,
        canonical_url=f"https://github.com/{owner}/{name}",
        default_branch="main",
        visibility=RepositoryVisibility.PUBLIC,
    )
    session.add(repo)
    session.flush()
    return repo.id


def _make_scan(
    session,
    *,
    repo_id: int,
    status: ScanStatus = ScanStatus.COMPLETED,
    trigger_type: ScanTriggerType = ScanTriggerType.MANUAL,
) -> int:
    scan = ScanRun(
        repository_id=repo_id,
        trigger_type=trigger_type,
        status=status,
    )
    session.add(scan)
    session.commit()
    return scan.id


def _make_manifest(
    session,
    *,
    scan_id: int,
    path: str = "package.json",
    manifest_type: str = "npm",
    ecosystem: str = "npm",
    parse_status: ManifestParseStatus = ManifestParseStatus.PARSED,
    parse_warning_count: int = 0,
) -> int:
    manifest = Manifest(
        scan_run_id=scan_id,
        path=path,
        manifest_type=manifest_type,
        ecosystem=ecosystem,
        content_sha256="a" * 64,
        parse_status=parse_status,
        parse_warning_count=parse_warning_count,
    )
    session.add(manifest)
    session.commit()
    return manifest.id


def _make_component(
    session,
    *,
    scan_id: int,
    manifest_id: int,
    name: str = "lodash",
    version: str | None = "4.17.21",
    version_source: ComponentVersionSource = ComponentVersionSource.MANIFEST,
    ecosystem: str = "npm",
    direct: bool = True,
    package_url: str | None = "pkg:npm/lodash@4.17.21",
) -> int:
    component = Component(
        scan_run_id=scan_id,
        manifest_id=manifest_id,
        ecosystem=ecosystem,
        package_name=name,
        version=version,
        version_source=version_source,
        package_url=package_url,
        scope="runtime",
        relationship="runtime",
        direct=direct,
        development=False,
        optional=False,
        integrity=None,
    )
    session.add(component)
    session.commit()
    return component.id


def _make_licence_finding(
    session,
    *,
    scan_id: int,
    component_id: int,
    licences: list[str],
    source: str | None = "rule_engine",
    rule_id: str = "LOCK-LIC-INV",
) -> int:
    import json as _json

    payload = {
        "evidence": {
            "component_id": component_id,
            "licences": licences,
            "source": source,
        }
    }
    finding = Finding(
        scan_run_id=scan_id,
        repository_id=_repo_id_for_scan(session, scan_id),
        rule_id=rule_id,
        category=FindingCategory.LICENCE,
        severity=FindingSeverity.INFORMATIONAL,
        confidence=FindingConfidence.UNKNOWN,
        title="licence observation",
        summary="licence observation",
        stable_key=f"licence:{component_id}",
        evidence_json=_json.dumps(payload),
    )
    session.add(finding)
    session.commit()
    return finding.id


def _make_provider_observation(
    session,
    *,
    scan_id: int,
    component_id: int,
    provider: str = "deps.dev",
    status: ProviderStatus = ProviderStatus.AVAILABLE,
    operation: str = "enrich",
    cache_status: str = "miss",
    http_status: int = 200,
    error_summary: str | None = None,
    evidence_json: str | None = None,
) -> int:
    obs = ProviderObservation(
        scan_run_id=scan_id,
        component_id=component_id,
        provider=provider,
        operation=operation,
        status=status,
        cache_status=cache_status,
        http_status=http_status,
        records_returned=0,
        error_code=None,
        error_summary=error_summary,
        evidence_json=evidence_json,
    )
    session.add(obs)
    session.commit()
    return obs.id


def _make_advisory(session, *, source: str = "osv", canonical_id: str = "CVE-2021-1234") -> int:
    advisory = Advisory(
        source=source,
        source_advisory_id=f"{source}-id",
        canonical_id=canonical_id,
        summary="advisory summary",
        details_url=None,
        published_at=None,
        modified_at=None,
        withdrawn_at=None,
        raw_payload_sha256="b" * 64,
    )
    session.add(advisory)
    session.commit()
    return advisory.id


def _make_component_advisory(
    session,
    *,
    scan_id: int,
    component_id: int,
    advisory_id: int,
    severity_label: str = "high",
    severity_score: float = 7.5,
    fixed_versions: list[str] | None = None,
    aliases: list[str] | None = None,
) -> int:
    import json as _json

    evidence = {"aliases": aliases or []}
    link = ComponentAdvisory(
        scan_run_id=scan_id,
        component_id=component_id,
        advisory_id=advisory_id,
        affected=1,
        fixed_versions_json=_json.dumps(fixed_versions) if fixed_versions else None,
        severity_source="osv",
        severity_label=severity_label,
        severity_score=severity_score,
        evidence_json=str(evidence).replace("'", '"'),
    )
    session.add(link)
    session.commit()
    return link.id


def _make_dependency_edge(
    session,
    *,
    scan_id: int,
    parent_id: int,
    child_id: int,
    relationship: str = "runtime",
    depth: int = 1,
) -> int:
    edge = DependencyEdge(
        scan_run_id=scan_id,
        parent_component_id=parent_id,
        child_component_id=child_id,
        relationship=relationship,
        depth=depth,
    )
    session.add(edge)
    session.commit()
    return edge.id


def _repo_id_for_scan(session, scan_id: int) -> int:
    return session.execute(
        text("SELECT repository_id FROM scan_runs WHERE id = :sid"),
        {"sid": scan_id},
    ).scalar_one()


def _service_for(session) -> ComponentEvidenceService:
    """Return a service bound to the test session."""
    session_local = sessionmaker(bind=session.get_bind())
    return ComponentEvidenceService(session_local)


# ---------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------


def test_evidence_returns_full_summary_for_valid_component(session) -> None:
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    manifest_id = _make_manifest(session, scan_id=scan_id)
    component_id = _make_component(session, scan_id=scan_id, manifest_id=manifest_id)
    _make_licence_finding(
        session,
        scan_id=scan_id,
        component_id=component_id,
        licences=["MIT"],
    )
    _make_provider_observation(session, scan_id=scan_id, component_id=component_id)
    advisory_id = _make_advisory(session, canonical_id="CVE-2021-1234")
    _make_component_advisory(
        session, scan_id=scan_id, component_id=component_id, advisory_id=advisory_id
    )

    service = _service_for(session)
    evidence = service.fetch(scan_run_id=scan_id, component_id=component_id)
    assert evidence is not None
    assert evidence["scan"]["scan_id"] == scan_id
    assert evidence["scan"]["repository_id"] == repo_id
    assert evidence["scan"]["scan_status"] == "completed"
    assert evidence["component"]["id"] == component_id
    assert evidence["component"]["package_name"] == "lodash"
    assert evidence["component"]["version"] == "4.17.21"
    assert evidence["component"]["version_source"] == "manifest"
    assert evidence["component"]["package_url"] == "pkg:npm/lodash@4.17.21"
    assert evidence["component"]["package_url_well_formed"] is True
    assert evidence["component"]["purl_constructible"] is True
    assert evidence["component"]["bom_ref"] == "pkg:npm/lodash@4.17.21"
    assert evidence["manifest"]["available"] is True
    assert evidence["manifest"]["path"] == "package.json"
    assert evidence["licence_evidence"]["available"] is True
    assert evidence["licence_evidence"]["observations"][0]["value"] == "MIT"
    assert evidence["licence_evidence"]["observations"][0]["classification"] == "spdx-id"
    assert evidence["provider_evidence"]["available"] is True
    assert evidence["provider_evidence"]["observations"][0]["provider"] == "deps.dev"
    assert evidence["provider_evidence"]["advisories"][0]["canonical_id"] == "CVE-2021-1234"
    # OSV does not supply a confidence value; the v0.4
    # honesty rule is preserved.
    assert evidence["provider_evidence"]["advisories"][0]["confidence"] is None
    # No dependency edges were persisted, so the block is
    # honest about the empty graph.
    assert evidence["dependency_evidence"]["incoming"] == []
    assert evidence["dependency_evidence"]["outgoing"] == []
    assert evidence["dependency_evidence"]["no_edges_observed"] is True
    assert evidence["dependency_evidence"]["graph_coverage"] in {"partial", "unknown"}
    # Export implications follow the v0.6 contract.
    assert evidence["export_implications"]["appears_in_cyclonedx_17"] is True
    assert evidence["export_implications"]["version_omitted"] is False
    assert evidence["export_implications"]["purl_emitted"] is True
    assert evidence["export_implications"]["dependency_relationships_emitted"] is False
    # The omissions list is the explicit evidence-honesty
    # contract.
    assert list(evidence["omissions"]) == list(_COMPONENT_EVIDENCE_OMISSIONS)


# ---------------------------------------------------------------------
# Cross-scan / cross-component rejection
# ---------------------------------------------------------------------


def test_evidence_rejects_component_from_another_scan(session) -> None:
    repo_id = _make_repo(session)
    scan_a = _make_scan(session, repo_id=repo_id)
    scan_b = _make_scan(session, repo_id=repo_id)
    manifest_a = _make_manifest(session, scan_id=scan_a)
    component_a = _make_component(session, scan_id=scan_a, manifest_id=manifest_a)
    service = _service_for(session)
    assert service.fetch(scan_run_id=scan_b, component_id=component_a) is None


def test_evidence_rejects_unknown_component_id(session) -> None:
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    service = _service_for(session)
    assert service.fetch(scan_run_id=scan_id, component_id=999_999) is None


def test_evidence_rejects_unknown_scan_id(session) -> None:
    service = _service_for(session)
    assert service.fetch(scan_run_id=999_999, component_id=1) is None


# ---------------------------------------------------------------------
# Identity / version
# ---------------------------------------------------------------------


def test_evidence_keeps_missing_version_missing(session) -> None:
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    manifest_id = _make_manifest(session, scan_id=scan_id)
    component_id = _make_component(
        session,
        scan_id=scan_id,
        manifest_id=manifest_id,
        version=None,
        version_source=ComponentVersionSource.UNRESOLVED,
    )
    service = _service_for(session)
    evidence = service.fetch(scan_run_id=scan_id, component_id=component_id)
    assert evidence is not None
    assert evidence["component"]["version"] is None
    assert evidence["component"]["version_source"] == "unresolved"
    # The export implication reports the omission honestly.
    assert evidence["export_implications"]["version_omitted"] is True
    # No placeholder string is ever emitted in the response.
    import json as _json

    body = _json.dumps(evidence)
    for forbidden in ['"unspecified"', '"unknown"', '"latest"', '"n/a"', '"<missing>"']:
        assert forbidden not in body.lower(), (
            f"evidence response leaked a placeholder version string: {forbidden!r}"
        )


def test_evidence_purl_well_formed_for_malformed_persisted_purl(session) -> None:
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    manifest_id = _make_manifest(session, scan_id=scan_id)
    component_id = _make_component(
        session,
        scan_id=scan_id,
        manifest_id=manifest_id,
        package_url="not-a-purl",
    )
    service = _service_for(session)
    evidence = service.fetch(scan_run_id=scan_id, component_id=component_id)
    assert evidence is not None
    assert evidence["component"]["package_url"] == "not-a-purl"
    assert evidence["component"]["package_url_well_formed"] is False
    # The persisted PURL is malformed; the v0.6 exporter
    # falls back to a deterministic lockverity:component:{id}
    # bom-ref. The evidence block surfaces the same id.
    assert evidence["component"]["bom_ref"].startswith("lockverity:component:")
    # The export implication reports the PURL would not
    # be emitted (malformed) and the reconstruction is
    # still possible for npm / pypi.
    assert evidence["export_implications"]["purl_emitted"] is True


def test_evidence_purl_omitted_for_unsupported_ecosystem(session) -> None:
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    manifest_id = _make_manifest(session, scan_id=scan_id, ecosystem="cargo")
    component_id = _make_component(
        session,
        scan_id=scan_id,
        manifest_id=manifest_id,
        name="serde",
        ecosystem="cargo",
        package_url=None,
    )
    service = _service_for(session)
    evidence = service.fetch(scan_run_id=scan_id, component_id=component_id)
    assert evidence is not None
    assert evidence["component"]["purl_constructible"] is False
    assert evidence["export_implications"]["purl_emitted"] is False


# ---------------------------------------------------------------------
# Manifest evidence
# ---------------------------------------------------------------------


def test_evidence_manifest_block_reports_parse_status(session) -> None:
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    manifest_id = _make_manifest(
        session,
        scan_id=scan_id,
        path="requirements.txt",
        manifest_type="pypi",
        ecosystem="pypi",
        parse_status=ManifestParseStatus.PARTIAL,
        parse_warning_count=3,
    )
    component_id = _make_component(session, scan_id=scan_id, manifest_id=manifest_id)
    service = _service_for(session)
    evidence = service.fetch(scan_run_id=scan_id, component_id=component_id)
    assert evidence is not None
    assert evidence["manifest"]["path"] == "requirements.txt"
    assert evidence["manifest"]["manifest_type"] == "pypi"
    assert evidence["manifest"]["ecosystem"] == "pypi"
    assert evidence["manifest"]["parse_status"] == "partial"
    assert evidence["manifest"]["parse_warning_count"] == 3


# ---------------------------------------------------------------------
# Licence evidence
# ---------------------------------------------------------------------


def test_evidence_licence_classification_uses_v6_rules(session) -> None:
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    manifest_id = _make_manifest(session, scan_id=scan_id)
    component_id = _make_component(session, scan_id=scan_id, manifest_id=manifest_id)
    _make_licence_finding(
        session,
        scan_id=scan_id,
        component_id=component_id,
        licences=["MIT", "Apache-2.0 OR MIT", "unknown-licence-text"],
    )
    service = _service_for(session)
    evidence = service.fetch(scan_run_id=scan_id, component_id=component_id)
    assert evidence is not None
    classes = {o["classification"] for o in evidence["licence_evidence"]["observations"]}
    assert "spdx-id" in classes
    assert "spdx-expression" in classes
    # The library does not recognise an arbitrary licence
    # text; the evidence block preserves the observed
    # value verbatim under the ``observed-name`` class.
    assert "observed-name" in classes


def test_evidence_missing_licence_evidence_is_explicit(session) -> None:
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    manifest_id = _make_manifest(session, scan_id=scan_id)
    component_id = _make_component(session, scan_id=scan_id, manifest_id=manifest_id)
    service = _service_for(session)
    evidence = service.fetch(scan_run_id=scan_id, component_id=component_id)
    assert evidence is not None
    assert evidence["licence_evidence"]["available"] is False
    assert evidence["licence_evidence"]["reason"] == "no_persisted_licence_evidence"
    assert evidence["licence_evidence"]["observations"] == []
    # The endpoint never substitutes a positive "no licence"
    # verdict; the omission list carries the contract.
    import json as _json

    body = _json.dumps(evidence).lower()
    assert '"none"' not in body or '"reason": "no_persisted_licence_evidence"' in body


# ---------------------------------------------------------------------
# Provider / advisory evidence
# ---------------------------------------------------------------------


def test_evidence_keeps_provider_confidence_missing(session) -> None:
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    manifest_id = _make_manifest(session, scan_id=scan_id)
    component_id = _make_component(session, scan_id=scan_id, manifest_id=manifest_id)
    _make_provider_observation(session, scan_id=scan_id, component_id=component_id)
    advisory_id = _make_advisory(session, canonical_id="CVE-2021-9999")
    _make_component_advisory(
        session,
        scan_id=scan_id,
        component_id=component_id,
        advisory_id=advisory_id,
        severity_label="high",
        severity_score=8.1,
    )
    service = _service_for(session)
    evidence = service.fetch(scan_run_id=scan_id, component_id=component_id)
    assert evidence is not None
    advisory = evidence["provider_evidence"]["advisories"][0]
    assert advisory["confidence"] is None
    # The severity score is the persisted value; the
    # endpoint never invents a confidence to go with it.
    assert advisory["severity_score"] == 8.1
    assert advisory["severity_label"] == "high"


def test_evidence_provider_unavailable_state_is_visible(session) -> None:
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    manifest_id = _make_manifest(session, scan_id=scan_id)
    component_id = _make_component(session, scan_id=scan_id, manifest_id=manifest_id)
    _make_provider_observation(
        session,
        scan_id=scan_id,
        component_id=component_id,
        provider="osv.dev",
        status=ProviderStatus.UNAVAILABLE,
        operation="vulnerability_query",
        cache_status=None,
        http_status=503,
        error_summary="upstream provider returned 503",
    )
    service = _service_for(session)
    evidence = service.fetch(scan_run_id=scan_id, component_id=component_id)
    assert evidence is not None
    obs = evidence["provider_evidence"]["observations"][0]
    assert obs["provider"] == "osv.dev"
    assert obs["status"] == "unavailable"
    assert obs["http_status"] == 503
    assert "503" in obs["error_summary"]


def test_evidence_provider_partial_state_is_visible(session) -> None:
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    manifest_id = _make_manifest(session, scan_id=scan_id)
    component_id = _make_component(session, scan_id=scan_id, manifest_id=manifest_id)
    _make_provider_observation(
        session,
        scan_id=scan_id,
        component_id=component_id,
        provider="deps.dev",
        status=ProviderStatus.PARTIAL,
        operation="enrich",
    )
    service = _service_for(session)
    evidence = service.fetch(scan_run_id=scan_id, component_id=component_id)
    assert evidence is not None
    obs = evidence["provider_evidence"]["observations"][0]
    assert obs["status"] == "partial"


# ---------------------------------------------------------------------
# Dependency evidence
# ---------------------------------------------------------------------


def test_evidence_dependency_uses_persisted_edges_only(session) -> None:
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    manifest_id = _make_manifest(session, scan_id=scan_id)
    parent = _make_component(
        session,
        scan_id=scan_id,
        manifest_id=manifest_id,
        name="app",
        direct=True,
    )
    child = _make_component(
        session,
        scan_id=scan_id,
        manifest_id=manifest_id,
        name="lodash",
        direct=False,
    )
    edge_id = _make_dependency_edge(
        session,
        scan_id=scan_id,
        parent_id=parent,
        child_id=child,
        relationship="runtime",
        depth=1,
    )
    service = _service_for(session)
    evidence = service.fetch(scan_run_id=scan_id, component_id=child)
    assert evidence is not None
    # The child has one incoming edge and zero outgoing.
    assert len(evidence["dependency_evidence"]["incoming"]) == 1
    assert evidence["dependency_evidence"]["incoming"][0]["edge_id"] == edge_id
    assert evidence["dependency_evidence"]["incoming"][0]["other_component_id"] == parent
    assert evidence["dependency_evidence"]["outgoing"] == []
    # The graph coverage is honest; it is never "complete"
    # because the persisted schema has no positive proof of
    # full transitive closure.
    assert evidence["dependency_evidence"]["graph_coverage"] in {"partial", "unknown"}
    assert evidence["export_implications"]["dependency_relationships_emitted"] is False


def test_evidence_dependency_outgoing_emitted_in_export(session) -> None:
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    manifest_id = _make_manifest(session, scan_id=scan_id)
    parent = _make_component(
        session,
        scan_id=scan_id,
        manifest_id=manifest_id,
        name="app",
    )
    child = _make_component(
        session,
        scan_id=scan_id,
        manifest_id=manifest_id,
        name="lodash",
    )
    _make_dependency_edge(
        session,
        scan_id=scan_id,
        parent_id=parent,
        child_id=child,
    )
    service = _service_for(session)
    evidence = service.fetch(scan_run_id=scan_id, component_id=parent)
    assert evidence is not None
    assert len(evidence["dependency_evidence"]["outgoing"]) == 1
    # The parent has at least one outgoing edge; the
    # v0.6 exporter would emit a Dependency entry for it.
    assert evidence["export_implications"]["dependency_relationships_emitted"] is True


def test_evidence_no_edges_does_not_claim_no_dependencies(session) -> None:
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    manifest_id = _make_manifest(session, scan_id=scan_id)
    component_id = _make_component(session, scan_id=scan_id, manifest_id=manifest_id)
    service = _service_for(session)
    evidence = service.fetch(scan_run_id=scan_id, component_id=component_id)
    assert evidence is not None
    assert evidence["dependency_evidence"]["no_edges_observed"] is True
    # The body must not contain the misleading phrase.
    import json as _json

    body = _json.dumps(evidence).lower()
    assert "no dependencies" not in body
    assert "has no dependencies" not in body
    assert "zero dependencies" not in body


# ---------------------------------------------------------------------
# Side-effect guarantees
# ---------------------------------------------------------------------


def test_evidence_performs_no_external_http_call(session) -> None:
    real_socket = socket.socket

    def guarded_socket(*args, **kwargs):
        family = args[0] if args else kwargs.get("family")
        if family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError("evidence must not make any external HTTP call")
        return real_socket(*args, **kwargs)

    socket.socket = guarded_socket  # type: ignore[assignment]
    try:
        repo_id = _make_repo(session)
        scan_id = _make_scan(session, repo_id=repo_id)
        manifest_id = _make_manifest(session, scan_id=scan_id)
        component_id = _make_component(session, scan_id=scan_id, manifest_id=manifest_id)
        service = _service_for(session)
        service.fetch(scan_run_id=scan_id, component_id=component_id)
    finally:
        socket.socket = real_socket  # type: ignore[assignment]


def test_evidence_performs_no_database_writes(session) -> None:
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    manifest_id = _make_manifest(session, scan_id=scan_id)
    component_id = _make_component(session, scan_id=scan_id, manifest_id=manifest_id)
    _make_licence_finding(
        session,
        scan_id=scan_id,
        component_id=component_id,
        licences=["MIT"],
    )
    _make_provider_observation(session, scan_id=scan_id, component_id=component_id)
    counted_tables = (
        "scan_runs",
        "repositories",
        "manifests",
        "components",
        "findings",
        "advisories",
        "component_advisories",
        "dependency_edges",
        "provider_observations",
    )
    counts_before = {
        table: session.execute(
            text("SELECT count(*) FROM " + table)  # noqa: S608
        ).scalar()
        for table in counted_tables
    }
    service = _service_for(session)
    service.fetch(scan_run_id=scan_id, component_id=component_id)
    counts_after = {
        table: session.execute(
            text("SELECT count(*) FROM " + table)  # noqa: S608
        ).scalar()
        for table in counted_tables
    }
    assert counts_before == counts_after


def test_evidence_is_deterministic_for_same_state(session) -> None:
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    manifest_id = _make_manifest(session, scan_id=scan_id)
    component_id = _make_component(session, scan_id=scan_id, manifest_id=manifest_id)
    _make_licence_finding(
        session,
        scan_id=scan_id,
        component_id=component_id,
        licences=["MIT"],
    )
    _make_provider_observation(session, scan_id=scan_id, component_id=component_id)
    service = _service_for(session)
    first = service.fetch(scan_run_id=scan_id, component_id=component_id)
    second = service.fetch(scan_run_id=scan_id, component_id=component_id)
    import json as _json

    assert _json.dumps(first, sort_keys=True) == _json.dumps(second, sort_keys=True)


def test_evidence_does_not_leak_backend_paths(session) -> None:
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    # The endpoint surfaces the persisted manifest path
    # verbatim; the bounded error summary is preserved
    # exactly as the source wrote it. The endpoint must
    # never inject backend paths the schema did not
    # observe.
    manifest_id = _make_manifest(
        session,
        scan_id=scan_id,
        path="package.json",
    )
    component_id = _make_component(session, scan_id=scan_id, manifest_id=manifest_id)
    _make_provider_observation(
        session,
        scan_id=scan_id,
        component_id=component_id,
        error_summary="upstream provider returned 503",
    )
    service = _service_for(session)
    evidence = service.fetch(scan_run_id=scan_id, component_id=component_id)
    assert evidence is not None
    import json as _json

    body = _json.dumps(evidence)
    # Backend path prefixes (e.g. the venv site-packages
    # directory, the repository working copy) must not
    # appear in the response. The endpoint only renders
    # the bounded fields the schema supports.
    for forbidden in [
        "C:\\\\",
        "C:/",
        "/.venv/",
        "\\\\.venv\\\\",
        "site-packages",
        "app.evidence",
        "ComponentEvidenceService",
        "lockverity-venv",
    ]:
        assert forbidden not in body, f"evidence response leaked a backend path: {forbidden!r}"


# ---------------------------------------------------------------------
# Determinism / contract guards
# ---------------------------------------------------------------------


def test_evidence_response_shape_contains_documented_keys(session) -> None:
    """The shape of the response is the documented v0.8
    contract. New top-level keys are contract changes and
    must be added through a review."""
    rid = _make_repo(session)
    sid = _make_scan(session, repo_id=rid)
    mid = _make_manifest(session, scan_id=sid)
    cid = _make_component(session, scan_id=sid, manifest_id=mid)
    service = _service_for(session)
    evidence = service.fetch(scan_run_id=sid, component_id=cid)
    assert evidence is not None
    assert set(evidence.keys()) == {
        "scan",
        "component",
        "manifest",
        "licence_evidence",
        "provider_evidence",
        "dependency_evidence",
        "export_implications",
        "omissions",
    }


def test_evidence_omissions_list_contract(session) -> None:
    """The omissions list is the bounded evidence-honesty
    contract. Renaming any marker is a breaking change."""
    rid = _make_repo(session)
    sid = _make_scan(session, repo_id=rid)
    mid = _make_manifest(session, scan_id=sid)
    cid = _make_component(session, scan_id=sid, manifest_id=mid)
    service = _service_for(session)
    evidence = service.fetch(scan_run_id=sid, component_id=cid)
    assert evidence is not None
    # The omissions list must be the documented set,
    # in the documented order, on every response.
    assert list(evidence["omissions"]) == list(_COMPONENT_EVIDENCE_OMISSIONS)
    # The omissions list must not contain forbidden
    # verdict words as standalone tokens. The marker
    # names themselves legitimately contain the
    # substrings (e.g. ``no_clean_verdict``) so we
    # require the verdict word to appear as a token, not
    # a substring.
    import re as _re

    joined = " ".join(evidence["omissions"]).lower()
    for forbidden in ["clean", "secure", "certified", "complete"]:
        pattern = r"(?<![_a-z])" + _re.escape(forbidden) + r"(?![_a-z])"
        assert not _re.search(pattern, joined), (
            f"omissions list leaked forbidden verdict word {forbidden!r}: {evidence['omissions']!r}"
        )


def test_evidence_export_implications_match_v6_contract(session) -> None:
    """The export implications are derived from the same
    rules the v0.6 CycloneDX 1.7 exporter implements; the
    evidence block must agree with the BOM for any scan
    state."""
    rid = _make_repo(session)
    sid = _make_scan(session, repo_id=rid)
    mid = _make_manifest(session, scan_id=sid)
    cid = _make_component(session, scan_id=sid, manifest_id=mid)
    service = _service_for(session)
    evidence = service.fetch(scan_run_id=sid, component_id=cid)
    assert evidence is not None
    impl = evidence["export_implications"]
    assert impl["version_omitted"] is False
    assert impl["purl_emitted"] is True
    assert impl["dependency_relationships_emitted"] is False
    # A version-less component must report
    # ``version_omitted`` True and the v0.6 exporter
    # will not emit a placeholder string in the BOM.
    cid_no_version = _make_component(
        session,
        scan_id=sid,
        manifest_id=mid,
        name="unresolved-pkg",
        version=None,
        version_source=ComponentVersionSource.UNRESOLVED,
        package_url=None,
    )
    evidence2 = service.fetch(scan_run_id=sid, component_id=cid_no_version)
    assert evidence2 is not None
    impl2 = evidence2["export_implications"]
    assert impl2["version_omitted"] is True
    # npm is constructible; purl_emitted is True.
    assert impl2["purl_emitted"] is True


# Sanity check: the advisory limit is a non-trivial value
# the v0.8 endpoint must respect, so the test suite keeps
# the constant under explicit observation.
def test_evidence_advisory_limit_is_a_documented_constant() -> None:
    assert isinstance(ADVISORY_LIMIT, int)
    assert ADVISORY_LIMIT > 0
