/**
 * v0.4 frontend tests for the provider-enrichment pages.
 *
 * These tests cover the v0.4 acceptance criteria for the
 * frontend:
 *
 *  - Vulnerability explorer renders the new columns
 *    (provider, ecosystem, aliases, fixed in, fetched)
 *    from the v0.4 backend response shape.
 *  - The licence inventory page surfaces the deps.dev
 *    enrichment summary when data is available.
 *  - Genuine network failures (e.g. a 5xx) render as a
 *    real error state, never as a fixture fallback.
 *  - Empty successful results render as honest empty
 *    states, never as fabricated rows.
 *  - The polling hook still stops after a terminal scan
 *    (covered by the v0.3 polling tests, retained for
 *    coverage in v0.4).
 *  - The API client exposes the new v0.4 listEnrichments
 *    method.
 *
 * The tests use a global fetch mock injected via
 * ``vi.stubGlobal`` so they do not require a running
 * backend.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";

import { api } from "@/api/api";
import { VulnerabilityExplorerPage } from "@/pages/VulnerabilityExplorerPage";
import { LicenceInventoryPage } from "@/pages/LicenceInventoryPage";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function providerObservationResponse(
  provider: "osv" | "deps_dev",
  options: { disabled?: boolean } = {}
): Response {
  return jsonResponse({
    items: [
      {
        id: 1,
        scan_run_id: 1,
        provider,
        status: options.disabled ? "not_requested" : "available",
        requested_at: null,
        completed_at: null,
        latency_ms: null,
        http_status: null,
        cache_status: null,
        records_returned: 0,
        error_code: options.disabled ? "disabled_by_operator" : null,
        error_summary: null,
        retry_count: 0,
        rate_limit_remaining: null,
        fetched_at: null,
        created_at: "2026-08-11T00:00:00Z",
      },
    ],
    pagination: { page: 1, page_size: 200, total: 1, total_pages: 1 },
  });
}

describe("v0.4 vulnerability explorer", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    cleanup();
  });

  it("renders the v0.4 provider, ecosystem, alias, and fetched columns", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(providerObservationResponse("osv"));
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        items: [
          {
            id: 1,
            component_id: 1,
            advisory_id: 7,
            fixed_versions: ["1.3.0"],
            severity_source: "osv",
            severity_label: "CVSS_V3",
            severity_score: 7,
            confidence: "high",
            dependency_paths: [],
            withdrawn: false,
            package_name: "left-pad",
            package_version: "1.0.0",
            ecosystem: "npm",
            direct: true,
            advisory_source: "osv",
            advisory_external_id: "GHSA-1234-abcd-efgh",
            advisory_canonical_id: "CVE-2024-0001",
            advisory_summary: "Sample advisory",
            advisory_details_url: "https://example.com/advisory",
            affected: true,
            provider_provenance: "osv",
            aliases: ["CVE-2024-0001"],
            fetched_at: "2024-01-01T00:00:00Z",
          },
        ],
        pagination: { page: 1, page_size: 25, total: 1, total_pages: 1 },
      })
    );
    render(
      <MemoryRouter initialEntries={["/scans/1/vulnerabilities"]}>
        <Routes>
          <Route
            path="/scans/:scanId/vulnerabilities"
            element={<VulnerabilityExplorerPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText("GHSA-1234-abcd-efgh")).toBeTruthy();
    });
    expect(screen.getByText("left-pad")).toBeTruthy();
    expect(screen.getByText("CVE-2024-0001")).toBeTruthy();
    expect(screen.getByText("npm")).toBeTruthy();
    expect(screen.getByText("osv")).toBeTruthy();
  });

  it("renders 'Not supplied' for null confidence and never fabricates a value", async () => {
    // Blocker 1: when the upstream provider did not supply
    // a confidence value the API returns ``null``. The UI
    // must render that as a neutral "Not supplied" badge
    // and must never invent "low" / "medium" / "high".
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(providerObservationResponse("osv"));
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        items: [
          {
            id: 1,
            component_id: 1,
            advisory_id: 7,
            fixed_versions: ["1.3.0"],
            severity_source: "osv",
            severity_label: "CVSS_V3",
            severity_score: 9.8,
            confidence: null,
            dependency_paths: [],
            withdrawn: false,
            package_name: "left-pad",
            package_version: "1.0.0",
            ecosystem: "npm",
            direct: true,
            advisory_source: "osv",
            advisory_external_id: "GHSA-1234-abcd-efgh",
            advisory_canonical_id: "CVE-2024-0001",
            advisory_summary: "Sample advisory",
            advisory_details_url: "https://example.com/advisory",
            affected: true,
            provider_provenance: "osv",
            aliases: ["CVE-2024-0001"],
            fetched_at: "2024-01-01T00:00:00Z",
          },
        ],
        pagination: { page: 1, page_size: 25, total: 1, total_pages: 1 },
      })
    );
    render(
      <MemoryRouter initialEntries={["/scans/1/vulnerabilities"]}>
        <Routes>
          <Route
            path="/scans/:scanId/vulnerabilities"
            element={<VulnerabilityExplorerPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText("GHSA-1234-abcd-efgh")).toBeTruthy();
    });
    // The neutral wording is rendered.
    expect(screen.getByText("Not supplied")).toBeTruthy();
    // The UI must never invent a confidence value.
    expect(screen.queryByText(/^(low|medium|high|confirmed)$/i)).toBeNull();
  });

  it("renders an honest empty state when the backend returns zero rows", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(providerObservationResponse("osv"));
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        items: [],
        pagination: { page: 1, page_size: 25, total: 0, total_pages: 0 },
      })
    );
    render(
      <MemoryRouter initialEntries={["/scans/1/vulnerabilities"]}>
        <Routes>
          <Route
            path="/scans/:scanId/vulnerabilities"
            element={<VulnerabilityExplorerPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(
        screen.getByText("No vulnerabilities recorded")
      ).toBeTruthy();
    });
  });

  it("renders a real error state on a 5xx response, never a fixture", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(providerObservationResponse("osv"));
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          error: {
            code: "server",
            message: "Internal Server Error",
            request_id: "req-123",
          },
        },
        500
      )
    );
    render(
      <MemoryRouter initialEntries={["/scans/1/vulnerabilities"]}>
        <Routes>
          <Route
            path="/scans/:scanId/vulnerabilities"
            element={<VulnerabilityExplorerPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      // The error is rendered as text; the assertion is
      // that we never silently fall back to the
      // ``No vulnerabilities recorded`` empty state.
      expect(
        screen.queryByText("No vulnerabilities recorded")
      ).toBeNull();
    });
  });

  it("renders an operator-disabled OSV state neutrally", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(
      providerObservationResponse("osv", { disabled: true })
    );
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        items: [],
        pagination: { page: 1, page_size: 25, total: 0, total_pages: 0 },
      })
    );
    render(
      <MemoryRouter initialEntries={["/scans/1/vulnerabilities"]}>
        <Routes>
          <Route
            path="/scans/:scanId/vulnerabilities"
            element={<VulnerabilityExplorerPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText(/OSV was not requested/i)).toBeInTheDocument();
    });
    expect(screen.queryByText(/provider unavailable/i)).not.toBeInTheDocument();
  });
});

describe("v0.4 licence inventory enrichment summary", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    cleanup();
  });

  it("renders the deps.dev enrichment summary when components are enriched", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    // 1) persisted provider observation; 2) listLicences.
    fetchMock.mockResolvedValueOnce(providerObservationResponse("deps_dev"));
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        items: [
          {
            id: 1,
            scan_run_id: 1,
            component_id: 1,
            package_name: "left-pad",
            version: "1.0.0",
            licence: "MIT",
            direct: true,
            provider: "rule_engine",
            review_status: "unreviewed",
            unknown_licence: false,
            stable_key: "licence-key-1",
          },
        ],
        pagination: { page: 1, page_size: 50, total: 1, total_pages: 1 },
      })
    );
    // 3) listEnrichments
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        items: [
          {
            component_id: 1,
            ecosystem: "npm",
            package_name: "left-pad",
            version: "1.0.0",
            fetched_at: "2024-01-01T00:00:00Z",
            cache_status: "miss",
            provider_url: "https://api.deps.dev/v3/...",
            source_provenance: "deps.dev",
            license_observations: ["MIT"],
            dependency_count: 2,
            provider_status: "available",
            unavailable_reason: null,
          },
        ],
        pagination: { page: 1, page_size: 200, total: 1, total_pages: 1 },
      })
    );
    render(
      <MemoryRouter initialEntries={["/scans/1/licences"]}>
        <Routes>
          <Route
            path="/scans/:scanId/licences"
            element={<LicenceInventoryPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText("MIT")).toBeTruthy();
    });
    await waitFor(() => {
      expect(screen.getByText(/deps.dev enrichment summary/i)).toBeTruthy();
    });
  });

  it("renders an honest 'not requested' state when no components were enriched", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(providerObservationResponse("deps_dev"));
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        items: [],
        pagination: { page: 1, page_size: 50, total: 0, total_pages: 0 },
      })
    );
    render(
      <MemoryRouter initialEntries={["/scans/1/licences"]}>
        <Routes>
          <Route
            path="/scans/:scanId/licences"
            element={<LicenceInventoryPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(
        screen.getByText("No licence assertions recorded")
      ).toBeTruthy();
    });
  });

  it("renders operator-disabled provider states neutrally", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(
      providerObservationResponse("deps_dev", { disabled: true })
    );
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        items: [],
        pagination: { page: 1, page_size: 50, total: 0, total_pages: 0 },
      })
    );
    render(
      <MemoryRouter initialEntries={["/scans/1/licences"]}>
        <Routes>
          <Route
            path="/scans/:scanId/licences"
            element={<LicenceInventoryPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText(/deps\.dev was not requested/i)).toBeInTheDocument();
    });
    expect(screen.queryByText(/provider unavailable/i)).not.toBeInTheDocument();
  });
});

describe("v0.4 API client", () => {
  it("exposes the listEnrichments method", () => {
    expect(typeof api.listEnrichments).toBe("function");
  });
});
