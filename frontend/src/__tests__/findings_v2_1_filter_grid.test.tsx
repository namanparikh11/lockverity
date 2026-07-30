/**
 * v2.1 findings filter grid layout test.
 *
 * Verifies that the Sort control sits inside the same coherent
 * responsive filter grid as the other data filters (Category,
 * Severity, Confidence, Status) and is visually aligned with the
 * Category control on the same row at the standard lg breakpoint.
 *
 * The grid is implemented by the ``FilterBar`` component with
 * ``layout="card"`` and ``stacked`` ``SelectFilter`` children.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";

import { FindingsPage } from "@/pages/FindingsPage";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function setupFetchMock() {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  const findingsBody = {
    items: [
      {
        id: 1,
        scan_run_id: 1,
        repository_id: 1,
        rule_id: "R001",
        category: "vulnerability",
        severity: "high",
        confidence: "confirmed",
        title: "title 1",
        summary: "summary 1",
        remediation: null,
        evidence_json: "{}",
        location_path: "package.json",
        location_start_line: 12,
        location_end_line: 12,
        stable_key: "0".repeat(64),
        status: "open",
        created_at: "2026-07-15T10:00:00Z",
        updated_at: "2026-07-15T10:01:00Z",
      },
    ],
    pagination: { page: 1, page_size: 25, total: 1, total_pages: 1 },
  };
  fetchMock.mockImplementation((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/api/v1/scans/1/findings")) {
      return Promise.resolve(jsonResponse(findingsBody));
    }
    if (url.includes("/api/v1/scans/1") && !url.includes("/findings") && !url.includes("/stages")) {
      return Promise.resolve(
        jsonResponse({
          id: 1,
          repository_id: 1,
          status: "completed",
          trigger_type: "manual",
          requested_ref: null,
          resolved_commit_sha: null,
          analyzer_version: null,
          started_at: "2026-07-15T10:00:00Z",
          completed_at: "2026-07-15T10:01:00Z",
          failure_code: null,
          failure_summary: null,
          created_at: "2026-07-15T10:00:00Z",
          updated_at: "2026-07-15T10:01:00Z",
        })
      );
    }
    if (url.includes("/api/v1/repositories/1")) {
      return Promise.resolve(
        jsonResponse({
          id: 1,
          source_type: "github",
          provider: "github",
          owner: "octocat",
          name: "Hello-World",
          canonical_url: "https://github.com/octocat/Hello-World",
          default_branch: "main",
          description: null,
          visibility: "public",
          archived: false,
          last_provider_sync_at: null,
          created_at: "2026-07-15T10:00:00Z",
          updated_at: "2026-07-15T10:01:00Z",
        })
      );
    }
    if (url.includes("/api/v1/scans/1/stages")) {
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

describe("findings v2.1 - filter grid layout", () => {
  it("renders the FilterBar in card layout with all data filters and Sort in the same grid", async () => {
    setupFetchMock();
    render(
      <MemoryRouter initialEntries={["/scans/1/findings"]}>
        <Routes>
          <Route path="/scans/:scanId/findings" element={<FindingsPage />} />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByTestId("findings-context-header")).toBeInTheDocument();
    });
    // The card layout is the v2.1 layout: a single
    // card with a title, a result count, and a single
    // responsive grid of stacked filters.
    const card = screen.getByTestId("filterbar-card");
    expect(card).toBeInTheDocument();
    expect(within(card).getByTestId("filterbar-title")).toHaveTextContent(
      /filters/i
    );
    // All five stacked filters live inside the same
    // grid; Category and Sort share the first row at
    // xl breakpoint.
    const grid = within(card).getByTestId("filterbar-grid");
    expect(within(grid).getByTestId("select-filter-category-filter")).toBeInTheDocument();
    expect(within(grid).getByTestId("select-filter-sort-filter")).toBeInTheDocument();
    expect(within(grid).getByTestId("select-filter-severity-filter")).toBeInTheDocument();
    expect(within(grid).getByTestId("select-filter-confidence-filter")).toBeInTheDocument();
    expect(within(grid).getByTestId("select-filter-status-filter")).toBeInTheDocument();
  });

  it("preserves sort as a labelled form control that submits to the API", async () => {
    const fetchMock = setupFetchMock();
    render(
      <MemoryRouter initialEntries={["/scans/1/findings"]}>
        <Routes>
          <Route path="/scans/:scanId/findings" element={<FindingsPage />} />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByTestId("filterbar-card")).toBeInTheDocument();
    });
    // The stacked layout still renders a "Sort" label
    // associated with the select, so the URL state and
    // the API call keep working.
    const sortLabel = screen.getByText("Sort");
    expect(sortLabel).toBeInTheDocument();
    expect(sortLabel.tagName).toBe("LABEL");
    const sortId = sortLabel.getAttribute("for");
    expect(sortId).toBeTruthy();
    const sortSelect = document.getElementById(sortId!) as HTMLSelectElement | null;
    expect(sortSelect).toBeTruthy();
    sortSelect!.value = "severity";
    sortSelect!.dispatchEvent(new Event("change", { bubbles: true }));
    await waitFor(() => {
      const call = [...fetchMock.mock.calls]
        .reverse()
        .find((c) => String(c[0]).includes("/findings?"));
      expect(call).toBeTruthy();
      expect(String(call![0])).toMatch(/sort=severity/);
    });
  });
});
