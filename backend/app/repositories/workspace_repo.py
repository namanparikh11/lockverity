"""Workspace data-access helpers."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.workspace import Workspace, WorkspaceKind, WorkspaceState


def get_by_id(session: Session, workspace_id: int) -> Workspace | None:
    return session.get(Workspace, workspace_id)


def get_by_key(session: Session, workspace_key: str) -> Workspace | None:
    stmt = select(Workspace).where(Workspace.workspace_key == workspace_key)
    return session.execute(stmt).scalar_one_or_none()


def get_for_scan(session: Session, scan_run_id: int) -> Workspace | None:
    stmt = select(Workspace).where(Workspace.scan_run_id == scan_run_id)
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
