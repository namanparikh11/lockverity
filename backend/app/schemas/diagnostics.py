"""v1.9 — Operational diagnostics summary schema.

The diagnostics endpoint is a read-only, bounded summary
that surfaces the application's runtime state without
ever triggering an external provider request, exposing
secrets or environment values, or rendering a
universal health / risk / compliance score.

The response is intentionally separated into
independent sections so the frontend can render each
axis in its own bounded card:

- ``application``   — runtime reachability + version
- ``executor``      — worker / scan-job heartbeat snapshot
- ``providers``     — per-provider persisted observation
- ``recent_scan_issues`` — bounded recent partial / failed
  / cancelled scan rows (no completed scans)
- ``stage_summary`` — aggregated persisted stage states

Every field is either a bounded enum value, a numeric
count, or a timestamp. Diagnostic consumers must not
treat any field as a security verdict.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import SchemaModel


class DiagnosticsApplication(SchemaModel):
    """Runtime reachability and version.

    The ``database`` value is one of:

    - ``available``   — the SELECT 1 probe succeeded
    - ``unavailable`` — the probe raised a controlled error
    - ``unknown``     — the probe result could not be
      interpreted (network partition, etc.)
    """

    status: str
    version: str
    environment: str
    database: str
    generated_at: datetime


class DiagnosticsExecutor(SchemaModel):
    """Worker / executor state.

    The executor section is bounded to the facts the
    backend can actually answer from persisted state.
    The in-process executor does not persist heartbeats
    to a database row, so the heartbeat field is always
    ``null`` here and the page renders the
    "Heartbeat not exposed by the current executor"
    notice. We do not invent a heartbeat from a wall-
    clock guess.
    """

    state: str  # available | unavailable | unknown
    implementation: str
    queued_scans: int
    running_scans: int
    last_heartbeat_at: datetime | None = None
    heartbeat_supported: bool
    details_available: bool
    notes: list[str] = Field(default_factory=list)


class DiagnosticsProvider(SchemaModel):
    """A single provider's most-recent persisted state.

    The fields below are independent on purpose:
    ``last_observed_state`` is the provider's
    availability at last call; ``cache_status`` is the
    cache-layer freshness; ``evidence_present`` is
    whether the persisted row carried a non-empty
    ``evidence_json`` block. The frontend must render
    each independently and must not collapse them into
    a single verdict.
    """

    provider: str
    last_observed_state: str
    configured_state: str
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    cache_status: str | None = None
    evidence_present: bool | None = None
    last_error_code: str | None = None
    last_error_summary: str | None = None
    source_scan_id: int | None = None
    source_observation_id: int | None = None


class DiagnosticsRecentScanIssue(SchemaModel):
    """A bounded recent partial / failed / cancelled scan.

    Completed scans are intentionally excluded. The
    failure_code is the bounded persisted code; the
    failure_summary is the bounded persisted text. No
    raw stack traces, no secrets, no local paths.
    """

    scan_id: int
    repository_id: int
    status: str
    trigger_type: str | None = None
    failure_code: str | None = None
    failure_summary: str | None = None
    updated_at: datetime
    completed_at: datetime | None = None
    started_at: datetime | None = None


class DiagnosticsStageSummary(SchemaModel):
    """Aggregated persisted stage state across the window.

    The counts are derived from a bounded SQL aggregate
    on persisted stage rows; the page never invents a
    percentage or a "healthy" label. A zero count is
    rendered as "No matching persisted stage failures
    were found in the selected window."
    """

    stage: str
    completed: int
    partial: int
    failed: int
    skipped: int
    running: int
    pending: int


class DiagnosticsSummaryResponse(SchemaModel):
    """The full operational-diagnostics summary.

    The response is read-only. No external provider call
    is triggered; no environment values or connection
    strings are exposed; no raw stack traces are
    included. The page consumes this shape and renders
    each section as an independent bounded card.
    """

    application: DiagnosticsApplication
    executor: DiagnosticsExecutor
    providers: list[DiagnosticsProvider]
    recent_scan_issues: list[DiagnosticsRecentScanIssue]
    stage_summary: list[DiagnosticsStageSummary]
    generated_at: datetime


__all__ = [
    "DiagnosticsApplication",
    "DiagnosticsExecutor",
    "DiagnosticsProvider",
    "DiagnosticsRecentScanIssue",
    "DiagnosticsStageSummary",
    "DiagnosticsSummaryResponse",
]
