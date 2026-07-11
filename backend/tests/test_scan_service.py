"""Scan service tests."""

from __future__ import annotations

import pytest
from app.models.scan_run import ScanStatus, ScanTriggerType
from app.models.scan_stage import StageStatus, StageType
from app.services import repository_service, scan_service
from app.utils.datetime import utcnow
from app.utils.errors import ApiError, ApiErrorCode


def _setup(session):
    repo = repository_service.create_repository_from_url(
        session, "https://github.com/octocat/Hello-World"
    )
    scan = scan_service.create_scan(
        session, repository_id=repo.id, trigger_type=ScanTriggerType.MANUAL
    )
    return repo, scan


def test_create_scan_seeds_default_pipeline(session) -> None:
    _, scan = _setup(session)
    stages = scan_service.list_stages_for_scan(session, scan.id)
    assert len(stages) == 10
    assert all(stage.status == StageStatus.PENDING for stage in stages)
    assert stages[0].stage_type == StageType.REPOSITORY_INTAKE
    assert stages[-1].stage_type == StageType.EXPORT_GENERATION


def test_create_scan_starts_queued(session) -> None:
    _, scan = _setup(session)
    assert scan.status == ScanStatus.QUEUED


def test_create_scan_for_unknown_repository_404(session) -> None:
    with pytest.raises(ApiError) as exc:
        scan_service.create_scan(
            session,
            repository_id=99999,
            trigger_type=ScanTriggerType.MANUAL,
        )
    assert exc.value.code == ApiErrorCode.NOT_FOUND.value


def test_legal_scan_transitions(session) -> None:
    _, scan = _setup(session)
    scan = scan_service.transition_scan(session, scan.id, target=ScanStatus.RUNNING)
    assert scan.status == ScanStatus.RUNNING
    scan = scan_service.transition_scan(session, scan.id, target=ScanStatus.COMPLETED)
    assert scan.status == ScanStatus.COMPLETED


def test_legal_partial_transition(session) -> None:
    _, scan = _setup(session)
    scan_service.transition_scan(session, scan.id, target=ScanStatus.RUNNING)
    scan = scan_service.transition_scan(session, scan.id, target=ScanStatus.PARTIAL)
    assert scan.status == ScanStatus.PARTIAL


def test_legal_cancellation_from_queued(session) -> None:
    _, scan = _setup(session)
    scan = scan_service.transition_scan(session, scan.id, target=ScanStatus.CANCELLED)
    assert scan.status == ScanStatus.CANCELLED


def test_illegal_transition_queued_to_completed(session) -> None:
    _, scan = _setup(session)
    with pytest.raises(ApiError) as exc:
        scan_service.transition_scan(session, scan.id, target=ScanStatus.COMPLETED)
    assert exc.value.code == ApiErrorCode.ILLEGAL_TRANSITION.value


def test_terminal_status_protection(session) -> None:
    _, scan = _setup(session)
    scan_service.transition_scan(session, scan.id, target=ScanStatus.RUNNING)
    scan_service.transition_scan(session, scan.id, target=ScanStatus.FAILED)
    with pytest.raises(ApiError) as exc:
        scan_service.transition_scan(session, scan.id, target=ScanStatus.RUNNING)
    assert exc.value.code == ApiErrorCode.ILLEGAL_TRANSITION.value


def test_legal_stage_transitions(session) -> None:
    _, scan = _setup(session)
    stage = scan_service.transition_stage(
        session,
        scan.id,
        StageType.REPOSITORY_INTAKE,
        target=StageStatus.RUNNING,
    )
    assert stage.status == StageStatus.RUNNING
    assert stage.started_at is not None
    stage = scan_service.transition_stage(
        session,
        scan.id,
        StageType.REPOSITORY_INTAKE,
        target=StageStatus.COMPLETED,
    )
    assert stage.status == StageStatus.COMPLETED
    assert stage.completed_at is not None


def test_illegal_stage_transition(session) -> None:
    _, scan = _setup(session)
    with pytest.raises(ApiError) as exc:
        scan_service.transition_stage(
            session,
            scan.id,
            StageType.REPOSITORY_INTAKE,
            target=StageStatus.COMPLETED,
        )
    assert exc.value.code == ApiErrorCode.ILLEGAL_TRANSITION.value


def test_terminal_stage_protection(session) -> None:
    _, scan = _setup(session)
    scan_service.transition_stage(
        session,
        scan.id,
        StageType.REPOSITORY_INTAKE,
        target=StageStatus.SKIPPED,
    )
    with pytest.raises(ApiError) as exc:
        scan_service.transition_stage(
            session,
            scan.id,
            StageType.REPOSITORY_INTAKE,
            target=StageStatus.RUNNING,
        )
    assert exc.value.code == ApiErrorCode.ILLEGAL_TRANSITION.value


def test_transition_scan_records_timestamps(session) -> None:
    _, scan = _setup(session)
    started_at = utcnow()
    scan_service.transition_scan(
        session,
        scan.id,
        target=ScanStatus.RUNNING,
        started_at=started_at,
    )
    completed_at = utcnow()
    scan_service.transition_scan(
        session,
        scan.id,
        target=ScanStatus.COMPLETED,
        completed_at=completed_at,
    )
    found = scan_service.get_scan_or_404(session, scan.id)
    assert found.started_at is not None
    assert found.completed_at is not None


def test_list_scans_for_repository(session) -> None:
    repo = repository_service.create_repository_from_url(
        session, "https://github.com/octocat/Hello-World"
    )
    for _ in range(3):
        scan_service.create_scan(
            session, repository_id=repo.id, trigger_type=ScanTriggerType.MANUAL
        )
    items, total = scan_service.list_scans_for_repository(session, repo.id, page=1, page_size=2)
    assert total == 3
    assert len(items) == 2
