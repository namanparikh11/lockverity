// API response type definitions. Kept narrow on purpose - the
// frontend never assumes a field is present unless the backend
// guarantees it in the OpenAPI schema.
//
// The v0.1 backend already exposes repositories, scans, stages,
// findings, and provider observations. The additional types below
// are forward-compatible declarations for the v0.2+/v0.3+ endpoints
// the frontend pages already use. The frontend gracefully renders
// "not yet available" empty states when a backend endpoint is not
// yet implemented (HTTP 404 or 501 is mapped to an empty list).

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

export type ComponentVersionSource =
  | "manifest"
  | "lockfile"
  | "override"
  | "unresolved"
  | "unknown";

export type ComponentScope = "runtime" | "development" | "build" | "test" | "optional" | "unknown";

export type DependencyScopeFilter = "all" | "direct" | "transitive";
export type DevelopmentScopeFilter = "all" | "production" | "development";
export type VulnerableOnlyFilter = "all" | "vulnerable";

// ---- System ----

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

// ---- Repositories ----

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

export interface RepositoryCreatePayload {
  canonical_url: string;
  requested_ref?: string;
}

// ---- Scans ----

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

export interface ScanCreatePayload {
  trigger_type?: ScanTriggerType;
  requested_ref?: string;
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

// ---- Findings ----

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

// ---- Provider observations ----

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

// ---- Components / dependencies (forward-compatible) ----

export interface Component {
  id: number;
  scan_run_id: number;
  manifest_id: number;
  ecosystem: string | null;
  package_name: string;
  version: string | null;
  version_source: ComponentVersionSource;
  package_url: string | null;
  scope: string | null;
  relationship: string | null;
  direct: boolean;
  development: boolean;
  optional: boolean;
  integrity: string | null;
  created_at: string;
  updated_at: string;
}

export interface DependencyEdge {
  id: number;
  scan_run_id: number;
  parent_component_id: number;
  child_component_id: number;
  depth: number;
  resolved: boolean;
}

export interface DependencyPath {
  components: Component[];
  edges: DependencyEdge[];
  truncated: boolean;
}

// ---- Component enrichments (v0.4) ----

export interface ComponentEnrichment {
  component_id: number;
  ecosystem: string | null;
  package_name: string;
  version: string | null;
  fetched_at: string | null;
  cache_status: string;
  provider_url: string | null;
  source_provenance: string | null;
  license_observations: string[];
  dependency_count: number | null;
  provider_status: ProviderStatus | null;
  unavailable_reason: string | null;
  // v0.4 honesty fix: the structured evidence envelope
  // from the underlying provider_observations row.
  // ``null`` for failed / never-queried rows; a JSON
  // object with ``licences`` and ``dependency_count`` for
  // successful rows. The UI never fabricates values.
  evidence: Record<string, unknown> | null;
}

// ---- Advisories / vulnerabilities (forward-compatible) ----

export interface Advisory {
  id: number;
  source: string;
  source_advisory_id: string;
  canonical_id: string | null;
  summary: string | null;
  details_url: string | null;
  published_at: string | null;
  modified_at: string | null;
  withdrawn_at: string | null;
  raw_payload_sha256: string | null;
  created_at: string;
  updated_at: string;
}

export interface ComponentAdvisory {
  id: number;
  component_id: number;
  advisory_id: number;
  fixed_versions: string[];
  severity_source: string | null;
  // v0.4 honesty fix: confidence is now nullable. The
  // previous v0.4 implementation substituted ``medium``
  // or ``high``; that was removed because the upstream
  // provider (OSV) does not supply a confidence. The
  // UI renders the ``null`` case as "Not supplied".
  confidence: FindingConfidence | null;
  dependency_paths: DependencyPath[];
  withdrawn: boolean;
  // v0.4 additions. The provider_provenance always
  // names a real upstream; ``local`` indicates a
  // rule-engine finding. Aliases cover the canonical
  // CVE / GHSA cross-references the provider
  // publishes. Fetched_at is the UTC ISO timestamp of
  // the provider call; ``null`` means the row was
  // written before v0.4 (legacy).
  provider_provenance?: string | null;
  aliases?: string[];
  fetched_at?: string | null;
  // The v0.3 read-side fields stay available for
  // backwards compatibility; new code can read the
  // renamed fields below.
  package_name?: string | null;
  package_version?: string | null;
  ecosystem?: string | null;
  direct?: boolean | null;
  advisory_source?: string | null;
  advisory_external_id?: string | null;
  advisory_canonical_id?: string | null;
  advisory_summary?: string | null;
  advisory_details_url?: string | null;
  affected: boolean;
  severity_label?: string | null;
  severity_score?: number | null;
}

// ---- Workflow findings (forward-compatible) ----

export interface WorkflowFinding {
  id: number;
  scan_run_id: number;
  repository_id: number;
  rule_id: string;
  severity: FindingSeverity;
  confidence: FindingConfidence;
  workflow_path: string;
  workflow_name: string;
  title: string;
  summary: string;
  remediation: string | null;
  permissions: string[];
  triggers: string[];
  unpinned_actions: string[];
  yaml_path: string | null;
  start_line: number | null;
  end_line: number | null;
  stable_key: string;
  limitations: string[];
  created_at: string;
  updated_at: string;
}

// ---- OpenSSF posture (forward-compatible) ----

export interface OpenSSFCheck {
  id: number;
  scan_run_id: number;
  repository_id: number;
  check_id: string;
  name: string;
  score: number | null;
  reason: string | null;
  details_url: string | null;
  source: string;
  created_at: string;
  updated_at: string;
}

// ---- Licence inventory (forward-compatible) ----

export type LicenceReviewStatus = "unreviewed" | "review_required" | "approved" | "rejected" | "unknown";

export interface LicenceAssertion {
  id: number;
  scan_run_id: number;
  component_id: number;
  package_name: string;
  version: string | null;
  licence: string;
  direct: boolean;
  provider: string;
  review_status: LicenceReviewStatus;
  unknown_licence: boolean;
  created_at: string;
  updated_at: string;
}

// ---- Scan comparison (v0.5 evidence-aware) ----

// The v0.5 state vocabulary. The comparator never claims a
// row was "fixed" or "resolved" - it only describes what the
// evidence shows between two scans. The frontend renders these
// as the only labels it ever uses for a comparison row.
export type ObservationState =
  | "newly_observed"
  | "still_observed"
  | "no_longer_observed"
  | "changed_observation"
  | "coverage_changed"
  | "comparison_indeterminate";

export type ProviderStateName =
  | "successful"
  | "cached"
  | "stale"
  | "partial"
  | "unavailable"
  | "unsupported"
  | "not_requested"
  | "unknown";

export interface ScanComparisonComponentObservation {
  ecosystem: string | null;
  package_name: string;
  version: string | null;
  manifest_paths: string[];
  direct_base: boolean | null;
  direct_head: boolean | null;
  state: ObservationState;
}

export interface ScanComparisonManifestObservation {
  manifest_path: string;
  manifest_type: string | null;
  ecosystem: string | null;
  parse_status_base: string | null;
  parse_status_head: string | null;
  content_sha256_base: string | null;
  content_sha256_head: string | null;
  state: ObservationState;
}

export interface ScanComparisonDependencyPathChange {
  ecosystem: string | null;
  package_name: string;
  version: string | null;
  parent_chain_base: string[];
  parent_chain_head: string[];
  state: ObservationState;
}

export interface ScanComparisonWorkflowObservation {
  rule_id: string;
  workflow_path: string;
  title: string;
  severity_base: string | null;
  severity_head: string | null;
  confidence_base: string | null;
  confidence_head: string | null;
  stable_key: string;
  state: ObservationState;
}

export interface ScanComparisonVulnerabilityObservation {
  component_id_base: number | null;
  component_id_head: number | null;
  ecosystem: string | null;
  package_name: string | null;
  package_version_base: string | null;
  package_version_head: string | null;
  advisory_source: string | null;
  advisory_external_id: string | null;
  advisory_canonical_id: string | null;
  severity_label_base: string | null;
  severity_score_base: number | null;
  severity_label_head: string | null;
  severity_score_head: number | null;
  state: ObservationState;
  provider_provenance_base: string | null;
  provider_provenance_head: string | null;
  fetched_at_base: string | null;
  fetched_at_head: string | null;
  ambiguity_reason: string | null;
}

export interface ScanComparisonLicenceObservation {
  ecosystem: string | null;
  package_name: string | null;
  package_version_base: string | null;
  package_version_head: string | null;
  licence_base: string | null;
  licence_head: string | null;
  provider_base: string | null;
  provider_head: string | null;
  review_status_base: string | null;
  review_status_head: string | null;
  state: ObservationState;
}

export interface ScanComparisonOpenSSFObservation {
  check_id: string;
  name: string;
  score_base: number | null;
  score_head: number | null;
  reason_base: string | null;
  reason_head: string | null;
  details_url: string | null;
  source: string;
  state: ObservationState;
}

export interface ScanComparisonProviderCoverage {
  provider: string;
  state_base: ProviderStateName;
  state_head: ProviderStateName;
  last_completed_at_base: string | null;
  last_completed_at_head: string | null;
  records_returned_base: number | null;
  records_returned_head: number | null;
  cache_status_base: string | null;
  cache_status_head: string | null;
  error_code_base: string | null;
  error_summary_base: string | null;
  error_code_head: string | null;
  error_summary_head: string | null;
  evidence_present_base: boolean;
  evidence_present_head: boolean;
  state: ObservationState;
}

export interface ScanComparisonCoverageSummary {
  base_scan_status: string;
  head_scan_status: string;
  components_in_base: number;
  components_in_head: number;
  findings_in_base: number;
  findings_in_head: number;
  vulnerabilities_in_base: number;
  vulnerabilities_in_head: number;
  workflows_in_base: number;
  workflows_in_head: number;
  manifests_in_base: number;
  manifests_in_head: number;
  licence_assertions_in_base: number;
  licence_assertions_in_head: number;
  openssf_checks_in_base: number;
  openssf_checks_in_head: number;
  providers_with_changed_state: number;
  providers_with_indeterminate_head: number;
}

export interface ScanComparison {
  base_scan_id: number;
  head_scan_id: number;
  repository_id: number;
  base_trigger_type: string | null;
  head_trigger_type: string | null;
  base_resolved_commit_sha: string | null;
  head_resolved_commit_sha: string | null;
  base_analyzer_version: string | null;
  head_analyzer_version: string | null;
  base_completed_at: string | null;
  head_completed_at: string | null;
  generated_at: string;
  coverage: ScanComparisonCoverageSummary;
  components: ScanComparisonComponentObservation[];
  manifests: ScanComparisonManifestObservation[];
  dependency_paths: ScanComparisonDependencyPathChange[];
  workflows: ScanComparisonWorkflowObservation[];
  vulnerabilities: ScanComparisonVulnerabilityObservation[];
  licences: ScanComparisonLicenceObservation[];
  openssf: ScanComparisonOpenSSFObservation[];
  providers: ScanComparisonProviderCoverage[];
  indeterminate_reasons: string[];
}

// ---- Provider health rollup (forward-compatible) ----

export type ProviderName = "github" | "osv" | "deps_dev" | "openssf";

export interface ProviderHealthEntry {
  provider: ProviderName;
  status: ProviderStatus;
  last_retrieved_at: string | null;
  records_returned: number;
  cache_status: string | null;
  redacted_failure_summary: string | null;
  last_error_code: string | null;
  scans_with_observations: number;
}

// ---- Exports ----

export type ExportFormat = "cyclonedx_json" | "findings_json" | "findings_csv" | "sarif_json";

export interface ExportDescriptor {
  format: ExportFormat;
  label: string;
  description: string;
  supported: boolean;
  not_supported_reason: string | null;
  content_type: string;
  filename_hint: string;
}

// ---- Pagination ----

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
