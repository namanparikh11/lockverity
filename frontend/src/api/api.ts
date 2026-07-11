import { apiClient } from "@/api/client";
import type {
  Finding,
  HealthResponse,
  Paginated,
  ProviderObservation,
  Repository,
  Scan,
  ScanStage,
  SystemInfoResponse,
} from "@/api/types";

export const api = {
  health: () => apiClient.get<HealthResponse>("/health"),
  systemInfo: () => apiClient.get<SystemInfoResponse>("/system/info"),

  listRepositories: (page = 1, pageSize = 25) =>
    apiClient.get<Paginated<Repository>>("/repositories", {
      query: { page, page_size: pageSize },
    }),
  getRepository: (id: number) =>
    apiClient.get<Repository>(`/repositories/${id}`),
  createRepository: (canonicalUrl: string) =>
    apiClient.post<Repository>("/repositories", { canonical_url: canonicalUrl }),

  listScansForRepository: (repositoryId: number, page = 1, pageSize = 25) =>
    apiClient.get<Paginated<Scan>>(`/repositories/${repositoryId}/scans`, {
      query: { page, page_size: pageSize },
    }),
  createScan: (repositoryId: number) =>
    apiClient.post<Scan>(`/repositories/${repositoryId}/scans`),
  getScan: (scanId: number) => apiClient.get<Scan>(`/scans/${scanId}`),
  listStages: (scanId: number) =>
    apiClient.get<{ items: ScanStage[] }>(`/scans/${scanId}/stages`),
  listFindings: (
    scanId: number,
    page = 1,
    pageSize = 25,
    filters?: { category?: string; severity?: string }
  ) =>
    apiClient.get<Paginated<Finding>>(`/scans/${scanId}/findings`, {
      query: {
        page,
        page_size: pageSize,
        ...(filters?.category ? { category: filters.category } : {}),
        ...(filters?.severity ? { severity: filters.severity } : {}),
      },
    }),
  listProviderObservations: (
    scanId: number,
    page = 1,
    pageSize = 25,
    status?: string
  ) =>
    apiClient.get<Paginated<ProviderObservation>>(`/scans/${scanId}/providers`, {
      query: {
        page,
        page_size: pageSize,
        ...(status ? { status } : {}),
      },
    }),
};
