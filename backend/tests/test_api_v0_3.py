"""API tests for the v0.3 end-to-end scan flow endpoints.

These tests build a scan by writing the data the orchestrator
would have written during a real run, then exercise every new
read endpoint to confirm the shape the v0.3 frontend depends on.

A separate test runs the orchestrator end-to-end against a
fresh intake to confirm the v0.3 pipeline populates the
expected tables.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.db import session as _db_session
from app.main import app
from app.models.component import Component, ComponentVersionSource
from app.models.dependency_edge import DependencyEdge
from app.models.finding import (
    Finding,
    FindingCategory,
    FindingConfidence,
    FindingSeverity,
)
from app.models.manifest import Manifest, ManifestParseStatus
from app.models.scan_run import ScanStatus, ScanTriggerType
from app.models.workspace import WorkspaceKind, WorkspaceState
from app.services import repository_service, scan_service
from app.services.orchestrator_service import ScanOrchestrator
from app.services.workspace_service import WorkspaceService
from app.utils.finding_keys import stable_finding_key
from fastapi.testclient import TestClient


def _setup_scan_with_zip(session, workspace_root: Path, *, include_workflow: bool = False):
    repo = repository_service.create_repository_from_url(
        session, "https://github.com/octocat/Hello-World"
    )
    scan = scan_service.create_scan(
        session, repository_id=repo.id, trigger_type=ScanTriggerType.MANUAL
    )
    workspaces = WorkspaceService(session)
    workspace = workspaces.create_for_scan(scan, kind=WorkspaceKind.GITHUB)
    paths = workspaces.paths_for(workspace.workspace_key)
    paths.contents_dir.mkdir(parents=True, exist_ok=True)
    (paths.contents_dir / "package.json").write_text(
        '{"name":"sample","version":"1.0.0","dependencies":{"left-pad":"^1.0.0"}}',
        encoding="utf-8",
    )
    if include_workflow:
        wf = paths.contents_dir / ".github" / "workflows"
        wf.mkdir(parents=True, exist_ok=True)
        # Use a third-party action that the analyzer will flag as
        # unpinned (``LOCK-WF-001``).
        (wf / "ci.yml").write_text(
            "name: ci\non: pull_request\njobs:\n  build:\n"
            "    runs-on: ubuntu-latest\n    steps:\n"
            "      - uses: third-party/setup-thing@main\n"
            "      - run: echo hi\n",
            encoding="utf-8",
        )
    workspaces.transition(workspace, target=WorkspaceState.VALIDATING)
    workspaces.transition(
        workspace,
        target=WorkspaceState.READY,
        archive_sha256="a" * 64,
        archive_size=200,
        file_count=2,
        uncompressed_size=200,
    )
    return scan.id, repo.id, workspace.workspace_key


def test_components_endpoint_returns_paginated_list(app_config, workspace_root) -> None:
    with _db_session.SessionLocal() as s:
        scan_id, _, _ = _setup_scan_with_zip(s, workspace_root)
        s.commit()
    client = TestClient(app)
    r = client.get(f"/api/v1/scans/{scan_id}/components")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body and "pagination" in body
    # Even an empty component list is a valid response; what
    # matters is the shape.
    assert isinstance(body["items"], list)


def test_vulnerabilities_endpoint_handles_empty_state(app_config, workspace_root) -> None:
    with _db_session.SessionLocal() as s:
        scan_id, _, _ = _setup_scan_with_zip(s, workspace_root)
        s.commit()
    client = TestClient(app)
    r = client.get(f"/api/v1/scans/{scan_id}/vulnerabilities")
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_advisories_endpoint_handles_empty_state(app_config, workspace_root) -> None:
    with _db_session.SessionLocal() as s:
        scan_id, _, _ = _setup_scan_with_zip(s, workspace_root)
        s.commit()
    client = TestClient(app)
    r = client.get(f"/api/v1/scans/{scan_id}/advisories")
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_workflow_findings_endpoint_returns_workflow_category(app_config, workspace_root) -> None:
    with _db_session.SessionLocal() as s:
        scan_id, repo_id, _ = _setup_scan_with_zip(s, workspace_root)
        s.add(
            Finding(
                scan_run_id=scan_id,
                repository_id=repo_id,
                rule_id="LOCK-WF-001",
                category=FindingCategory.WORKFLOW,
                severity=FindingSeverity.HIGH,
                confidence=FindingConfidence.HIGH,
                title="Unpinned third-party action",
                summary="actions/checkout is not pinned to a SHA",
                remediation="Pin to a SHA.",
                location_path=".github/workflows/ci.yml",
                location_start_line=5,
                location_end_line=5,
                stable_key=stable_finding_key("LOCK-WF-001", {"path": ".github/workflows/ci.yml"}),
                evidence_json=json.dumps(
                    {
                        "permissions": [],
                        "triggers": ["pull_request"],
                        "unpinned_actions": ["actions/checkout"],
                        "yaml_path": "$.jobs.build.steps[0].uses",
                        "limitations": [],
                    }
                ),
            )
        )
        s.commit()
    client = TestClient(app)
    r = client.get(f"/api/v1/scans/{scan_id}/workflows")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["rule_id"] == "LOCK-WF-001"
    assert item["workflow_name"] == "ci.yml"
    assert item["triggers"] == ["pull_request"]


def test_licences_endpoint_returns_licence_category(app_config, workspace_root) -> None:
    with _db_session.SessionLocal() as s:
        scan_id, repo_id, _ = _setup_scan_with_zip(s, workspace_root)
        s.add(
            Finding(
                scan_run_id=scan_id,
                repository_id=repo_id,
                rule_id="LOCK-LIC-001",
                category=FindingCategory.LICENCE,
                severity=FindingSeverity.MEDIUM,
                confidence=FindingConfidence.MEDIUM,
                title="Component has no licence assertion",
                summary="left-pad has no licence assertion.",
                stable_key=stable_finding_key("LOCK-LIC-001", {"package_name": "left-pad"}),
                evidence_json=json.dumps(
                    {
                        "evidence": {
                            "package_name": "left-pad",
                            "version": "1.0.0",
                            "licences": [],
                        }
                    }
                ),
            )
        )
        s.commit()
    client = TestClient(app)
    r = client.get(f"/api/v1/scans/{scan_id}/licences")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["package_name"] == "left-pad"
    assert item["review_status"] == "unreviewed"


def test_dependency_path_for_known_component(app_config, workspace_root) -> None:
    with _db_session.SessionLocal() as s:
        scan_id, _repo_id, _ = _setup_scan_with_zip(s, workspace_root)
        manifest = Manifest(
            scan_run_id=scan_id,
            path="package.json",
            manifest_type="package_json",
            ecosystem="npm",
            parse_status=ManifestParseStatus.PARSED,
        )
        s.add(manifest)
        s.flush()
        parent = Component(
            scan_run_id=scan_id,
            manifest_id=manifest.id,
            ecosystem="npm",
            package_name="left-pad",
            version="1.0.0",
            version_source=ComponentVersionSource.LOCKFILE,
            direct=True,
        )
        child = Component(
            scan_run_id=scan_id,
            manifest_id=manifest.id,
            ecosystem="npm",
            package_name="left-pad-deep",
            version="0.0.1",
            version_source=ComponentVersionSource.LOCKFILE,
            direct=False,
        )
        s.add_all([parent, child])
        s.flush()
        s.add(
            DependencyEdge(
                scan_run_id=scan_id,
                parent_component_id=parent.id,
                child_component_id=child.id,
                depth=1,
            )
        )
        s.commit()
        child_id = child.id
    client = TestClient(app)
    r = client.get(f"/api/v1/scans/{scan_id}/components/{child_id}/path")
    assert r.status_code == 200
    body = r.json()
    names = {c["package_name"] for c in body["components"]}
    assert "left-pad" in names
    assert "left-pad-deep" in names


def test_exports_listing_returns_supported_formats(app_config, workspace_root) -> None:
    with _db_session.SessionLocal() as s:
        scan_id, _, _ = _setup_scan_with_zip(s, workspace_root)
        s.commit()
    client = TestClient(app)
    r = client.get(f"/api/v1/scans/{scan_id}/exports")
    assert r.status_code == 200
    body = r.json()
    formats = {item["format"] for item in body["items"]}
    assert formats == {
        "cyclonedx_json",
        "findings_json",
        "findings_csv",
        "sarif_json",
    }
    for item in body["items"]:
        assert item["supported"] is True
        assert item["filename_hint"]
        assert item["content_type"]


def test_export_download_returns_attachment_with_filename(app_config, workspace_root) -> None:
    with _db_session.SessionLocal() as s:
        scan_id, _, _ = _setup_scan_with_zip(s, workspace_root)
        s.commit()
    client = TestClient(app)
    r = client.get(f"/api/v1/scans/{scan_id}/exports/findings_json")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "")
    assert "lockverity-findings.json" in r.headers.get("content-disposition", "")


def test_export_unknown_format_returns_404(app_config, workspace_root) -> None:
    with _db_session.SessionLocal() as s:
        scan_id, _, _ = _setup_scan_with_zip(s, workspace_root)
        s.commit()
    client = TestClient(app)
    r = client.get(f"/api/v1/scans/{scan_id}/exports/spdx_xml")
    assert r.status_code == 404


def test_compare_scans_endpoint_returns_diff(app_config, workspace_root) -> None:
    with _db_session.SessionLocal() as s:
        base_id, repo_id, _ = _setup_scan_with_zip(s, workspace_root)
        # Create a second scan and bump one component.
        head_scan = scan_service.create_scan(
            s, repository_id=repo_id, trigger_type=ScanTriggerType.MANUAL
        )
        head_id = head_scan.id
        manifest = Manifest(
            scan_run_id=head_id,
            path="package.json",
            manifest_type="package_json",
            ecosystem="npm",
            parse_status=ManifestParseStatus.PARSED,
        )
        s.add(manifest)
        s.flush()
        s.add(
            Component(
                scan_run_id=head_id,
                manifest_id=manifest.id,
                ecosystem="npm",
                package_name="left-pad",
                version="2.0.0",
                version_source=ComponentVersionSource.LOCKFILE,
                direct=True,
            )
        )
        s.commit()
    client = TestClient(app)
    r = client.get(f"/api/v1/scans/{head_id}/compare/{base_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["base_scan_id"] == base_id
    assert body["head_scan_id"] == head_id
    assert body["repository_id"] == repo_id
    assert isinstance(body["components"], list)
    # We added a manifest with a component; the comparison
    # should at least show the head scan's findings.
    assert isinstance(body["findings"], list)


def test_compare_scans_rejects_different_repositories(app_config, workspace_root) -> None:
    with _db_session.SessionLocal() as s:
        # Two scans on two different repositories.
        scan1, repo1, _ = _setup_scan_with_zip(s, workspace_root)
        scan2 = scan_service.create_scan(
            s, repository_id=repo1, trigger_type=ScanTriggerType.MANUAL
        )
        # Make scan2 belong to a different repo.
        repo2 = repository_service.create_repository_from_url(
            s, "https://github.com/anthropics/anthropic-sdk-python"
        )
        scan2.repository_id = repo2.id
        s.commit()
    client = TestClient(app)
    r = client.get(f"/api/v1/scans/{scan2.id}/compare/{scan1}")
    assert r.status_code in {400, 422}


def test_orchestrator_end_to_end_pipeline_writes_components(app_config, workspace_root) -> None:
    """A real orchestrator run should write components for the discovered manifests.

    v0.4 honesty fix: the scan may finish as ``partial`` if
    the provider network is unavailable. The previous
    v0.3 baseline asserted ``completed`` because the
    state machine laundered provider-unavailable stages
    through ``COMPLETED``. The v0.4 contract accepts
    either ``completed`` (all providers reachable) or
    ``partial`` (a provider-backed stage saw an
    unavailable observation); both shapes are truthful
    given the network state of the test environment.
    """
    with _db_session.SessionLocal() as s:
        scan_id, _, _ = _setup_scan_with_zip(s, workspace_root, include_workflow=True)
        s.commit()
    orchestrator = ScanOrchestrator(_db_session.SessionLocal)
    outcome = orchestrator.run(scan_id)
    assert outcome.final_status in {ScanStatus.COMPLETED, ScanStatus.PARTIAL}, (
        f"v0.4 honest failure semantics: a scan with unavailable "
        f"provider data must finish 'partial', not 'failed'; "
        f"got {outcome.final_status!r}"
    )
    # The orchestrator should have at least one component row
    # for the left-pad dependency declared in package.json.
    with _db_session.SessionLocal() as s:
        rows = s.query(Component).filter(Component.scan_run_id == scan_id).all()
        names = {r.package_name for r in rows}
        assert "left-pad" in names, names
    # And the workflow analyzer should have produced at least
    # one workflow finding for the unpinned action.
    client = TestClient(app)
    r = client.get(f"/api/v1/scans/{scan_id}/workflows")
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(item["rule_id"] == "LOCK-WF-001" for item in items), items
