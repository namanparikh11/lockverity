"""v0.9 evidence-aware search and filtering tests.

The tests exercise the free function and the session-lifecycle
service over a small in-memory SQLite database. The fixtures
build a minimal but representative scan: a completed scan with
one manifest, three components (with varied evidence
conditions), optional licence findings, optional provider
observations, and an optional dependency edge.

The negative tests prove the bounded not-found / no-side-effect
rules.
"""

from __future__ import annotations

import json
import socket

import pytest

# Compatibility: the evidence module re-exports the version
# symbol so callers can introspect the running app version
# without an explicit circular import.
from app._version import __version__  # noqa: F401
from app.db.base import Base
from app.evidence.summary import (
    BOOL_VALUES,
    DEFAULT_PAGE_SIZE,
    DIRECT_VALUES,
    EDGE_VALUES,
    MAX_PAGE_SIZE,
    PRESENT_VALUES,
    PURL_VALUES,
    SORT_VALUES,
    ComponentEvidenceSummaryService,
)
from app.models.component import Component, ComponentVersionSource
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

# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest.fixture()
def session():
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
) -> int:
    scan = ScanRun(
        repository_id=repo_id,
        trigger_type=ScanTriggerType.MANUAL,
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
) -> int:
    manifest = Manifest(
        scan_run_id=scan_id,
        path=path,
        manifest_type=manifest_type,
        ecosystem=ecosystem,
        content_sha256="a" * 64,
        parse_status=ManifestParseStatus.PARSED,
    )
    session.add(manifest)
    session.commit()
    return manifest.id


def _make_component(
    session,
    *,
    scan_id: int,
    manifest_id: int,
    name: str,
    version: str | None = "1.0.0",
    direct: bool = True,
    package_url: str | None = "pkg:npm/example@1.0.0",
    ecosystem: str = "npm",
) -> int:
    component = Component(
        scan_run_id=scan_id,
        manifest_id=manifest_id,
        ecosystem=ecosystem,
        package_name=name,
        version=version,
        version_source=(
            ComponentVersionSource.UNRESOLVED
            if version is None
            else ComponentVersionSource.MANIFEST
        ),
        package_url=package_url,
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
) -> int:
    payload = {
        "evidence": {
            "component_id": component_id,
            "licences": licences,
            "source": "rule_engine",
        }
    }
    finding = Finding(
        scan_run_id=scan_id,
        repository_id=_repo_id_for_scan(session, scan_id),
        rule_id="LOCK-LIC-INV",
        category=FindingCategory.LICENCE,
        severity=FindingSeverity.INFORMATIONAL,
        confidence=FindingConfidence.UNKNOWN,
        title="licence observation",
        summary="licence observation",
        stable_key=f"licence:{component_id}",
        evidence_json=json.dumps(payload),
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
) -> int:
    obs = ProviderObservation(
        scan_run_id=scan_id,
        component_id=component_id,
        provider=provider,
        operation="enrich",
        status=status,
        cache_status="miss",
        http_status=200,
        records_returned=0,
    )
    session.add(obs)
    session.commit()
    return obs.id


def _make_dependency_edge(
    session,
    *,
    scan_id: int,
    parent_id: int,
    child_id: int,
) -> int:
    edge = DependencyEdge(
        scan_run_id=scan_id,
        parent_component_id=parent_id,
        child_component_id=child_id,
        relationship="runtime",
        depth=1,
    )
    session.add(edge)
    session.commit()
    return edge.id


def _repo_id_for_scan(session, scan_id: int) -> int:
    return session.execute(
        text("SELECT repository_id FROM scan_runs WHERE id = :sid"),
        {"sid": scan_id},
    ).scalar_one()


def _service_for(session) -> ComponentEvidenceSummaryService:
    session_local = sessionmaker(bind=session.get_bind())
    return ComponentEvidenceSummaryService(session_local)


def _summary_via_service(
    session,
    *,
    scan_id: int,
    **filters,
) -> dict:
    service = _service_for(session)
    return service.fetch(scan_run_id=scan_id, **filters)


# ---------------------------------------------------------------------
# Reference scan fixture: three components with varied evidence
# ---------------------------------------------------------------------


def _setup_reference_scan(session) -> dict[str, int]:
    """Build a small but representative scan.

    The fixture returns the relevant component ids so the
    tests can assert per-row state.

    Components:

    - ``direct_with_everything``: direct, has version,
      persisted PURL, has a licence observation, has a
      provider observation, has an outgoing edge.
    - ``direct_missing_evidence``: direct, has version,
      no persisted PURL, no licence, no provider, no
      edges.
    - ``transitive_missing_version``: transitive, missing
      version, no PURL, no licence, no provider, no edges.
    """
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    manifest_id = _make_manifest(session, scan_id=scan_id)
    direct_full = _make_component(
        session,
        scan_id=scan_id,
        manifest_id=manifest_id,
        name="left-pad",
        direct=True,
        package_url="pkg:npm/left-pad@1.0.0",
    )
    _make_licence_finding(session, scan_id=scan_id, component_id=direct_full, licences=["MIT"])
    _make_provider_observation(session, scan_id=scan_id, component_id=direct_full)
    direct_missing = _make_component(
        session,
        scan_id=scan_id,
        manifest_id=manifest_id,
        name="lodash",
        direct=True,
        package_url=None,
    )
    transitive_no_version = _make_component(
        session,
        scan_id=scan_id,
        manifest_id=manifest_id,
        name="stay",
        version=None,
        direct=False,
        package_url=None,
    )
    # A persisted dependency edge from ``direct_full`` to
    # ``direct_missing``. ``transitive_no_version`` is left
    # without an outgoing edge so the
    # ``none_observed`` filter has at least one matching
    # row.
    _make_dependency_edge(
        session,
        scan_id=scan_id,
        parent_id=direct_full,
        child_id=direct_missing,
    )
    session.commit()
    return {
        "scan_id": scan_id,
        "direct_full": direct_full,
        "direct_missing": direct_missing,
        "transitive_no_version": transitive_no_version,
    }


# ---------------------------------------------------------------------
# Default / pagination / sort
# ---------------------------------------------------------------------


def test_default_summary_returns_all_components_deterministically(
    session,
) -> None:
    ids = _setup_reference_scan(session)
    one = _summary_via_service(session, scan_id=ids["scan_id"])
    two = _summary_via_service(session, scan_id=ids["scan_id"])
    assert one is not None and two is not None
    assert one == two
    # The default sort is package_name; the three
    # components come back in deterministic order.
    names = [it["package_name"] for it in one["items"]]
    assert names == sorted(names, key=str.lower)
    assert one["pagination"]["total"] == 3
    assert one["pagination"]["page"] == 1


def test_pagination_is_stable_and_bounded(session) -> None:
    ids = _setup_reference_scan(session)
    page1 = _summary_via_service(session, scan_id=ids["scan_id"], page=1, page_size=2)
    page2 = _summary_via_service(session, scan_id=ids["scan_id"], page=2, page_size=2)
    assert page1 is not None and page2 is not None
    assert page1["pagination"]["total"] == 3
    assert page1["pagination"]["total_pages"] == 2
    assert len(page1["items"]) == 2
    assert len(page2["items"]) == 1
    # The two pages are disjoint and cover the full set.
    seen_ids = {it["id"] for it in page1["items"]} | {it["id"] for it in page2["items"]}
    assert seen_ids == {
        ids["direct_full"],
        ids["direct_missing"],
        ids["transitive_no_version"],
    }


def test_sort_options_are_deterministic(session) -> None:
    ids = _setup_reference_scan(session)
    for sort_key in SORT_VALUES:
        result = _summary_via_service(session, scan_id=ids["scan_id"], sort=sort_key)
        assert result is not None
        # Every sort returns every component exactly once.
        seen = {it["id"] for it in result["items"]}
        assert seen == {
            ids["direct_full"],
            ids["direct_missing"],
            ids["transitive_no_version"],
        }


def test_version_missing_first_sorts_missing_first(session) -> None:
    ids = _setup_reference_scan(session)
    result = _summary_via_service(
        session,
        scan_id=ids["scan_id"],
        sort="version_missing_first",
    )
    assert result is not None
    first_id = result["items"][0]["id"]
    assert first_id == ids["transitive_no_version"]
    assert result["items"][0]["version"] is None


# ---------------------------------------------------------------------
# Text + categorical filters
# ---------------------------------------------------------------------


def test_text_search_filters_by_package_name(session) -> None:
    ids = _setup_reference_scan(session)
    result = _summary_via_service(session, scan_id=ids["scan_id"], search="left")
    assert result is not None
    assert result["pagination"]["total"] == 1
    assert result["items"][0]["id"] == ids["direct_full"]


def test_text_search_is_case_insensitive(session) -> None:
    ids = _setup_reference_scan(session)
    upper = _summary_via_service(session, scan_id=ids["scan_id"], search="LODASH")
    assert upper is not None
    assert upper["pagination"]["total"] == 1
    assert upper["items"][0]["id"] == ids["direct_missing"]


def test_ecosystem_filter_works(session) -> None:
    ids = _setup_reference_scan(session)
    result = _summary_via_service(session, scan_id=ids["scan_id"], ecosystem="npm")
    assert result is not None
    assert result["pagination"]["total"] == 3
    none = _summary_via_service(session, scan_id=ids["scan_id"], ecosystem="pypi")
    assert none is not None
    assert none["pagination"]["total"] == 0


def test_direct_yes_filter_keeps_only_direct_components(session) -> None:
    ids = _setup_reference_scan(session)
    result = _summary_via_service(session, scan_id=ids["scan_id"], direct="yes")
    assert result is not None
    kept = {it["id"] for it in result["items"]}
    assert kept == {ids["direct_full"], ids["direct_missing"]}


def test_direct_no_filter_keeps_only_transitive_components(session) -> None:
    ids = _setup_reference_scan(session)
    result = _summary_via_service(session, scan_id=ids["scan_id"], direct="no")
    assert result is not None
    kept = {it["id"] for it in result["items"]}
    assert kept == {ids["transitive_no_version"]}


def test_version_missing_filter_does_not_invent_a_placeholder(
    session,
) -> None:
    ids = _setup_reference_scan(session)
    result = _summary_via_service(session, scan_id=ids["scan_id"], version="missing")
    assert result is not None
    assert result["pagination"]["total"] == 1
    only = result["items"][0]
    assert only["id"] == ids["transitive_no_version"]
    assert only["version"] is None
    # The response must never include a placeholder string
    # in the missing-version slot. A grep against the
    # serialised response confirms the contract.
    body = json.dumps(result)
    for forbidden in ['"unspecified"', '"unknown"', '"latest"', '"n/a"']:
        assert forbidden not in body.lower()


def test_licence_evidence_present_filter(session) -> None:
    ids = _setup_reference_scan(session)
    result = _summary_via_service(session, scan_id=ids["scan_id"], licence_evidence="present")
    assert result is not None
    assert result["pagination"]["total"] == 1
    assert result["items"][0]["id"] == ids["direct_full"]


def test_licence_evidence_missing_filter(session) -> None:
    ids = _setup_reference_scan(session)
    result = _summary_via_service(session, scan_id=ids["scan_id"], licence_evidence="missing")
    assert result is not None
    kept = {it["id"] for it in result["items"]}
    assert kept == {ids["direct_missing"], ids["transitive_no_version"]}


def test_provider_evidence_present_filter(session) -> None:
    ids = _setup_reference_scan(session)
    result = _summary_via_service(session, scan_id=ids["scan_id"], provider_evidence="present")
    assert result is not None
    assert result["pagination"]["total"] == 1
    assert result["items"][0]["id"] == ids["direct_full"]


def test_provider_evidence_missing_filter(session) -> None:
    ids = _setup_reference_scan(session)
    result = _summary_via_service(session, scan_id=ids["scan_id"], provider_evidence="missing")
    assert result is not None
    kept = {it["id"] for it in result["items"]}
    assert kept == {ids["direct_missing"], ids["transitive_no_version"]}


def test_purl_persisted_filter(session) -> None:
    ids = _setup_reference_scan(session)
    result = _summary_via_service(session, scan_id=ids["scan_id"], purl="persisted")
    assert result is not None
    assert result["pagination"]["total"] == 1
    assert result["items"][0]["id"] == ids["direct_full"]


def test_purl_constructible_filter(session) -> None:
    ids = _setup_reference_scan(session)
    result = _summary_via_service(session, scan_id=ids["scan_id"], purl="constructible")
    assert result is not None
    kept = {it["id"] for it in result["items"]}
    assert kept == {ids["direct_missing"], ids["transitive_no_version"]}


def test_purl_omitted_filter_for_unsupported_ecosystem(session) -> None:
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    manifest_id = _make_manifest(session, scan_id=scan_id, ecosystem="cargo", path="Cargo.toml")
    component_id = _make_component(
        session,
        scan_id=scan_id,
        manifest_id=manifest_id,
        name="serde",
        ecosystem="cargo",
        package_url=None,
    )
    result = _summary_via_service(session, scan_id=scan_id, purl="omitted")
    assert result is not None
    kept = {it["id"] for it in result["items"]}
    assert kept == {component_id}


def test_dependency_edges_present_filter_uses_persisted_rows_only(
    session,
) -> None:
    ids = _setup_reference_scan(session)
    result = _summary_via_service(session, scan_id=ids["scan_id"], dependency_edges="present")
    assert result is not None
    # Only ``direct_full`` has an outgoing edge.
    assert result["pagination"]["total"] == 1
    assert result["items"][0]["id"] == ids["direct_full"]


def test_dependency_edges_none_observed_filter_does_not_claim_no_dependencies(
    session,
) -> None:
    ids = _setup_reference_scan(session)
    result = _summary_via_service(session, scan_id=ids["scan_id"], dependency_edges="none_observed")
    assert result is not None
    kept = {it["id"] for it in result["items"]}
    assert ids["direct_full"] not in kept
    body = json.dumps(result).lower()
    # The summary must not make the affirmative claim
    # "no dependencies". The wording the endpoint uses
    # is "none_observed", which is bounded and honest.
    assert "no dependencies" not in body


# ---------------------------------------------------------------------
# CycloneDX 1.7 export implication filters
# ---------------------------------------------------------------------


def test_cyclonedx_version_omitted_filter_matches_v6_contract(
    session,
) -> None:
    ids = _setup_reference_scan(session)
    result = _summary_via_service(
        session,
        scan_id=ids["scan_id"],
        cyclonedx_version_omitted="yes",
    )
    assert result is not None
    # Only the component with no version is omitted.
    assert result["pagination"]["total"] == 1
    assert result["items"][0]["id"] == ids["transitive_no_version"]


def test_cyclonedx_relationships_emitted_filter(session) -> None:
    ids = _setup_reference_scan(session)
    result = _summary_via_service(
        session,
        scan_id=ids["scan_id"],
        cyclonedx_relationships_emitted="yes",
    )
    assert result is not None
    # Only ``direct_full`` has an outgoing edge.
    assert result["pagination"]["total"] == 1
    assert result["items"][0]["id"] == ids["direct_full"]


def test_cyclonedx_appears_filter_is_yes_for_every_component(session) -> None:
    ids = _setup_reference_scan(session)
    result = _summary_via_service(
        session,
        scan_id=ids["scan_id"],
        cyclonedx_appears="yes",
    )
    assert result is not None
    assert result["pagination"]["total"] == 3


# ---------------------------------------------------------------------
# Facets
# ---------------------------------------------------------------------


def test_facet_counts_match_filtered_set(session) -> None:
    ids = _setup_reference_scan(session)
    result = _summary_via_service(session, scan_id=ids["scan_id"])
    assert result is not None
    facets = result["facets"]
    # Three npm components, no other ecosystems.
    assert facets["ecosystems"] == {"npm": 3}
    # Exactly one component has a missing version.
    assert facets["missing_version"] == 1
    # Two components have missing licence evidence.
    assert facets["missing_licence_evidence"] == 2
    # Two components have missing provider evidence.
    assert facets["missing_provider_evidence"] == 2
    # One component has a persisted PURL, two are
    # constructible, zero are omitted.
    assert facets["purl_persisted"] == 1
    assert facets["purl_constructible"] == 2
    assert facets["purl_omitted"] == 0
    # One component has an outgoing edge, two do not.
    assert facets["edges_observed"] == 1
    assert facets["edges_none_observed"] == 2
    # Two direct components, one transitive.
    assert facets["direct_yes"] == 2
    assert facets["direct_no"] == 1
    # One component has its version omitted from the
    # CycloneDX 1.7 export.
    assert facets["cyclonedx_version_omitted"] == 1


# ---------------------------------------------------------------------
# Vocabulary guards
# ---------------------------------------------------------------------


def test_summary_vocabulary_is_documented(session) -> None:
    ids = _setup_reference_scan(session)
    result = _summary_via_service(session, scan_id=ids["scan_id"])
    assert result is not None
    # The omissions list is the bounded evidence-honesty
    # contract. Forbidden verdict words must not appear
    # as standalone tokens.
    import re

    joined = " ".join(result["omissions"]).lower()
    for forbidden in ["clean", "secure", "certified", "fixed"]:
        pattern = r"(?<![_a-z])" + re.escape(forbidden) + r"(?![_a-z])"
        assert not re.search(pattern, joined), (
            f"omissions list leaked forbidden verdict word {forbidden!r}"
        )


def test_filter_vocabulary_is_documented() -> None:
    # The filter value sets are the contract; renaming
    # any value is a breaking change.
    assert DIRECT_VALUES == ("all", "yes", "no")
    assert PRESENT_VALUES == ("all", "present", "missing")
    assert PURL_VALUES == ("all", "persisted", "constructible", "omitted")
    assert EDGE_VALUES == ("all", "present", "none_observed")
    assert BOOL_VALUES == ("all", "yes", "no")
    assert DEFAULT_PAGE_SIZE == 50
    assert MAX_PAGE_SIZE == 200


# ---------------------------------------------------------------------
# Side-effect guarantees
# ---------------------------------------------------------------------


def test_endpoint_returns_404_for_unknown_scan(session) -> None:
    service = _service_for(session)
    assert service.fetch(scan_run_id=999_999) is None


def test_summary_performs_no_external_http_call(session) -> None:
    real_socket = socket.socket

    def guarded_socket(*args, **kwargs):
        family = args[0] if args else kwargs.get("family")
        if family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError("summary must not make any external HTTP call")
        return real_socket(*args, **kwargs)

    socket.socket = guarded_socket  # type: ignore[assignment]
    try:
        ids = _setup_reference_scan(session)
        service = _service_for(session)
        service.fetch(scan_run_id=ids["scan_id"])
    finally:
        socket.socket = real_socket  # type: ignore[assignment]


def test_summary_performs_no_database_writes(session) -> None:
    ids = _setup_reference_scan(session)
    counted_tables = (
        "scan_runs",
        "repositories",
        "manifests",
        "components",
        "findings",
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
    # Call every filter combination at least once to
    # confirm no combination writes.
    for direct in DIRECT_VALUES:
        for version in PRESENT_VALUES:
            for lic in PRESENT_VALUES:
                for prov in PRESENT_VALUES:
                    for purl in PURL_VALUES:
                        for edges in EDGE_VALUES:
                            service.fetch(
                                scan_run_id=ids["scan_id"],
                                direct=direct,
                                version=version,
                                licence_evidence=lic,
                                provider_evidence=prov,
                                purl=purl,
                                dependency_edges=edges,
                            )
    counts_after = {
        table: session.execute(
            text("SELECT count(*) FROM " + table)  # noqa: S608
        ).scalar()
        for table in counted_tables
    }
    assert counts_before == counts_after


def test_summary_does_not_leak_backend_paths(session) -> None:
    ids = _setup_reference_scan(session)
    # The summary must not echo any backend file path.
    # The endpoint surfaces only the bounded fields the
    # schema supports (manifest path, package name,
    # version). The endpoint must never include the
    # venv site-packages directory, the running app
    # module path, or any internal class name.
    service = _service_for(session)
    result = service.fetch(scan_run_id=ids["scan_id"])
    assert result is not None
    body = json.dumps(result)
    for forbidden in [
        "C:/",
        "C:\\\\",
        "site-packages",
        "app.evidence",
        "ComponentEvidenceSummaryService",
        "build_component_evidence_summary",
    ]:
        assert forbidden not in body, f"summary response leaked a backend path: {forbidden!r}"


# ---------------------------------------------------------------------
# Combined filters
# ---------------------------------------------------------------------


def test_combined_filters_apply_logical_and(session) -> None:
    ids = _setup_reference_scan(session)
    result = _summary_via_service(
        session,
        scan_id=ids["scan_id"],
        direct="yes",
        version="missing",
    )
    assert result is not None
    # Only ``transitive_no_version`` is missing a
    # version; filtering by ``direct=yes`` therefore
    # yields zero rows (logical AND).
    assert result["pagination"]["total"] == 0
    result2 = _summary_via_service(
        session,
        scan_id=ids["scan_id"],
        direct="no",
        version="missing",
    )
    assert result2 is not None
    assert result2["pagination"]["total"] == 1
    assert result2["items"][0]["id"] == ids["transitive_no_version"]


def test_unknown_filter_value_is_treated_as_no_filter(session) -> None:
    ids = _setup_reference_scan(session)
    # Pass an unknown value; the function must not raise.
    result = _summary_via_service(session, scan_id=ids["scan_id"], direct="not-a-valid-value")
    assert result is not None
    # All three components are returned.
    assert result["pagination"]["total"] == 3
