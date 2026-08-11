import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router";

import { OpenSSFPosturePage } from "@/pages/OpenSSFPosturePage";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function observation(errorCode: "disabled_by_operator" | "not_applicable") {
  return {
    items: [
      {
        id: 1,
        scan_run_id: 1,
        provider: "openssf",
        status: "not_requested",
        requested_at: null,
        completed_at: null,
        latency_ms: null,
        http_status: null,
        cache_status: null,
        records_returned: 0,
        error_code: errorCode,
        error_summary: null,
        retry_count: 0,
        rate_limit_remaining: null,
        fetched_at: null,
        created_at: "2026-08-11T00:00:00Z",
      },
    ],
    pagination: { page: 1, page_size: 200, total: 1, total_pages: 1 },
  };
}

function renderOpenSSF(errorCode: "disabled_by_operator" | "not_applicable") {
  const fetchMock = vi.fn();
  fetchMock.mockResolvedValueOnce(jsonResponse(observation(errorCode)));
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      items: [],
      pagination: { page: 1, page_size: 25, total: 0, total_pages: 0 },
    })
  );
  vi.stubGlobal("fetch", fetchMock);
  render(
    <MemoryRouter initialEntries={["/scans/1/openssf"]}>
      <Routes>
        <Route path="/scans/:scanId/openssf" element={<OpenSSFPosturePage />} />
      </Routes>
    </MemoryRouter>
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  cleanup();
});

describe("provider-disabled result surfaces", () => {
  it("renders operator-disabled OpenSSF as a neutral not-requested state", async () => {
    renderOpenSSF("disabled_by_operator");
    await waitFor(() => {
      expect(
        screen.getByText(/OpenSSF Scorecard was not requested/i)
      ).toBeInTheDocument();
    });
    expect(screen.queryByText(/provider unavailable/i)).not.toBeInTheDocument();
  });

  it("keeps archive not-applicable distinct from operator disabled", async () => {
    renderOpenSSF("not_applicable");
    await waitFor(() => {
      expect(
        screen.getByText(/OpenSSF Scorecard is not applicable/i)
      ).toBeInTheDocument();
    });
    expect(screen.queryByText(/disabled by the operator/i)).not.toBeInTheDocument();
  });
});
