"""Finding and provider-observation service tests."""

from __future__ import annotations

from app.models.finding import (
    Finding,
    FindingCategory,
    FindingConfidence,
    FindingSeverity,
)
from app.models.provider_observation import (
    ProviderObservation,
    ProviderStatus,
)
from app.models.scan_run import ScanTriggerType
from app.services import (
    finding_service,
    observation_service,
    repository_service,
    scan_service,
)
from app.utils.finding_keys import stable_finding_key


def _setup_scan_with_findings(session) -> int:
    repo = repository_service.create_repository_from_url(
        session, "https://github.com/octocat/Hello-World"
    )
    scan = scan_service.create_scan(
        session, repository_id=repo.id, trigger_type=ScanTriggerType.MANUAL
    )
    for i, (sev, cat) in enumerate(
        [
            (FindingSeverity.LOW, FindingCategory.DEPENDENCY),
            (FindingSeverity.HIGH, FindingCategory.VULNERABILITY),
            (FindingSeverity.MEDIUM, FindingCategory.WORKFLOW),
        ]
    ):
        f = Finding(
            scan_run_id=scan.id,
            repository_id=repo.id,
            rule_id=f"R{i:03d}",
            category=cat,
            severity=sev,
            confidence=FindingConfidence.MEDIUM,
            title=f"finding {i}",
            summary="summary",
            stable_key=stable_finding_key(f"R{i:03d}", {"i": i}),
        )
        session.add(f)
    session.flush()
    for i, status in enumerate(
        [
            ProviderStatus.AVAILABLE,
            ProviderStatus.UNAVAILABLE,
            ProviderStatus.RATE_LIMITED,
        ]
    ):
        obs = ProviderObservation(
            scan_run_id=scan.id,
            provider=f"provider-{i}",
            operation="query",
            status=status,
            records_returned=0,
        )
        session.add(obs)
    session.flush()
    return scan.id


def test_list_findings_pagination(session) -> None:
    scan_id = _setup_scan_with_findings(session)
    items, total = finding_service.list_findings_for_scan(session, scan_id, page=1, page_size=2)
    assert total == 3
    assert len(items) == 2


def test_list_findings_filter_by_severity(session) -> None:
    scan_id = _setup_scan_with_findings(session)
    items, total = finding_service.list_findings_for_scan(
        session,
        scan_id,
        page=1,
        page_size=10,
        severity=FindingSeverity.HIGH,
    )
    assert total == 1
    assert items[0].severity == FindingSeverity.HIGH


def test_list_findings_for_unknown_scan_404(session) -> None:
    from app.utils.errors import ApiError, ApiErrorCode

    with pytest.raises(ApiError) as exc:
        finding_service.list_findings_for_scan(session, 99_999, page=1, page_size=10)
    assert exc.value.code == ApiErrorCode.NOT_FOUND.value


def test_list_observations_pagination(session) -> None:
    scan_id = _setup_scan_with_findings(session)
    items, total = observation_service.list_provider_observations(
        session, scan_id, page=1, page_size=2
    )
    assert total == 3
    assert len(items) == 2


def test_list_observations_filter_by_status(session) -> None:
    scan_id = _setup_scan_with_findings(session)
    items, total = observation_service.list_provider_observations(
        session,
        scan_id,
        page=1,
        page_size=10,
        status=ProviderStatus.UNAVAILABLE,
    )
    assert total == 1
    assert items[0].status == ProviderStatus.UNAVAILABLE


def test_list_observations_for_unknown_scan_404(session) -> None:
    from app.utils.errors import ApiError, ApiErrorCode

    with pytest.raises(ApiError) as exc:
        observation_service.list_provider_observations(session, 99_999, page=1, page_size=10)
    assert exc.value.code == ApiErrorCode.NOT_FOUND.value


import pytest  # noqa: E402  (import after fixtures for clarity)
