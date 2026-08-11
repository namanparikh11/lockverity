/**
 * v1.6 scan workbench + execution controls tests.
 *
 * The workbench is the destination for the v1.5 guided
 * intake page once execution starts. It must surface:
 *
 * - truthful state for queued / running / terminal scans;
 * - Start scan action for queued scans;
 * - Cancel scan action with confirmation;
 * - Run another scan / Retry as new scan for terminal
 *   scans (creates a fresh scan, never mutates the
 *   historical one);
 * - bounded partial-success intake UX on the /analyze
 *   page;
 * - no invented percentage progress;
 * - no fabricated clean / secure / certified wording;
 * - the AppShell Analyze nav entry and the /demo route
 *   remain functional.
 */

import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";

import { AppShell } from "@/layouts/AppShell";
import { AnalyzePage } from "@/pages/AnalyzePage";
import { DemoHomePage } from "@/pages/DemoHomePage";
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
  requested_ref: string | null;
  resolved_commit_sha: string | null;
}> = {}) {
  return {
    id: overrides.id ?? 12,
    repository_id: 7,
    status: overrides.status ?? "queued",
    trigger_type: overrides.trigger_type ?? "manual",
    requested_ref: overrides.requested_ref ?? null,
    resolved_commit_sha: overrides.resolved_commit_sha ?? null,
    analyzer_version: "lockverity 1.6.0",
    started_at: null,
    completed_at: null,
    failure_code: overrides.failure_code ?? null,
    failure_summary: overrides.failure_summary ?? null,
    created_at: "2026-07-18T00:00:00Z",
    updated_at: "2026-07-18T00:00:00Z",
  };
}

function makeStage(status: "pending" | "running" | "completed" | "partial" | "failed" | "skipped", overrides: Partial<{
  stage_type: string;
  failure_code: string | null;
  failure_summary: string | null;
  records_processed: number;
}> = {}) {
  return {
    id: 1,
    scan_run_id: 12,
    stage_type: overrides.stage_type ?? "repository_intake",
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
    records_processed: overrides.records_processed ?? 0,
    failure_code: overrides.failure_code ?? null,
    failure_summary: overrides.failure_summary ?? null,
    created_at: "2026-07-18T00:00:00Z",
    updated_at: "2026-07-18T00:00:00Z",
  };
}

const SYSTEM_INFO = {
  name: "Lockverity",
  version: "1.6.0",
  tagline: "Evidence-first software supply-chain assurance",
  environment: "test",
  api_prefix: "/api/v1",
  archive_limits: {},
  pagination: {},
  provider_safety: {},
  intake: {},
};

describe("v1.6 scan workbench + execution controls", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    cleanup();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("renders a queued workbench without result claims", async () => {
    global.fetch = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/v1/system/info")) {
        return Promise.resolve(jsonResponse(SYSTEM_INFO));
      }
      if (url.match(/\/api\/v1\/scans\/\d+$/)) {
        return Promise.resolve(jsonResponse(makeScan({ id: 12, status: "queued" })));
      }
      if (url.match(/\/api\/v1\/scans\/\d+\/stages$/)) {
        return Promise.resolve(
          jsonResponse({
            items: [
              makeStage("pending", { stage_type: "repository_intake" }),
              makeStage("pending", { stage_type: "archive_validation" }),
            ],
          })
        );
      }
      return Promise.resolve(jsonResponse({}, 404));
    });

    render(
      <MemoryRouter initialEntries={["/scans/12"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/scans/:scanId" element={<ScanDetailsPage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(
        screen.getByTestId("scan-status-explanation")
      ).toBeInTheDocument();
    });
    // Queued wording: waiting for execution; no result claim.
    expect(
      screen.getByText(/waiting for execution/i)
    ).toBeInTheDocument();
    // Stage progress: 0 of N terminal states; N != percentage.
    expect(
      screen.getByTestId("stage-progress-summary")
    ).toHaveTextContent(/0 of 2 stages reached a terminal state/i);
    expect(
      screen.getByTestId("stage-progress-summary")
    ).toHaveTextContent(/terminal does not imply successful/i);
    // No invented percentage.
    expect(screen.queryByText(/\b\d{1,3}%/)).not.toBeInTheDocument();
    // Start scan action is available for queued status.
    const startButton = await screen.findByTestId("scan-action-start");
    expect(startButton).toBeInTheDocument();
    expect(startButton).not.toBeDisabled();
  });

  it("renders a running workbench with truthful status and no completion claim", async () => {
    global.fetch = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/v1/system/info")) {
        return Promise.resolve(jsonResponse(SYSTEM_INFO));
      }
      if (url.match(/\/api\/v1\/scans\/\d+$/)) {
        return Promise.resolve(
          jsonResponse(
            makeScan({
              id: 12,
              status: "running",
              resolved_commit_sha: "0123456789abcdef0123456789abcdef01234567",
            })
          )
        );
      }
      if (url.match(/\/api\/v1\/scans\/\d+\/stages$/)) {
        return Promise.resolve(
          jsonResponse({
            items: [
              makeStage("completed", { stage_type: "repository_intake" }),
              makeStage("running", { stage_type: "manifest_discovery" }),
              makeStage("pending", { stage_type: "dependency_parsing" }),
            ],
          })
        );
      }
      return Promise.resolve(jsonResponse({}, 404));
    });

    render(
      <MemoryRouter initialEntries={["/scans/12"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/scans/:scanId" element={<ScanDetailsPage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(
        screen.getByText(/analysis in progress/i)
      ).toBeInTheDocument();
    });
    // 1 of 3 stages terminal; the wording never claims
    // "successful" for the terminal stage.
    expect(
      screen.getByTestId("stage-progress-summary")
    ).toHaveTextContent(/1 of 3 stages reached a terminal state/i);
    // Cancel is available for running scans.
    const cancelButton = await screen.findByTestId("scan-action-cancel");
    expect(cancelButton).toBeInTheDocument();
    expect(cancelButton).not.toBeDisabled();
  });

  it("renders the failed status with bounded failure code and message", async () => {
    global.fetch = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/v1/system/info")) {
        return Promise.resolve(jsonResponse(SYSTEM_INFO));
      }
      if (url.match(/\/api\/v1\/scans\/\d+$/)) {
        return Promise.resolve(
          jsonResponse(
            makeScan({
              id: 12,
              status: "failed",
              failure_code: "scanner_crashed",
              failure_summary: "Scanner crashed before inventory capture.",
            })
          )
        );
      }
      if (url.match(/\/api\/v1\/scans\/\d+\/stages$/)) {
        return Promise.resolve(
          jsonResponse({
            items: [makeStage("failed", { stage_type: "dependency_parsing" })],
          })
        );
      }
      return Promise.resolve(jsonResponse({}, 404));
    });

    render(
      <MemoryRouter initialEntries={["/scans/12"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/scans/:scanId" element={<ScanDetailsPage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(
        screen.getByText(/scan did not complete/i)
      ).toBeInTheDocument();
    });
    // The failure code is rendered in BOTH the new
    // bounded "Bounded failure: <code>" explanation
    // and the existing "Scan failure (<code>)" alert.
    // The substring must appear at least once in the
    // bounded workbench wording.
    const failureMatches = screen.getAllByText(/scanner_crashed/i);
    expect(failureMatches.length).toBeGreaterThan(0);
    expect(
      screen.getByText(/bounded failure: scanner_crashed/i)
    ).toBeInTheDocument();
    // Retry button appears for failed scans.
    const retry = await screen.findByTestId("scan-action-rescan");
    expect(retry).toBeInTheDocument();
    expect(retry).toHaveTextContent(/retry as new scan/i);
  });

  it("renders the partial status with bounded reason", async () => {
    global.fetch = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/v1/system/info")) {
        return Promise.resolve(jsonResponse(SYSTEM_INFO));
      }
      if (url.match(/\/api\/v1\/scans\/\d+$/)) {
        return Promise.resolve(
          jsonResponse(
            makeScan({
              id: 12,
              status: "partial",
              failure_summary: "Provider coverage was degraded.",
            })
          )
        );
      }
      if (url.match(/\/api\/v1\/scans\/\d+\/stages$/)) {
        return Promise.resolve(
          jsonResponse({
            items: [
              makeStage("completed", { stage_type: "repository_intake" }),
              makeStage("partial", { stage_type: "vulnerability_query" }),
            ],
          })
        );
      }
      return Promise.resolve(jsonResponse({}, 404));
    });

    render(
      <MemoryRouter initialEntries={["/scans/12"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/scans/:scanId" element={<ScanDetailsPage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(
        screen.getByText(/missing or degraded evidence/i)
      ).toBeInTheDocument();
    });
    const partialMatches = screen.getAllByText(/provider coverage was degraded/i);
    expect(partialMatches.length).toBeGreaterThan(0);
  });

  it("calls POST /scans/{id}/run when Start scan is clicked and the workbench refreshes", async () => {
    let scanStatus: "queued" | "running" = "queued";
    const fetchMock = vi.fn().mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/api/v1/system/info")) {
          return jsonResponse(SYSTEM_INFO);
        }
        if (url.match(/\/api\/v1\/scans\/\d+\/run$/) && init?.method === "POST") {
          scanStatus = "running";
          return jsonResponse(
            makeScan({ id: 12, status: scanStatus })
          );
        }
        if (url.match(/\/api\/v1\/scans\/\d+$/)) {
          return jsonResponse(makeScan({ id: 12, status: scanStatus }));
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

    const startButton = await screen.findByTestId("scan-action-start");
    fireEvent.click(
      screen.getByRole("checkbox", { name: /OpenSSF Scorecard/i })
    );
    await act(async () => {
      fireEvent.click(startButton);
    });

    // The workbench polled and the scan is now "running".
    await waitFor(
      () => {
        expect(screen.getByText(/analysis in progress/i)).toBeInTheDocument();
      },
      { timeout: 3000 }
    );
    const runCalls = fetchMock.mock.calls.filter((args) => {
      const u = args[0] as unknown;
      const init = args[1] as RequestInit | undefined;
      const url = typeof u === "string" ? u : (u as URL).toString();
      return url.endsWith("/api/v1/scans/12/run") && init?.method === "POST";
    });
    expect(runCalls.length).toBe(1);
    expect(JSON.parse(String(runCalls[0][1]?.body))).toEqual({
      external_evidence_providers: {
        osv: true,
        deps_dev: true,
        openssf: false,
      },
    });
  });

  it("shows a confirmation dialog before cancelling an eligible scan", async () => {
    const fetchMock = vi.fn().mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/api/v1/system/info")) {
          return jsonResponse(SYSTEM_INFO);
        }
        if (
          url.match(/\/api\/v1\/scans\/\d+\/cancel$/) &&
          init?.method === "POST"
        ) {
          return jsonResponse(
            makeScan({ id: 12, status: "cancelled" })
          );
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

    // The dialog wording must include the bounded copy.
    const dialog = screen.getByRole("dialog", { name: /cancel scan #12\?/i });
    expect(dialog).toBeInTheDocument();
    expect(
      screen.getByText(/persisted evidence remains available/i)
    ).toBeInTheDocument();
    // Cancel-the-scan confirm is a destructive button.
    // Scope the query to inside the dialog so the
    // workbench's primary "Cancel scan" action button
    // does not collide.
    const confirmButton = within(dialog).getByRole("button", {
      name: /^cancel scan$/i,
    });
    await act(async () => {
      fireEvent.click(confirmButton);
    });

    // The cancel endpoint was called exactly once.
    await waitFor(() => {
      const calls = fetchMock.mock.calls.filter((args) => {
        const u = args[0] as unknown;
        const init = args[1] as RequestInit | undefined;
        const url = typeof u === "string" ? u : (u as URL).toString();
        return url.endsWith("/api/v1/scans/12/cancel") && init?.method === "POST";
      });
      expect(calls.length).toBe(1);
    });
  });

  it("creates a new scan and navigates to its workbench when Run another scan is clicked", async () => {
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
    fireEvent.click(screen.getByRole("checkbox", { name: /deps\.dev/i }));
    await act(async () => {
      fireEvent.click(rescanButton);
    });

    await waitFor(() => {
      expect(screen.getByText("new-scan-workbench")).toBeInTheDocument();
    });
    // The historical scan was never mutated: only the
    // repository-scans POST was issued, never a PATCH
    // against the historical scan id.
    const historicalMutations = fetchMock.mock.calls.filter((args) => {
      const u = args[0] as unknown;
      const init = args[1] as RequestInit | undefined;
      const url = typeof u === "string" ? u : (u as URL).toString();
      return url.endsWith("/api/v1/scans/12") && init?.method !== undefined && init.method !== "GET";
    });
    expect(historicalMutations.length).toBe(0);
    const runCall = fetchMock.mock.calls.find((args) => {
      const url = String(args[0]);
      return url.endsWith("/api/v1/scans/99/run");
    });
    expect(JSON.parse(String(runCall?.[1]?.body))).toEqual({
      external_evidence_providers: {
        osv: true,
        deps_dev: false,
        openssf: true,
      },
    });
  });

  it("renders the partial-success intake UX when intake succeeds but start fails", async () => {
    const fetchMock = vi.fn().mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/api/v1/system/info")) {
          return jsonResponse(SYSTEM_INFO);
        }
        if (url.endsWith("/api/v1/repositories/github") && init?.method === "POST") {
          return jsonResponse(
            {
              repository: {
                id: 7,
                source_type: "github",
                provider: "github",
                owner: "octocat",
                name: "hello-world",
                canonical_url: "https://github.com/octocat/hello-world",
                default_branch: "main",
                description: null,
                visibility: "public",
                archived: false,
                last_provider_sync_at: null,
                created_at: "2026-07-18T00:00:00Z",
                updated_at: "2026-07-18T00:00:00Z",
              },
              scan: {
                id: 42,
                repository_id: 7,
                status: "queued",
                trigger_type: "manual",
                requested_ref: null,
                resolved_commit_sha: null,
                analyzer_version: null,
                started_at: null,
                completed_at: null,
                failure_code: null,
                failure_summary: null,
                created_at: "2026-07-18T00:00:00Z",
                updated_at: "2026-07-18T00:00:00Z",
              },
              workspace: {
                id: 1,
                scan_run_id: 42,
                workspace_key: "wks-placeholder",
                kind: "github",
                state: "ready",
                archive_filename: "octocat.tar.gz",
                archive_sha256: null,
                archive_size: 0,
                file_count: 0,
                uncompressed_size: 0,
                failure_code: null,
                failure_summary: null,
                ready_at: "2026-07-18T00:00:00Z",
                cleaned_up_at: null,
                created_at: "2026-07-18T00:00:00Z",
                updated_at: "2026-07-18T00:00:00Z",
              },
              intake_summary: {},
            },
            201
          );
        }
        if (url.match(/\/api\/v1\/scans\/\d+\/run$/) && init?.method === "POST") {
          return new Response(
            JSON.stringify({
              error: {
                code: "internal_error",
                message: "Worker queue rejected the scan.",
              },
            }),
            { status: 500, headers: { "content-type": "application/json" } }
          );
        }
        return jsonResponse({}, 404);
      }
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    render(
      <MemoryRouter initialEntries={["/analyze"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/analyze" element={<AnalyzePage />} />
            <Route path="/scans/:scanId" element={<div>scan-detail</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    );

    const urlInput = screen.getByLabelText(/public github url/i);
    const submitButton = screen.getByRole("button", { name: /^analyze repository$/i });
    await act(async () => {
      fireEvent.change(urlInput, {
        target: { value: "https://github.com/octocat/hello-world" },
      });
      fireEvent.click(
        within(
          screen.getByLabelText("Analyze public GitHub repository form")
        ).getByRole("checkbox", { name: /OSV/i })
      );
    });
    await act(async () => {
      fireEvent.click(submitButton);
    });

    // Partial-success copy: intake completed, start did
    // not. The page never claims the scan started.
    await waitFor(() => {
      expect(
        screen.getByText(/intake completed, but scan execution did not start/i)
      ).toBeInTheDocument();
    });
    // The page renders a Retry start button that re-issues
    // ``/scans/{id}/run`` (no new repository is created).
    const retry = screen.getByRole("button", { name: /^retry start$/i });
    await act(async () => {
      fireEvent.click(retry);
    });
    const runCalls = fetchMock.mock.calls.filter((args) => {
      const u = args[0] as unknown;
      const url = typeof u === "string" ? u : (u as URL).toString();
      return url.endsWith("/api/v1/scans/42/run");
    });
    // The initial run + one retry = 2 calls to /run.
    expect(runCalls.length).toBe(2);
    for (const call of runCalls) {
      expect(JSON.parse(String(call[1]?.body))).toEqual({
        external_evidence_providers: {
          osv: false,
          deps_dev: true,
          openssf: true,
        },
      });
    }
    // No new repository was created.
    const repoCalls = fetchMock.mock.calls.filter((args) => {
      const u = args[0] as unknown;
      const url = typeof u === "string" ? u : (u as URL).toString();
      return url.endsWith("/api/v1/repositories/github");
    });
    expect(repoCalls.length).toBe(1);
  });

  it("does not invent percentage progress anywhere on the workbench", async () => {
    global.fetch = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/v1/system/info")) {
        return Promise.resolve(jsonResponse(SYSTEM_INFO));
      }
      if (url.match(/\/api\/v1\/scans\/\d+$/)) {
        return Promise.resolve(jsonResponse(makeScan({ id: 12, status: "running" })));
      }
      if (url.match(/\/api\/v1\/scans\/\d+\/stages$/)) {
        return Promise.resolve(
          jsonResponse({
            items: [
              makeStage("completed", { stage_type: "repository_intake" }),
              makeStage("running", { stage_type: "manifest_discovery" }),
            ],
          })
        );
      }
      return Promise.resolve(jsonResponse({}, 404));
    });

    render(
      <MemoryRouter initialEntries={["/scans/12"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/scans/:scanId" element={<ScanDetailsPage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(
        screen.getByTestId("scan-status-explanation")
      ).toBeInTheDocument();
    });
    // No percentage string anywhere in the workbench.
    expect(screen.queryByText(/\b\d{1,3}%/)).not.toBeInTheDocument();
    // No fabricated "secure / clean / certified / passed" wording.
    expect(screen.queryByText(/secure/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/clean scan/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/certified/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/no vulnerabilities/i)).not.toBeInTheDocument();
  });

  it("exposes the AppShell Analyze entry and keeps the /demo route working", async () => {
    global.fetch = vi.fn().mockResolvedValue(jsonResponse(SYSTEM_INFO));
    render(
      <MemoryRouter initialEntries={["/demo"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/demo" element={<DemoHomePage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    );
    const navAnalyze = screen.getByRole("link", { name: /^Analyze$/ });
    expect(navAnalyze.getAttribute("href")).toBe("/analyze");
    expect(
      screen.getByRole("heading", { name: /local demo/i })
    ).toBeInTheDocument();
  });
});
