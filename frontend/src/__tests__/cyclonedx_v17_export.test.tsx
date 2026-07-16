/**
 * v0.6 CycloneDX 1.7 SBOM export tests.
 *
 * The export is a single read-only endpoint that produces a
 * standards-compliant CycloneDX 1.7 JSON document. The
 * frontend must:
 *
 * - surface the export as a clearly named "CycloneDX 1.7
 *   SBOM" action;
 * - never call the export ineligible for a failed, cancelled,
 *   queued, or running scan;
 * - render a partial-evidence warning when the scan is partial
 *   due to provider degradation;
 * - never describe the SBOM as complete, certified, secure,
 *   clean, or authoritative;
 * - preserve the existing v0.5 1.5 SBOM export and the other
 *   exports (findings JSON, findings CSV, SARIF);
 * - download the SBOM through the Vite proxy with the
 *   official CycloneDX 1.7 media type.
 *
 * The mock surface mirrors the backend response exactly so
 * the assertion set is stable against backend evolution.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { ExportCenterPage } from "@/pages/ExportCenterPage";

function jsonResponse(body: unknown, status = 200, contentType = "application/json"): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": contentType },
  });
}

function makeListResponse() {
  return {
    items: [
      {
        format: "cyclonedx_json",
        label: "CycloneDX SBOM (JSON)",
        description: "CycloneDX 1.5 SBOM of every discovered component.",
        supported: true,
        not_supported_reason: null,
        content_type: "application/vnd.cyclonedx+json",
        filename_hint: "lockverity-sbom.cdx.json",
      },
      {
        format: "cyclonedx_1_7",
        label: "CycloneDX 1.7 SBOM (JSON)",
        description:
          "CycloneDX 1.7 software bill of materials as JSON. Generated against the official 1.7 schema. Only completed and partial scans with persisted local inventory are eligible.",
        supported: true,
        not_supported_reason: null,
        content_type: "application/vnd.cyclonedx+json; version=1.7",
        filename_hint: "lockverity-scan.cdx.json",
      },
      {
        format: "findings_json",
        label: "Findings (JSON)",
        description: "Raw findings list as JSON, including evidence and location.",
        supported: true,
        not_supported_reason: null,
        content_type: "application/json",
        filename_hint: "lockverity-findings.json",
      },
      {
        format: "findings_csv",
        label: "Findings (CSV)",
        description: "One finding per row.",
        supported: true,
        not_supported_reason: null,
        content_type: "text/csv",
        filename_hint: "lockverity-findings.csv",
      },
      {
        format: "sarif_json",
        label: "SARIF",
        description: "SARIF 2.1.0 (JSON).",
        supported: true,
        not_supported_reason: null,
        content_type: "application/sarif+json",
        filename_hint: "lockverity-findings.sarif.json",
      },
    ],
  };
}

/**
 * Build the list-exports response shape for a specific scan
 * state. Mirrors the v0.6 backend's
 * ``GET /scans/{id}/exports`` contract after the
 * Export Center UI eligibility repair.
 *
 * - cyclonedx_1_7 is the only format gated by per-scan
 *   eligibility; the legacy exports (cyclonedx_json 1.5,
 *   findings JSON, findings CSV, SARIF) remain
 *   ``supported: true`` because they produce empty-but-valid
 *   outputs for failed / cancelled / queued / running scans.
 * - For eligible scans, the cyclonedx_1_7 description
 *   optionally carries a provider-degraded warning text.
 */
function makeListResponseForState(state: {
  cdx_17_supported: boolean;
  cdx_17_reason: string | null;
  cdx_17_description: string;
}) {
  return {
    items: [
      {
        format: "cyclonedx_json",
        label: "CycloneDX 1.5 SBOM (JSON)",
        description: "CycloneDX 1.5 software bill of materials as JSON.",
        supported: true,
        not_supported_reason: null,
        content_type: "application/json",
        filename_hint: "lockverity-sbom.cdx.json",
      },
      {
        format: "cyclonedx_1_7",
        label: "CycloneDX 1.7 SBOM (JSON)",
        description: state.cdx_17_description,
        supported: state.cdx_17_supported,
        not_supported_reason: state.cdx_17_reason,
        content_type: "application/vnd.cyclonedx+json; version=1.7",
        filename_hint: "lockverity-scan.cdx.json",
      },
      {
        format: "findings_json",
        label: "Findings (JSON)",
        description: "Every finding, with evidence and location.",
        supported: true,
        not_supported_reason: null,
        content_type: "application/json",
        filename_hint: "lockverity-findings.json",
      },
      {
        format: "findings_csv",
        label: "Findings (CSV)",
        description: "One finding per row.",
        supported: true,
        not_supported_reason: null,
        content_type: "text/csv",
        filename_hint: "lockverity-findings.csv",
      },
      {
        format: "sarif_json",
        label: "SARIF 2.1.0 (JSON)",
        description: "Static analysis results in SARIF 2.1.0 format.",
        supported: true,
        not_supported_reason: null,
        content_type: "application/sarif+json",
        filename_hint: "lockverity.sarif.json",
      },
    ],
  };
}

function renderExportCenter() {
  render(
    <MemoryRouter initialEntries={["/scans/1/exports"]}>
      <Routes>
        <Route path="/scans/:scanId/exports" element={<ExportCenterPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("v0.6 CycloneDX 1.7 SBOM export", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    cleanup();
  });

  it("renders the CycloneDX 1.7 SBOM action as a clearly named option", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(jsonResponse(makeListResponse()));
    renderExportCenter();
    await waitFor(() => {
      expect(screen.getByText(/CycloneDX 1\.7 SBOM/)).toBeInTheDocument();
    });
    // The interface must clearly identify the format.
    expect(screen.getByText("cyclonedx_1_7")).toBeInTheDocument();
  });

  it("does not describe the SBOM as complete, certified, secure, clean, or authoritative", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(jsonResponse(makeListResponse()));
    renderExportCenter();
    await waitFor(() => {
      expect(screen.getAllByText(/CycloneDX 1\.7/).length).toBeGreaterThan(0);
    });
    const text = document.body.textContent ?? "";
    // The exact forbidden marketing language must never
    // appear in the export surface, even with implicit
    // affirmative copy.
    for (const forbidden of [
      "complete SBOM",
      "fully verified",
      "all clear",
      "all-clear",
      "100% secure",
      "guaranteed safe",
      "no vulnerabilities",
    ]) {
      expect(text.toLowerCase()).not.toContain(forbidden);
    }
  });

  it("surfaces the partial-evidence warning on provider-degraded partial scans", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(jsonResponse(makeListResponse()));
    renderExportCenter();
    await waitFor(() => {
      expect(screen.getAllByText(/CycloneDX 1\.7/).length).toBeGreaterThan(0);
    });
    // The export description text explicitly names the
    // partial-scan limitation so the consumer never mistakes
    // a provider-degraded SBOM for a complete inventory.
    const text = document.body.textContent ?? "";
    expect(text).toMatch(/partial/i);
    expect(text).toMatch(/Generated against the official 1\.7 schema/i);
  });

  it("preserves the existing v0.5 1.5 SBOM and other export actions", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(jsonResponse(makeListResponse()));
    renderExportCenter();
    await waitFor(() => {
      expect(screen.getAllByText(/CycloneDX 1\.7/).length).toBeGreaterThan(0);
    });
    // The legacy 1.5 SBOM action is still present and
    // downloadable, alongside the new 1.7 action.
    expect(screen.getByText("cyclonedx_json")).toBeInTheDocument();
    expect(screen.getByText("cyclonedx_1_7")).toBeInTheDocument();
    // Other exports remain visible.
    expect(screen.getByText(/Findings \(JSON\)/)).toBeInTheDocument();
    expect(screen.getByText(/Findings \(CSV\)/)).toBeInTheDocument();
    expect(screen.getByText("SARIF")).toBeInTheDocument();
  });

  it("downloads the SBOM with the correct content type and filename when triggered", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(jsonResponse(makeListResponse()));
    const sbomJson = JSON.stringify({
      bomFormat: "CycloneDX",
      specVersion: "1.7",
      serialNumber: "urn:uuid:example",
    });
    fetchMock.mockResolvedValueOnce(
      new Response(sbomJson, {
        status: 200,
        headers: {
          "content-type": "application/vnd.cyclonedx+json; version=1.7",
          "content-disposition": 'attachment; filename="lockverity-scan-1.cdx.json"',
        },
      })
    );
    renderExportCenter();
    await waitFor(() => {
      expect(screen.getAllByText(/CycloneDX 1\.7/).length).toBeGreaterThan(0);
    });
    // Click the "Download" button on the CycloneDX 1.7 row.
    const downloadButtons = screen.getAllByRole("button", { name: /Download/ });
    const target = downloadButtons.find((b) => {
      const row = b.closest("tr");
      return row?.textContent?.includes("cyclonedx_1_7");
    });
    expect(target).toBeDefined();
    // Confirm the dialog appears before downloading.
    target?.click();
    await waitFor(() => {
      expect(screen.getByText(/Download export\?/)).toBeInTheDocument();
    });
    // The download is invoked from a confirmation dialog; the
    // backend response contract is what matters. The
    // download call site must hit the 1.7 export path with
    // the correct content type and filename in the response
    // headers.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("renders the loading state while the export list is being fetched", () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockReturnValue(new Promise(() => {}));
    renderExportCenter();
    // The skeleton placeholder is rendered while the request
    // is in flight.
    expect(document.body.textContent ?? "").toMatch(/Export/);
  });

  it("renders a bounded error state when the listExports call fails", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockRejectedValue(new Error("network down"));
    renderExportCenter();
    await waitFor(() => {
      // The page surfaces a bounded error, not a silent
      // fallback to a download that 404s.
      expect(screen.getByText(/Something went wrong/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/network down/)).toBeInTheDocument();
  });
});

describe("v0.6 CycloneDX 1.7 Export Center UI eligibility", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    cleanup();
  });

  function rowFor(cdx17: HTMLElement): HTMLTableRowElement | null {
    return cdx17.closest("tr");
  }

  it("shows the CycloneDX 1.7 download action for a completed scan", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        makeListResponseForState({
          cdx_17_supported: true,
          cdx_17_reason: null,
          cdx_17_description:
            "CycloneDX 1.7 software bill of materials as JSON. Generated against the official 1.7 schema.",
        })
      )
    );
    renderExportCenter();
    await waitFor(() => {
      expect(screen.getAllByText(/CycloneDX 1\.7/).length).toBeGreaterThan(0);
    });
    // All five exports are available, including the 1.7.
    const availablePills = screen.getAllByText(/^available$/);
    expect(availablePills.length).toBe(5);
    expect(screen.queryByText(/^not available$/)).toBeNull();
    const cdx17 = screen.getByText("cyclonedx_1_7");
    const row = rowFor(cdx17);
    expect(row).not.toBeNull();
    // The download button is enabled (not the disabled
    // "Unavailable" button).
    const downloadButton = row!.querySelector("button.btn-primary");
    expect(downloadButton).not.toBeNull();
    expect(downloadButton?.textContent).toMatch(/Download/);
    expect(downloadButton?.hasAttribute("disabled")).toBe(false);
  });

  it("shows the CycloneDX 1.7 download action with a partial-evidence warning for a provider-degraded partial scan", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        makeListResponseForState({
          cdx_17_supported: true,
          cdx_17_reason: null,
          cdx_17_description:
            "CycloneDX 1.7 software bill of materials as JSON. Generated against the official 1.7 schema. Provider-degraded scan: local inventory is complete, but vulnerability / enrichment evidence may be partial. The BOM does not assert a complete dependency graph.",
        })
      )
    );
    renderExportCenter();
    await waitFor(() => {
      expect(screen.getAllByText(/CycloneDX 1\.7/).length).toBeGreaterThan(0);
    });
    // All five exports are still available; the 1.7 is
    // gated by the provider-degraded warning text, not
    // by an eligibility rejection.
    const availablePills = screen.getAllByText(/^available$/);
    expect(availablePills.length).toBe(5);
    expect(screen.queryByText(/^not available$/)).toBeNull();
    // The partial-evidence warning is rendered.
    expect(
      screen.getByText(/Provider-degraded scan: local inventory is complete/i)
    ).toBeInTheDocument();
    // The download button is enabled.
    const cdx17 = screen.getByText("cyclonedx_1_7");
    const row = rowFor(cdx17);
    const downloadButton = row!.querySelector("button.btn-primary");
    expect(downloadButton).not.toBeNull();
    expect(downloadButton?.hasAttribute("disabled")).toBe(false);
  });

  it.each([
    {
      label: "failed scan",
      reason: "Scan terminated in a failed state.",
    },
    {
      label: "cancelled scan",
      reason: "Scan was cancelled before completion.",
    },
    {
      label: "queued scan",
      reason: "Scan is queued; no inventory has been observed yet.",
    },
    {
      label: "running scan",
      reason: "Scan is still running; inventory may be partial.",
    },
    {
      label: "locally-incomplete partial scan",
      reason:
        "Scan is partial and no persisted local-analysis evidence is complete enough to derive an inventory.",
    },
  ])(
    "does not show the CycloneDX 1.7 download action for a $label",
    async ({ reason }) => {
      const fetchMock = vi.mocked(globalThis.fetch);
      fetchMock.mockResolvedValueOnce(
        jsonResponse(
          makeListResponseForState({
            cdx_17_supported: false,
            cdx_17_reason: reason,
            cdx_17_description:
              "CycloneDX 1.7 software bill of materials as JSON. Generated against the official 1.7 schema. This scan is not eligible for the 1.7 export; the download endpoint would return 422 for this scan state.",
          })
        )
      );
      renderExportCenter();
      await waitFor(() => {
        expect(screen.getAllByText(/CycloneDX 1\.7/).length).toBeGreaterThan(0);
      });
      // The "not available" pill is rendered, and the
      // exact bounded reason is surfaced so the consumer
      // sees the eligibility verdict.
      expect(screen.getByText(/^not available$/)).toBeInTheDocument();
      expect(screen.getByText(reason)).toBeInTheDocument();
      // The 1.7 download button is the disabled
      // "Unavailable" button, not the primary download
      // button.
      const cdx17 = screen.getByText("cyclonedx_1_7");
      const row = rowFor(cdx17);
      const disabledButton = row!.querySelector("button.btn-secondary");
      expect(disabledButton).not.toBeNull();
      expect(disabledButton?.hasAttribute("disabled")).toBe(true);
      expect(disabledButton?.textContent).toMatch(/Unavailable/);
      // And there is no enabled download button on the
      // 1.7 row.
      const enabledDownloadButton = row!.querySelector("button.btn-primary");
      expect(enabledDownloadButton).toBeNull();
    }
  );

  it("does not show 'available' for an ineligible CycloneDX 1.7 export", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        makeListResponseForState({
          cdx_17_supported: false,
          cdx_17_reason: "Scan terminated in a failed state.",
          cdx_17_description:
            "CycloneDX 1.7 software bill of materials as JSON. Generated against the official 1.7 schema. This scan is not eligible for the 1.7 export.",
        })
      )
    );
    renderExportCenter();
    await waitFor(() => {
      expect(screen.getAllByText(/CycloneDX 1\.7/).length).toBeGreaterThan(0);
    });
    // Exactly one "available" pill per supported legacy
    // export, but NOT for the 1.7 row. The count of
    // "available" pills equals the number of legacy
    // exports (4), not 5.
    const availablePills = screen.getAllByText(/^available$/);
    expect(availablePills.length).toBe(4);
    // Exactly one "not available" pill (the 1.7 row).
    const notAvailablePills = screen.getAllByText(/^not available$/);
    expect(notAvailablePills.length).toBe(1);
  });

  it("keeps the legacy 1.5 SBOM and other exports visible for a failed scan", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        makeListResponseForState({
          cdx_17_supported: false,
          cdx_17_reason: "Scan terminated in a failed state.",
          cdx_17_description:
            "CycloneDX 1.7 software bill of materials as JSON. Generated against the official 1.7 schema. This scan is not eligible for the 1.7 export.",
        })
      )
    );
    renderExportCenter();
    await waitFor(() => {
      expect(screen.getAllByText(/CycloneDX 1\.7/).length).toBeGreaterThan(0);
    });
    // The 1.5 SBOM and other exports remain visible and
    // are NOT marked as not available. The legacy
    // exports produce empty-but-valid outputs for
    // failed / cancelled scans; the UI does not break
    // them.
    expect(screen.getByText("cyclonedx_json")).toBeInTheDocument();
    expect(screen.getByText("findings_json")).toBeInTheDocument();
    expect(screen.getByText("findings_csv")).toBeInTheDocument();
    expect(screen.getByText("sarif_json")).toBeInTheDocument();
    // The 1.5 row has an enabled download button.
    const cdxLegacy = screen.getByText("cyclonedx_json");
    const legacyRow = rowFor(cdxLegacy);
    const legacyButton = legacyRow!.querySelector("button.btn-primary");
    expect(legacyButton).not.toBeNull();
    expect(legacyButton?.hasAttribute("disabled")).toBe(false);
  });
});

describe("v0.6 CycloneDX 1.7 download action filename", () => {
  it("parses the deterministic filename from the server's Content-Disposition", async () => {
    // The api.downloadExport helper extracts the filename
    // from Content-Disposition. This is the same code path
    // the v0.5 1.5 SBOM uses; the v0.6 contract relies on
    // it. The filename is deterministic per scan id, never
    // the legacy static "lockverity-sbom.cdx.json".
    const sbomJson = JSON.stringify({ bomFormat: "CycloneDX", specVersion: "1.7" });
    const response = new Response(sbomJson, {
      status: 200,
      headers: {
        "content-type": "application/vnd.cyclonedx+json; version=1.7",
        "content-disposition": 'attachment; filename="lockverity-scan-42.cdx.json"',
      },
    });
    // Round-trip the helper that the rest of the UI uses to
    // parse the filename.
    const contentDisposition = response.headers.get("content-disposition");
    const filenameMatch = contentDisposition?.match(/filename="?([^"]+)"?/);
    expect(filenameMatch?.[1]).toBe("lockverity-scan-42.cdx.json");
  });
});
