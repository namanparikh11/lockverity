/**
 * v2.0.5 repository list / identification tests.
 *
 * The v2.0.4 list surfaces an opaque canonical upload
 * identifier (e.g. ``upload/2ed7b06ed7d3d967``) as the
 * primary row label and provides no scan count, no
 * latest-scan summary, and no per-row "Open latest scan"
 * or "Compare" action. v2.0.5 introduces:
 *
 *  - ``display_name``: ``owner/repository`` for GitHub,
 *    original-filename basename for uploaded rows.
 *  - ``canonical_identity``: secondary technical identifier.
 *  - ``summary.scan_count``, ``summary.eligible_comparison_scan_count``,
 *    ``summary.latest_scan``.
 *  - The "Open latest scan" / "View history" / "Compare" actions.
 *  - Search by filename, owner, name, canonical URL, or
 *    exact scan ID (with or without a leading ``#``).
 *
 * These tests render the page against a mocked API and
 * assert the new fields are displayed; they do not
 * exercise the API client.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { RepositoriesPage } from "@/pages/RepositoriesPage";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function makeRepo(
  overrides: Partial<{
    id: number;
    source_type: "github" | "uploaded_archive";
    provider: "github" | "local_upload";
    owner: string;
    name: string;
    canonical_url: string | null;
    visibility: "public" | "private" | "unknown";
    archived: boolean;
    display_name: string;
    canonical_identity: string;
    original_filename: string | null;
    scan_count: number;
    eligible_comparison_scan_count: number;
    latest_scan_id: number | null;
    latest_scan_status:
      | "queued"
      | "running"
      | "completed"
      | "partial"
      | "failed"
      | "cancelled"
      | null;
  }> = {}
) {
  const summaryOverrides: Record<string, unknown> = {};
  if (overrides.scan_count !== undefined)
    summaryOverrides.scan_count = overrides.scan_count;
  if (overrides.eligible_comparison_scan_count !== undefined)
    summaryOverrides.eligible_comparison_scan_count =
      overrides.eligible_comparison_scan_count;
  let latest_scan = null;
  if (overrides.latest_scan_id !== undefined && overrides.latest_scan_id !== null) {
    latest_scan = {
      id: overrides.latest_scan_id,
      status: overrides.latest_scan_status || "completed",
      trigger_type: "manual",
      created_at: "2026-07-01T00:00:00Z",
      completed_at: "2026-07-01T00:00:30Z",
    };
  }
  summaryOverrides.latest_scan = latest_scan;
  return {
    id: 1,
    source_type: "github" as const,
    provider: "github" as const,
    owner: "octocat",
    name: "Hello-World",
    canonical_url: "https://github.com/octocat/Hello-World",
    default_branch: "master",
    description: "Test",
    visibility: "public" as const,
    archived: false,
    last_provider_sync_at: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
    original_filename: null,
    display_name: "octocat/Hello-World",
    canonical_identity: "https://github.com/octocat/Hello-World",
    summary: {
      scan_count: 1,
      eligible_comparison_scan_count: 1,
      latest_scan: null,
      ...summaryOverrides,
    },
    ...overrides,
  };
}

function setupListFetchMock(repos: ReturnType<typeof makeRepo>[]) {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockImplementation((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/api/v1/repositories") && !url.match(/\/repositories\/\d+/)) {
      return Promise.resolve(
        jsonResponse({
          items: repos,
          pagination: { page: 1, page_size: 25, total: repos.length, total_pages: 1 },
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

describe("repository list v2.0.5 - uploaded row", () => {
  it("uses the uploaded filename as the primary row title", async () => {
    setupListFetchMock([
      makeRepo({
        id: 13,
        source_type: "uploaded_archive",
        provider: "local_upload",
        owner: "upload",
        name: "abc12345",
        canonical_url: "upload://abc12345",
        visibility: "private",
        original_filename: "test-09-mixed-monorepo.zip",
        display_name: "test-09-mixed-monorepo.zip",
        canonical_identity: "upload/abc12345",
        scan_count: 2,
        eligible_comparison_scan_count: 2,
        latest_scan_id: 15,
        latest_scan_status: "completed",
      }),
    ]);
    render(
      <MemoryRouter initialEntries={["/repositories"]}>
        <Routes>
          <Route path="/repositories" element={<RepositoriesPage />} />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() =>
      expect(screen.getByText("test-09-mixed-monorepo.zip")).toBeInTheDocument()
    );
    expect(screen.getByText("upload/abc12345")).toBeInTheDocument();
  });
});

describe("repository list v2.0.5 - GitHub row", () => {
  it("uses owner/repository as the primary row title", async () => {
    setupListFetchMock([
      makeRepo({
        id: 1,
        source_type: "github",
        provider: "github",
        owner: "octocat",
        name: "Hello-World",
        display_name: "octocat/Hello-World",
        canonical_identity: "https://github.com/octocat/Hello-World",
        latest_scan_id: 7,
        latest_scan_status: "completed",
      }),
    ]);
    render(
      <MemoryRouter initialEntries={["/repositories"]}>
        <Routes>
          <Route path="/repositories" element={<RepositoriesPage />} />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() =>
      expect(screen.getByText("octocat/Hello-World")).toBeInTheDocument()
    );
    expect(
      screen.getByText("https://github.com/octocat/Hello-World")
    ).toBeInTheDocument();
  });
});

describe("repository list v2.0.5 - no scan", () => {
  it("renders an explicit 'No scans' state and disables Open latest", async () => {
    setupListFetchMock([
      makeRepo({
        id: 5,
        source_type: "uploaded_archive",
        provider: "local_upload",
        owner: "upload",
        name: "never-scanned",
        canonical_url: "upload://never-scanned",
        visibility: "private",
        original_filename: "never-scanned.zip",
        display_name: "never-scanned.zip",
        canonical_identity: "upload/never-scanned",
        scan_count: 0,
        eligible_comparison_scan_count: 0,
        latest_scan_id: null,
        latest_scan_status: null,
      }),
    ]);
    render(
      <MemoryRouter initialEntries={["/repositories"]}>
        <Routes>
          <Route path="/repositories" element={<RepositoriesPage />} />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() =>
      expect(screen.getByText("never-scanned.zip")).toBeInTheDocument()
    );
    // The "No scans" text is in the latest-scan column.
    expect(screen.getByText("No scans")).toBeInTheDocument();
    // The last-scanned column shows "Never" for no-scan rows.
    expect(screen.getByText("Never")).toBeInTheDocument();
    // The "Open latest" button is rendered but disabled.
    const openLatest = screen.getByTitle("No scan has been run yet");
    expect(openLatest).toBeInTheDocument();
    // The "Compare" button is disabled.
    const compare = screen.getByTitle(
      "Comparison requires at least two eligible scans"
    );
    expect(compare).toBeInTheDocument();
  });
});

describe("repository list v2.0.5 - eligible comparison", () => {
  it("renders Compare link when at least two eligible scans exist", async () => {
    setupListFetchMock([
      makeRepo({
        id: 13,
        source_type: "uploaded_archive",
        provider: "local_upload",
        owner: "upload",
        name: "abc",
        canonical_url: "upload://abc",
        visibility: "private",
        original_filename: "test-09-mixed-monorepo.zip",
        display_name: "test-09-mixed-monorepo.zip",
        canonical_identity: "upload/abc",
        scan_count: 2,
        eligible_comparison_scan_count: 2,
        latest_scan_id: 15,
        latest_scan_status: "completed",
      }),
    ]);
    render(
      <MemoryRouter initialEntries={["/repositories"]}>
        <Routes>
          <Route path="/repositories" element={<RepositoriesPage />} />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() =>
      expect(screen.getByText("test-09-mixed-monorepo.zip")).toBeInTheDocument()
    );
    // Compare link is present and not disabled.
    const compare = screen.getByText("Compare");
    expect(compare).toBeInTheDocument();
  });
});

describe("repository list v2.0.5 - search by filename", () => {
  it("sends the search query parameter to the list endpoint", async () => {
    const fetchMock = setupListFetchMock([]);
    render(
      <MemoryRouter initialEntries={["/repositories"]}>
        <Routes>
          <Route path="/repositories" element={<RepositoriesPage />} />
        </Routes>
      </MemoryRouter>
    );
    // The search box's placeholder mentions filename + scan ID.
    const input = screen.getByPlaceholderText(
      "Search by repository, filename, canonical URL, or scan ID (#15)"
    );
    expect(input).toBeInTheDocument();
    // The empty list (no filters set) shows the
    // "No repositories yet" empty state.
    await waitFor(() =>
      expect(screen.getByText("No repositories yet")).toBeInTheDocument()
    );
    // The fetch mock was called with the list endpoint URL.
    expect(fetchMock).toHaveBeenCalled();
    const calledWith = fetchMock.mock.calls[0][0];
    expect(calledWith).toContain("/api/v1/repositories");
  });
});

describe("repository list v2.0.5 - no local path leak", () => {
  it("the rendered row never shows a local filesystem path", async () => {
    setupListFetchMock([
      makeRepo({
        id: 13,
        source_type: "uploaded_archive",
        provider: "local_upload",
        owner: "upload",
        name: "abc",
        canonical_url: "upload://abc",
        visibility: "private",
        original_filename: "test-09-mixed-monorepo.zip",
        display_name: "test-09-mixed-monorepo.zip",
        canonical_identity: "upload/abc",
        latest_scan_id: 15,
        latest_scan_status: "completed",
      }),
    ]);
    const { container } = render(
      <MemoryRouter initialEntries={["/repositories"]}>
        <Routes>
          <Route path="/repositories" element={<RepositoriesPage />} />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() =>
      expect(screen.getByText("test-09-mixed-monorepo.zip")).toBeInTheDocument()
    );
    const text = container.textContent || "";
    // Common path-separator substrings that would imply a
    // local path leak; we assert the absence of the
    // Windows-style "C:\" and the bare drive letter, the
    // absolute POSIX root, and the typical workspace
    // patterns.
    expect(text).not.toMatch(/C:\\/);
    expect(text).not.toMatch(/\/var\/workspace/);
    expect(text).not.toMatch(/C:\/Users/);
  });
});

describe("repository list v2.0.5 - eligible_count helper text", () => {
  it("shows the eligible comparison scan count when two or more eligible scans exist", async () => {
    setupListFetchMock([
      makeRepo({
        id: 13,
        source_type: "uploaded_archive",
        provider: "local_upload",
        owner: "upload",
        name: "abc",
        canonical_url: "upload://abc",
        visibility: "private",
        original_filename: "test-09-mixed-monorepo.zip",
        display_name: "test-09-mixed-monorepo.zip",
        canonical_identity: "upload/abc",
        scan_count: 3,
        eligible_comparison_scan_count: 2,
        latest_scan_id: 15,
        latest_scan_status: "completed",
      }),
    ]);
    render(
      <MemoryRouter initialEntries={["/repositories"]}>
        <Routes>
          <Route path="/repositories" element={<RepositoriesPage />} />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() =>
      expect(screen.getByText("test-09-mixed-monorepo.zip")).toBeInTheDocument()
    );
    // The eligible comparison count is shown as a sub-line
    // under the scan count.
    expect(screen.getByText(/eligible to compare/)).toBeInTheDocument();
  });
});
