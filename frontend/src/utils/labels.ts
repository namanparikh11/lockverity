/**
 * Centralised human-readable labels for enum values. Keeping
 * them in one place prevents per-page drift and makes them
 * testable. The labels are intentionally bland and descriptive
 * - no marketing language.
 */

import type {
  FindingCategory,
  FindingConfidence,
  FindingSeverity,
  FindingStatus,
  ProviderName,
  ProviderStatus,
  RepositoryProvider,
  RepositorySourceType,
  RepositoryVisibility,
  ScanStatus,
  ScanTriggerType,
  StageStatus,
  StageType,
} from "@/api/types";

const LABEL_OVERRIDES: Record<string, string> = {
  // Provider names
  osv: "OSV",
  deps_dev: "deps.dev",
  openssf: "OpenSSF Scorecard",
  github: "GitHub",
  // Provider status
  not_requested: "not requested",
};

export function labelFor(value: string | null | undefined, fallback = "—"): string {
  if (!value) return fallback;
  if (LABEL_OVERRIDES[value]) return LABEL_OVERRIDES[value];
  return value
    .split("_")
    .map((part) => (part ? part[0].toUpperCase() + part.slice(1) : ""))
    .join(" ");
}

export const scanStatusLabel: Record<ScanStatus, string> = {
  queued: "Queued",
  running: "Running",
  completed: "Completed",
  partial: "Partial",
  failed: "Failed",
  cancelled: "Cancelled",
};

export const stageStatusLabel: Record<StageStatus, string> = {
  pending: "Pending",
  running: "Running",
  completed: "Completed",
  partial: "Partial",
  failed: "Failed",
  skipped: "Skipped",
};

export const stageTypeLabel: Record<StageType, string> = {
  repository_intake: "Repository intake",
  archive_validation: "Archive validation",
  manifest_discovery: "Manifest discovery",
  dependency_parsing: "Dependency parsing",
  dependency_enrichment: "Dependency enrichment",
  vulnerability_query: "Vulnerability query",
  workflow_analysis: "Workflow analysis",
  repository_posture: "Repository posture",
  finding_reconciliation: "Finding reconciliation",
  export_generation: "Export generation",
};

export const providerStatusLabel: Record<ProviderStatus, string> = {
  available: "Available",
  partial: "Partial",
  rate_limited: "Rate limited",
  unavailable: "Unavailable",
  not_requested: "Not requested",
  cached: "Cached",
  unknown: "Unknown",
};

export const providerNameLabel: Record<ProviderName, string> = {
  osv: "OSV",
  deps_dev: "deps.dev",
  openssf: "OpenSSF Scorecard",
  github: "GitHub",
};

export const findingSeverityLabel: Record<FindingSeverity, string> = {
  informational: "Informational",
  low: "Low",
  medium: "Medium",
  high: "High",
  critical: "Critical",
  unknown: "Unknown",
};

export const findingConfidenceLabel: Record<FindingConfidence, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  confirmed: "Confirmed",
  unknown: "Unknown",
};

export const findingStatusLabel: Record<FindingStatus, string> = {
  open: "Open",
  resolved: "Resolved",
  accepted: "Accepted",
  suppressed: "Suppressed",
};

export const findingCategoryLabel: Record<FindingCategory, string> = {
  dependency: "Dependency",
  vulnerability: "Vulnerability",
  workflow: "Workflow",
  repository_posture: "Repository posture",
  licence: "Licence",
  provider: "Provider availability",
  data_quality: "Data quality",
};

export const scanTriggerLabel: Record<ScanTriggerType, string> = {
  manual: "Manual",
  upload: "Upload",
  scheduled: "Scheduled",
  api: "API",
};

export const repositoryProviderLabel: Record<RepositoryProvider, string> = {
  github: "GitHub",
  local_upload: "Local upload",
};

export const repositorySourceLabel: Record<RepositorySourceType, string> = {
  github: "GitHub",
  uploaded_archive: "Uploaded archive",
};

export const repositoryVisibilityLabel: Record<RepositoryVisibility, string> = {
  public: "Public",
  private: "Private",
  unknown: "Unknown",
};
