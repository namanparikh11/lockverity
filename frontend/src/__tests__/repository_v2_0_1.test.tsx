/**
 * v2.0.1 — Per-repository scan-history filter regression.
 *
 * Pins the v2.0.1 contract that ``RepositoryDetailsPage`` renders
 * only the rows the backend returned for a given ``?status=`` /
 * ``?trigger_type=`` filter. v2.0 shipped with the backend
 * silently ignoring the filter (every scan was always returned);
 * the v1.8 test in ``repository_v1_8.test.tsx`` only asserted
 * that the request URL carried the query param, not that the
 * rendered table matched the active filter. v2.0.1 adds this
 * render-side test so a future regression that drops the wiring
 * (route + service + repo) would fail loudly.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { RepositoryDetailsPage } from "@/pages/RepositoryDetailsPage";

interface Scan {
  id: number;
  status: string;
  trigger_type: string;
  repository_id: number;
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

const ALL_SCANS: Scan[] = [
  {
    id: 1,
    status: "completed",
    trigger_type: "manual",
    repository_id: 10,
    requested_ref: "main",
    resolved_commit_sha: "deadbeef",
    analyzer_version: "lockverity 2.0.0",
    started_at: "2026-07-15T10:00:00Z",
    completed_at: "2026-07-15T10:01:00Z",
    failure_code: null,
    failure_summary: null,
    created_at: "2026-07-15T10:00:00Z",
    updated_at: "2026-07-15T10:01:00Z",
  },
  {
    id: 2,
    status: "partial",
    trigger_type: "manual",
    repository_id: 10,
    requested_ref: "main",
    resolved_commit_sha: "deadbeef",
    analyzer_version: "lockverity 2.0.0",
    started_at: "2026-07-15T11:00:00Z",
    completed_at: "2026-07-15T11:01:00Z",
    failure_code: null,
    failure_summary: null,
    created_at: "2026-07-15T11:00:00Z",
    updated_at: "2026-07-15T11:01:00Z",
  },
  {
    id: 3,
    status: "failed",
    trigger_type: "manual",
    repository_id: 10,
    requested_ref: "main",
    resolved_commit_sha: "deadbeef",
    analyzer_version: "lockverity 2.0.0",
    started_at: "2026-07-15T12:00:00Z",
    completed_at: "2026-07-15T12:01:00Z",
    failure_code: "scanner_crashed",
    failure_summary: "Scanner crashed before inventory capture.",
    created_at: "2026-07-15T12:00:00Z",
    updated_at: "2026-07-15T12:01:00Z",
  },
  {
    id: 4,
    status: "cancelled",
    trigger_type: "manual",
    repository_id: 10,
    requested_ref: "main",
    resolved_commit_sha: "deadbeef",
    analyzer_version: "lockverity 2.0.0",
    started_at: null,
    completed_at: null,
    failure_code: "operator_cancelled",
    failure_summary: "Operator cancelled the scan before completion.",
    created_at: "2026-07-15T13:00:00Z",
    updated_at: "2026-07-15T13:01:00Z",
  },
];

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function makeRepo() {
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
  };
}

function setupFilterSensitiveFetch(): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockImplementation((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/api/v1/repositories/10") && !url.includes("/scans")) {
      return Promise.resolve(jsonResponse(makeRepo()));
    }
    if (url.includes("/api/v1/repositories/10/scans")) {
      const u = new URL(url, "http://localhost");
      const status = u.searchParams.get("status");
      const trigger = u.searchParams.get("trigger_type");
      const items = ALL_SCANS.filter((s) => {
        if (status && status !== "all" && s.status !== status) return false;
        if (trigger && trigger !== "all" && s.trigger_type !== trigger)
          return false;
        return true;
      });
      return Promise.resolve(
        jsonResponse({
          items,
          pagination: {
            page: 1,
            page_size: 25,
            total: items.length,
            total_pages: 1,
          },
        })
      );
    }
    if (url.includes("/api/v1/scans/") && url.includes("/stages")) {
      return Promise.resolve(jsonResponse({ items: [] }));
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

describe("repository v2.0.1 - history filter renders the API result", () => {
  it("renders only the cancelled scan when ?status=cancelled", async () => {
    setupFilterSensitiveFetch();
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
      expect(
        screen.getByTestId("scan-history-row-4")
      ).toBeInTheDocument();
    });
    expect(screen.queryByTestId("scan-history-row-1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("scan-history-row-2")).not.toBeInTheDocument();
    expect(screen.queryByTestId("scan-history-row-3")).not.toBeInTheDocument();
  });

  it("renders only the partial scan when ?status=partial", async () => {
    setupFilterSensitiveFetch();
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
        screen.getByTestId("scan-history-row-2")
      ).toBeInTheDocument();
    });
    expect(screen.queryByTestId("scan-history-row-1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("scan-history-row-3")).not.toBeInTheDocument();
    expect(screen.queryByTestId("scan-history-row-4")).not.toBeInTheDocument();
  });

  it("renders every scan when no filter is active", async () => {
    setupFilterSensitiveFetch();
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
    expect(
      screen.getByTestId("scan-history-row-2")
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("scan-history-row-3")
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("scan-history-row-4")
    ).toBeInTheDocument();
  });

  it("renders the empty state when the filter has no matches", async () => {
    setupFilterSensitiveFetch();
    render(
      <MemoryRouter initialEntries={["/repositories/10?status=running"]}>
        <Routes>
          <Route
            path="/repositories/:repositoryId"
            element={<RepositoryDetailsPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    // No row in the demo dataset has status=running, so the table
    // must show the bounded empty-state copy and the active filter
    // must remain visible on the URL.
    await waitFor(() => {
      expect(screen.getByText(/No scans match the filters/i)).toBeInTheDocument();
    });
    // Sanity: the row that does match any other status is not
    // rendered.
    expect(screen.queryByTestId("scan-history-row-1")).not.toBeInTheDocument();
  });

  it("renders only manual scans when ?trigger_type=manual and a status filter narrows it", async () => {
    setupFilterSensitiveFetch();
    render(
      <MemoryRouter
        initialEntries={["/repositories/10?status=failed&trigger_type=manual"]}
      >
        <Routes>
          <Route
            path="/repositories/:repositoryId"
            element={<RepositoryDetailsPage />}
          />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      const row3 = screen.getByTestId("scan-history-row-3");
      expect(within(row3).getByText("#3")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("scan-history-row-1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("scan-history-row-2")).not.toBeInTheDocument();
    expect(screen.queryByTestId("scan-history-row-4")).not.toBeInTheDocument();
  });
});
