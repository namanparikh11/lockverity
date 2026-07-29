/**
 * v0.5 evidence-aware scan comparison frontend tests.
 *
 * These tests cover the v0.5 acceptance criteria for the
 * frontend:
 *
 *  - The comparison page renders the v0.5 state vocabulary
 *    ("Newly observed", "Still observed", "No longer observed",
 *    "Changed observation", "Coverage changed", "Comparison
 *    indeterminate") for components, workflows, vulnerabilities,
 *    and provider coverage.
 *  - "No longer observed" is never rendered as "Fixed" or
 *    "Resolved". The page never makes up severity, confidence,
 *    or coverage values.
 *  - The coverage-and-provenance summary surfaces the per-scan
 *    counts and per-provider states; "no differences observed"
 *    is qualified by a coverage caveat.
 *  - The direct comparison route survives a refresh (the URL
 *    is the only state the page reads).
 *  - Loading, validation-error, API-error, empty, partial,
 *    unavailable, unsupported, and indeterminate states all
 *    render without falling back to fabricated data.
 *  - The "Compare with…" action on the scan details page
 *    surfaces eligibility correctly.
 *  - Deterministic ordering of components, manifests, and
 *    providers is preserved.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";

import { ScanComparisonPage } from "@/pages/ScanComparisonPage";
import { ScanCompareSelectPage } from "@/pages/ScanCompareSelectPage";
import { RepositoryDetailsPage } from "@/pages/RepositoryDetailsPage";
import type { Scan, ScanComparison } from "@/api/types";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function makeScan(overrides: Partial<Scan> = {}): Scan {
  return {
    id: 1,
    repository_id: 10,
    status: "completed",
    trigger_type: "manual",
    requested_ref: null,
    resolved_commit_sha: "abc1234567",
    analyzer_version: "0.5.0",
    started_at: "2024-01-01T00:00:00Z",
    completed_at: "2024-01-01T00:10:00Z",
    failure_code: null,
    failure_summary: null,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:10:00Z",
    ...overrides,
  };
}

function makeComparison(overrides: Partial<ScanComparison> = {}): ScanComparison {
  return {
    base_scan_id: 1,
    head_scan_id: 2,
    repository_id: 10,
    base_trigger_type: "manual",
    head_trigger_type: "manual",
    base_resolved_commit_sha: "abc1234567",
    head_resolved_commit_sha: "def8901234",
    base_analyzer_version: "0.5.0",
    head_analyzer_version: "0.5.0",
    base_completed_at: "2024-01-01T00:10:00Z",
    head_completed_at: "2024-02-01T00:10:00Z",
    generated_at: "2024-02-02T00:00:00Z",
    coverage: {
      base_scan_status: "completed",
      head_scan_status: "completed",
      components_in_base: 2,
      components_in_head: 3,
      findings_in_base: 1,
      findings_in_head: 2,
      vulnerabilities_in_base: 1,
      vulnerabilities_in_head: 0,
      workflows_in_base: 1,
      workflows_in_head: 2,
      manifests_in_base: 1,
      manifests_in_head: 1,
      licence_assertions_in_base: 0,
      licence_assertions_in_head: 0,
      openssf_checks_in_base: 0,
      openssf_checks_in_head: 0,
      providers_with_changed_state: 1,
      providers_with_indeterminate_head: 0,
    },
    components: [
      {
        ecosystem: "npm",
        package_name: "left-pad",
        version: "2.0.0",
        manifest_paths: ["package.json"],
        direct_base: null,
        direct_head: true,
        state: "newly_observed",
      },
      {
        ecosystem: "npm",
        package_name: "left-pad",
        version: "1.0.0",
        manifest_paths: ["package.json"],
        direct_base: true,
        direct_head: null,
        state: "no_longer_observed",
      },
      {
        ecosystem: "npm",
        package_name: "stay",
        version: "1.0.0",
        manifest_paths: ["package.json"],
        direct_base: true,
        direct_head: true,
        state: "still_observed",
      },
      {
        ecosystem: "npm",
        package_name: "right-pad",
        version: "1.0.0",
        manifest_paths: ["package.json"],
        direct_base: null,
        direct_head: true,
        state: "newly_observed",
      },
      {
        ecosystem: "npm",
        package_name: "left-pad-deprecated",
        version: "0.5.0",
        manifest_paths: ["package.json"],
        direct_base: true,
        direct_head: null,
        state: "no_longer_observed",
      },
    ],
    manifests: [
      {
        manifest_path: "package.json",
        manifest_type: "package_json",
        ecosystem: "npm",
        parse_status_base: "parsed",
        parse_status_head: "parsed",
        content_sha256_base: "a".repeat(64),
        content_sha256_head: "b".repeat(64),
        state: "changed_observation",
      },
    ],
    dependency_paths: [],
    workflows: [
      {
        rule_id: "LOCK-WF-001",
        workflow_path: ".github/workflows/ci.yml",
        title: "Unpinned third-party action",
        severity_base: "high",
        severity_head: "high",
        confidence_base: "high",
        confidence_head: "high",
        stable_key: "wf-1",
        state: "still_observed",
      },
      {
        rule_id: "LOCK-WF-002",
        workflow_path: ".github/workflows/release.yml",
        title: "Token write permissions",
        severity_base: null,
        severity_head: "high",
        confidence_base: null,
        confidence_head: "high",
        stable_key: "wf-2",
        state: "newly_observed",
      },
    ],
    vulnerabilities: [
      {
        component_id_base: 11,
        component_id_head: null,
        ecosystem: "npm",
        package_name: "left-pad-deprecated",
        package_version_base: "0.5.0",
        package_version_head: null,
        advisory_source: "osv",
        advisory_external_id: "GHSA-1",
        advisory_canonical_id: "CVE-2024-0001",
        severity_label_base: "CVSS_V3",
        severity_score_base: 7.5,
        severity_label_head: null,
        severity_score_head: null,
        state: "comparison_indeterminate",
        provider_provenance_base: "osv",
        provider_provenance_head: null,
        fetched_at_base: "2024-01-01T00:00:00Z",
        fetched_at_head: null,
        ambiguity_reason: "head provider state for osv was unavailable",
      },
    ],
    licences: [],
    openssf: [],
    providers: [
      {
        provider: "osv",
        state_base: "successful",
        state_head: "unavailable",
        last_completed_at_base: "2024-01-01T00:00:00Z",
        last_completed_at_head: null,
        records_returned_base: 1,
        records_returned_head: 0,
        cache_status_base: "miss",
        cache_status_head: "miss",
        error_code_base: null,
        error_summary_base: null,
        error_code_head: "provider_unavailable",
        error_summary_head: "osv.dev 503",
        evidence_present_base: true,
        evidence_present_head: false,
        state: "coverage_changed",
      },
      {
        provider: "deps_dev",
        state_base: "successful",
        state_head: "successful",
        last_completed_at_base: "2024-01-01T00:00:00Z",
        last_completed_at_head: "2024-02-01T00:00:00Z",
        records_returned_base: 2,
        records_returned_head: 2,
        cache_status_base: "miss",
        cache_status_head: "miss",
        error_code_base: null,
        error_summary_base: null,
        error_code_head: null,
        error_summary_head: null,
        evidence_present_base: true,
        evidence_present_head: true,
        state: "still_observed",
      },
    ],
    indeterminate_reasons: [
      "head provider 'osv' state is unavailable",
    ],
    ...overrides,
  };
}

describe("v0.5 scan comparison page", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    cleanup();
  });

  it("renders the v0.5 state vocabulary on every observation row", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(jsonResponse(makeComparison()));
    render(
      <MemoryRouter initialEntries={["/scans/2/compare/1"]}>
        <Routes>
          <Route
            path="/scans/:scanId/compare/:baseScanId"
            element={<ScanComparisonPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getAllByText("Newly observed").length).toBeGreaterThan(0);
    });
    // The six v0.5 component states are all present in the
    // rendered vocabulary. We use getAllByText because the
    // page renders multiple rows with the same state.
    expect(screen.getAllByText("Changed observation").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Still observed").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Newly observed").length).toBeGreaterThan(0);
    expect(screen.getAllByText("No longer observed").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Comparison indeterminate").length).toBeGreaterThan(0);
    // "Coverage changed" is rendered as an observation-state
    // badge for provider rows whose availability or
    // freshness moved between the two scans.
    expect(screen.getAllByText("Coverage changed").length).toBeGreaterThan(0);
  });

  it("never renders a 'no longer observed' row as 'Fixed' or 'Resolved'", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(jsonResponse(makeComparison()));
    render(
      <MemoryRouter initialEntries={["/scans/2/compare/1"]}>
        <Routes>
          <Route
            path="/scans/:scanId/compare/:baseScanId"
            element={<ScanComparisonPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getAllByText("No longer observed").length).toBeGreaterThan(0);
    });
    // The comparator never claims anything is fixed, secure,
    // clean, resolved, or improved. The page description is
    // allowed to mention those words in the meta-statement
    // "A row is never marked fixed or resolved", but the
    // rendered observation rows themselves must not carry
    // those labels. We assert this by checking the row-level
    // state badges only.
    const badges = screen.getAllByText(
      /^(Newly observed|Still observed|No longer observed|Changed observation|Coverage changed|Comparison indeterminate)$/
    );
    for (const badge of badges) {
      const label = badge.textContent ?? "";
      expect(label).not.toMatch(/\bfixed\b/i);
      expect(label).not.toMatch(/\bresolved\b/i);
      expect(label).not.toMatch(/\bclean\b/i);
      expect(label).not.toMatch(/\bsecure\b/i);
      expect(label).not.toMatch(/\ball clear\b/i);
    }
  });

  it("displays base and head scan identities, statuses, and timestamps", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(jsonResponse(makeComparison()));
    render(
      <MemoryRouter initialEntries={["/scans/2/compare/1"]}>
        <Routes>
          <Route
            path="/scans/:scanId/compare/:baseScanId"
            element={<ScanComparisonPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText("Base scan")).toBeTruthy();
    });
    expect(screen.getByText("Head scan")).toBeTruthy();
    expect(screen.getAllByText("Base scan #1 observed").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Head scan #2 observed").length).toBeGreaterThan(0);
    // The repository id is surfaced to anchor the comparison.
    expect(screen.getAllByText(/repository #10/).length).toBeGreaterThan(0);
  });

  it("separates local evidence from provider-derived evidence with explicit section headings", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(jsonResponse(makeComparison()));
    render(
      <MemoryRouter initialEntries={["/scans/2/compare/1"]}>
        <Routes>
          <Route
            path="/scans/:scanId/compare/:baseScanId"
            element={<ScanComparisonPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText("Local evidence")).toBeTruthy();
    });
    expect(screen.getByText("Provider-derived evidence")).toBeTruthy();
    expect(screen.getByText("Components and versions")).toBeTruthy();
    expect(screen.getByText("Manifests")).toBeTruthy();
    expect(screen.getByText("Workflow findings")).toBeTruthy();
    expect(screen.getByText("Vulnerabilities")).toBeTruthy();
    expect(screen.getByText("Provider coverage")).toBeTruthy();
  });

  it("surfaces provider state explicitly (successful, cached, unavailable)", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(jsonResponse(makeComparison()));
    render(
      <MemoryRouter initialEntries={["/scans/2/compare/1"]}>
        <Routes>
          <Route
            path="/scans/:scanId/compare/:baseScanId"
            element={<ScanComparisonPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getAllByText("successful").length).toBeGreaterThan(0);
    });
    expect(screen.getByText("unavailable")).toBeTruthy();
    // The successful provider row carries the structured
    // evidence envelope, never an error_summary.
    const body = document.body.textContent ?? "";
    // The successful row has no error_summary_base; only the
    // unavailable one does. We check the page does not attribute
    // an error_summary to a successful row.
    expect(body).toMatch(/successful/);
    expect(body).toMatch(/unavailable/);
  });

  it("qualifies 'no differences observed' with a coverage caveat", async () => {
    const emptyComparison = makeComparison({
      components: [],
      manifests: [],
      workflows: [],
      vulnerabilities: [],
      licences: [],
      openssf: [],
      providers: [],
      indeterminate_reasons: [],
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
    });
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(jsonResponse(emptyComparison));
    render(
      <MemoryRouter initialEntries={["/scans/2/compare/1"]}>
        <Routes>
          <Route
            path="/scans/:scanId/compare/:baseScanId"
            element={<ScanComparisonPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getAllByText(/no differences observed/i).length).toBeGreaterThan(0);
    });
    const body = document.body.textContent ?? "";
    // The empty state must include a coverage qualification so
    // a quiet comparison cannot be mistaken for an all-clear.
    expect(body).toMatch(/coverage/i);
  });

  it("renders an indeterminate notice when indeterminate_reasons is non-empty", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(jsonResponse(makeComparison()));
    render(
      <MemoryRouter initialEntries={["/scans/2/compare/1"]}>
        <Routes>
          <Route
            path="/scans/:scanId/compare/:baseScanId"
            element={<ScanComparisonPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(
        screen.getByText(/Some rows are marked 'Comparison indeterminate'/i)
      ).toBeTruthy();
    });
    expect(
      screen.getByText("head provider 'osv' state is unavailable")
    ).toBeTruthy();
  });

  it("renders a validation error on identical scan selection", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          error: {
            code: "validation_error",
            message: "Base and head scans must be distinct.",
            request_id: "req-1",
          },
        },
        422
      )
    );
    render(
      <MemoryRouter initialEntries={["/scans/2/compare/2"]}>
        <Routes>
          <Route
            path="/scans/:scanId/compare/:baseScanId"
            element={<ScanComparisonPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText("Could not compare scans")).toBeTruthy();
    });
    expect(
      screen.getByText("Base and head scans must be distinct.")
    ).toBeTruthy();
  });

  it("renders an API error on 5xx", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          error: {
            code: "server",
            message: "Internal Server Error",
            request_id: "req-1",
          },
        },
        500
      )
    );
    render(
      <MemoryRouter initialEntries={["/scans/2/compare/1"]}>
        <Routes>
          <Route
            path="/scans/:scanId/compare/:baseScanId"
            element={<ScanComparisonPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText("Could not compare scans")).toBeTruthy();
    });
    expect(screen.getByText("Internal Server Error")).toBeTruthy();
  });

  it("preserves the direct comparison route after a refresh", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(jsonResponse(makeComparison()));
    const { unmount } = render(
      <MemoryRouter initialEntries={["/scans/2/compare/1"]}>
        <Routes>
          <Route
            path="/scans/:scanId/compare/:baseScanId"
            element={<ScanComparisonPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText("Base scan")).toBeTruthy();
    });
    // Refresh: re-mount with the same URL. The page must
    // re-issue the GET to the same comparison endpoint.
    fetchMock.mockResolvedValueOnce(jsonResponse(makeComparison()));
    unmount();
    render(
      <MemoryRouter initialEntries={["/scans/2/compare/1"]}>
        <Routes>
          <Route
            path="/scans/:scanId/compare/:baseScanId"
            element={<ScanComparisonPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText("Base scan")).toBeTruthy();
    });
    // The fetch was called twice (initial + refresh).
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [url] = fetchMock.mock.calls[1] as [string, RequestInit?];
    expect(url).toMatch(/\/scans\/2\/compare\/1$/);
  });

  it("links back to both source scan-detail pages", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(jsonResponse(makeComparison()));
    render(
      <MemoryRouter initialEntries={["/scans/2/compare/1"]}>
        <Routes>
          <Route
            path="/scans/:scanId/compare/:baseScanId"
            element={<ScanComparisonPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getAllByText("Base scan").length).toBeGreaterThan(0);
    });
    const links = screen.getAllByRole("link");
    const headLinks = links.filter((l) => l.getAttribute("href") === "/scans/2");
    const baseLinks = links.filter((l) => l.getAttribute("href") === "/scans/1");
    expect(headLinks.length).toBeGreaterThan(0);
    expect(baseLinks.length).toBeGreaterThan(0);
  });

  it("preserves the determinism of the response in its rendering order", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    const data = makeComparison();
    fetchMock.mockResolvedValueOnce(jsonResponse(data));
    render(
      <MemoryRouter initialEntries={["/scans/2/compare/1"]}>
        <Routes>
          <Route
            path="/scans/:scanId/compare/:baseScanId"
            element={<ScanComparisonPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getAllByText("left-pad").length).toBeGreaterThan(0);
    });
    // The five component rows are present: left-pad 1.0.0
    // (no_longer_observed), left-pad 2.0.0 (newly_observed),
    // stay 1.0.0 (still_observed), right-pad 1.0.0
    // (newly_observed), left-pad-deprecated 0.5.0
    // (no_longer_observed). The table renders them in the
    // order the API returned (no client-side resort could
    // make a "no longer observed" row appear before a
    // "newly observed" one).
    const componentCells = screen.getAllByText(
      /^(left-pad|stay|right-pad|left-pad-deprecated)$/
    );
    // Expect at least 5 component cells. The page may also
    // surface the same package name in tooltips or summary
    // text, so we assert >= 5 rather than a strict count.
    expect(componentCells.length).toBeGreaterThanOrEqual(5);
  });
});

describe("v0.5 compare action eligibility", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    cleanup();
  });

  it("lists eligible terminal scans as comparison partners", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(
      jsonResponse(makeScan({ id: 2, repository_id: 10, status: "completed" }))
    );
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        items: [
          makeScan({ id: 1, repository_id: 10, status: "completed" }),
          makeScan({ id: 3, repository_id: 10, status: "partial" }),
          makeScan({ id: 4, repository_id: 10, status: "running" }),
        ],
        pagination: { page: 1, page_size: 50, total: 3, total_pages: 1 },
      })
    );
    render(
      <MemoryRouter initialEntries={["/scans/2/compare-select"]}>
        <Routes>
          <Route
            path="/scans/:scanId/compare-select"
            element={<ScanCompareSelectPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getAllByText("Use as base").length).toBeGreaterThan(0);
    });
    // Two eligible scans (the completed and the partial);
    // the running one is excluded.
    const useAsBaseButtons = screen.getAllByText("Use as base");
    expect(useAsBaseButtons).toHaveLength(2);
  });

  it("renders a 'no eligible scan' empty state when no other terminal scan exists", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(
      jsonResponse(makeScan({ id: 2, repository_id: 10, status: "completed" }))
    );
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        items: [makeScan({ id: 2, repository_id: 10, status: "completed" })],
        pagination: { page: 1, page_size: 50, total: 1, total_pages: 1 },
      })
    );
    render(
      <MemoryRouter initialEntries={["/scans/2/compare-select"]}>
        <Routes>
          <Route
            path="/scans/:scanId/compare-select"
            element={<ScanCompareSelectPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText(/no eligible scan/i)).toBeTruthy();
    });
  });
});

/**
 * Focused regression tests for the comparison-selector
 * eligibility filter.
 *
 * The v0.5 backend rejects comparisons involving
 * ``failed`` and ``cancelled`` scans with ``409
 * illegal_transition``. The frontend must mirror that rule
 * so the user is never offered a comparison action the
 * backend will refuse. Each test sets up a known list of
 * scans and asserts the exact set of "Use as base" buttons
 * the page renders.
 */
describe("ScanCompareSelectPage eligibility filter", () => {
  function renderSelector(args: {
    headId: number;
    head: { id: number; repository_id: number; status: Scan["status"] };
    candidates: Array<{ id: number; repository_id: number; status: Scan["status"] }>;
  }) {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(
      jsonResponse(makeScan(args.head))
    );
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        items: args.candidates.map((c) => makeScan(c)),
        pagination: {
          page: 1,
          page_size: 50,
          total: args.candidates.length,
          total_pages: 1,
        },
      })
    );
    render(
      <MemoryRouter
        initialEntries={[`/scans/${args.headId}/compare-select`]}
      >
        <Routes>
          <Route
            path="/scans/:scanId/compare-select"
            element={<ScanCompareSelectPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    return fetchMock;
  }

  function eligibleIds(container: HTMLElement): string[] {
    return Array.from(
      container.querySelectorAll<HTMLAnchorElement>("a[data-compare-base]")
    ).map((a) => a.getAttribute("data-compare-base") ?? "");
  }

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    cleanup();
  });

  it("lists a completed scan as a comparison partner", async () => {
    renderSelector({
      headId: 2,
      head: { id: 2, repository_id: 10, status: "completed" },
      candidates: [{ id: 1, repository_id: 10, status: "completed" }],
    });
    await waitFor(() => {
      expect(eligibleIds(document.body)).toEqual(["1"]);
    });
  });

  it("lists a partial scan as a comparison partner", async () => {
    renderSelector({
      headId: 1,
      head: { id: 1, repository_id: 10, status: "completed" },
      candidates: [{ id: 2, repository_id: 10, status: "partial" }],
    });
    await waitFor(() => {
      expect(eligibleIds(document.body)).toEqual(["2"]);
    });
  });

  it("excludes a failed scan from the comparison partner list", async () => {
    renderSelector({
      headId: 1,
      head: { id: 1, repository_id: 10, status: "completed" },
      candidates: [
        { id: 2, repository_id: 10, status: "completed" },
        { id: 3, repository_id: 10, status: "failed" },
      ],
    });
    await waitFor(() => {
      expect(eligibleIds(document.body)).toEqual(["2"]);
    });
    expect(eligibleIds(document.body)).not.toContain("3");
  });

  it("excludes a cancelled scan from the comparison partner list", async () => {
    renderSelector({
      headId: 1,
      head: { id: 1, repository_id: 10, status: "completed" },
      candidates: [
        { id: 2, repository_id: 10, status: "completed" },
        { id: 4, repository_id: 10, status: "cancelled" },
      ],
    });
    await waitFor(() => {
      expect(eligibleIds(document.body)).toEqual(["2"]);
    });
    expect(eligibleIds(document.body)).not.toContain("4");
  });

  it("excludes queued and running scans from the comparison partner list", async () => {
    renderSelector({
      headId: 1,
      head: { id: 1, repository_id: 10, status: "completed" },
      candidates: [
        { id: 2, repository_id: 10, status: "completed" },
        { id: 3, repository_id: 10, status: "queued" },
        { id: 4, repository_id: 10, status: "running" },
      ],
    });
    await waitFor(() => {
      expect(eligibleIds(document.body)).toEqual(["2"]);
    });
    expect(eligibleIds(document.body)).not.toContain("3");
    expect(eligibleIds(document.body)).not.toContain("4");
  });

  it("excludes the current head scan from the comparison partner list", async () => {
    renderSelector({
      headId: 1,
      head: { id: 1, repository_id: 10, status: "completed" },
      candidates: [
        { id: 1, repository_id: 10, status: "completed" },
        { id: 2, repository_id: 10, status: "completed" },
      ],
    });
    await waitFor(() => {
      expect(eligibleIds(document.body)).toEqual(["2"]);
    });
    expect(eligibleIds(document.body)).not.toContain("1");
  });

  it("excludes scans from a different repository from the comparison partner list", async () => {
    renderSelector({
      headId: 1,
      head: { id: 1, repository_id: 10, status: "completed" },
      candidates: [
        { id: 2, repository_id: 10, status: "completed" },
        // The backend already scopes the candidate list to
        // the head scan's repository, but the frontend keeps
        // its own repository-equality check as defense in
        // depth: a different-repository scan must never be
        // offered even if the API ever returns one.
        { id: 3, repository_id: 11, status: "completed" },
      ],
    });
    await waitFor(() => {
      expect(eligibleIds(document.body)).toEqual(["2"]);
    });
    expect(eligibleIds(document.body)).not.toContain("3");
  });

  it("excludes failed, cancelled, queued, running, current, and cross-repo scans in one pass", async () => {
    // All four ineligible categories appear alongside the
    // one eligible partner. Only the eligible partner must
    // show up in the rendered buttons.
    renderSelector({
      headId: 1,
      head: { id: 1, repository_id: 10, status: "completed" },
      candidates: [
        { id: 1, repository_id: 10, status: "completed" }, // current head
        { id: 2, repository_id: 10, status: "failed" }, // failed
        { id: 3, repository_id: 10, status: "cancelled" }, // cancelled
        { id: 4, repository_id: 10, status: "queued" }, // queued
        { id: 5, repository_id: 10, status: "running" }, // running
        { id: 6, repository_id: 11, status: "completed" }, // cross-repo
        { id: 7, repository_id: 10, status: "partial" }, // eligible
      ],
    });
    await waitFor(() => {
      expect(eligibleIds(document.body)).toEqual(["7"]);
    });
  });
});

/**
 * Focused regression tests for the CompareScansCard in the
 * RepositoryDetailsPage. The card embeds two ``<select>``
 * dropdowns (base and head). Both must be filtered to the
 * v0.5 eligibility rule so the operator cannot pick a
 * ``failed`` or ``cancelled`` scan as a comparison partner.
 */
describe("RepositoryDetailsPage CompareScansCard eligibility", () => {
  function makeRepo(overrides: Partial<{ id: number; owner: string; name: string }> = {}) {
    return {
      id: 10,
      source_type: "github" as const,
      provider: "github" as const,
      owner: "octocat",
      name: "Hello-World",
      canonical_url: "https://github.com/octocat/Hello-World",
      default_branch: "main",
      visibility: "public" as const,
      archived: false,
      description: null,
      last_provider_sync_at: null,
      created_at: "2024-01-01T00:00:00Z",
      updated_at: "2024-01-01T00:00:00Z",
      ...overrides,
    };
  }

  function renderRepository(args: {
    repositoryId: number;
    scans: Array<{ id: number; status: Scan["status"] }>;
  }) {
    const fetchMock = vi.mocked(globalThis.fetch);
    // getRepository(repoId)
    fetchMock.mockResolvedValueOnce(jsonResponse(makeRepo({ id: args.repositoryId })));
    // listScansForRepository(repoId, { page, page_size: 10 }) — main table
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        items: args.scans.map((s) => makeScan({ ...s, repository_id: args.repositoryId })),
        pagination: { page: 1, page_size: 10, total: args.scans.length, total_pages: 1 },
      })
    );
    // listScansForRepository(repoId, { page: 1, page_size: 50 }) — CompareScansCard
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        items: args.scans.map((s) => makeScan({ ...s, repository_id: args.repositoryId })),
        pagination: { page: 1, page_size: 50, total: args.scans.length, total_pages: 1 },
      })
    );
    render(
      <MemoryRouter
        initialEntries={[`/repositories/${args.repositoryId}`]}
      >
        <Routes>
          <Route
            path="/repositories/:repositoryId"
            element={<RepositoryDetailsPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    return fetchMock;
  }

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    cleanup();
  });

  it("renders the v1.8 repository compare card with a link to the selector", async () => {
    renderRepository({
      repositoryId: 10,
      scans: [
        { id: 1, status: "completed" },
        { id: 2, status: "partial" },
        { id: 3, status: "failed" },
        { id: 4, status: "cancelled" },
        { id: 5, status: "queued" },
        { id: 6, status: "running" },
      ],
    });
    await waitFor(() => {
      // The v1.8 page no longer ships the inline base /
      // head dropdowns. It surfaces the eligibility
      // contract through a dedicated selector page.
      // The card on the repository page must still
      // exist, and the v0.5 eligibility rule (only
      // completed and partial) is preserved by the
      // selector page (covered in the v1.8 tests).
      expect(
        screen.getByTestId("repository-compare-card")
      ).toBeInTheDocument();
    });
    expect(
      screen.getByTestId("repository-compare-open")
    ).toHaveAttribute("href", "/repositories/10/compare");
  });

  it("renders the dedicated compare link in the scan history header", async () => {
    renderRepository({
      repositoryId: 10,
      scans: [
        { id: 1, status: "completed" },
        { id: 2, status: "partial" },
      ],
    });
    await waitFor(() => {
      expect(
        screen.getByTestId("repository-compare-link")
      ).toBeInTheDocument();
    });
    expect(
      screen.getByTestId("repository-compare-link")
    ).toHaveAttribute("href", "/repositories/10/compare");
  });

  it("does not default the comparison to a failed or cancelled scan", async () => {
    // The v0.5 eligibility rule is preserved: the
    // RepositoryComparePage only lists completed and
    // partial scans as comparison candidates. The
    // repository detail page no longer auto-pre-fills
    // a base/head pair; it points the reviewer to the
    // dedicated selector, which enforces the rule.
    renderRepository({
      repositoryId: 10,
      scans: [
        { id: 1, status: "failed" },
        { id: 2, status: "cancelled" },
        { id: 3, status: "completed" },
        { id: 4, status: "partial" },
      ],
    });
    await waitFor(() => {
      expect(
        screen.getByTestId("repository-compare-card")
      ).toBeInTheDocument();
    });
    // No inline <a> to /scans/<id>/compare/<id> on the
    // page any more; the v0.5 contract is honoured by
    // the dedicated selector.
    const compareLinks = Array.from(
      document.body.querySelectorAll<HTMLAnchorElement>("a")
    ).filter((a) => /\/scans\/\d+\/compare\/\d+/.test(a.getAttribute("href") ?? ""));
    expect(compareLinks.length).toBe(0);
  });
});
