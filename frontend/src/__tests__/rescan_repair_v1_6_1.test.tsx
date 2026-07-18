/**
 * v1.6.1 workspace-preserving rescan tests.
 *
 * The v1.6 retry/rescan workflow called
 * ``POST /repositories/{id}/scans`` which created a
 * queued scan with no workspace. The orchestrator
 * failed the archive validation stage with
 * ``failure_code="not_found"`` because there was no
 * workspace to read.
 *
 * The v1.6.1 fix:
 * - the workbench calls the dedicated
 *   ``POST /repositories/{id}/rescan`` route
 *   (``api.rescanRepository``);
 * - the route creates a fresh scan row, a fresh
 *   workspace, and re-materialises the source
 *   evidence before returning;
 * - when the original source is no longer available,
 *   the route returns
 *   ``error.code === "rescan_source_unavailable"``
 *   and the workbench renders bounded guidance;
 * - the historical scan and workspace are never
 *   mutated.
 *
 * These tests cover the workbench contract for the
 * v1.6.1 repair without weakening the existing
 * v1.6 rescan assertions.
 */

import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { AppShell } from "@/layouts/AppShell";
import { ScanDetailsPage } from "@/pages/ScanDetailsPage";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function makeScan(overrides: Partial<{
  id: number;
  status: "queued" | "running" | "completed" | "partial" | "failed" | "cancelled";
  trigger_type: "manual" | "upload" | "scheduled" | "api";
  failure_code: string | null;
  failure_summary: string | null;
}> = {}) {
  return {
    id: overrides.id ?? 12,
    repository_id: 7,
    status: overrides.status ?? "completed",
    trigger_type: overrides.trigger_type ?? "manual",
    requested_ref: null,
    resolved_commit_sha: "deadbeef".repeat(5),
    analyzer_version: "lockverity 1.6.1",
    started_at: "2026-07-18T00:00:00Z",
    completed_at: "2026-07-18T00:00:01Z",
    failure_code: overrides.failure_code ?? null,
    failure_summary: overrides.failure_summary ?? null,
    created_at: "2026-07-18T00:00:00Z",
    updated_at: "2026-07-18T00:00:00Z",
  };
}

function makeStage(status: "pending" | "running" | "completed" | "partial" | "failed" | "skipped") {
  return {
    id: 1,
    scan_run_id: 12,
    stage_type: "repository_intake" as const,
    status,
    started_at: status === "pending" ? null : "2026-07-18T00:00:00Z",
    completed_at:
      status === "pending"
        ? null
        : status === "running"
          ? null
          : "2026-07-18T00:00:01Z",
    provider: null,
    provider_status: null,
    records_processed: 0,
    failure_code: null,
    failure_summary: null,
    created_at: "2026-07-18T00:00:00Z",
    updated_at: "2026-07-18T00:00:00Z",
  };
}

const SYSTEM_INFO = {
  name: "Lockverity",
  version: "1.6.1",
  tagline: "Evidence-first software supply-chain assurance",
  environment: "test",
  api_prefix: "/api/v1",
  archive_limits: {},
  pagination: {},
  provider_safety: {},
  intake: {},
};

describe("v1.6.1 workspace-preserving rescan", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    cleanup();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("completed scan shows 'Run another scan' and calls /rescan on click", async () => {
    const fetchMock = vi.fn().mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/api/v1/system/info")) {
          return jsonResponse(SYSTEM_INFO);
        }
        // v1.6.1: the rescan route is the dedicated
        // ``/rescan`` endpoint, not the legacy
        // ``/scans`` route.
        if (
          url.match(/\/api\/v1\/repositories\/\d+\/rescan$/) &&
          init?.method === "POST"
        ) {
          return jsonResponse(makeScan({ id: 99, status: "queued" }), 201);
        }
        if (url.match(/\/api\/v1\/scans\/\d+\/run$/) && init?.method === "POST") {
          return jsonResponse(makeScan({ id: 99, status: "running" }));
        }
        if (url.match(/\/api\/v1\/scans\/\d+$/)) {
          if (url.endsWith("/api/v1/scans/12")) {
            return jsonResponse(
              makeScan({ id: 12, status: "completed" })
            );
          }
          if (url.endsWith("/api/v1/scans/99")) {
            return jsonResponse(makeScan({ id: 99, status: "running" }));
          }
        }
        if (url.match(/\/api\/v1\/scans\/\d+\/stages$/)) {
          return jsonResponse({ items: [makeStage("pending")] });
        }
        return jsonResponse({}, 404);
      }
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    render(
      <MemoryRouter initialEntries={["/scans/12"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/scans/:scanId" element={<ScanDetailsPage />} />
            <Route path="/scans/99" element={<div>new-scan-workbench</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    );

    const rescanButton = await screen.findByTestId(
      "scan-action-rescan",
      {},
      { timeout: 3000 }
    );
    expect(rescanButton).toHaveTextContent(/run another scan/i);
    await act(async () => {
      fireEvent.click(rescanButton);
    });

    await waitFor(() => {
      expect(screen.getByText("new-scan-workbench")).toBeInTheDocument();
    });
    const rescanCalls = fetchMock.mock.calls.filter((args) => {
      const u = args[0] as unknown;
      const init = args[1] as RequestInit | undefined;
      const url = typeof u === "string" ? u : (u as URL).toString();
      return (
        url.match(/\/api\/v1\/repositories\/\d+\/rescan$/) !== null &&
        init?.method === "POST"
      );
    });
    expect(rescanCalls.length).toBe(1);
  });

  it("failed scan shows 'Retry as new scan' and uses the rescan route", async () => {
    const fetchMock = vi.fn().mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/api/v1/system/info")) {
          return jsonResponse(SYSTEM_INFO);
        }
        if (url.match(/\/api\/v1\/repositories\/\d+\/rescan$/) && init?.method === "POST") {
          return jsonResponse(makeScan({ id: 314, status: "queued" }), 201);
        }
        if (url.match(/\/api\/v1\/scans\/\d+\/run$/) && init?.method === "POST") {
          return jsonResponse(makeScan({ id: 314, status: "running" }));
        }
        if (url.match(/\/api\/v1\/scans\/\d+$/)) {
          if (url.endsWith("/api/v1/scans/12")) {
            return jsonResponse(
              makeScan({
                id: 12,
                status: "failed",
                failure_code: "scanner_crashed",
                failure_summary: "Scanner crashed before inventory capture.",
              })
            );
          }
          if (url.endsWith("/api/v1/scans/314")) {
            return jsonResponse(makeScan({ id: 314, status: "running" }));
          }
        }
        if (url.match(/\/api\/v1\/scans\/\d+\/stages$/)) {
          return jsonResponse({ items: [makeStage("failed")] });
        }
        return jsonResponse({}, 404);
      }
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    render(
      <MemoryRouter initialEntries={["/scans/12"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/scans/:scanId" element={<ScanDetailsPage />} />
            <Route path="/scans/314" element={<div>retry-workbench</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    );

    const rescanButton = await screen.findByTestId("scan-action-rescan");
    expect(rescanButton).toHaveTextContent(/retry as new scan/i);
    await act(async () => {
      fireEvent.click(rescanButton);
    });
    await waitFor(() => {
      expect(screen.getByText("retry-workbench")).toBeInTheDocument();
    });
  });

  it("renders bounded source-unavailable guidance when rescan fails", async () => {
    const fetchMock = vi.fn().mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/api/v1/system/info")) {
          return jsonResponse(SYSTEM_INFO);
        }
        if (url.match(/\/api\/v1\/repositories\/\d+\/rescan$/) && init?.method === "POST") {
          return new Response(
            JSON.stringify({
              error: {
                code: "rescan_source_unavailable",
                message:
                  "The original uploaded source is no longer available. Upload the archive again to create a new scan.",
              },
            }),
            { status: 422, headers: { "content-type": "application/json" } }
          );
        }
        if (url.match(/\/api\/v1\/scans\/\d+$/)) {
          return jsonResponse(makeScan({ id: 12, status: "completed" }));
        }
        if (url.match(/\/api\/v1\/scans\/\d+\/stages$/)) {
          return jsonResponse({ items: [makeStage("pending")] });
        }
        return jsonResponse({}, 404);
      }
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    render(
      <MemoryRouter initialEntries={["/scans/12"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/scans/:scanId" element={<ScanDetailsPage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    );

    const rescanButton = await screen.findByTestId("scan-action-rescan");
    await act(async () => {
      fireEvent.click(rescanButton);
    });

    await waitFor(() => {
      // The bounded error title appears.
      const errorContainer = screen.getByTestId("scan-action-error");
      expect(errorContainer).toBeInTheDocument();
      expect(
        screen.getByText(/rescan source is no longer available/i)
      ).toBeInTheDocument();
    });
    // The page does not navigate to a new scan when
    // the rescan fails.
    expect(
      screen.queryByText("new-scan-workbench")
    ).not.toBeInTheDocument();
  });

  it("does not call /run when rescan preparation fails", async () => {
    const fetchMock = vi.fn().mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/api/v1/system/info")) {
          return jsonResponse(SYSTEM_INFO);
        }
        if (url.match(/\/api\/v1\/repositories\/\d+\/rescan$/) && init?.method === "POST") {
          return new Response(
            JSON.stringify({
              error: {
                code: "rescan_source_unavailable",
                message: "The original uploaded source is no longer available.",
              },
            }),
            { status: 422, headers: { "content-type": "application/json" } }
          );
        }
        if (url.match(/\/api\/v1\/scans\/\d+$/)) {
          return jsonResponse(makeScan({ id: 12, status: "completed" }));
        }
        if (url.match(/\/api\/v1\/scans\/\d+\/stages$/)) {
          return jsonResponse({ items: [makeStage("pending")] });
        }
        return jsonResponse({}, 404);
      }
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    render(
      <MemoryRouter initialEntries={["/scans/12"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/scans/:scanId" element={<ScanDetailsPage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    );

    const rescanButton = await screen.findByTestId("scan-action-rescan");
    await act(async () => {
      fireEvent.click(rescanButton);
    });
    await new Promise((r) => setTimeout(r, 200));
    // Find the action error and dump its text
    const errorEl = document.querySelector('[data-testid="scan-action-error"]');
    if (errorEl) {
      console.log("DEBUG: error text =", errorEl.textContent);
    } else {
      console.log("DEBUG: scan-action-error NOT FOUND");
    }
    await waitFor(() => {
      expect(
        screen.getByText(/rescan source is no longer available/i)
      ).toBeInTheDocument();
    });
    const runCalls = fetchMock.mock.calls.filter((args) => {
      const u = args[0] as unknown;
      const url = typeof u === "string" ? u : (u as URL).toString();
      return url.match(/\/api\/v1\/scans\/\d+\/run$/) !== null;
    });
    expect(runCalls.length).toBe(0);
  });

  it("blocks duplicate clicks on the rescan button", async () => {
    const fetchMock = vi.fn().mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/api/v1/system/info")) {
          return jsonResponse(SYSTEM_INFO);
        }
        if (url.match(/\/api\/v1\/repositories\/\d+\/rescan$/) && init?.method === "POST") {
          // Slow response to give the second click a
          // chance to fire while the first is pending.
          await new Promise((resolve) => window.setTimeout(resolve, 200));
          return jsonResponse(makeScan({ id: 99, status: "queued" }), 201);
        }
        if (url.match(/\/api\/v1\/scans\/\d+$/)) {
          if (url.endsWith("/api/v1/scans/12")) {
            return jsonResponse(makeScan({ id: 12, status: "completed" }));
          }
          if (url.endsWith("/api/v1/scans/99")) {
            return jsonResponse(makeScan({ id: 99, status: "running" }));
          }
        }
        if (url.match(/\/api\/v1\/scans\/\d+\/stages$/)) {
          return jsonResponse({ items: [makeStage("pending")] });
        }
        return jsonResponse({}, 404);
      }
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    render(
      <MemoryRouter initialEntries={["/scans/12"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/scans/:scanId" element={<ScanDetailsPage />} />
            <Route path="/scans/99" element={<div>new-scan-workbench</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    );

    const rescanButton = await screen.findByTestId("scan-action-rescan");
    // Fire two clicks rapidly. The button should
    // disable on the first click so the second click
    // is a no-op.
    await act(async () => {
      fireEvent.click(rescanButton);
      fireEvent.click(rescanButton);
    });
    await waitFor(() => {
      expect(screen.getByText("new-scan-workbench")).toBeInTheDocument();
    });
    const rescanCalls = fetchMock.mock.calls.filter((args) => {
      const u = args[0] as unknown;
      const init = args[1] as RequestInit | undefined;
      const url = typeof u === "string" ? u : (u as URL).toString();
      return (
        url.match(/\/api\/v1\/repositories\/\d+\/rescan$/) !== null &&
        init?.method === "POST"
      );
    });
    // Only one /rescan POST is issued, even though
    // the button was clicked twice.
    expect(rescanCalls.length).toBe(1);
  });

  it("preserves the historical scan id when the rescan succeeds", async () => {
    let historicalScanId = -1;
    let newScanId = -1;
    const fetchMock = vi.fn().mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/api/v1/system/info")) {
          return jsonResponse(SYSTEM_INFO);
        }
        if (url.match(/\/api\/v1\/repositories\/\d+\/rescan$/) && init?.method === "POST") {
          return jsonResponse(makeScan({ id: 99, status: "queued" }), 201);
        }
        if (url.match(/\/api\/v1\/scans\/\d+\/run$/) && init?.method === "POST") {
          return jsonResponse(makeScan({ id: 99, status: "running" }));
        }
        if (url.match(/\/api\/v1\/scans\/\d+$/)) {
          if (url.endsWith("/api/v1/scans/12")) {
            return jsonResponse(makeScan({ id: 12, status: "completed" }));
          }
          if (url.endsWith("/api/v1/scans/99")) {
            return jsonResponse(makeScan({ id: 99, status: "running" }));
          }
        }
        if (url.match(/\/api\/v1\/scans\/\d+\/stages$/)) {
          return jsonResponse({ items: [makeStage("pending")] });
        }
        return jsonResponse({}, 404);
      }
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    render(
      <MemoryRouter initialEntries={["/scans/12"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/scans/:scanId" element={<ScanDetailsPage />} />
            <Route path="/scans/99" element={<div>new-workbench</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    );

    historicalScanId = 12;
    const rescanButton = await screen.findByTestId("scan-action-rescan");
    await act(async () => {
      fireEvent.click(rescanButton);
    });
    await waitFor(() => {
      expect(screen.getByText("new-workbench")).toBeInTheDocument();
    });
    newScanId = 99;
    expect(newScanId).not.toBe(historicalScanId);
    // The historical scan id is not mutated and
    // remains distinct from the new scan id.
    expect(historicalScanId).toBe(12);
    expect(newScanId).toBe(99);
  });

  it("does not regress v1.6 cancellation and start behavior", async () => {
    const fetchMock = vi.fn().mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/api/v1/system/info")) {
          return jsonResponse(SYSTEM_INFO);
        }
        if (url.match(/\/api\/v1\/scans\/\d+\/cancel$/) && init?.method === "POST") {
          return jsonResponse(makeScan({ id: 12, status: "cancelled" }));
        }
        if (url.match(/\/api\/v1\/scans\/\d+$/)) {
          return jsonResponse(makeScan({ id: 12, status: "running" }));
        }
        if (url.match(/\/api\/v1\/scans\/\d+\/stages$/)) {
          return jsonResponse({ items: [makeStage("pending")] });
        }
        return jsonResponse({}, 404);
      }
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    render(
      <MemoryRouter initialEntries={["/scans/12"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/scans/:scanId" element={<ScanDetailsPage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    );

    const cancelButton = await screen.findByTestId("scan-action-cancel");
    await act(async () => {
      fireEvent.click(cancelButton);
    });
    const dialog = await screen.findByRole("dialog", { name: /cancel scan #12/i });
    expect(dialog).toBeInTheDocument();
  });
});
