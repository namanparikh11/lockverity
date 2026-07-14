import { apiClient } from "@/api/client";
import type {
  Advisory,
  Component,
  ComponentAdvisory,
  DependencyPath,
  ExportDescriptor,
  ExportFormat,
  Finding,
  FindingCategory,
  FindingConfidence,
  FindingSeverity,
  FindingStatus,
  HealthResponse,
  LicenceAssertion,
  OpenSSFCheck,
  Paginated,
  ProviderHealthEntry,
  ProviderName,
  ProviderObservation,
  ProviderStatus,
  Repository,
  RepositoryCreatePayload,
  Scan,
  ScanCreatePayload,
  ScanComparison,
  ScanStage,
  ScanStatus,
  SystemInfoResponse,
  WorkflowFinding,
} from "@/api/types";

export interface ListRepositoriesFilters {
  page?: number;
  page_size?: number;
  search?: string;
  provider?: string;
  source_type?: string;
  archived?: "all" | "archived" | "active";
}

export interface ListScansFilters {
  page?: number;
  page_size?: number;
  status?: ScanStatus | "all";
  trigger_type?: string;
}

export interface ListFindingsFilters {
  page?: number;
  page_size?: number;
  category?: FindingCategory | "all";
  severity?: FindingSeverity | "all";
  confidence?: FindingConfidence | "all";
  rule_id?: string;
  path?: string;
  status?: FindingStatus | "all";
  direct_transitive?: "all" | "direct" | "transitive";
  provider?: string;
  search?: string;
}

export interface ListComponentsFilters {
  page?: number;
  page_size?: number;
  ecosystem?: string;
  scope?: "all" | "direct" | "transitive";
  development?: "all" | "production" | "development";
  vulnerable_only?: "all" | "vulnerable";
  search?: string;
}

export interface ListVulnerabilitiesFilters {
  page?: number;
  page_size?: number;
  ecosystem?: string;
  direct_transitive?: "all" | "direct" | "transitive";
  search?: string;
}

export interface ListWorkflowFindingsFilters {
  page?: number;
  page_size?: number;
  rule_id?: string;
  severity?: FindingSeverity | "all";
}

export interface ListOpenSSFFilters {
  page?: number;
  page_size?: number;
  check_id?: string;
}

export interface ListLicenceFilters {
  page?: number;
  page_size?: number;
  provider?: string;
  review_status?: string;
  search?: string;
  direct_transitive?: "all" | "direct" | "transitive";
}

function buildQuery<T extends object>(obj: T): Record<string, string | number | boolean | undefined | null> {
  const out: Record<string, string | number | boolean | undefined | null> = {};
  for (const [key, value] of Object.entries(obj)) {
    if (value === undefined || value === null) continue;
    if (typeof value === "string" && value === "all") continue;
    out[key] = value as string | number | boolean;
  }
  return out;
}

export const api = {
  // ---- System ----
  health: () => apiClient.get<HealthResponse>("/health"),
  systemInfo: () => apiClient.get<SystemInfoResponse>("/system/info"),

  // ---- Repositories ----
  listRepositories: (filters: ListRepositoriesFilters = {}) =>
    apiClient.get<Paginated<Repository>>("/repositories", {
      query: buildQuery({
        page: filters.page ?? 1,
        page_size: filters.page_size ?? 25,
        search: filters.search,
        provider: filters.provider,
        source_type: filters.source_type,
        archived: filters.archived && filters.archived !== "all" ? filters.archived : undefined,
      }),
    }),
  getRepository: (id: number) =>
    apiClient.get<Repository>(`/repositories/${id}`),
  createRepository: (payload: RepositoryCreatePayload | string) => {
    const body: RepositoryCreatePayload =
      typeof payload === "string" ? { canonical_url: payload } : payload;
    return apiClient.post<Repository>("/repositories", body);
  },
  createRepositoryUpload: (file: File | Blob) =>
    apiClient.upload<Repository>("/repositories/upload", file),

  // ---- Scans ----
  listScansForRepository: (
    repositoryId: number,
    filters: ListScansFilters = {}
  ) =>
    apiClient.get<Paginated<Scan>>(`/repositories/${repositoryId}/scans`, {
      query: buildQuery({
        page: filters.page ?? 1,
        page_size: filters.page_size ?? 25,
        status: filters.status,
        trigger_type: filters.trigger_type,
      }),
    }),
  listAllScans: (filters: ListScansFilters = {}) =>
    apiClient.get<Paginated<Scan>>("/scans", {
      query: buildQuery({
        page: filters.page ?? 1,
        page_size: filters.page_size ?? 25,
        status: filters.status,
        trigger_type: filters.trigger_type,
      }),
    }),
  createScan: (repositoryId: number, payload: ScanCreatePayload = {}) =>
    apiClient.post<Scan>(`/repositories/${repositoryId}/scans`, payload),
  getScan: (scanId: number) => apiClient.get<Scan>(`/scans/${scanId}`),
  listStages: (scanId: number) =>
    apiClient.get<{ items: ScanStage[] }>(`/scans/${scanId}/stages`),

  // ---- Findings ----
  listFindings: (scanId: number, filters: ListFindingsFilters = {}) =>
    apiClient.get<Paginated<Finding>>(`/scans/${scanId}/findings`, {
      query: buildQuery({
        page: filters.page ?? 1,
        page_size: filters.page_size ?? 25,
        category: filters.category,
        severity: filters.severity,
        confidence: filters.confidence,
        rule_id: filters.rule_id,
        path: filters.path,
        status: filters.status,
        direct_transitive: filters.direct_transitive,
        provider: filters.provider,
        search: filters.search,
      }),
    }),
  getFinding: (scanId: number, findingId: number) =>
    apiClient.get<Finding>(`/scans/${scanId}/findings/${findingId}`),

  // ---- Provider observations ----
  listProviderObservations: (
    scanId: number,
    filters: { page?: number; page_size?: number; status?: ProviderStatus | "all"; provider?: string } = {}
  ) =>
    apiClient.get<Paginated<ProviderObservation>>(`/scans/${scanId}/providers`, {
      query: buildQuery({
        page: filters.page ?? 1,
        page_size: filters.page_size ?? 25,
        status: filters.status,
        provider: filters.provider,
      }),
    }),
  getProviderHealth: (scanId?: number) =>
    apiClient.get<{ entries: ProviderHealthEntry[] }>(
      scanId ? `/scans/${scanId}/provider-health` : "/provider-health"
    ),
  listProviderHealth: () =>
    apiClient.get<{ entries: ProviderHealthEntry[]; providers: ProviderName[] }>(
      "/provider-health"
    ),

  // ---- Components / dependencies ----
  listComponents: (scanId: number, filters: ListComponentsFilters = {}) =>
    apiClient.get<Paginated<Component>>(`/scans/${scanId}/components`, {
      query: buildQuery({
        page: filters.page ?? 1,
        page_size: filters.page_size ?? 50,
        ecosystem: filters.ecosystem,
        scope: filters.scope,
        development: filters.development,
        vulnerable_only: filters.vulnerable_only,
        search: filters.search,
      }),
    }),
  getDependencyPath: (scanId: number, componentId: number) =>
    apiClient.get<DependencyPath>(`/scans/${scanId}/components/${componentId}/path`),

  // ---- Vulnerabilities ----
  listVulnerabilities: (scanId: number, filters: ListVulnerabilitiesFilters = {}) =>
    apiClient.get<Paginated<ComponentAdvisory>>(`/scans/${scanId}/vulnerabilities`, {
      query: buildQuery({
        page: filters.page ?? 1,
        page_size: filters.page_size ?? 25,
        ecosystem: filters.ecosystem,
        direct_transitive: filters.direct_transitive,
        search: filters.search,
      }),
    }),
  listAdvisories: (scanId: number) =>
    apiClient.get<Paginated<Advisory>>(`/scans/${scanId}/advisories`),

  // ---- Workflow findings ----
  listWorkflowFindings: (scanId: number, filters: ListWorkflowFindingsFilters = {}) =>
    apiClient.get<Paginated<WorkflowFinding>>(`/scans/${scanId}/workflows`, {
      query: buildQuery({
        page: filters.page ?? 1,
        page_size: filters.page_size ?? 25,
        rule_id: filters.rule_id,
        severity: filters.severity,
      }),
    }),

  // ---- OpenSSF posture ----
  listOpenSSF: (scanId: number, filters: ListOpenSSFFilters = {}) =>
    apiClient.get<Paginated<OpenSSFCheck>>(`/scans/${scanId}/openssf`, {
      query: buildQuery({
        page: filters.page ?? 1,
        page_size: filters.page_size ?? 25,
        check_id: filters.check_id,
      }),
    }),

  // ---- Licence inventory ----
  listLicences: (scanId: number, filters: ListLicenceFilters = {}) =>
    apiClient.get<Paginated<LicenceAssertion>>(`/scans/${scanId}/licences`, {
      query: buildQuery({
        page: filters.page ?? 1,
        page_size: filters.page_size ?? 50,
        provider: filters.provider,
        review_status: filters.review_status,
        search: filters.search,
        direct_transitive: filters.direct_transitive,
      }),
    }),

  // ---- Scan comparison ----
  compareScans: (baseScanId: number, headScanId: number) =>
    apiClient.get<ScanComparison>(
      `/scans/${headScanId}/compare/${baseScanId}`
    ),

  // ---- Exports ----
  listExports: (scanId: number) =>
    apiClient.get<{ items: ExportDescriptor[] }>(`/scans/${scanId}/exports`),
  downloadExport: (scanId: number, format: ExportFormat) =>
    apiClient.getText(`/scans/${scanId}/exports/${format}`),
};

export type { ListRepositoriesFilters as _ListRepositoriesFilters };
