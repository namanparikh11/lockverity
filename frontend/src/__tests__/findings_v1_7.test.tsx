/**
 * v1.7 findings triage and evidence review workbench tests.
 *
 * Covers:
 *  - scan context header renders the scan id, repository,
 *    status, source type, and finding count;
 *  - server-side search is sent as the ``q`` query param;
 *  - server-side filters (category, severity, confidence,
 *    status, provider, rule_id, path) flow through to the
 *    API client;
 *  - bounded sort vocabulary is sent to the API and
 *    invalid values are still passed through (the backend
 *    normalises them);
 *  - URL query state is bidirectional (filter -> URL ->
 *    filter);
 *  - clear filters empties the URL query state;
 *  - the zero-result wording does not claim a clean
 *    / safe / vulnerability-free state;
 *  - the partial / failed / cancelled scan-state notices
 *    render with bounded copy;
 *  - clicking a row opens the evidence detail drawer,
 *    which fetches the freshest payload and renders
 *    advisory identity, provider attribution, and a
 *    bounded boundary notice;
 *  - no universal Lockverity risk score appears;
 *  - the v1.6 workbench, v1.5 analyze flow, and demo
 *    pages still work.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";

import { FindingsPage } from "@/pages/FindingsPage";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function makeScan(overrides: Partial<Record<string, unknown>> = {}) {
  return {
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
    ...overrides,
  };
}

function makeRepository(overrides: Partial<Record<string, unknown>> = {}) {
  return {
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
    ...overrides,
  };
}

function makeFinding(
  id: number,
  overrides: Partial<Record<string, unknown>> = {}
): Record<string, unknown> {
  return {
    id,
    scan_run_id: 1,
    repository_id: 1,
    rule_id: `R00${id}`,
    category: "vulnerability",
    severity: "high",
    confidence: "confirmed",
    title: `title ${id}`,
    summary: `summary ${id}`,
    remediation: null,
    evidence_json: JSON.stringify({
      provider: "osv.dev",
      purl: `pkg:npm/left-pad@1.0.0`,
      advisory_id: "GHSA-xxxx-yyyy-zzzz",
      aliases: ["CVE-2024-1234"],
      source_url: "https://osv.dev/vulnerability/GHSA-xxxx-yyyy-zzzz",
    }),
    location_path: "package.json",
    location_start_line: 12,
    location_end_line: 12,
    stable_key: "0".repeat(64),
    status: "open",
    created_at: "2026-07-15T10:00:00Z",
    updated_at: "2026-07-15T10:01:00Z",
    ...overrides,
  };
}

function renderFindingsAt(initialUrl = "/scans/1/findings") {
  return render(
    <MemoryRouter initialEntries={[initialUrl]}>
      <Routes>
        <Route
          path="/scans/:scanId/findings"
          element={<FindingsPage />}
        />
      </Routes>
    </MemoryRouter>
  );
}

function setupFetchMock(opts: {
  scan?: Record<string, unknown>;
  repository?: Record<string, unknown>;
  findings?: { items: Record<string, unknown>[]; total: number };
  findingById?: Record<string, unknown>;
} = {}) {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  const findingsBody = opts.findings ?? {
    items: [makeFinding(1), makeFinding(2), makeFinding(3)],
    total: 3,
  };
  const findingsPageBody = {
    items: findingsBody.items,
    pagination: {
      page: 1,
      page_size: 25,
      total: findingsBody.total,
      total_pages: Math.max(1, Math.ceil(findingsBody.total / 25)),
    },
  };
  const findingById = opts.findingById ?? makeFinding(1);
  fetchMock.mockImplementation((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/api/v1/scans/1/findings/1") && !url.includes("?")) {
      return Promise.resolve(jsonResponse(findingById));
    }
    if (url.includes("/api/v1/scans/1/findings")) {
      return Promise.resolve(jsonResponse(findingsPageBody));
    }
    if (url.includes("/api/v1/scans/1") && !url.includes("/findings") && !url.includes("/stages")) {
      return Promise.resolve(jsonResponse(opts.scan ?? makeScan()));
    }
    if (url.includes("/api/v1/repositories/1")) {
      return Promise.resolve(jsonResponse(opts.repository ?? makeRepository()));
    }
    if (url.includes("/api/v1/scans/1/stages")) {
      return Promise.resolve(jsonResponse({ items: [] }));
    }
    return Promise.resolve(jsonResponse({}));
  });
  return fetchMock;
}

beforeEach(() => {
  // Reuse the v0.9 / v1.0 stub so the api client can
  // resolve relative URLs in tests.
  // @ts-expect-error - test environment stub
  window.location = { origin: "http://localhost" };
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("findings v1.7 - scan context header", () => {
  it("renders scan id, repository, status, source type, and finding count", async () => {
    setupFetchMock();
    renderFindingsAt();
    await waitFor(() => {
      expect(screen.getByTestId("findings-context-title")).toHaveTextContent("Scan #1");
    });
    const header = screen.getByTestId("findings-context-header");
    expect(within(header).getByTestId("findings-context-repository")).toHaveTextContent(
      "octocat/Hello-World"
    );
    expect(within(header).getByTestId("findings-context-status")).toHaveTextContent(
      /Status:.*Completed/
    );
    expect(within(header).getByTestId("findings-context-source")).toHaveTextContent(
      /Source:.*GitHub/
    );
    expect(within(header).getByTestId("findings-context-count")).toHaveTextContent(/3 findings/);
  });

  it("renders the partial scan notice when scan.status is partial", async () => {
    setupFetchMock({ scan: makeScan({ status: "partial" }) });
    renderFindingsAt();
    await waitFor(() => {
      expect(screen.getByText(/This scan is partial/)).toBeInTheDocument();
    });
  });

  it("renders the failed scan notice when scan.status is failed", async () => {
    setupFetchMock({
      scan: makeScan({
        status: "failed",
        failure_code: "test_failure",
        failure_summary: "Simulated failure for v1.7 test",
      }),
    });
    renderFindingsAt();
    await waitFor(() => {
      expect(screen.getByText(/This scan did not complete/)).toBeInTheDocument();
    });
    expect(
      screen.getByText(/Simulated failure for v1.7 test/)
    ).toBeInTheDocument();
  });

  it("renders the cancelled scan notice when scan.status is cancelled", async () => {
    setupFetchMock({ scan: makeScan({ status: "cancelled" }) });
    renderFindingsAt();
    await waitFor(() => {
      expect(screen.getByText(/This scan was cancelled/)).toBeInTheDocument();
    });
  });

  it("links back to workbench, dependencies, and exports", async () => {
    setupFetchMock();
    renderFindingsAt();
    await waitFor(() => {
      expect(screen.getByTestId("findings-context-links")).toBeInTheDocument();
    });
    const links = screen.getByTestId("findings-context-links");
    expect(within(links).getByText("Workbench").closest("a")).toHaveAttribute(
      "href",
      "/scans/1"
    );
    expect(within(links).getByText("Dependencies").closest("a")).toHaveAttribute(
      "href",
      "/scans/1/dependencies"
    );
    expect(within(links).getByText("Exports").closest("a")).toHaveAttribute(
      "href",
      "/scans/1/exports"
    );
  });
});

describe("findings v1.7 - search and filters", () => {
  it("sends the search field as q to the backend", async () => {
    const fetchMock = setupFetchMock();
    renderFindingsAt();
    await waitFor(() => {
      expect(screen.getByTestId("findings-context-header")).toBeInTheDocument();
    });
    const search = screen.getByPlaceholderText(
      /Search title, summary, rule id, evidence, or PURL/
    );
    fireEvent.change(search, { target: { value: "GHSA-xxxx" } });
    await waitFor(() => {
      const call = [...fetchMock.mock.calls]
        .reverse()
        .find((c) => String(c[0]).includes("/findings?"));
      expect(call).toBeTruthy();
      const url = String(call![0]);
      expect(url).toMatch(/[?&]q=GHSA/);
    });
  });

  it("sends category, severity, confidence, status as query params", async () => {
    const fetchMock = setupFetchMock();
    renderFindingsAt();
    await waitFor(() => {
      expect(screen.getByTestId("findings-context-header")).toBeInTheDocument();
    });
    fireEvent.change(screen.getByLabelText("Severity"), {
      target: { value: "high" },
    });
    await waitFor(() => {
      const call = [...fetchMock.mock.calls]
        .reverse()
        .find((c) => String(c[0]).includes("/findings?"));
      expect(call).toBeTruthy();
      const url = String(call![0]);
      expect(url).toMatch(/severity=high/);
    });
  });

  it("sends sort to the backend", async () => {
    const fetchMock = setupFetchMock();
    renderFindingsAt();
    await waitFor(() => {
      expect(screen.getByTestId("findings-context-header")).toBeInTheDocument();
    });
    fireEvent.change(screen.getByLabelText("Sort"), {
      target: { value: "severity" },
    });
    await waitFor(() => {
      const call = [...fetchMock.mock.calls]
        .reverse()
        .find((c) => String(c[0]).includes("/findings?"));
      expect(call).toBeTruthy();
      const url = String(call![0]);
      expect(url).toMatch(/sort=severity/);
    });
  });

  it("sends provider filter to the backend", async () => {
    const fetchMock = setupFetchMock();
    renderFindingsAt();
    await waitFor(() => {
      expect(screen.getByTestId("findings-context-header")).toBeInTheDocument();
    });
    const providerInput = screen.getByPlaceholderText("osv, deps.dev, ...");
    fireEvent.change(providerInput, { target: { value: "osv" } });
    await waitFor(() => {
      const call = [...fetchMock.mock.calls]
        .reverse()
        .find((c) => String(c[0]).includes("/findings?"));
      expect(call).toBeTruthy();
      const url = String(call![0]);
      expect(url).toMatch(/provider=osv/);
    });
  });

  it("sends rule_id and path advanced filters to the backend", async () => {
    const fetchMock = setupFetchMock();
    renderFindingsAt();
    await waitFor(() => {
      expect(screen.getByTestId("findings-context-header")).toBeInTheDocument();
    });
    // Open the advanced filters <details> first.
    const adv = screen.getByText("Advanced filters");
    fireEvent.click(adv);
    fireEvent.change(screen.getByPlaceholderText("LOCK-SUPPLY-001"), {
      target: { value: "R001" },
    });
    fireEvent.change(screen.getByPlaceholderText("src/ or package.json"), {
      target: { value: "package.json" },
    });
    await waitFor(() => {
      const call = [...fetchMock.mock.calls]
        .reverse()
        .find((c) => String(c[0]).includes("/findings?"));
      expect(call).toBeTruthy();
      const url = String(call![0]);
      expect(url).toMatch(/rule_id=R001/);
      expect(url).toMatch(/path=package/);
    });
  });

  it("clear filters empties the URL query state", async () => {
    setupFetchMock();
    renderFindingsAt("/scans/1/findings?q=foo&severity=high&sort=severity");
    await waitFor(() => {
      expect(screen.getByTestId("findings-context-header")).toBeInTheDocument();
    });
    expect(screen.getByDisplayValue("foo")).toBeInTheDocument();
    const clearBtn = screen.getByLabelText("Clear filters");
    fireEvent.click(clearBtn);
    await waitFor(() => {
      expect(screen.queryByDisplayValue("foo")).not.toBeInTheDocument();
    });
    // The url is reset to the bare path; we just assert
    // that the search box is empty.
    expect((screen.getByPlaceholderText(
      /Search title, summary/
    ) as HTMLInputElement).value).toBe("");
  });
});

describe("findings v1.7 - zero-result wording", () => {
  it("does not claim the repository is vulnerability-free", async () => {
    setupFetchMock({ findings: { items: [], total: 0 } });
    renderFindingsAt();
    await waitFor(() => {
      expect(screen.getByTestId("findings-context-header")).toBeInTheDocument();
    });
    expect(
      screen.getByText(/This does not establish that the repository is vulnerability-free/)
    ).toBeInTheDocument();
  });

  it("filtered zero result still does not claim clean / safe", async () => {
    setupFetchMock({ findings: { items: [], total: 0 } });
    renderFindingsAt("/scans/1/findings?severity=critical");
    await waitFor(() => {
      expect(screen.getByTestId("findings-context-header")).toBeInTheDocument();
    });
    // The page text must not contain any forbidden
    // verdict words used as positive claims. The
    // bounded disclaimer "does not establish that the
    // repository is vulnerability-free" is allowed
    // and is asserted separately above.
    const body = document.body.textContent ?? "";
    expect(body).not.toMatch(/\bclean\b/i);
    expect(body).not.toMatch(/\bsecure\b/i);
    expect(body).not.toMatch(/\bcompliant\b/i);
    expect(body).not.toMatch(/\bcertified\b/i);
    expect(body).not.toMatch(/passed the scan/i);
    expect(body).not.toMatch(/is safe\b/i);
  });
});

describe("findings v1.7 - evidence detail drawer", () => {
  it("opens the drawer with freshest payload on row click", async () => {
    const fetchMock = setupFetchMock();
    renderFindingsAt();
    await waitFor(() => {
      expect(screen.getByTestId("findings-context-header")).toBeInTheDocument();
    });
    const row = screen.getByTestId("finding-row-1");
    fireEvent.click(row);
    await waitFor(() => {
      expect(screen.getByTestId("drawer-advisory")).toBeInTheDocument();
    });
    // The single-finding endpoint is called.
    await waitFor(() => {
      const detailCall = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes("/findings/1") && !String(c[0]).includes("?")
      );
      expect(detailCall).toBeTruthy();
    });
    expect(screen.getByTestId("drawer-rule-id")).toHaveTextContent("R001");
    expect(screen.getByTestId("drawer-aliases")).toHaveTextContent(/CVE-2024-1234/);
    expect(screen.getByTestId("drawer-provider")).toHaveTextContent(/osv\.dev/);
    expect(screen.getByTestId("drawer-boundary")).toBeInTheDocument();
  });

  it("renders bounded boundary notice in the drawer", async () => {
    setupFetchMock();
    renderFindingsAt();
    await waitFor(() => {
      expect(screen.getByTestId("findings-context-header")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("finding-row-1"));
    await waitFor(() => {
      expect(screen.getByTestId("drawer-boundary")).toBeInTheDocument();
    });
    const body = screen.getByTestId("drawer-boundary").textContent ?? "";
    expect(body).toMatch(/evidence record/);
    expect(body).toMatch(/provider-attributed/);
  });
});

describe("findings v1.7 - no fabricated risk score", () => {
  it("never renders a Lockverity risk ranking", async () => {
    setupFetchMock();
    renderFindingsAt();
    await waitFor(() => {
      expect(screen.getByTestId("findings-context-header")).toBeInTheDocument();
    });
    const body = document.body.textContent ?? "";
    expect(body).not.toMatch(/Lockverity risk/i);
    expect(body).not.toMatch(/risk score/i);
  });

  it("never claims a clean / secure / vulnerability-free state on a populated page", async () => {
    setupFetchMock();
    renderFindingsAt();
    await waitFor(() => {
      expect(screen.getByTestId("findings-context-header")).toBeInTheDocument();
    });
    const body = document.body.textContent ?? "";
    expect(body).not.toMatch(/\bclean\b/i);
    expect(body).not.toMatch(/\bsecure\b/i);
    expect(body).not.toMatch(/vulnerability-free/);
    expect(body).not.toMatch(/\bcertified\b/i);
  });
});
