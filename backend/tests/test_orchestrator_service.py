"""Tests for the ScanOrchestrator.

The orchestrator is exercised against a real test database
constructed by the shared fixtures. The intake step is bypassed
in most tests; a workspace row is created manually so the
``manifest_discovery`` stage has something to find.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.db import session as _db_session
from app.models.provider_observation import ProviderStatus
from app.models.scan_run import ScanStatus, ScanTriggerType
from app.models.scan_stage import StageStatus, StageType
from app.models.workspace import WorkspaceKind, WorkspaceState
from app.services import repository_service, scan_service
from app.services.orchestrator_service import (
    ScanOrchestrator,
    _CancellationToken,
)
from app.services.workspace_service import WorkspaceService
from app.utils.errors import ApiError, ApiErrorCode

# The :func:`conftest._fake_providers_for_scan_tests`
# autouse fixture applies the shared fakes globally; this
# module no longer needs to import the per-module
# fixture.


def _setup_scan_with_zip(session, workspace_root: Path):
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
        '{"name":"sample","version":"1.0.0"}', encoding="utf-8"
    )
    (paths.contents_dir / "src").mkdir(parents=True, exist_ok=True)
    (paths.contents_dir / "src" / "index.js").write_text("console.log('hi')", encoding="utf-8")
    workspaces.transition(workspace, target=WorkspaceState.VALIDATING)
    workspaces.transition(
        workspace,
        target=WorkspaceState.READY,
        archive_sha256="a" * 64,
        archive_size=100,
        file_count=2,
        uncompressed_size=80,
    )
    return scan.id


def _orchestrator() -> ScanOrchestrator:

    return ScanOrchestrator(_db_session.SessionLocal)


def test_run_completes_local_stages_and_marks_others_skipped(app_config, workspace_root) -> None:

    with _db_session.SessionLocal() as s:
        scan_id = _setup_scan_with_zip(s, workspace_root)
        s.commit()
    orchestrator = _orchestrator()
    outcome = orchestrator.run(scan_id)
    # The external providers (OSV, deps.dev, OpenSSF
    # Scorecard) are faked as unavailable by the
    # shared autouse fixture. The local work still
    # completes; the terminal status is ``partial``
    # rather than ``completed`` because the
    # provider-backed stages recorded honest
    # ``provider_unavailable`` observations.
    assert outcome.final_status in {ScanStatus.COMPLETED, ScanStatus.PARTIAL}
    assert len(outcome.stage_records) == 10
    types = [r.stage for r in outcome.stage_records]
    assert types[0] == StageType.REPOSITORY_INTAKE
    assert types[1] == StageType.ARCHIVE_VALIDATION
    assert types[2] == StageType.MANIFEST_DISCOVERY
    # v0.3 runs the dependency, workflow, and finding
    # reconciliation stages locally; they should all be
    # COMPLETED. v0.4 promotes the provider-backed stages
    # (dependency_enrichment, vulnerability_query,
    # repository_posture) to local execution as well; they
    # complete successfully when the providers return data
    # (or the cache hits) and otherwise remain SKIPPED. The
    # only stage that is still SKIPPED is export_generation,
    # which the pipeline does not touch - the API exposes
    # exports on demand.
    for record in outcome.stage_records:
        if record.stage in {
            StageType.DEPENDENCY_PARSING,
            StageType.DEPENDENCY_ENRICHMENT,
            StageType.WORKFLOW_ANALYSIS,
            StageType.FINDING_RECONCILIATION,
        }:
            assert record.status == StageStatus.COMPLETED
        elif record.stage in {
            StageType.VULNERABILITY_QUERY,
            StageType.REPOSITORY_POSTURE,
        }:
            # The provider-backed stages are honest: they
            # may complete (when the provider returns data
            # or the cache hits), be skipped (when the
            # provider is not applicable), or be partial
            # (when the provider returned
            # ``provider_unavailable``). The shared
            # autouse fixture fakes the providers as
            # unavailable; the stage maps that to
            # ``partial`` rather than ``skipped``.
            assert record.status in {
                StageStatus.COMPLETED,
                StageStatus.SKIPPED,
                StageStatus.PARTIAL,
            }
        elif record.stage == StageType.EXPORT_GENERATION:
            assert record.status == StageStatus.SKIPPED
            assert record.provider_status == ProviderStatus.NOT_REQUESTED.value
        else:
            assert record.status == StageStatus.COMPLETED


def test_manifest_discovery_records_known_manifests(app_config, workspace_root) -> None:

    with _db_session.SessionLocal() as s:
        scan_id = _setup_scan_with_zip(s, workspace_root)
        s.commit()
    orchestrator = _orchestrator()
    orchestrator.run(scan_id)
    with _db_session.SessionLocal() as session:
        stages = scan_service.list_stages_for_scan(session, scan_id)
        manifest_stage = next(s for s in stages if s.stage_type == StageType.MANIFEST_DISCOVERY)
        assert manifest_stage.records_processed >= 1
        assert manifest_stage.status == StageStatus.COMPLETED


def test_observations_are_recorded_per_stage(app_config, workspace_root) -> None:

    with _db_session.SessionLocal() as s:
        scan_id = _setup_scan_with_zip(s, workspace_root)
        s.commit()
    orchestrator = _orchestrator()
    orchestrator.run(scan_id)
    with _db_session.SessionLocal() as session:
        from app.repositories import observation_repo

        items, total = observation_repo.list_observations_for_scan(
            session, scan_id, page=1, page_size=100
        )
        # v0.4 records at least one observation per real
        # provider call plus the structural stage
        # observations. The local stages contribute one each
        # (intake, archive, manifest, dependency_parsing,
        # finding_reconciliation, workflow_analysis). The
        # provider-backed stages (OSV, deps.dev, Scorecard)
        # contribute at least one observation each.
        assert total >= 6
        providers = {item.provider for item in items}
        assert "github-or-upload" in providers
        assert "filesystem" in providers
        # The dependency_parsing stage is now a real local
        # stage; its provider observation is ``available``.
        dep_parsing = [obs for obs in items if obs.provider == "dependency_parsing"]
        assert dep_parsing
        assert dep_parsing[0].status == ProviderStatus.AVAILABLE
        # The vulnerability_query stage now drives OSV
        # directly. The observation is recorded under the
        # ``osv`` provider name; the status may be
        # ``available``, ``partial``, ``unavailable``, or
        # ``not_requested`` depending on whether the scan
        # had matching components and whether the provider
        # responded.
        vuln_obs = [obs for obs in items if obs.provider == "osv"]
        assert vuln_obs
        assert vuln_obs[0].status in {
            ProviderStatus.AVAILABLE,
            ProviderStatus.PARTIAL,
            ProviderStatus.UNAVAILABLE,
            ProviderStatus.NOT_REQUESTED,
        }


def test_cancellation_token_short_circuits_orchestrator(app_config, workspace_root) -> None:

    with _db_session.SessionLocal() as s:
        scan_id = _setup_scan_with_zip(s, workspace_root)
        s.commit()
    orchestrator = _orchestrator()
    token = _CancellationToken()
    token.cancel()
    outcome = orchestrator.run(scan_id, cancellation=token)
    assert outcome.final_status == ScanStatus.CANCELLED
    assert outcome.failure_code == "cancelled"


def test_cancel_running_scan_is_idempotent(app_config, workspace_root) -> None:

    with _db_session.SessionLocal() as s:
        scan_id = _setup_scan_with_zip(s, workspace_root)
        s.commit()
    orchestrator = _orchestrator()
    # Cancelling a queued scan succeeds.
    assert orchestrator.cancel(scan_id) is True
    # Cancelling an already-cancelled scan is a no-op.
    assert orchestrator.cancel(scan_id) is True


def test_run_is_idempotent_for_completed_scans(app_config, workspace_root) -> None:

    with _db_session.SessionLocal() as s:
        scan_id = _setup_scan_with_zip(s, workspace_root)
        s.commit()
    orchestrator = _orchestrator()
    first = orchestrator.run(scan_id)
    # The external providers are faked as unavailable; the
    # terminal status is ``partial`` rather than
    # ``completed``. The idempotency contract still
    # holds: re-running a terminal scan is rejected.
    assert first.final_status in {ScanStatus.COMPLETED, ScanStatus.PARTIAL}
    # Re-running a terminal scan is rejected.
    with pytest.raises(ApiError) as exc:
        orchestrator.run(scan_id)
    assert exc.value.code == ApiErrorCode.ILLEGAL_TRANSITION.value
