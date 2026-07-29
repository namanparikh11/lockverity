/**
 * v1.2 demo-dataset notice tests.
 *
 * The frontend renders a small, neutral in-product notice
 * on the scan list when every listed scan belongs to the
 * synthetic demo fixture repository. The notice must not
 * appear when the scans belong to other repositories and
 * must not imply real provider data.
 */

import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";

import { AppShell } from "@/layouts/AppShell";
import { ScansIndexPage } from "@/pages/ScansIndexPage";

const DEMO_FIXTURE = "https://github.com/example-org/lockverity-fixture";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("v1.2 demo-dataset notice on the scan list", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    cleanup();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("renders the demo notice when every scan belongs to the demo fixture", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/v1/system/info")) {
        return Promise.resolve(
          jsonResponse({
            name: "Lockverity",
            version: "1.2.0",
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
      if (url.endsWith("/api/v1/repositories?page=1&page_size=50")) {
        return Promise.resolve(
          jsonResponse({
            items: [
              {
                id: 1,
                source_type: "github",
                provider: "github",
                owner: "example-org",
                name: "lockverity-fixture",
                canonical_url: DEMO_FIXTURE,
                default_branch: "main",
                description: null,
                visibility: "public",
                archived: false,
                last_provider_sync_at: null,
                created_at: "2026-07-17T00:00:00Z",
                updated_at: "2026-07-17T00:00:00Z",
              },
            ],
          })
        );
      }
      if (url.endsWith("/api/v1/repositories/1/scans?page=1&page_size=5")) {
        return Promise.resolve(
          jsonResponse({
            items: [
              {
                id: 1,
                repository_id: 1,
                status: "completed",
                trigger_type: "manual",
                requested_ref: "main",
                resolved_commit_sha: "deadbeef".repeat(5),
                analyzer_version: "lockverity 1.2.0",
                created_at: "2026-07-17T00:00:00Z",
                updated_at: "2026-07-17T00:00:00Z",
              },
              {
                id: 2,
                repository_id: 1,
                status: "partial",
                trigger_type: "manual",
                requested_ref: "main",
                resolved_commit_sha: "deadbeef".repeat(5),
                analyzer_version: "lockverity 1.2.0",
                created_at: "2026-07-17T00:00:00Z",
                updated_at: "2026-07-17T00:00:00Z",
              },
              {
                id: 3,
                repository_id: 1,
                status: "failed",
                trigger_type: "manual",
                requested_ref: "main",
                resolved_commit_sha: "deadbeef".repeat(5),
                analyzer_version: "lockverity 1.2.0",
                created_at: "2026-07-17T00:00:00Z",
                updated_at: "2026-07-17T00:00:00Z",
              },
              {
                id: 4,
                repository_id: 1,
                status: "cancelled",
                trigger_type: "manual",
                requested_ref: "main",
                resolved_commit_sha: "deadbeef".repeat(5),
                analyzer_version: "lockverity 1.2.0",
                created_at: "2026-07-17T00:00:00Z",
                updated_at: "2026-07-17T00:00:00Z",
              },
            ],
          })
        );
      }
      return Promise.resolve(jsonResponse({}, 404));
    });
    global.fetch = fetchMock;

    render(
      <MemoryRouter initialEntries={["/scans"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/scans" element={<ScansIndexPage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(
        screen.getByText(/demo evidence: synthetic persisted dataset/i)
      ).toBeInTheDocument();
    });
    expect(
      screen.getByText(/no provider calls were made/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/not a security verdict, certification, or compliance pass-or-fail/i)
    ).toBeInTheDocument();
  });

  it("does not render the demo notice when a non-demo repository is in the list", async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/v1/system/info")) {
        return Promise.resolve(
          jsonResponse({
            name: "Lockverity",
            version: "1.2.0",
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
      if (url.endsWith("/api/v1/repositories?page=1&page_size=50")) {
        return Promise.resolve(
          jsonResponse({
            items: [
              {
                id: 7,
                source_type: "github",
                provider: "github",
                owner: "real-org",
                name: "real-repo",
                canonical_url: "https://github.com/real-org/real-repo",
                default_branch: "main",
                description: null,
                visibility: "public",
                archived: false,
                last_provider_sync_at: null,
                created_at: "2026-07-17T00:00:00Z",
                updated_at: "2026-07-17T00:00:00Z",
              },
            ],
          })
        );
      }
      if (url.endsWith("/api/v1/repositories/7/scans?page=1&page_size=5")) {
        return Promise.resolve(
          jsonResponse({
            items: [
              {
                id: 42,
                repository_id: 7,
                status: "completed",
                trigger_type: "manual",
                requested_ref: "main",
                resolved_commit_sha: "0123456789abcdef0123456789abcdef01234567",
                analyzer_version: "lockverity 1.2.0",
                created_at: "2026-07-17T00:00:00Z",
                updated_at: "2026-07-17T00:00:00Z",
              },
            ],
          })
        );
      }
      return Promise.resolve(jsonResponse({}, 404));
    });
    global.fetch = fetchMock;

    render(
      <MemoryRouter initialEntries={["/scans"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/scans" element={<ScansIndexPage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    );

    // Wait for the list to render, then assert the demo
    // notice is NOT present.
    await waitFor(() => {
      expect(screen.getByText("#42")).toBeInTheDocument();
    });
    expect(
      screen.queryByText(/demo evidence: synthetic persisted dataset/i)
    ).not.toBeInTheDocument();
  });
});
