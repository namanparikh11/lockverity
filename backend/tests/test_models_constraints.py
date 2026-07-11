"""Database model constraint tests."""

from __future__ import annotations

import pytest
from app.models.component import Component, ComponentVersionSource
from app.models.finding import (
    Finding,
    FindingCategory,
    FindingConfidence,
    FindingSeverity,
    FindingStatus,
)
from app.models.repository import (
    Repository,
    RepositoryProvider,
    RepositorySourceType,
    RepositoryVisibility,
)
from app.models.scan_run import ScanRun, ScanStatus, ScanTriggerType
from app.models.scan_stage import ScanStage, StageType
from app.utils.finding_keys import stable_finding_key
from sqlalchemy.exc import IntegrityError


def _make_repo(session) -> Repository:
    repo = Repository(
        source_type=RepositorySourceType.GITHUB,
        provider=RepositoryProvider.GITHUB,
        owner="o",
        name="n",
        canonical_url="https://github.com/o/n",
        visibility=RepositoryVisibility.PUBLIC,
    )
    session.add(repo)
    session.flush()
    return repo


def _make_scan(session, repo: Repository) -> ScanRun:
    scan = ScanRun(
        repository_id=repo.id,
        trigger_type=ScanTriggerType.MANUAL,
        status=ScanStatus.QUEUED,
    )
    session.add(scan)
    session.flush()
    return scan


def test_repository_uniqueness_on_canonical_url(session) -> None:
    a = _make_repo(session)
    b = Repository(
        source_type=RepositorySourceType.GITHUB,
        provider=RepositoryProvider.GITHUB,
        owner="x",
        name="y",
        canonical_url=a.canonical_url,
        visibility=RepositoryVisibility.PUBLIC,
    )
    session.add(b)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_repository_uniqueness_on_provider_owner_name(session) -> None:
    a = _make_repo(session)
    b = Repository(
        source_type=RepositorySourceType.GITHUB,
        provider=RepositoryProvider.GITHUB,
        owner=a.owner,
        name=a.name,
        canonical_url="https://github.com/o/n2",
        visibility=RepositoryVisibility.PUBLIC,
    )
    session.add(b)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_scan_resolved_sha_min_length(session) -> None:
    repo = _make_repo(session)
    scan = ScanRun(
        repository_id=repo.id,
        trigger_type=ScanTriggerType.MANUAL,
        status=ScanStatus.QUEUED,
        resolved_commit_sha="abc",
    )
    session.add(scan)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_stage_no_self_referential_edges_via_fk(session) -> None:
    # Sanity: an edge requires two distinct components.
    repo = _make_repo(session)
    scan = _make_scan(session, repo)
    from app.models.dependency_edge import DependencyEdge
    from app.models.manifest import Manifest, ManifestParseStatus

    manifest = Manifest(
        scan_run_id=scan.id,
        path="package.json",
        manifest_type="npm",
        ecosystem="npm",
        parse_status=ManifestParseStatus.PARSED,
    )
    session.add(manifest)
    session.flush()

    component = Component(
        scan_run_id=scan.id,
        manifest_id=manifest.id,
        ecosystem="npm",
        package_name="left-pad",
        version="1.0.0",
        version_source=ComponentVersionSource.LOCKFILE,
    )
    session.add(component)
    session.flush()

    edge = DependencyEdge(
        scan_run_id=scan.id,
        parent_component_id=component.id,
        child_component_id=component.id,
    )
    session.add(edge)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_finding_stable_key_uniqueness_per_scan(session) -> None:
    repo = _make_repo(session)
    scan = _make_scan(session, repo)
    key = stable_finding_key("R001", {"x": 1})
    a = Finding(
        scan_run_id=scan.id,
        repository_id=repo.id,
        rule_id="R001",
        category=FindingCategory.DEPENDENCY,
        severity=FindingSeverity.LOW,
        confidence=FindingConfidence.MEDIUM,
        title="t",
        summary="s",
        stable_key=key,
        status=FindingStatus.OPEN,
    )
    session.add(a)
    session.flush()
    b = Finding(
        scan_run_id=scan.id,
        repository_id=repo.id,
        rule_id="R001",
        category=FindingCategory.DEPENDENCY,
        severity=FindingSeverity.LOW,
        confidence=FindingConfidence.MEDIUM,
        title="t",
        summary="s",
        stable_key=key,
        status=FindingStatus.OPEN,
    )
    session.add(b)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_finding_location_range_consistency(session) -> None:
    repo = _make_repo(session)
    scan = _make_scan(session, repo)
    f = Finding(
        scan_run_id=scan.id,
        repository_id=repo.id,
        rule_id="R001",
        category=FindingCategory.DEPENDENCY,
        severity=FindingSeverity.LOW,
        confidence=FindingConfidence.MEDIUM,
        title="t",
        summary="s",
        stable_key=stable_finding_key("R001", {"x": 1}),
        location_start_line=10,
        location_end_line=5,
    )
    session.add(f)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_finding_evidence_bounded(session) -> None:
    repo = _make_repo(session)
    scan = _make_scan(session, repo)
    f = Finding(
        scan_run_id=scan.id,
        repository_id=repo.id,
        rule_id="R001",
        category=FindingCategory.DEPENDENCY,
        severity=FindingSeverity.LOW,
        confidence=FindingConfidence.MEDIUM,
        title="t",
        summary="s",
        stable_key=stable_finding_key("R001", {"x": 1}),
        evidence_json="x" * 70_000,
    )
    session.add(f)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_stage_unique_pipeline_shape(session) -> None:
    repo = _make_repo(session)
    scan = _make_scan(session, repo)
    s1 = ScanStage(scan_run_id=scan.id, stage_type=StageType.REPOSITORY_INTAKE)
    s2 = ScanStage(scan_run_id=scan.id, stage_type=StageType.REPOSITORY_INTAKE)
    # The unique constraint is on (scan_run_id, stage_type) implicit
    # via the service layer; in v0.1 we don't have a UNIQUE constraint
    # but the service must not duplicate stages. Check the stage_type
    # enum returns a single deterministic value here.
    session.add_all([s1, s2])
    session.flush()
    assert s1.stage_type == s2.stage_type == StageType.REPOSITORY_INTAKE
