"""Scan API schemas."""

from __future__ import annotations

from datetime import datetime

from app.models.scan_run import ScanStatus, ScanTriggerType
from app.schemas.common import NonEmptyStr, SchemaModel, TimestampMixin


class ScanCreate(SchemaModel):
    """Payload for ``POST /api/v1/repositories/{id}/scans``."""

    trigger_type: ScanTriggerType = ScanTriggerType.MANUAL
    requested_ref: NonEmptyStr | None = None


class ScanRead(TimestampMixin):
    id: int
    repository_id: int
    status: ScanStatus
    trigger_type: ScanTriggerType
    requested_ref: str | None = None
    resolved_commit_sha: str | None = None
    analyzer_version: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failure_code: str | None = None
    failure_summary: str | None = None


class ScanStageRead(TimestampMixin):
    id: int
    scan_run_id: int
    stage_type: str
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    provider: str | None = None
    provider_status: str | None = None
    records_processed: int
    failure_code: str | None = None
    failure_summary: str | None = None


class FindingRead(TimestampMixin):
    id: int
    scan_run_id: int
    repository_id: int
    rule_id: str
    category: str
    severity: str
    confidence: str
    title: str
    summary: str
    remediation: str | None = None
    evidence_json: str | None = None
    location_path: str | None = None
    location_start_line: int | None = None
    location_end_line: int | None = None
    stable_key: str
    status: str


class ProviderObservationRead(TimestampMixin):
    id: int
    scan_run_id: int
    provider: str
    operation: str
    status: str
    requested_at: datetime | None = None
    completed_at: datetime | None = None
    http_status: int | None = None
    records_returned: int
    cache_status: str | None = None
    retry_after: datetime | None = None
    error_code: str | None = None
    error_summary: str | None = None
