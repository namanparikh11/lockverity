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


class ComponentRead(SchemaModel):
    id: int
    scan_run_id: int
    manifest_id: int
    ecosystem: str | None = None
    package_name: str
    version: str | None = None
    version_source: str
    package_url: str | None = None
    scope: str | None = None
    relationship: str | None = None
    direct: bool
    development: bool
    optional: bool
    integrity: str | None = None


class DependencyPathEntry(SchemaModel):
    id: int
    package_name: str
    version: str | None = None
    version_source: str
    ecosystem: str | None = None
    direct: bool
    development: bool


class DependencyPathRead(SchemaModel):
    components: list[DependencyPathEntry]
    edges: list[dict]
    truncated: bool


class AdvisoryRead(SchemaModel):
    id: int
    source: str
    source_advisory_id: str
    canonical_id: str | None = None
    summary: str | None = None
    details_url: str | None = None
    published_at: datetime | None = None
    modified_at: datetime | None = None
    withdrawn_at: datetime | None = None
    raw_payload_sha256: str | None = None


class ComponentAdvisoryRead(SchemaModel):
    id: int
    component_id: int
    advisory_id: int
    fixed_versions: list[str]
    severity_source: str | None = None
    confidence: str
    dependency_paths: list[dict]
    withdrawn: bool
    # Enriched join fields for the frontend.
    package_name: str | None = None
    package_version: str | None = None
    ecosystem: str | None = None
    direct: bool | None = None
    advisory_source: str | None = None
    advisory_external_id: str | None = None
    advisory_canonical_id: str | None = None
    advisory_summary: str | None = None
    advisory_details_url: str | None = None
    affected: bool
    severity_label: str | None = None
    severity_score: int | None = None


class WorkflowFindingRead(SchemaModel):
    id: int
    scan_run_id: int
    repository_id: int
    rule_id: str
    severity: str
    confidence: str
    workflow_path: str
    workflow_name: str
    title: str
    summary: str
    remediation: str | None = None
    permissions: list[str]
    triggers: list[str]
    unpinned_actions: list[str]
    yaml_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    stable_key: str
    limitations: list[str]


class ScanComparisonRead(SchemaModel):
    base_scan_id: int
    head_scan_id: int
    repository_id: int
    generated_at: datetime
    components: list[dict]
    findings: list[dict]
    manifests: list[dict]
    workflows: list[dict]
    providers: list[dict]
    unable_to_determine: list[str]
