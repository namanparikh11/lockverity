"""Workspace data-access helpers."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.scan_run import ScanRun
from app.models.workspace import Workspace, WorkspaceKind, WorkspaceState


def get_by_id(session: Session, workspace_id: int) -> Workspace | None:
    return session.get(Workspace, workspace_id)


def get_by_key(session: Session, workspace_key: str) -> Workspace | None:
    stmt = select(Workspace).where(Workspace.workspace_key == workspace_key)
    return session.execute(stmt).scalar_one_or_none()


def get_for_scan(session: Session, scan_run_id: int) -> Workspace | None:
    stmt = select(Workspace).where(Workspace.scan_run_id == scan_run_id)
    return session.execute(stmt).scalar_one_or_none()


def get_latest_ready_workspace_for_repository(
    session: Session, repository_id: int
) -> Workspace | None:
    """Return the most recent READY workspace for a repository.

    The rescan service uses this to find the previous
    upload-source workspace whose contents can be
    safely copied into the new workspace. Only READY
    workspaces are returned; failed and cleaned-up
    workspaces are ignored.
    """
    stmt = (
        select(Workspace)
        .join(ScanRun, Workspace.scan_run_id == ScanRun.id)
        .where(ScanRun.repository_id == repository_id)
        .where(Workspace.state == WorkspaceState.READY)
        .order_by(Workspace.id.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def create(
    session: Session,
    *,
    scan_run_id: int,
    workspace_key: str,
    kind: WorkspaceKind,
    archive_filename: str | None = None,
) -> Workspace:
    workspace = Workspace(
        scan_run_id=scan_run_id,
        workspace_key=workspace_key,
        kind=kind,
        state=WorkspaceState.QUARANTINED,
        archive_filename=archive_filename,
    )
    session.add(workspace)
    session.flush()
    return workspace


def list_states(
    session: Session,
    *,
    states: Sequence[WorkspaceState] = (),
) -> Sequence[Workspace]:
    stmt = select(Workspace)
    if states:
        stmt = stmt.where(Workspace.state.in_(list(states)))
    return session.execute(stmt.order_by(Workspace.id.asc())).scalars().all()


def count(session: Session) -> int:
    return int(session.execute(select(func.count()).select_from(Workspace)).scalar_one() or 0)
