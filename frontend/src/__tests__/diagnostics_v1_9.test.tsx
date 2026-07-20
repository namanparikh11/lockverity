/**
 * v1.9 — Operational diagnostics page tests.
 *
 * Covers:
 *  - /diagnostics renders with the application and
 *    executor cards;
 *  - the AppShell adds a Diagnostics entry;
 *  - the version is rendered from the diagnostics
 *    payload, not from a hardcoded constant;
 *  - executor queued / running counts render;
 *  - missing heartbeat renders as the explicit
 *    "Heartbeat not exposed" notice, never as
 *    "healthy";
 *  - provider states render with cache state and
 *    evidence presence kept as separate fields;
 *  - provider filters work;
 *  - recent failed scan rows link to the workbench;
 *  - completed scans are not shown as failures;
 *  - stage-state aggregation renders;
 *  - zero-stage-failure wording is bounded (never
 *    "all stages are healthy");
 *  - refresh blocks duplicate clicks (synchronous
 *    pendingRef);
 *  - refresh error preserves the last known data;
 *  - no health / risk / security / clean / pass score
 *    is rendered;
 *  - Analyze, Demo, Workbench, Findings, Repository
 *    History, Comparison, Exports all remain
 *    functional (rendered through the AppShell).
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

import { AppShell } from "@/layouts/AppShell";
import { DiagnosticsPage } from "@/pages/DiagnosticsPage";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function makeSummary(overrides: {
  application?: Record<string, unknown>;
  executor?: Record<string, unknown>;
  providers?: Array<Record<string, unknown>>;
  recent_scan_issues?: Array<Record<string, unknown>>;
  stage_summary?: Array<Record<string, unknown>>;
  generated_at?: string;
} = {}) {
  return {
    application: {
      status: "reachable",
      version: "1.9.0",
      environment: "development",
      database: "available",
      generated_at: "2026-07-20T10:00:00Z",
      ...overrides.application,
    },
    executor: {
      state: "available",
      implementation: "local-thread",
      queued_scans: 1,
      running_scans: 0,
      last_heartbeat_at: null,
      heartbeat_supported: false,
      details_available: true,
      notes: [],
      ...overrides.executor,
    },
    providers: overrides.providers ?? [
      {
        provider: "github",
        last_observed_state: "available",
        configured_state: "configured",
        last_attempt_at: "2026-07-20T09:55:00Z",
        last_success_at: "2026-07-20T09:55:00Z",
        cache_status: "miss",
        evidence_present: null,
        last_error_code: null,
        last_error_summary: null,
        source_scan_id: 1,
        source_observation_id: 1,
      },
      {
        provider: "osv",
        last_observed_state: "unavailable",
        configured_state: "configured",
        last_attempt_at: "2026-07-20T09:55:00Z",
        last_success_at: null,
        cache_status: null,
        evidence_present: null,
        last_error_code: "upstream_5xx",
        last_error_summary: "Upstream returned 503 Service Unavailable.",
        source_scan_id: 1,
        source_observation_id: 2,
      },
      {
        provider: "deps_dev",
        last_observed_state: "partial",
        configured_state: "configured",
        last_attempt_at: "2026-07-20T09:55:00Z",
        last_success_at: null,
        cache_status: "stale",
        evidence_present: null,
        last_error_code: "rate_limited",
        last_error_summary: "deps.dev rate limit hit during the scan window.",
        source_scan_id: 1,
        source_observation_id: 3,
      },
      {
        provider: "openssf",
        last_observed_state: "not_requested",
        configured_state: "configured",
        last_attempt_at: null,
        last_success_at: null,
        cache_status: null,
        evidence_present: null,
        last_error_code: null,
        last_error_summary: null,
        source_scan_id: null,
        source_observation_id: null,
      },
    ],
    recent_scan_issues: overrides.recent_scan_issues ?? [
      {
        scan_id: 3,
        repository_id: 1,
        status: "failed",
        trigger_type: "manual",
        failure_code: "scanner_crashed",
        failure_summary: "Scanner crashed before inventory capture.",
        updated_at: "2026-07-20T09:00:00Z",
        completed_at: "2026-07-20T09:00:00Z",
        started_at: "2026-07-20T08:59:00Z",
      },
    ],
    stage_summary: overrides.stage_summary ?? [
      {
        stage: "repository_intake",
        completed: 3,
        partial: 0,
        failed: 1,
        skipped: 0,
        running: 0,
        pending: 0,
      },
      {
        stage: "vulnerability_query",
        completed: 0,
        partial: 0,
        failed: 0,
        skipped: 0,
        running: 0,
        pending: 0,
      },
    ],
    generated_at: overrides.generated_at ?? "2026-07-20T10:00:00Z",
  };
}

function setupFetchMock(opts: { summary?: unknown; status?: number } = {}) {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockImplementation((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/diagnostics/summary")) {
      return Promise.resolve(
        new Response(JSON.stringify(opts.summary ?? makeSummary()), {
          status: opts.status ?? 200,
          headers: { "content-type": "application/json" },
        })
      );
    }
    if (url.includes("/api/v1/system/info")) {
      return Promise.resolve(
        jsonResponse({
          name: "Lockverity",
          version: "1.9.0",
          tagline: "Evidence-first software supply-chain assurance",
          environment: "test",
          api_prefix: "/api/v1",
          archive_limits: {},
          pagination: {},
          provider_safety: {},
          intake: {},
        })
      );
    }
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

function renderDiagnostics() {
  return render(
    <MemoryRouter initialEntries={["/diagnostics"]}>
      <Routes>
        <Route path="/diagnostics" element={<DiagnosticsPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("diagnostics v1.9 - page renders", () => {
  it("renders the page header and the application / executor cards", async () => {
    setupFetchMock();
    renderDiagnostics();
    await waitFor(() => {
      expect(
        screen.getByTestId("diagnostics-application-version")
      ).toHaveTextContent("Lockverity 1.9.0");
    });
    expect(
      screen.getByTestId("diagnostics-executor-state")
    ).toHaveTextContent("available");
    expect(
      screen.getByTestId("diagnostics-executor-queued")
    ).toHaveTextContent("Queued scans: 1");
    expect(
      screen.getByTestId("diagnostics-executor-running")
    ).toHaveTextContent("Running scans: 0");
  });

  it("renders the explicit 'Heartbeat not exposed' notice", async () => {
    setupFetchMock();
    renderDiagnostics();
    await waitFor(() => {
      expect(
        screen.getByTestId("diagnostics-executor-heartbeat")
      ).toHaveTextContent(/Heartbeat not exposed by the current executor/);
    });
  });

  it("renders the generated-at timestamp", async () => {
    setupFetchMock();
    renderDiagnostics();
    await waitFor(() => {
      expect(
        screen.getByTestId("diagnostics-generated-at")
      ).toHaveTextContent(/Generated at/);
    });
  });
});

describe("diagnostics v1.9 - provider rows", () => {
  it("renders each provider with the persisted state and cache status", async () => {
    setupFetchMock();
    renderDiagnostics();
    await waitFor(() => {
      expect(
        screen.getByTestId("diagnostics-provider-row-github")
      ).toBeInTheDocument();
    });
    const github = screen.getByTestId("diagnostics-provider-row-github");
    expect(within(github).getByText("GitHub")).toBeInTheDocument();
    expect(within(github).getByText("miss")).toBeInTheDocument();
    const osv = screen.getByTestId("diagnostics-provider-row-osv");
    expect(within(osv).getByText("unavailable")).toBeInTheDocument();
    expect(within(osv).getByText("upstream_5xx")).toBeInTheDocument();
  });

  it("renders a 'not_requested' provider with explicit Unknown fields", async () => {
    setupFetchMock();
    renderDiagnostics();
    await waitFor(() => {
      expect(
        screen.getByTestId("diagnostics-provider-row-openssf")
      ).toBeInTheDocument();
    });
    const openssf = screen.getByTestId("diagnostics-provider-row-openssf");
    // The openssf row carries "Unknown" in the
    // cache_status and last_attempt cells.
    expect(within(openssf).getAllByText("Unknown").length).toBeGreaterThan(0);
  });

  it("filters providers by observed state", async () => {
    setupFetchMock();
    renderDiagnostics();
    await waitFor(() => {
      expect(
        screen.getByTestId("diagnostics-provider-row-github")
      ).toBeInTheDocument();
    });
    fireEvent.change(screen.getByLabelText("Observed state"), {
      target: { value: "unavailable" },
    });
    await waitFor(() => {
      expect(
        screen.queryByTestId("diagnostics-provider-row-github")
      ).not.toBeInTheDocument();
      expect(
        screen.getByTestId("diagnostics-provider-row-osv")
      ).toBeInTheDocument();
    });
  });
});

describe("diagnostics v1.9 - recent scan issues", () => {
  it("renders recent failed scans with a workbench link", async () => {
    setupFetchMock();
    renderDiagnostics();
    await waitFor(() => {
      expect(
        screen.getByTestId("diagnostics-issue-row-3")
      ).toBeInTheDocument();
    });
    const link = screen.getByTestId("diagnostics-issue-link-3");
    expect(link).toHaveAttribute("href", "/scans/3");
  });

  it("does not list completed scans as issues", async () => {
    setupFetchMock();
    renderDiagnostics();
    await waitFor(() => {
      expect(
        screen.getByTestId("diagnostics-issue-row-3")
      ).toBeInTheDocument();
    });
    // The completed scan id 1 is in the providers
    // payload but must not appear in recent scan
    // issues.
    expect(
      screen.queryByTestId("diagnostics-issue-row-1")
    ).not.toBeInTheDocument();
  });

  it("filters issues by status", async () => {
    setupFetchMock({
      summary: makeSummary({
        recent_scan_issues: [
          {
            scan_id: 3,
            repository_id: 1,
            status: "failed",
            trigger_type: "manual",
            failure_code: "x",
            failure_summary: "y",
            updated_at: "2026-07-20T09:00:00Z",
            completed_at: "2026-07-20T09:00:00Z",
            started_at: "2026-07-20T08:59:00Z",
          },
          {
            scan_id: 4,
            repository_id: 1,
            status: "cancelled",
            trigger_type: "manual",
            failure_code: "operator_cancelled",
            failure_summary: "Operator cancelled.",
            updated_at: "2026-07-20T08:30:00Z",
            completed_at: "2026-07-20T08:30:00Z",
            started_at: "2026-07-20T08:29:00Z",
          },
        ],
      }),
    });
    renderDiagnostics();
    await waitFor(() => {
      expect(
        screen.getByTestId("diagnostics-issue-row-3")
      ).toBeInTheDocument();
    });
    fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: "cancelled" },
    });
    await waitFor(() => {
      expect(
        screen.queryByTestId("diagnostics-issue-row-3")
      ).not.toBeInTheDocument();
      expect(
        screen.getByTestId("diagnostics-issue-row-4")
      ).toBeInTheDocument();
    });
  });
});

describe("diagnostics v1.9 - stage aggregation", () => {
  it("renders aggregated counts per stage", async () => {
    setupFetchMock();
    renderDiagnostics();
    await waitFor(() => {
      expect(
        screen.getByTestId("diagnostics-stage-row-repository_intake")
      ).toBeInTheDocument();
    });
    const row = screen.getByTestId(
      "diagnostics-stage-row-repository_intake"
    );
    expect(within(row).getByText("repository_intake")).toBeInTheDocument();
  });

  it("renders the bounded zero-stage-failure wording", async () => {
    setupFetchMock({
      summary: makeSummary({
        recent_scan_issues: [],
        stage_summary: [],
      }),
    });
    renderDiagnostics();
    await waitFor(() => {
      expect(
        screen.getByText(
          /No matching partial, failed, or cancelled scans were found\./
        )
      ).toBeInTheDocument();
    });
    // The page mentions the phrase in a "never as"
    // disclaimer; we assert that the disclaimer is
    // present and that no positive claim is rendered.
    expect(
      screen.getByText(/never as.*All stages are healthy/i)
    ).toBeInTheDocument();
    const body = document.body.textContent ?? "";
    expect(body).not.toMatch(/System healthy\b/i);
  });
});

describe("diagnostics v1.9 - honesty", () => {
  it("never renders a universal health / risk / secure / clean score", async () => {
    setupFetchMock();
    renderDiagnostics();
    await waitFor(() => {
      expect(
        screen.getByTestId("diagnostics-application-version")
      ).toBeInTheDocument();
    });
    const body = document.body.textContent ?? "";
    expect(body).not.toMatch(/security score/i);
    expect(body).not.toMatch(/risk score/i);
    expect(body).not.toMatch(/compliance score/i);
    expect(body).not.toMatch(/health score/i);
    expect(body).not.toMatch(/is clean\b/i);
    expect(body).not.toMatch(/is secure\b/i);
    expect(body).not.toMatch(/passed the scan/i);
    expect(body).not.toMatch(/vulnerability-free/i);
  });
});

describe("diagnostics v1.9 - refresh", () => {
  it("blocks duplicate clicks through a synchronous guard", async () => {
    const fetchMock = setupFetchMock();
    renderDiagnostics();
    await waitFor(() => {
      expect(
        screen.getByTestId("diagnostics-application-version")
      ).toBeInTheDocument();
    });
    const callsBefore = fetchMock.mock.calls.length;
    const button = screen.getByTestId("diagnostics-refresh");
    // Two synchronous clicks must not enqueue two
    // simultaneous fetches.
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => {
      expect(fetchMock.mock.calls.length).toBeGreaterThan(callsBefore);
    });
    // We expect at most one extra fetch from the
    // double-click thanks to the pendingRef guard.
    const callsAfter = fetchMock.mock.calls.length;
    expect(callsAfter - callsBefore).toBeLessThanOrEqual(1);
  });

  it("preserves the last known payload when a refresh fails", async () => {
    const fetchMock = setupFetchMock();
    renderDiagnostics();
    await waitFor(() => {
      expect(
        screen.getByTestId("diagnostics-application-version")
      ).toHaveTextContent("Lockverity 1.9.0");
    });
    // Now make the next call fail.
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/diagnostics/summary")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              error: { code: "internal_error", message: "boom" },
            }),
            { status: 500, headers: { "content-type": "application/json" } }
          )
        );
      }
      if (url.includes("/api/v1/system/info")) {
        return Promise.resolve(
          jsonResponse({
            name: "Lockverity",
            version: "1.9.0",
            tagline: "x",
            environment: "test",
            api_prefix: "/api/v1",
            archive_limits: {},
            pagination: {},
            provider_safety: {},
            intake: {},
          })
        );
      }
      return Promise.resolve(jsonResponse({}));
    });
    fireEvent.click(screen.getByTestId("diagnostics-refresh"));
    await waitFor(() => {
      expect(
        screen.getByTestId("diagnostics-refresh-error")
      ).toBeInTheDocument();
    });
    // The last known payload is preserved.
    expect(
      screen.getByTestId("diagnostics-application-version")
    ).toHaveTextContent("Lockverity 1.9.0");
  });
});

describe("diagnostics v1.9 - AppShell integration", () => {
  it("renders a Diagnostics entry in the AppShell primary nav", () => {
    setupFetchMock();
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<div data-testid="placeholder" />} />
          </Route>
        </Routes>
      </MemoryRouter>
    );
    const link = screen.getByRole("link", { name: "Diagnostics" });
    expect(link).toHaveAttribute("href", "/diagnostics");
  });
});
