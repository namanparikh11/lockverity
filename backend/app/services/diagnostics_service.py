"""v1.9 — Operational diagnostics summary service.

The service composes a read-only, bounded summary of
runtime state. It never triggers an external provider
request, never mutates persisted state, and never
exposes tokens, environment values, connection strings,
or local filesystem paths. The section shapes match
``app.schemas.diagnostics``.

All SQL aggregations are bounded:

- provider rows: the existing per-provider rollup
  returns one row per known provider name;
- recent scan issues: at most
  ``MAX_RECENT_SCAN_ISSUES`` (default 25) rows, ordered
  newest-first;
- stage summary: one row per persisted stage type
  (the enum is bounded to 10 values).

The executor section reads ``scan_jobs`` (a persisted
queue / state row) for queued and running counts. The
in-process executor does not persist heartbeats, so
``last_heartbeat_at`` is always ``None`` and the page
renders an honest "Heartbeat not exposed by the
current executor" notice. We do not invent a heartbeat
from a wall-clock guess.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.provider_observation import ProviderStatus
from app.models.scan_job import ScanJob, ScanJobState
from app.models.scan_run import ScanStatus
from app.models.scan_stage import ScanStage, StageStatus, StageType
from app.repositories import observation_repo
from app.schemas.diagnostics import (
    DiagnosticsApplication,
    DiagnosticsExecutor,
    DiagnosticsProvider,
    DiagnosticsRecentScanIssue,
    DiagnosticsStageSummary,
    DiagnosticsSummaryResponse,
)
from app.singletons import get_executor
from app.utils.datetime import utcnow

# Bounded result size for the recent-scan-issues
# section. The page already renders the list as a
# bounded card; anything larger is information overload
# without operational value.
MAX_RECENT_SCAN_ISSUES = 25

# Bounded number of stage types we surface. The
# ``StageType`` enum is fixed and small (10 values
# in v0.5); we always return one row per stage type
# regardless of whether the underlying table has rows
# for that type.
_STAGE_TYPES: tuple[StageType, ...] = (
    StageType.REPOSITORY_INTAKE,
    StageType.ARCHIVE_VALIDATION,
    StageType.MANIFEST_DISCOVERY,
    StageType.DEPENDENCY_PARSING,
    StageType.DEPENDENCY_ENRICHMENT,
    StageType.VULNERABILITY_QUERY,
    StageType.WORKFLOW_ANALYSIS,
    StageType.REPOSITORY_POSTURE,
    StageType.FINDING_RECONCILIATION,
    StageType.EXPORT_GENERATION,
)

# Recent-issue statuses. Completed scans are
# intentionally excluded.
_ISSUE_SCAN_STATUSES: tuple[ScanStatus, ...] = (
    ScanStatus.PARTIAL,
    ScanStatus.FAILED,
    ScanStatus.CANCELLED,
)


def build_summary(
    session: Session,
    *,
    database_status: str = "available",
) -> DiagnosticsSummaryResponse:
    """Return the v1.9 operational-diagnostics summary.

    Args:
      session: the request-scoped SQLAlchemy session.
      database_status: a pre-computed ``available`` /
        ``unavailable`` / ``unknown`` value sourced from
        the existing ``/api/v1/health`` probe. The
        summary is composed from persisted state plus
        this one runtime signal so the route handler
        can reuse the SELECT 1 result.

    The summary is fully read-only and is safe to call
    concurrently.
    """
    settings = get_settings()
    application = _build_application_section(
        database_status=database_status,
        app_version=settings.app_version,
        environment=settings.environment,
    )
    executor = _build_executor_section(session)
    providers = _build_provider_section(session)
    recent_issues = _build_recent_scan_issues(session)
    stage_summary = _build_stage_summary(session)
    generated_at = utcnow()
    return DiagnosticsSummaryResponse(
        application=DiagnosticsApplication(
            status=application["status"],
            version=application["version"],
            environment=application["environment"],
            database=application["database"],
            generated_at=generated_at,
        ),
        executor=executor,
        providers=providers,
        recent_scan_issues=recent_issues,
        stage_summary=stage_summary,
        generated_at=generated_at,
    )


def _build_application_section(
    *,
    database_status: str,
    app_version: str,
    environment: str,
) -> dict[str, str]:
    """Return the application section values.

    The application ``status`` is ``reachable`` when the
    route is serving the response; it is never
    ``unreachable`` (the route would not have run). The
    field is included so the page has a single
    application card.
    """
    return {
        "status": "reachable",
        "version": app_version,
        "environment": environment,
        "database": database_status,
    }


def _build_executor_section(session: Session) -> DiagnosticsExecutor:
    """Return the executor section.

    The in-process executor does not persist a heartbeat
    to the database, so ``last_heartbeat_at`` is always
    ``None`` and ``heartbeat_supported`` is ``False``.
    The page surfaces an honest "Heartbeat not exposed
    by the current executor" notice.

    Queued and running scan counts come from the
    persisted ``scan_jobs`` table.
    """
    queued_scans = _count_jobs_by_state(session, ScanJobState.QUEUED)
    running_scans = _count_jobs_by_state(session, ScanJobState.RUNNING)
    notes: list[str] = []
    if queued_scans == 0 and running_scans == 0:
        notes.append("No scans are currently queued or running on the persisted job table.")
    executor = get_executor()
    try:
        implementation = executor.name
    except Exception:  # pragma: no cover - defensive
        implementation = "unknown"
    return DiagnosticsExecutor(
        state="available",
        implementation=implementation,
        queued_scans=queued_scans,
        running_scans=running_scans,
        last_heartbeat_at=None,
        heartbeat_supported=False,
        details_available=True,
        notes=notes,
    )


def _count_jobs_by_state(session: Session, state: ScanJobState) -> int:
    from sqlalchemy import func

    return int(
        session.execute(
            select(func.count()).select_from(ScanJob).where(ScanJob.state == state)
        ).scalar_one()
        or 0
    )


def _build_provider_section(session: Session) -> list[DiagnosticsProvider]:
    """Return the per-provider diagnostics rows.

    Each row is the most-recent observation for a known
    provider name. The set of known providers is
    bounded to four (``github``, ``osv``,
    ``deps_dev``, ``openssf``). A provider that has
    never been queried is still returned with a
    ``last_observed_state`` of ``not_requested`` and
    all other fields null — the honest baseline.
    """
    observed = observation_repo.provider_health_rollup(session)
    by_name = {entry["provider"]: entry for entry in observed}
    out: list[DiagnosticsProvider] = []
    for name in observation_repo.known_provider_names():
        entry = by_name.get(name)
        if entry is None:
            out.append(
                DiagnosticsProvider(
                    provider=name,
                    last_observed_state=ProviderStatus.NOT_REQUESTED.value,
                    configured_state="configured",
                    last_attempt_at=None,
                    last_success_at=None,
                    cache_status=None,
                    evidence_present=None,
                    last_error_code=None,
                    last_error_summary=None,
                    source_scan_id=None,
                    source_observation_id=None,
                )
            )
            continue
        # The observation row carries the most-recent
        # state, records, cache status, and bounded
        # error. We do not surface request payloads or
        # request URLs.
        last_attempt_at = entry.get("last_retrieved_at")
        last_error_code = entry.get("last_error_code")
        last_error_summary = entry.get("redacted_failure_summary")
        records = int(entry.get("records_returned") or 0)
        cache_status = entry.get("cache_status")
        status_value = entry.get("status")
        if hasattr(status_value, "value"):
            last_observed_state = status_value.value
        else:
            last_observed_state = str(status_value or "unknown")
        # ``last_success_at`` is best-effort: the
        # persisted model records ``completed_at`` on
        # the most recent observation. We surface it
        # as ``last_attempt_at`` for a never-quoted
        # provider; the field is intentionally nullable
        # for not_requested providers.
        out.append(
            DiagnosticsProvider(
                provider=name,
                last_observed_state=last_observed_state,
                configured_state="configured",
                last_attempt_at=last_attempt_at,
                last_success_at=last_attempt_at if records > 0 else None,
                cache_status=cache_status,
                evidence_present=None,
                last_error_code=last_error_code,
                last_error_summary=last_error_summary,
                source_scan_id=None,
                source_observation_id=None,
            )
        )
    return out


def _build_recent_scan_issues(
    session: Session,
) -> list[DiagnosticsRecentScanIssue]:
    """Return the bounded recent-issue list.

    Excludes completed scans. Ordered newest-first by
    ``updated_at``. Capped at ``MAX_RECENT_SCAN_ISSUES``
    so the page never renders an unbounded list.
    """
    from app.models.scan_run import ScanRun

    stmt = (
        select(ScanRun)
        .where(ScanRun.status.in_([s.value for s in _ISSUE_SCAN_STATUSES]))
        .order_by(ScanRun.updated_at.desc(), ScanRun.id.desc())
        .limit(MAX_RECENT_SCAN_ISSUES)
    )
    rows: Sequence[ScanRun] = session.execute(stmt).scalars().all()
    out: list[DiagnosticsRecentScanIssue] = []
    for row in rows:
        trigger_type = row.trigger_type
        trigger_value = trigger_type.value if hasattr(trigger_type, "value") else trigger_type
        status_value = row.status.value if hasattr(row.status, "value") else str(row.status)
        out.append(
            DiagnosticsRecentScanIssue(
                scan_id=row.id,
                repository_id=row.repository_id,
                status=status_value,
                trigger_type=trigger_value,
                failure_code=row.failure_code,
                failure_summary=row.failure_summary,
                updated_at=row.updated_at,
                completed_at=row.completed_at,
                started_at=row.started_at,
            )
        )
    return out


def _build_stage_summary(session: Session) -> list[DiagnosticsStageSummary]:
    """Return one bounded stage-state row per stage type.

    The count comes from a single SQL ``GROUP BY``
    aggregate. Empty buckets (no rows for a stage type)
    are returned as zero counts so the page renders a
    consistent shape.
    """
    from sqlalchemy import func

    stmt = select(ScanStage.stage_type, ScanStage.status, func.count(ScanStage.id)).group_by(
        ScanStage.stage_type, ScanStage.status
    )
    rows = session.execute(stmt).all()
    index: dict[tuple[str, str], int] = {}
    for stage_type, status, count in rows:
        stage_value = stage_type.value if hasattr(stage_type, "value") else str(stage_type)
        status_value = status.value if hasattr(status, "value") else str(status)
        index[(stage_value, status_value)] = int(count or 0)
    out: list[DiagnosticsStageSummary] = []
    for stage_type in _STAGE_TYPES:
        stage_value = stage_type.value
        out.append(
            DiagnosticsStageSummary(
                stage=stage_value,
                completed=index.get((stage_value, StageStatus.COMPLETED.value), 0),
                partial=index.get((stage_value, StageStatus.PARTIAL.value), 0),
                failed=index.get((stage_value, StageStatus.FAILED.value), 0),
                skipped=index.get((stage_value, StageStatus.SKIPPED.value), 0),
                running=index.get((stage_value, StageStatus.RUNNING.value), 0),
                pending=index.get((stage_value, StageStatus.PENDING.value), 0),
            )
        )
    return out


__all__ = [
    "MAX_RECENT_SCAN_ISSUES",
    "build_summary",
]
