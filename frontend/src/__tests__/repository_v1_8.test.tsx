/**
 * v1.8 — Repository history, rescan, and comparison workflow.
 *
 * Covers:
 *  - repository identity, scan history, and per-scan
 *    cross-links;
 *  - URL-persisted status / trigger / page filters;
 *  - bounded wording for partial / failed / cancelled
 *    states;
 *  - the v1.6.1 rescan flow (``api.rescanRepository`` +
 *    ``api.runScan``) replaces the low-level
 *    ``api.createScan`` path;
 *  - ``rescan_source_unavailable`` renders bounded
 *    guidance;
 *  - the repository-scoped comparison selector
 *    (``/repositories/:id/compare?baseline=&comparison=``)
 *    preserves the v0.5 eligibility rules (only
 *    completed / partial scans; same-scan and
 *    cross-repository rejections);
 *  - removed-finding disclaimer and no universal
 *    improvement / worsening claim.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { RepositoryDetailsPage } from "@/pages/RepositoryDetailsPage";
import { RepositoryComparePage } from "@/pages/RepositoryComparePage";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function makeRepo(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 10,
    source_type: "github",
    provider: "github",
    owner: "octocat",
    name: "Hello-World",
    canonical_url: "https://github.com/octocat/Hello-World",
    default_branch: "main",
    description: "synthetic fixture",
    visibility: "public",
    archived: false,
    last_provider_sync_at: null,
    created_at: "2026-07-15T10:00:00Z",
    updated_at: "2026-07-15T10:01:00Z",
    ...overrides,
  };
}

function makeScan(
  id: number,
  overrides: Partial<Record<string, unknown>> = {}
): Record<string, unknown> {
  return {
    id,
    repository_id: 10,
    status: "completed",
    trigger_type: "manual",
    requested_ref: "main",
    resolved_commit_sha: "deadbeef",
    analyzer_version: "lockverity 1.7.0",
    started_at: "2026-07-15T10:00:00Z",
    completed_at: "2026-07-15T10:01:00Z",
    failure_code: null,
    failure_summary: null,
    created_at: "2026-07-15T10:00:00Z",
    updated_at: "2026-07-15T10:01:00Z",
    ...overrides,
  };
}

function setupFetchMock(opts: {
  repository?: Record<string, unknown>;
  scans?: Array<Record<string, unknown>>;
  scansById?: Record<number, Record<string, unknown>>;
  compareResponse?: Record<string, unknown>;
  rescanError?: { status?: number; body?: unknown };
} = {}) {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  const scans = opts.scans ?? [makeScan(1), makeScan(2), makeScan(3)];
  const repo = opts.repository ?? makeRepo();
  const scansById = opts.scansById ?? {};
  fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";
    if (/\/repositories\/10\/rescan/.test(url)) {
      if (opts.rescanError) {
        return Promise.resolve(
          new Response(
            JSON.stringify(
              opts.rescanError.body ?? {
                error: {
                  code: "rescan_source_unavailable",
                  message: "The original uploaded source is no longer available.",
                },
              }
            ),
            {
              status: opts.rescanError.status ?? 422,
              headers: { "content-type": "application/json" },
            }
          )
        );
      }
      return Promise.resolve(
        jsonResponse({ id: 99, ...makeScan(99, { status: "queued" }) })
      );
    }
    if (url.match(/\/scans\/\d+\/run/)) {
      return Promise.resolve(
        jsonResponse({ id: 99, ...makeScan(99, { status: "queued" }) })
      );
    }
    if (url.match(/\/api\/v1\/scans\/\d+$/)) {
      const match = url.match(/\/scans\/(\d+)$/);
      const id = match ? Number.parseInt(match[1], 10) : 1;
      const scan = scansById[id] ?? makeScan(id);
      return Promise.resolve(jsonResponse(scan));
    }
    if (/\/scans\/\d+\/compare\/\d+/.test(url) && opts.compareResponse) {
      return Promise.resolve(jsonResponse(opts.compareResponse));
    }
    if (url.includes("/api/v1/repositories/10") && !url.includes("/scans")) {
      return Promise.resolve(jsonResponse(repo));
    }
    if (url.includes("/api/v1/repositories/10/scans")) {
      return Promise.resolve(
        jsonResponse({
          items: scans,
          pagination: {
            page: 1,
            page_size: 50,
            total: scans.length,
            total_pages: 1,
          },
        })
      );
    }
    if (url.includes("/api/v1/scans/") && url.includes("/stages")) {
      return Promise.resolve(jsonResponse({ items: [] }));
    }
    // Fallback: also accept unused method markers for test
    // inspection.
    void method;
    return Promise.resolve(jsonResponse({}));
  });
  return fetchMock;
}

beforeEach(() => {
  // @ts-expect-error - test environment stub
  window.location = { origin: "http://localhost" };
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("repository v1.8 - history page", () => {
  it("renders scan history newest-first with cross-links", async () => {
    setupFetchMock({
      scans: [
        makeScan(1, { status: "completed", created_at: "2026-07-15T10:00:00Z" }),
        makeScan(2, { status: "partial", created_at: "2026-07-15T11:00:00Z" }),
        makeScan(3, { status: "failed", created_at: "2026-07-15T12:00:00Z" }),
      ],
    });
    render(
      <MemoryRouter initialEntries={["/repositories/10"]}>
        <Routes>
          <Route
            path="/repositories/:repositoryId"
            element={<RepositoryDetailsPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(
        screen.getByTestId("scan-history-row-1")
      ).toBeInTheDocument();
    });
    const row1 = screen.getByTestId("scan-history-row-1");
    expect(within(row1).getByText("#1")).toHaveAttribute(
      "href",
      "/scans/1"
    );
    // Each row exposes the workbench / findings / dependencies / exports
    // cross-links.
    expect(within(row1).getByText("Findings")).toHaveAttribute(
      "href",
      "/scans/1/findings"
    );
    expect(within(row1).getByText("Dependencies")).toHaveAttribute(
      "href",
      "/scans/1/dependencies"
    );
    expect(within(row1).getByText("Exports")).toHaveAttribute(
      "href",
      "/scans/1/exports"
    );
  });

  it("filters by status through the URL", async () => {
    const fetchMock = setupFetchMock();
    render(
      <MemoryRouter initialEntries={["/repositories/10?status=partial"]}>
        <Routes>
          <Route
            path="/repositories/:repositoryId"
            element={<RepositoryDetailsPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(
        screen.getByTestId("scan-history-heading")
      ).toBeInTheDocument();
    });
    await waitFor(() => {
      // The main table is the first call (before the
      // CompareScansCard helper fetch). Look for any
      // /repositories/:id/scans? call that carries
      // the status filter.
      const call = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes("/scans?")
      );
      expect(call).toBeTruthy();
      const url = String(call![0]);
      expect(url).toMatch(/status=partial/);
    });
  });

  it("renders the partial-scan notice when filtering to partial", async () => {
    setupFetchMock();
    render(
      <MemoryRouter initialEntries={["/repositories/10?status=partial"]}>
        <Routes>
          <Route
            path="/repositories/:repositoryId"
            element={<RepositoryDetailsPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText(/Showing partial scans only/)).toBeInTheDocument();
    });
  });

  it("renders the failed-scan notice when filtering to failed", async () => {
    setupFetchMock();
    render(
      <MemoryRouter initialEntries={["/repositories/10?status=failed"]}>
        <Routes>
          <Route
            path="/repositories/:repositoryId"
            element={<RepositoryDetailsPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText(/Showing failed scans only/)).toBeInTheDocument();
    });
  });

  it("renders the cancelled-scan notice when filtering to cancelled", async () => {
    setupFetchMock();
    render(
      <MemoryRouter initialEntries={["/repositories/10?status=cancelled"]}>
        <Routes>
          <Route
            path="/repositories/:repositoryId"
            element={<RepositoryDetailsPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText(/Showing cancelled scans only/)).toBeInTheDocument();
    });
  });

  it("renders the empty-state bounded copy when no scans exist", async () => {
    setupFetchMock({ scans: [] });
    render(
      <MemoryRouter initialEntries={["/repositories/10"]}>
        <Routes>
          <Route
            path="/repositories/:repositoryId"
            element={<RepositoryDetailsPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(
        screen.getAllByText(/No scans have been recorded for this repository/)
          .length
      ).toBeGreaterThan(0);
    });
    // The empty state must NOT claim a clean result.
    // The bounded disclaimer explicitly says
    // "vulnerability-free" in its negative form, so we
    // assert the negative framing and the absence of
    // positive claim words.
    const body = document.body.textContent ?? "";
    expect(body).toMatch(/does not establish that the repository is vulnerability-free/);
    expect(body).not.toMatch(/is clean\b/i);
    expect(body).not.toMatch(/is secure\b/i);
    expect(body).not.toMatch(/is safe\b/i);
    expect(body).not.toMatch(/passed the scan/i);
  });
});

describe("repository v1.8 - rescan integration", () => {
  it("Run another scan uses the v1.6.1 rescan endpoint, not the low-level scan-record creator", async () => {
    const fetchMock = setupFetchMock({
      scansById: { 1: makeScan(1, { status: "completed" }) },
    });
    render(
      <MemoryRouter initialEntries={["/repositories/10"]}>
        <Routes>
          <Route
            path="/repositories/:repositoryId"
            element={<RepositoryDetailsPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(
        screen.getByTestId("repository-run-another-scan")
      ).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("repository-run-another-scan"));
    await waitFor(() => {
      const rescanCall = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes("/rescan")
      );
      expect(rescanCall).toBeTruthy();
    });
    // The low-level scan-record endpoint MUST NOT be
    // called from the "Run another scan" button. The
    // v1.6.1 fix replaces this path.
    const lowLevelCalls = fetchMock.mock.calls.filter((c) => {
      const url = String(c[0]);
      return (
        url.endsWith("/repositories/10/scans") &&
        (url.includes("POST") || c[1]?.method === "POST")
      );
    });
    expect(lowLevelCalls.length).toBe(0);
    // After rescan, the worker is asked to start the new
    // scan. The page navigates to the new workbench.
    await waitFor(() => {
      const runCall = fetchMock.mock.calls.find((c) =>
        String(c[0]).match(/\/scans\/\d+\/run/)
      );
      expect(runCall).toBeTruthy();
    });
  });

  it("renders bounded source-unavailable guidance when rescan fails", async () => {
    setupFetchMock({
      rescanError: {
        status: 422,
        body: {
          error: {
            code: "rescan_source_unavailable",
            message:
              "The original uploaded source is no longer available.",
            details: { repository_id: 10 },
          },
        },
      },
    });
    render(
      <MemoryRouter initialEntries={["/repositories/10"]}>
        <Routes>
          <Route
            path="/repositories/:repositoryId"
            element={<RepositoryDetailsPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(
        screen.getByTestId("repository-run-another-scan")
      ).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("repository-run-another-scan"));
    await waitFor(() => {
      expect(
        screen.getByTestId("repository-rescan-error")
      ).toBeInTheDocument();
    });
    expect(
      screen.getByText(/Rescan source is no longer available/)
    ).toBeInTheDocument();
  });
});

describe("repository v1.8 - comparison selector", () => {
  it("renders the selector when no ids are supplied", async () => {
    setupFetchMock({
      scans: [
        makeScan(1, { status: "completed" }),
        makeScan(2, { status: "partial" }),
        makeScan(3, { status: "failed" }),
        makeScan(4, { status: "cancelled" }),
      ],
    });
    render(
      <MemoryRouter initialEntries={["/repositories/10/compare"]}>
        <Routes>
          <Route
            path="/repositories/:repositoryId/compare"
            element={<RepositoryComparePage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(
        screen.getByTestId("repository-compare-help")
      ).toBeInTheDocument();
    });
    // The selector lists only completed and partial scans.
    expect(
      screen.getByTestId("compare-candidate-row-1")
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("compare-candidate-row-2")
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("compare-candidate-row-3")
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("compare-candidate-row-4")
    ).not.toBeInTheDocument();
  });

  it("renders the empty-state when no eligible scans exist", async () => {
    setupFetchMock({
      scans: [makeScan(1, { status: "failed" })],
    });
    render(
      <MemoryRouter initialEntries={["/repositories/10/compare"]}>
        <Routes>
          <Route
            path="/repositories/:repositoryId/compare"
            element={<RepositoryComparePage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(
        screen.getByText(/No eligible scans to compare/)
      ).toBeInTheDocument();
    });
  });

  it("blocks same-scan selection through the URL state", async () => {
    setupFetchMock({
      scansById: { 1: makeScan(1, { status: "completed" }) },
      scans: [makeScan(1, { status: "completed" })],
    });
    render(
      <MemoryRouter
        initialEntries={["/repositories/10/compare?baseline=1&comparison=1"]}
      >
        <Routes>
          <Route
            path="/repositories/:repositoryId/compare"
            element={<RepositoryComparePage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(
        screen.getByText(/Same-scan comparison is not allowed/)
      ).toBeInTheDocument();
    });
  });

  it("blocks a failed scan as a baseline", async () => {
    setupFetchMock({
      scansById: {
        1: makeScan(1, { status: "completed" }),
        2: makeScan(2, { status: "failed" }),
      },
      scans: [
        makeScan(1, { status: "completed" }),
        makeScan(2, { status: "failed" }),
      ],
    });
    render(
      <MemoryRouter
        initialEntries={["/repositories/10/compare?baseline=2&comparison=1"]}
      >
        <Routes>
          <Route
            path="/repositories/:repositoryId/compare"
            element={<RepositoryComparePage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(
        screen.getByText(
          /This scan did not complete and is not eligible as a comparison baseline/
        )
      ).toBeInTheDocument();
    });
  });

  it("blocks a cross-repository scan id", async () => {
    setupFetchMock({
      scansById: {
        1: makeScan(1, { status: "completed", repository_id: 999 }),
        2: makeScan(2, { status: "completed", repository_id: 999 }),
      },
      scans: [
        makeScan(1, { status: "completed", repository_id: 999 }),
        makeScan(2, { status: "completed", repository_id: 999 }),
      ],
    });
    render(
      <MemoryRouter
        initialEntries={["/repositories/10/compare?baseline=1&comparison=2"]}
      >
        <Routes>
          <Route
            path="/repositories/:repositoryId/compare"
            element={<RepositoryComparePage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(
        screen.getByText(/Cross-repository comparison is not allowed/)
      ).toBeInTheDocument();
    });
  });

  it("URL state survives reload through ?baseline=&comparison=", async () => {
    setupFetchMock({
      scansById: {
        1: makeScan(1, { status: "completed" }),
        2: makeScan(2, { status: "completed" }),
      },
      scans: [
        makeScan(1, { status: "completed" }),
        makeScan(2, { status: "completed" }),
      ],
      compareResponse: {
        base_scan_id: 1,
        head_scan_id: 2,
        repository_id: 10,
        base_trigger_type: "manual",
        head_trigger_type: "manual",
        base_resolved_commit_sha: "deadbeef",
        head_resolved_commit_sha: "deadbeef",
        base_analyzer_version: "lockverity 1.7.0",
        head_analyzer_version: "lockverity 1.7.0",
        base_completed_at: "2026-07-15T10:00:00Z",
        head_completed_at: "2026-07-15T10:01:00Z",
        generated_at: "2026-07-15T10:01:30Z",
        coverage: {
          base_scan_status: "completed",
          head_scan_status: "completed",
          components_in_base: 0,
          components_in_head: 0,
          findings_in_base: 0,
          findings_in_head: 0,
          vulnerabilities_in_base: 0,
          vulnerabilities_in_head: 0,
          workflows_in_base: 0,
          workflows_in_head: 0,
          manifests_in_base: 0,
          manifests_in_head: 0,
          licence_assertions_in_base: 0,
          licence_assertions_in_head: 0,
          openssf_checks_in_base: 0,
          openssf_checks_in_head: 0,
          providers_with_changed_state: 0,
          providers_with_indeterminate_head: 0,
        },
        components: [],
        manifests: [],
        dependency_paths: [],
        workflows: [],
        vulnerabilities: [],
        licences: [],
        openssf: [],
        providers: [],
        indeterminate_reasons: [],
      },
    });
    render(
      <MemoryRouter
        initialEntries={["/repositories/10/compare?baseline=1&comparison=2"]}
      >
        <Routes>
          <Route
            path="/repositories/:repositoryId/compare"
            element={<RepositoryComparePage />}
          />
        </Routes>
      </MemoryRouter>
    );
    // The comparison engine renders the v0.5 state
    // vocabulary; the page's breadcrumb is
    // Repository -> Compare.
    await waitFor(() => {
      expect(screen.getAllByText(/newly observed/i).length).toBeGreaterThan(0);
    });
  });
});

describe("repository v1.8 - honesty and integrity", () => {
  it("never labels a scan as improved or worsened in the comparison response", async () => {
    setupFetchMock({
      scansById: {
        1: makeScan(1, { status: "completed" }),
        2: makeScan(2, { status: "completed" }),
      },
      scans: [makeScan(1, { status: "completed" }), makeScan(2, { status: "completed" })],
      compareResponse: {
        base_scan_id: 1,
        head_scan_id: 2,
        repository_id: 10,
        base_trigger_type: "manual",
        head_trigger_type: "manual",
        base_resolved_commit_sha: "deadbeef",
        head_resolved_commit_sha: "deadbeef",
        base_analyzer_version: "lockverity 1.7.0",
        head_analyzer_version: "lockverity 1.7.0",
        base_completed_at: "2026-07-15T10:00:00Z",
        head_completed_at: "2026-07-15T10:01:00Z",
        generated_at: "2026-07-15T10:01:30Z",
        coverage: {
          base_scan_status: "completed",
          head_scan_status: "completed",
          components_in_base: 0,
          components_in_head: 0,
          findings_in_base: 0,
          findings_in_head: 0,
          vulnerabilities_in_base: 0,
          vulnerabilities_in_head: 0,
          workflows_in_base: 0,
          workflows_in_head: 0,
          manifests_in_base: 0,
          manifests_in_head: 0,
          licence_assertions_in_base: 0,
          licence_assertions_in_head: 0,
          openssf_checks_in_base: 0,
          openssf_checks_in_head: 0,
          providers_with_changed_state: 0,
          providers_with_indeterminate_head: 0,
        },
        components: [],
        manifests: [],
        dependency_paths: [],
        workflows: [],
        vulnerabilities: [
          {
            component_id_base: 1,
            component_id_head: null,
            ecosystem: "npm",
            package_name: "left-pad",
            package_version_base: "1.0.0",
            package_version_head: null,
            advisory_source: "osv",
            advisory_external_id: "GHSA-removed",
            advisory_canonical_id: null,
            severity_label_base: "low",
            severity_score_base: 3.0,
            severity_label_head: null,
            severity_score_head: null,
            state: "no_longer_observed",
            provider_provenance_base: "osv",
            provider_provenance_head: null,
            fetched_at_base: "2026-07-15T10:00:00Z",
            fetched_at_head: null,
            ambiguity_reason: null,
          },
        ],
        licences: [],
        openssf: [],
        providers: [],
        indeterminate_reasons: [],
      },
    });
    render(
      <MemoryRouter
        initialEntries={["/repositories/10/compare?baseline=1&comparison=2"]}
      >
        <Routes>
          <Route
            path="/repositories/:repositoryId/compare"
            element={<RepositoryComparePage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText(/no longer observed/i)).toBeInTheDocument();
    });
    // The page must surface the v0.5 removed-finding
    // disclaimer (the comparison engine plus the page
    // copy) and must NOT claim security improved. The
    // existing v0.5 wording in the Vulnerabilities
    // section says: "is not described as fixed or
    // resolved".
    expect(
      screen.getByText(
        /is not described as fixed or resolved/i
      )
    ).toBeInTheDocument();
    const body = document.body.textContent ?? "";
    expect(body).not.toMatch(/security improved/i);
    expect(body).not.toMatch(/security worsened/i);
    expect(body).not.toMatch(/risk increased/i);
    expect(body).not.toMatch(/risk decreased/i);
    expect(body).not.toMatch(/remediated/i);
  });

  it("renders a partial-comparison warning when one side is partial", async () => {
    setupFetchMock({
      scansById: {
        1: makeScan(1, { status: "completed" }),
        2: makeScan(2, { status: "partial" }),
      },
      scans: [makeScan(1, { status: "completed" }), makeScan(2, { status: "partial" })],
      compareResponse: {
        base_scan_id: 1,
        head_scan_id: 2,
        repository_id: 10,
        base_trigger_type: "manual",
        head_trigger_type: "manual",
        base_resolved_commit_sha: "deadbeef",
        head_resolved_commit_sha: "deadbeef",
        base_analyzer_version: "lockverity 1.7.0",
        head_analyzer_version: "lockverity 1.7.0",
        base_completed_at: "2026-07-15T10:00:00Z",
        head_completed_at: null,
        generated_at: "2026-07-15T10:01:30Z",
        coverage: {
          base_scan_status: "completed",
          head_scan_status: "partial",
          components_in_base: 0,
          components_in_head: 0,
          findings_in_base: 0,
          findings_in_head: 0,
          vulnerabilities_in_base: 0,
          vulnerabilities_in_head: 0,
          workflows_in_base: 0,
          workflows_in_head: 0,
          manifests_in_base: 0,
          manifests_in_head: 0,
          licence_assertions_in_base: 0,
          licence_assertions_in_head: 0,
          openssf_checks_in_base: 0,
          openssf_checks_in_head: 0,
          providers_with_changed_state: 0,
          providers_with_indeterminate_head: 0,
        },
        components: [],
        manifests: [],
        dependency_paths: [],
        workflows: [],
        vulnerabilities: [],
        licences: [],
        openssf: [],
        providers: [],
        indeterminate_reasons: [
          "head scan is in state partial; coverage may be incomplete",
        ],
      },
    });
    render(
      <MemoryRouter
        initialEntries={["/repositories/10/compare?baseline=1&comparison=2"]}
      >
        <Routes>
          <Route
            path="/repositories/:repositoryId/compare"
            element={<RepositoryComparePage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(
        screen.getByText(/Comparison indeterminate/i)
      ).toBeInTheDocument();
    });
  });
});
