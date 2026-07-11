// API response type definitions. Kept narrow on purpose - the
// frontend never assumes a field is present unless the backend
// guarantees it in the OpenAPI schema.

export type ScanStatus =
  | "queued"
  | "running"
  | "completed"
  | "partial"
  | "failed"
  | "cancelled";

export type ScanTriggerType = "manual" | "upload" | "scheduled" | "api";

export type StageType =
  | "repository_intake"
  | "archive_validation"
  | "manifest_discovery"
  | "dependency_parsing"
  | "dependency_enrichment"
  | "vulnerability_query"
  | "workflow_analysis"
  | "repository_posture"
  | "finding_reconciliation"
  | "export_generation";

export type StageStatus =
  | "pending"
  | "running"
  | "completed"
  | "partial"
  | "failed"
  | "skipped";

export type ProviderStatus =
  | "available"
  | "partial"
  | "rate_limited"
  | "unavailable"
  | "not_requested"
  | "cached"
  | "unknown";

export type FindingSeverity =
  | "informational"
  | "low"
  | "medium"
  | "high"
  | "critical"
  | "unknown";

export type FindingConfidence =
  | "low"
  | "medium"
  | "high"
  | "confirmed"
  | "unknown";

export type FindingStatus = "open" | "resolved" | "accepted" | "suppressed";

export type FindingCategory =
  | "dependency"
  | "vulnerability"
  | "workflow"
  | "repository_posture"
  | "licence"
  | "provider"
  | "data_quality";

export type RepositorySourceType = "github" | "uploaded_archive";
export type RepositoryProvider = "github" | "local_upload";
export type RepositoryVisibility = "public" | "private" | "unknown";

export interface HealthResponse {
  status: "ok" | "degraded";
  database: "ok" | "unavailable";
  version: string;
  environment: string;
  timestamp: string;
}

export interface SystemInfoResponse {
  name: string;
  version: string;
  tagline: string;
  environment: string;
  api_prefix: string;
  archive_limits: Record<string, number>;
  pagination: Record<string, number>;
  provider_safety: Record<string, number>;
}

export interface Repository {
  id: number;
  source_type: RepositorySourceType;
  provider: RepositoryProvider;
  owner: string;
  name: string;
  canonical_url: string | null;
  default_branch: string | null;
  description: string | null;
  visibility: RepositoryVisibility;
  archived: boolean;
  last_provider_sync_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Scan {
  id: number;
  repository_id: number;
  status: ScanStatus;
  trigger_type: ScanTriggerType;
  requested_ref: string | null;
  resolved_commit_sha: string | null;
  analyzer_version: string | null;
  started_at: string | null;
  completed_at: string | null;
  failure_code: string | null;
  failure_summary: string | null;
  created_at: string;
  updated_at: string;
}

export interface ScanStage {
  id: number;
  scan_run_id: number;
  stage_type: StageType;
  status: StageStatus;
  started_at: string | null;
  completed_at: string | null;
  provider: string | null;
  provider_status: string | null;
  records_processed: number;
  failure_code: string | null;
  failure_summary: string | null;
  created_at: string;
  updated_at: string;
}

export interface Finding {
  id: number;
  scan_run_id: number;
  repository_id: number;
  rule_id: string;
  category: FindingCategory;
  severity: FindingSeverity;
  confidence: FindingConfidence;
  title: string;
  summary: string;
  remediation: string | null;
  evidence_json: string | null;
  location_path: string | null;
  location_start_line: number | null;
  location_end_line: number | null;
  stable_key: string;
  status: FindingStatus;
  created_at: string;
  updated_at: string;
}

export interface ProviderObservation {
  id: number;
  scan_run_id: number;
  provider: string;
  operation: string;
  status: ProviderStatus;
  requested_at: string | null;
  completed_at: string | null;
  http_status: number | null;
  records_returned: number;
  cache_status: string | null;
  retry_after: string | null;
  error_code: string | null;
  error_summary: string | null;
  created_at: string;
  updated_at: string;
}

export interface PageMeta {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface Paginated<T> {
  items: T[];
  pagination: PageMeta;
}
