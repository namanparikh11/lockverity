/**
 * v2.1.1: tests for ``/repositories/new`` after the intake
 * consistency defect closure.
 *
 * The page must:
 *
 * - submit through the canonical GitHub intake endpoint
 *   ``POST /api/v1/repositories/github`` (NOT the legacy
 *   ``POST /api/v1/repositories`` shape);
 * - render the same classified error taxonomy as
 *   ``/analyze`` via the shared
 *   ``intakeErrorTitleFor`` / ``intakeErrorDescriptionFor``
 *   helpers;
 * - render the ``internal_unexpected`` correlation id in
 *   the body line so the operator can grep the runtime
 *   log;
 * - never render the literal string "Unknown error.";
 * - never render the legacy generic "Server error" title
 *   when an ``internal_unexpected`` envelope is available;
 * - preserve the reset / retry behaviour (the submit
 *   button is re-enabled after an error).
 *
 * The legacy ``POST /repositories`` endpoint is still
 * exercised by the backend ``test_api_repositories.py``
 * tests; the frontend no longer calls it from the
 * bundled UI.
 */

import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { act, render, screen, waitFor, cleanup, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";

import { AppShell } from "@/layouts/AppShell";
import { NewRepositoryPage } from "@/pages/NewRepositoryPage";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function makeIntakeResult(overrides: {
  scanId?: number;
  repositoryId?: number;
} = {}) {
  const scanId = overrides.scanId ?? 12;
  const repositoryId = overrides.repositoryId ?? 7;
  return {
    repository: {
      id: repositoryId,
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
      id: scanId,
      repository_id: repositoryId,
      status: "queued",
      trigger_type: "manual",
      requested_ref: null,
      resolved_commit_sha: null,
      analyzer_version: "lockverity 2.1.1",
      started_at: null,
      completed_at: null,
      failure_code: null,
      failure_summary: null,
      created_at: "2026-07-18T00:00:00Z",
      updated_at: "2026-07-18T00:00:00Z",
    },
    workspace: {
      id: 1,
      scan_run_id: scanId,
      workspace_key: "wks-" + "a".repeat(32),
      kind: "github",
      state: "quarantined",
      archive_filename: "github/octocat/hello-world.tar.gz",
      archive_sha256: null,
      archive_size: 0,
      file_count: 0,
      uncompressed_size: 0,
      failure_code: null,
      failure_summary: null,
      ready_at: null,
      cleaned_up_at: null,
      created_at: "2026-07-18T00:00:00Z",
      updated_at: "2026-07-18T00:00:00Z",
    },
    intake_summary: {
      kind: "github",
      owner: "octocat",
      name: "hello-world",
    },
  };
}

function systemInfoResponse(): Response {
  return jsonResponse({
    name: "Lockverity",
    version: "2.1.1",
    tagline: "Evidence-first software supply-chain assurance",
    environment: "test",
    api_prefix: "/api/v1",
    archive_limits: {},
    pagination: {},
    provider_safety: {},
    intake: {},
  });
}

function renderNewRepositoryPage() {
  return render(
    <MemoryRouter initialEntries={["/repositories/new"]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/repositories/new" element={<NewRepositoryPage />} />
        </Route>
      </Routes>
    </MemoryRouter>
  );
}

describe("v2.1.1 /repositories/new unified intake error handling", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    cleanup();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("submits through the canonical GitHub intake endpoint (POST /repositories/github) and never the legacy POST /repositories", async () => {
    const fetchMock = vi.fn().mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/api/v1/system/info")) {
          return systemInfoResponse();
        }
        if (
          url.endsWith("/api/v1/repositories/github") &&
          init?.method === "POST"
        ) {
          return jsonResponse(makeIntakeResult({ scanId: 88 }), 201);
        }
        return jsonResponse({}, 404);
      }
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    renderNewRepositoryPage();

    const urlInput = screen.getByLabelText(/public github url/i);
    const submitButton = screen.getByRole("button", { name: /^add repository$/i });

    await act(async () => {
      fireEvent.change(urlInput, {
        target: { value: "https://github.com/octocat/hello-world" },
      });
    });
    await act(async () => {
      fireEvent.click(submitButton);
    });

    await waitFor(() => {
      const calls = fetchMock.mock.calls.filter((args) => {
        const u = args[0] as unknown;
        const init = args[1] as RequestInit | undefined;
        const url = typeof u === "string" ? u : (u as URL).toString();
        return (
          url.endsWith("/api/v1/repositories/github") &&
          init?.method === "POST"
        );
      });
      expect(calls.length).toBe(1);
    });

    // The page must NEVER call the legacy POST /repositories.
    const legacyCalls = fetchMock.mock.calls.filter((args) => {
      const u = args[0] as unknown;
      const init = args[1] as RequestInit | undefined;
      const url = typeof u === "string" ? u : (u as URL).toString();
      const path = url.split("?")[0] ?? url;
      return (
        path.endsWith("/api/v1/repositories") &&
        init?.method === "POST" &&
        !url.includes("/github") &&
        !url.includes("/upload")
      );
    });
    expect(legacyCalls.length).toBe(0);
  });

  it("renders the private / not_found actionable body for a 404 envelope", async () => {
    const fetchMock = vi.fn().mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/api/v1/system/info")) {
          return systemInfoResponse();
        }
        if (
          url.endsWith("/api/v1/repositories/github") &&
          init?.method === "POST"
        ) {
          return new Response(
            JSON.stringify({
              error: {
                code: "not_found",
                message:
                  "Repository could not be accessed. Confirm that the URL exists and is public. Private repositories are not supported in this version.",
              },
            }),
            { status: 404, headers: { "content-type": "application/json" } }
          );
        }
        return jsonResponse({}, 404);
      }
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    renderNewRepositoryPage();

    const urlInput = screen.getByLabelText(/public github url/i);
    const submitButton = screen.getByRole("button", { name: /^add repository$/i });

    await act(async () => {
      fireEvent.change(urlInput, {
        target: { value: "https://github.com/octocat/hello-world" },
      });
    });
    await act(async () => {
      fireEvent.click(submitButton);
    });

    await waitFor(() => {
      expect(
        screen.getByText(/Repository could not be accessed\./),
      ).toBeInTheDocument();
    });
    // The shared title for the not_found category.
    expect(
      screen.getByRole("heading", { name: /repository could not be accessed/i }),
    ).toBeInTheDocument();
    // Never literal "Unknown error.".
    expect(screen.queryByText(/Unknown error\./)).toBeNull();
    // Never literal "Upstream returned 404 Not Found".
    expect(screen.queryByText(/Upstream returned 404/i)).toBeNull();
  });

  it("renders the invalid_ref actionable body for a 422 envelope", async () => {
    const fetchMock = vi.fn().mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/api/v1/system/info")) {
          return systemInfoResponse();
        }
        if (
          url.endsWith("/api/v1/repositories/github") &&
          init?.method === "POST"
        ) {
          return new Response(
            JSON.stringify({
              error: {
                code: "invalid_ref",
                message:
                  "The requested branch, tag, or commit could not be found on the repository. Check the ref and try again.",
              },
            }),
            { status: 422, headers: { "content-type": "application/json" } }
          );
        }
        return jsonResponse({}, 404);
      }
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    renderNewRepositoryPage();

    const urlInput = screen.getByLabelText(/public github url/i);
    const refInput = screen.getByLabelText(/branch, tag, or commit/i);
    const submitButton = screen.getByRole("button", { name: /^add repository$/i });

    await act(async () => {
      fireEvent.change(urlInput, {
        target: { value: "https://github.com/octocat/hello-world" },
      });
    });
    await act(async () => {
      fireEvent.change(refInput, { target: { value: "definitely-not-a-real-branch" } });
    });
    await act(async () => {
      fireEvent.click(submitButton);
    });

    await waitFor(() => {
      expect(
        screen.getByText(/Check the ref and try again\./),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByRole("heading", {
        name: /the requested branch, tag, or commit was not found/i,
      }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Unknown error\./)).toBeNull();
  });

  it("renders the rate-limit body for a 429 envelope", async () => {
    const fetchMock = vi.fn().mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/api/v1/system/info")) {
          return systemInfoResponse();
        }
        if (
          url.endsWith("/api/v1/repositories/github") &&
          init?.method === "POST"
        ) {
          return new Response(
            JSON.stringify({
              error: {
                code: "rate_limited",
                message:
                  "GitHub rate limit reached. Wait a few minutes and retry.",
              },
            }),
            { status: 429, headers: { "content-type": "application/json" } }
          );
        }
        return jsonResponse({}, 404);
      }
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    renderNewRepositoryPage();

    const urlInput = screen.getByLabelText(/public github url/i);
    const submitButton = screen.getByRole("button", { name: /^add repository$/i });

    await act(async () => {
      fireEvent.change(urlInput, {
        target: { value: "https://github.com/octocat/hello-world" },
      });
    });
    await act(async () => {
      fireEvent.click(submitButton);
    });

    await waitFor(() => {
      // The title and the body both contain "rate limit
      // reached", so use getAllByText.
      expect(
        screen.getAllByText(/rate limit reached/i).length,
      ).toBeGreaterThanOrEqual(2);
    });
    expect(
      screen.getByRole("heading", { name: /github rate limit reached/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Unknown error\./)).toBeNull();
  });

  it("renders the internal_unexpected title and correlation-id body line for a 500 envelope", async () => {
    const cid = "0123456789abcdef";
    const fetchMock = vi.fn().mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/api/v1/system/info")) {
          return systemInfoResponse();
        }
        if (
          url.endsWith("/api/v1/repositories/github") &&
          init?.method === "POST"
        ) {
          return new Response(
            JSON.stringify({
              error: {
                code: "internal_unexpected",
                message:
                  "An internal error occurred. See Diagnostics for the correlation id and the runtime log for the full trace.",
                details: { correlation_id: cid, kind: "github" },
              },
            }),
            { status: 500, headers: { "content-type": "application/json" } }
          );
        }
        return jsonResponse({}, 404);
      }
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    renderNewRepositoryPage();

    const urlInput = screen.getByLabelText(/public github url/i);
    const submitButton = screen.getByRole("button", { name: /^add repository$/i });

    await act(async () => {
      fireEvent.change(urlInput, {
        target: { value: "https://github.com/octocat/hello-world" },
      });
    });
    await act(async () => {
      fireEvent.click(submitButton);
    });

    // Title is the canonical "An internal error occurred".
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: /^an internal error occurred$/i }),
      ).toBeInTheDocument();
    });
    // Body includes the safe backend message.
    expect(
      screen.getByText(
        /An internal error occurred\. See Diagnostics for the correlation id/,
      ),
    ).toBeInTheDocument();
    // Body includes the 16-character correlation id and the
    // diagnostic guidance.
    expect(
      screen.getByText(new RegExp(`Reference: ${cid}\\..*Open Diagnostics`)),
    ).toBeInTheDocument();
    // Never literal "Unknown error.".
    expect(screen.queryByText(/Unknown error\./)).toBeNull();
    // Never the legacy generic "Server error" title for
    // a classified internal_unexpected envelope.
    expect(
      screen.queryByRole("heading", { name: /^server error$/i }),
    ).toBeNull();
    // Never the raw traceback.
    expect(screen.queryByText(/Traceback/)).toBeNull();
    expect(screen.queryByText(/OperationalError/)).toBeNull();
    expect(screen.queryByText(/FileNotFoundError/)).toBeNull();
  });

  it("re-enables the submit button after an error so the user can retry", async () => {
    const fetchMock = vi.fn().mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/api/v1/system/info")) {
          return systemInfoResponse();
        }
        if (
          url.endsWith("/api/v1/repositories/github") &&
          init?.method === "POST"
        ) {
          return new Response(
            JSON.stringify({
              error: {
                code: "not_found",
                message: "Repository could not be accessed.",
              },
            }),
            { status: 404, headers: { "content-type": "application/json" } }
          );
        }
        return jsonResponse({}, 404);
      }
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    renderNewRepositoryPage();

    const urlInput = screen.getByLabelText(/public github url/i);
    const submitButton = screen.getByRole("button", { name: /^add repository$/i });

    await act(async () => {
      fireEvent.change(urlInput, {
        target: { value: "https://github.com/octocat/hello-world" },
      });
    });
    await act(async () => {
      fireEvent.click(submitButton);
    });

    await waitFor(() => {
      expect(
        screen.getByText(/Repository could not be accessed\./),
      ).toBeInTheDocument();
    });
    // The submit button is re-enabled after the error so
    // the operator can correct the URL and retry.
    expect(submitButton).not.toBeDisabled();

    // A second click issues a new POST to the same
    // canonical endpoint.
    await act(async () => {
      fireEvent.click(submitButton);
    });
    const calls = fetchMock.mock.calls.filter((args) => {
      const u = args[0] as unknown;
      const init = args[1] as RequestInit | undefined;
      const url = typeof u === "string" ? u : (u as URL).toString();
      return (
        url.endsWith("/api/v1/repositories/github") &&
        init?.method === "POST"
      );
    });
    expect(calls.length).toBe(2);
  });
});
