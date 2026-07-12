"""Tests for the WorkspaceService."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.models.scan_run import ScanStatus, ScanTriggerType
from app.models.workspace import WorkspaceKind, WorkspaceState
from app.services import repository_service, scan_service
from app.services.workspace_service import (
    WorkspaceService,
    assert_legal_workspace_transition,
)
from app.utils.errors import ApiError, ApiErrorCode


def _setup(session, workspace_root: Path):
    repo = repository_service.create_repository_from_url(
        session, "https://github.com/octocat/Hello-World"
    )
    scan = scan_service.create_scan(
        session, repository_id=repo.id, trigger_type=ScanTriggerType.MANUAL
    )
    return repo, scan


def test_create_for_scan_yields_unique_workspace(session, workspace_root) -> None:
    _repo, scan = _setup(session, workspace_root)
    workspaces = WorkspaceService(session)
    workspace = workspaces.create_for_scan(scan, kind=WorkspaceKind.GITHUB)
    assert workspace.scan_run_id == scan.id
    assert workspace.state == WorkspaceState.QUARANTINED
    assert workspace.workspace_key
    assert (workspaces.root / "workspaces" / workspace.workspace_key).exists()


def test_create_for_scan_is_idempotent(session, workspace_root) -> None:
    _repo, scan = _setup(session, workspace_root)
    workspaces = WorkspaceService(session)
    a = workspaces.create_for_scan(scan, kind=WorkspaceKind.GITHUB)
    b = workspaces.create_for_scan(scan, kind=WorkspaceKind.GITHUB)
    assert a.id == b.id


def test_transition_to_validating(session, workspace_root) -> None:
    _repo, scan = _setup(session, workspace_root)
    workspaces = WorkspaceService(session)
    workspace = workspaces.create_for_scan(scan, kind=WorkspaceKind.UPLOADED_ARCHIVE)
    workspaces.transition(workspace, target=WorkspaceState.VALIDATING)
    assert workspace.state == WorkspaceState.VALIDATING


def test_transition_to_ready_records_sha_and_size(session, workspace_root) -> None:
    _repo, scan = _setup(session, workspace_root)
    workspaces = WorkspaceService(session)
    workspace = workspaces.create_for_scan(scan, kind=WorkspaceKind.GITHUB)
    workspaces.transition(workspace, target=WorkspaceState.VALIDATING)
    workspaces.transition(
        workspace,
        target=WorkspaceState.READY,
        archive_sha256="a" * 64,
        archive_size=1024,
        file_count=2,
        uncompressed_size=2048,
    )
    assert workspace.archive_sha256 == "a" * 64
    assert workspace.archive_size == 1024
    assert workspace.file_count == 2
    assert workspace.uncompressed_size == 2048
    assert workspace.ready_at is not None


def test_cleanup_removes_workspace_directory(session, workspace_root) -> None:
    _repo, scan = _setup(session, workspace_root)
    workspaces = WorkspaceService(session)
    workspace = workspaces.create_for_scan(scan, kind=WorkspaceKind.GITHUB)
    workspaces.transition(workspace, target=WorkspaceState.VALIDATING)
    workspaces.transition(workspace, target=WorkspaceState.READY, archive_sha256="x" * 64)
    paths = workspaces.paths_for(workspace.workspace_key)
    assert paths.workspace_dir.exists()
    workspaces.cleanup(workspace)
    assert not paths.workspace_dir.exists()
    assert workspace.state == WorkspaceState.CLEANED_UP


def test_cleanup_stale_removes_old_quarantined_workspaces(session, workspace_root) -> None:
    from datetime import timedelta

    from app.utils.datetime import utcnow

    _repo, scan = _setup(session, workspace_root)
    workspaces = WorkspaceService(session)
    workspace = workspaces.create_for_scan(scan, kind=WorkspaceKind.GITHUB)
    # Backdate the workspace so it looks stale. The scan is
    # still ``queued``, so we mark it as a failed state to make
    # ``cleanup_stale`` eligible to remove the workspace.
    scan.status = ScanStatus.FAILED
    workspace.updated_at = utcnow() - timedelta(seconds=10_000)
    session.commit()
    removed = workspaces.cleanup_stale()
    assert removed == 1
    assert workspace.state == WorkspaceState.CLEANED_UP


def test_cleanup_failed_scans_removes_terminal_workspace_workspaces(
    session, workspace_root
) -> None:
    _repo, scan = _setup(session, workspace_root)
    workspaces = WorkspaceService(session)
    workspace = workspaces.create_for_scan(scan, kind=WorkspaceKind.GITHUB)
    workspaces.transition(workspace, target=WorkspaceState.VALIDATING)
    workspaces.transition(workspace, target=WorkspaceState.READY, archive_sha256="x" * 64)
    # Mark the scan as FAILED.
    scan_service.transition_scan(session, scan.id, target=ScanStatus.RUNNING)
    scan_service.transition_scan(
        session, scan.id, target=ScanStatus.FAILED, failure_code="manual", failure_summary="x"
    )
    removed = workspaces.cleanup_failed_scans()
    assert removed == 1


def test_assert_legal_workspace_transition_rejects_invalid_jump() -> None:
    # The legal jump is quarantined -> validating, not
    # quarantined -> ready.
    assert_legal_workspace_transition(WorkspaceState.QUARANTINED, WorkspaceState.VALIDATING)
    with pytest.raises(ApiError) as exc:
        assert_legal_workspace_transition(WorkspaceState.QUARANTINED, WorkspaceState.READY)
    assert exc.value.code == ApiErrorCode.ILLEGAL_TRANSITION.value


def test_get_or_404_raises_for_missing_key(session, workspace_root) -> None:
    workspaces = WorkspaceService(session)
    with pytest.raises(ApiError) as exc:
        workspaces.get_or_404("does-not-exist-key")
    assert exc.value.code == ApiErrorCode.NOT_FOUND.value


def test_get_for_scan_raises_when_no_workspace(session, workspace_root) -> None:
    _repo, scan = _setup(session, workspace_root)
    workspaces = WorkspaceService(session)
    with pytest.raises(ApiError):
        workspaces.get_for_scan(scan.id)


def test_paths_for_returns_deterministic_layout(session, workspace_root) -> None:
    workspaces = WorkspaceService(session)
    paths = workspaces.paths_for("a" * 24)
    expected_root = workspaces.root
    assert paths.workspace_dir == expected_root / "workspaces" / ("a" * 24)
    assert paths.quarantine_dir == paths.workspace_dir / "quarantine"
    assert paths.contents_dir == paths.workspace_dir / "contents"
