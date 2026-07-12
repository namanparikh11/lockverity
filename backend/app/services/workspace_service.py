"""Workspace lifecycle service.

The :class:`WorkspaceService` owns the on-disk layout and the
state transitions for a workspace. A workspace moves through:

- ``quarantined`` (bytes on disk, not yet validated)
- ``validating`` (validation in progress)
- ``ready`` (extraction succeeded)
- ``failed`` (validation or extraction failed)
- ``cleaned_up`` (the on-disk layout has been removed)

The service never returns an absolute filesystem path. The
*workspace_key* is the only handle the rest of the application
sees; the service resolves it on demand.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.scan_run import ScanRun
from app.models.workspace import Workspace, WorkspaceKind, WorkspaceState
from app.repositories import scan_repo, workspace_repo
from app.utils.datetime import utcnow
from app.utils.errors import ApiError, ApiErrorCode
from app.utils.zip_intake import (
    WorkspacePaths,
    cleanup_workspace,
    create_workspace_paths,
    new_workspace_key,
)

logger = logging.getLogger("lockverity.workspace")

# Allowed forward transitions; the service layer asserts them.
_WORKSPACE_TRANSITIONS: dict[WorkspaceState, frozenset[WorkspaceState]] = {
    WorkspaceState.QUARANTINED: frozenset(
        {WorkspaceState.VALIDATING, WorkspaceState.FAILED, WorkspaceState.CLEANED_UP}
    ),
    WorkspaceState.VALIDATING: frozenset(
        {WorkspaceState.READY, WorkspaceState.FAILED, WorkspaceState.CLEANED_UP}
    ),
    WorkspaceState.READY: frozenset({WorkspaceState.CLEANED_UP}),
    WorkspaceState.FAILED: frozenset({WorkspaceState.CLEANED_UP}),
    WorkspaceState.CLEANED_UP: frozenset(),
}


def assert_legal_workspace_transition(current: WorkspaceState, target: WorkspaceState) -> None:
    legal = _WORKSPACE_TRANSITIONS.get(current, frozenset())
    if target not in legal:
        raise ApiError(
            ApiErrorCode.ILLEGAL_TRANSITION,
            "Illegal workspace state transition.",
            details={
                "current_state": current.value,
                "target_state": target.value,
                "allowed": sorted(s.value for s in legal),
            },
        )


@dataclass(frozen=True, slots=True)
class WorkspaceRead:
    """The safe metadata view of a workspace."""

    id: int
    scan_run_id: int
    workspace_key: str
    kind: WorkspaceKind
    state: WorkspaceState
    archive_filename: str | None
    archive_sha256: str | None
    archive_size: int
    file_count: int
    uncompressed_size: int
    failure_code: str | None
    failure_summary: str | None
    ready_at: object | None
    cleaned_up_at: object | None
    created_at: object
    updated_at: object


def _to_read(workspace: Workspace) -> WorkspaceRead:
    return WorkspaceRead(
        id=workspace.id,
        scan_run_id=workspace.scan_run_id,
        workspace_key=workspace.workspace_key,
        kind=workspace.kind,
        state=workspace.state,
        archive_filename=workspace.archive_filename,
        archive_sha256=workspace.archive_sha256,
        archive_size=workspace.archive_size,
        file_count=workspace.file_count,
        uncompressed_size=workspace.uncompressed_size,
        failure_code=workspace.failure_code,
        failure_summary=workspace.failure_summary,
        ready_at=workspace.ready_at,
        cleaned_up_at=workspace.cleaned_up_at,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
    )


class WorkspaceService:
    """All workspace lifecycle operations."""

    def __init__(
        self,
        session: Session,
        *,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()

    # ------------------------------------------------------------------
    # Properties / lookups
    # ------------------------------------------------------------------
    @property
    def root(self) -> Path:
        return Path(self._settings.workspace_root).resolve()

    def paths_for(self, workspace_key: str) -> WorkspacePaths:
        return create_workspace_paths(self.root, workspace_key)

    def get_or_404(self, workspace_key: str) -> Workspace:
        workspace = workspace_repo.get_by_key(self._session, workspace_key)
        if workspace is None:
            raise ApiError(
                ApiErrorCode.NOT_FOUND,
                "Workspace not found.",
                details={"workspace_key_len": len(workspace_key)},
            )
        return workspace

    def get_for_scan(self, scan_id: int) -> Workspace:
        workspace = workspace_repo.get_for_scan(self._session, scan_id)
        if workspace is None:
            raise ApiError(
                ApiErrorCode.NOT_FOUND,
                "No workspace is associated with this scan.",
                details={"scan_id": scan_id},
            )
        return workspace

    def to_read(self, workspace: Workspace) -> WorkspaceRead:
        return _to_read(workspace)

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------
    def create_for_scan(
        self,
        scan: ScanRun,
        *,
        kind: WorkspaceKind,
        archive_filename: str | None = None,
    ) -> Workspace:
        """Create a fresh workspace for ``scan`` and return the row."""
        existing = workspace_repo.get_for_scan(self._session, scan.id)
        if existing is not None:
            # Idempotency: a scan always has at most one workspace.
            return existing
        workspace_key = new_workspace_key()
        workspace = workspace_repo.create(
            self._session,
            scan_run_id=scan.id,
            workspace_key=workspace_key,
            kind=kind,
            archive_filename=archive_filename,
        )
        # Pre-create the on-disk layout so the path is known.
        self.paths_for(workspace_key).ensure()
        self._session.flush()
        return workspace

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------
    def transition(
        self,
        workspace: Workspace,
        *,
        target: WorkspaceState,
        archive_sha256: str | None = None,
        archive_size: int | None = None,
        file_count: int | None = None,
        uncompressed_size: int | None = None,
        failure_code: str | None = None,
        failure_summary: str | None = None,
    ) -> Workspace:
        assert_legal_workspace_transition(workspace.state, target)
        workspace.state = target
        now = utcnow()
        if archive_sha256 is not None:
            workspace.archive_sha256 = archive_sha256
        if archive_size is not None:
            workspace.archive_size = archive_size
        if file_count is not None:
            workspace.file_count = file_count
        if uncompressed_size is not None:
            workspace.uncompressed_size = uncompressed_size
        if failure_code is not None:
            workspace.failure_code = failure_code
        if failure_summary is not None:
            workspace.failure_summary = failure_summary[:2048]
        if target == WorkspaceState.READY and workspace.ready_at is None:
            workspace.ready_at = now
        if target == WorkspaceState.CLEANED_UP and workspace.cleaned_up_at is None:
            workspace.cleaned_up_at = now
        self._session.flush()
        return workspace

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def cleanup(self, workspace: Workspace) -> Workspace:
        """Remove the on-disk layout and mark the workspace cleaned."""
        paths = self.paths_for(workspace.workspace_key)
        cleanup_workspace(paths)
        if workspace.state in {
            WorkspaceState.QUARANTINED,
            WorkspaceState.VALIDATING,
            WorkspaceState.READY,
            WorkspaceState.FAILED,
        }:
            return self.transition(workspace, target=WorkspaceState.CLEANED_UP)
        return workspace

    def cleanup_many(self, workspaces: Iterable[Workspace]) -> int:
        removed = 0
        for workspace in workspaces:
            self.cleanup(workspace)
            removed += 1
        return removed

    def cleanup_failed_scans(self) -> int:
        from app.models.scan_run import ScanStatus

        failed_scans = scan_repo.list_scans_by_status(
            self._session,
            [
                ScanStatus.FAILED,
                ScanStatus.CANCELLED,
            ],
        )
        removed = 0
        for scan in failed_scans:
            workspace = workspace_repo.get_for_scan(self._session, scan.id)
            if workspace is None or workspace.state == WorkspaceState.CLEANED_UP:
                continue
            self.cleanup(workspace)
            removed += 1
        return removed

    def cleanup_stale(self) -> int:
        from app.models.scan_run import ScanStatus

        threshold_states = [
            WorkspaceState.QUARANTINED,
            WorkspaceState.VALIDATING,
        ]
        workspaces = workspace_repo.list_states(self._session, states=threshold_states)
        # The orchestrator will treat any workspace older than a
        # small threshold as stale. We treat anything in
        # ``quarantined`` or ``validating`` that is older than
        # the configured heartbeat timeout as stale.
        from datetime import timedelta

        from app.utils.datetime import ensure_utc, utcnow

        threshold = utcnow() - timedelta(seconds=self._settings.scan_heartbeat_timeout_seconds)
        removed = 0
        for workspace in workspaces:
            updated_at = ensure_utc(workspace.updated_at)
            if updated_at >= threshold:
                continue
            # Only clean up if the owning scan is no longer
            # running. We accept scans in any terminal state, or
            # scans that have been queued for too long.
            scan = scan_repo.get_scan_by_id(self._session, workspace.scan_run_id)
            if scan is None:
                self.cleanup(workspace)
                removed += 1
                continue
            if scan.status in {
                ScanStatus.QUEUED,
                ScanStatus.RUNNING,
            }:
                # A running scan may legitimately have a stale
                # workspace if it is still being built; we err on
                # the safe side and leave it alone.
                continue
            self.cleanup(workspace)
            removed += 1
        return removed
