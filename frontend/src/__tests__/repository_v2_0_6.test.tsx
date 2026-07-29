/**
 * v2.0.6 repository historical label tests.
 *
 * v2.0.5 added ``display_name`` and ``canonical_identity``
 * to the repository list response. For uploaded rows,
 * ``display_name`` used ``Repository.original_filename``;
 * historical v0.x-v2.0.4 rows had ``original_filename =
 * null`` and rendered the bounded opaque fallback
 * ``Uploaded archive · upload/<short-key>``.
 *
 * v2.0.6 derives a per-repository historical archive
 * filename from the existing ``Workspace.archive_filename``
 * rows. The list endpoint returns the historical filename
 * as ``display_name`` when ``original_filename`` is null.
 *
 * The backend decision and the search behaviour are
 * covered by
 * ``backend/tests/test_repository_historical_filenames_v2_0_6.py``.
 * These frontend tests pin the rendering contract: a
 * historical archive filename becomes the primary title,
 * the canonical upload identifier remains secondary, and
 * the bounded fallback is used when the historical helper
 * returns a conflict or no filename.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";

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
  const summary: Record<string, unknown> = {
    scan_count: overrides.scan_count ?? 0,
    eligible_comparison_scan_count:
      overrides.eligible_comparison_scan_count ?? 0,
    latest_scan:
      overrides.latest_scan_id != null
        ? {
            id: overrides.latest_scan_id,
            status: overrides.latest_scan_status || "completed",
            trigger_type: "upload",
            created_at: "2026-07-22T00:00:00Z",
            completed_at: "2026-07-22T00:00:30Z",
          }
        : null,
  };
  return {
    id: overrides.id ?? 13,
    source_type: overrides.source_type ?? "uploaded_archive",
    provider: overrides.provider ?? "local_upload",
    owner: overrides.owner ?? "upload",
    name: overrides.name ?? "7e12fbd201665dd4",
    canonical_url:
      overrides.canonical_url !== undefined
        ? overrides.canonical_url
        : "upload://7e12fbd201665dd4",
    default_branch: null,
    description: "Uploaded archive",
    visibility: overrides.visibility ?? "private",
    archived: overrides.archived ?? false,
    last_provider_sync_at: null,
    created_at: "2026-07-22T00:00:00Z",
    updated_at: "2026-07-22T00:00:00Z",
    original_filename:
      overrides.original_filename !== undefined
        ? overrides.original_filename
        : null,
    display_name:
      overrides.display_name !== undefined
        ? overrides.display_name
        : "Uploaded archive · upload/7e12fbd201665dd4",
    canonical_identity:
      overrides.canonical_identity !== undefined
        ? overrides.canonical_identity
        : "upload/7e12fbd201665dd4",
    summary,
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

describe("v2.0.6 repository list - historical archive filename", () => {
  it("renders the historical archive filename as the primary row title", async () => {
    setupListFetchMock([
      makeRepo({
        id: 13,
        display_name: "test-09-mixed-monorepo.zip",
        canonical_identity: "upload/7e12fbd201665dd4",
        original_filename: null,
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
      expect(
        screen.getByText("test-09-mixed-monorepo.zip")
      ).toBeInTheDocument()
    );
    // Canonical upload key remains secondary.
    expect(
      screen.getByText("upload/7e12fbd201665dd4")
    ).toBeInTheDocument();
  });

  it("renders the bounded opaque fallback for a repository with no filename metadata", async () => {
    setupListFetchMock([
      makeRepo({
        id: 14,
        display_name: "Uploaded archive · upload/2ed7b06ed7d3d967",
        canonical_identity: "upload/2ed7b06ed7d3d967",
        original_filename: null,
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
      expect(
        screen.getByText(/^Uploaded archive · upload\//)
      ).toBeInTheDocument()
    );
  });

  it("renders new-upload original_filename as the primary title (regression)", async () => {
    setupListFetchMock([
      makeRepo({
        id: 15,
        display_name: "fresh-upload.zip",
        canonical_identity: "upload/aaaa1111",
        original_filename: "fresh-upload.zip",
        scan_count: 1,
        eligible_comparison_scan_count: 1,
        latest_scan_id: 16,
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
      expect(screen.getByText("fresh-upload.zip")).toBeInTheDocument()
    );
  });

  it("does not render any local absolute path in the row", async () => {
    setupListFetchMock([
      makeRepo({
        id: 17,
        display_name: "secret.zip",
        canonical_identity: "upload/abcdef",
        original_filename: "secret.zip",
        scan_count: 1,
        eligible_comparison_scan_count: 1,
        latest_scan_id: 18,
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
      expect(screen.getByText("secret.zip")).toBeInTheDocument()
    );
    const html = container.innerHTML;
    // No local absolute path substring appears in the rendered HTML.
    expect(html.includes("C:\\Users")).toBe(false);
    expect(html.includes("C:/Users")).toBe(false);
    expect(html.includes("/var/workspace")).toBe(false);
  });

  it("renders scan count, latest scan, and actions for the historical row", async () => {
    setupListFetchMock([
      makeRepo({
        id: 13,
        display_name: "test-09-mixed-monorepo.zip",
        canonical_identity: "upload/7e12fbd201665dd4",
        original_filename: null,
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
      expect(
        screen.getByText("test-09-mixed-monorepo.zip")
      ).toBeInTheDocument()
    );
    // The latest scan id is rendered.
    expect(screen.getByText("#15")).toBeInTheDocument();
    // The scan count is rendered.
    expect(screen.getByText("2")).toBeInTheDocument();
    // The Compare action is present (2 eligible scans).
    expect(screen.getAllByText(/^Compare$/).length).toBeGreaterThan(0);
  });
});
