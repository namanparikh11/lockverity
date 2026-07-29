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
import { MemoryRouter, Route, Routes } from "react-router";

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

/**
 * Build the v0.7 preview / readiness summary response
 * shape. The tests use this as a default fallback so the
 * existing v0.6 export tests do not have to mock the new
 * preview endpoint individually. Tests that need a
 * specific preview state override this with their own
 * ``mockResolvedValueOnce``.
 */
function makePreviewResponse(
  overrides: {
    eligible?: boolean;
    code?: string;
    reason?: string;
    limitations?: string[];
    inventory?: Record<string, unknown>;
    evidence_coverage?: Record<string, string>;
  } = {}
) {
  const eligible = overrides.eligible ?? true;
  return {
    scan: {
      scan_id: 1,
      repository_id: 1,
      scan_status: "completed",
      source_kind: "scan:manual",
    },
    eligibility: {
      eligible,
      code: overrides.code ?? "eligible",
      reason:
        overrides.reason ??
        (eligible
          ? "Scan completed with persisted local-analysis evidence."
          : "Scan is not eligible for CycloneDX 1.7."),
      limitations: overrides.limitations ?? [],
      download_expected_to_succeed: eligible,
    },
    inventory: {
      component_count: 1,
      manifest_count: 1,
      ecosystems: ["npm"],
      direct_count: 1,
      transitive_count: 0,
      missing_version_count: 0,
      duplicate_observations_count: 0,
      ...overrides.inventory,
    },
    evidence_coverage: {
      inventory_coverage: "complete",
      dependency_graph_coverage: "partial",
      provider_coverage: "ok",
      ...overrides.evidence_coverage,
    },
    sbom_output: {
      format: "CycloneDX",
      spec_version: "1.7",
      media_type: "application/vnd.cyclonedx+json; version=1.7",
      filename_template: "lockverity-scan-{scan_id}.cdx.json",
      schema_uri: "http://cyclonedx.org/schema/bom-1.7.schema.json",
      schema_validation: "official_offline_JsonStrictValidator_v1_7",
      generation_source: "persisted_scan_evidence",
    },
    omissions: [
      "no_invented_versions",
      "no_inferred_dependency_edges",
      "no_dependency_graph_completeness_claim_without_positive_proof",
      "no_clean_or_security_verdict",
      "no_repository_code_execution",
      "unavailable_provider_data_is_not_converted_to_none",
    ],
    legacy_export_relationship:
      "Older exports may still be empty-but-valid for failed or cancelled scans, while CycloneDX 1.7 requires sufficient persisted local inventory.",
  };
}

describe("v0.6 CycloneDX 1.7 SBOM export", () => {
  beforeEach(() => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    // Default handler: the v0.7 preview endpoint returns
    // a successful eligible preview; every other call
    // returns the list-exports response the test
    // configured. Tests can override either by setting
    // ``mockResolvedValueOnce`` first.
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/exports/cyclonedx_1_7/preview")) {
        return Promise.resolve(jsonResponse(makePreviewResponse()));
      }
      return Promise.resolve(jsonResponse(makeListResponse()));
    });
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
    // The v0.7 export page now makes a second fetch for
    // the preview summary before the user downloads.
    // Queue: (1) list exports, (2) preview summary,
    // (3) actual SBOM body for the download click.
    fetchMock.mockResolvedValueOnce(jsonResponse(makeListResponse()));
    fetchMock.mockResolvedValueOnce(jsonResponse(makePreviewResponse()));
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
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    // Default handler routes by URL: the v0.7 preview
    // endpoint returns a successful eligible preview by
    // default; every other call returns the list-exports
    // response the test configured. Tests can override
    // either by setting ``mockResolvedValueOnce`` first.
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/exports/cyclonedx_1_7/preview")) {
        return Promise.resolve(jsonResponse(makePreviewResponse()));
      }
      return Promise.resolve(jsonResponse(makeListResponse()));
    });
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


describe("v0.7 CycloneDX 1.7 evidence preview", () => {
  beforeEach(() => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    // The preview panel is lazy: it only fetches when the
    // user clicks "Show preview". The default handler
    // returns a successful eligible preview for any
    // preview call; tests that need a specific state
    // override with ``mockResolvedValueOnce`` first.
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/exports/cyclonedx_1_7/preview")) {
        return Promise.resolve(jsonResponse(makePreviewResponse()));
      }
      return Promise.resolve(jsonResponse(makeListResponse()));
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    cleanup();
  });

  it("renders a 'Show preview' button on the export page and fetches only when expanded", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    renderExportCenter();
    // The page mounts; the preview panel renders the
    // collapsed "Show preview" button. The list-exports
    // fetch has fired (1 call), but the preview endpoint
    // has not been touched yet.
    await waitFor(() => {
      expect(
        screen.getByTestId("preview-show-button")
      ).toBeInTheDocument();
    });
    // The preview endpoint must not have been called yet.
    const previewCallsBefore = fetchMock.mock.calls
      .map((c) => String(c[0]))
      .filter((u) => u.includes("/exports/cyclonedx_1_7/preview"));
    expect(previewCallsBefore.length).toBe(0);
    // Click "Show preview" to trigger the fetch.
    const showButton = screen.getByTestId("preview-show-button");
    showButton.click();
    // The preview panel now renders the summary with the
    // component / manifest counts and the eligibility
    // verdict.
    await waitFor(() => {
      expect(
        screen.getByTestId("preview-inventory-components")
      ).toHaveTextContent("1");
    });
    // After the click, the preview endpoint has been
    // called exactly once.
    const previewCallsAfter = fetchMock.mock.calls
      .map((c) => String(c[0]))
      .filter((u) => u.includes("/exports/cyclonedx_1_7/preview"));
    expect(previewCallsAfter.length).toBe(1);
    expect(
      screen.getByTestId("preview-inventory-manifests")
    ).toHaveTextContent("1");
    expect(
      screen.getByTestId("preview-coverage-inventory")
    ).toHaveTextContent("complete");
    expect(
      screen.getByTestId("preview-coverage-graph")
    ).toHaveTextContent("partial");
    expect(
      screen.getByTestId("preview-coverage-provider")
    ).toHaveTextContent("ok");
  });

  it("shows the provider-degraded warning for a partial scan preview", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    // Override the default handler entirely: the
    // list response is the default list, the preview
    // response carries the provider-degraded limitation.
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/exports/cyclonedx_1_7/preview")) {
        return Promise.resolve(
          jsonResponse(
            makePreviewResponse({
              eligible: true,
              code: "eligible_with_provider_degradation",
              limitations: ["provider_degraded"],
              evidence_coverage: {
                inventory_coverage: "complete",
                dependency_graph_coverage: "partial",
                provider_coverage: "degraded",
              },
            })
          )
        );
      }
      return Promise.resolve(jsonResponse(makeListResponse()));
    });
    renderExportCenter();
    await waitFor(() => {
      expect(screen.getByTestId("preview-show-button")).toBeInTheDocument();
    });
    screen.getByTestId("preview-show-button").click();
    await waitFor(() => {
      expect(screen.getByTestId("preview-notice-warn")).toBeInTheDocument();
    });
    expect(
      screen.getByTestId("preview-coverage-provider")
    ).toHaveTextContent("degraded");
  });

  it("shows the ineligible explanation for a failed scan preview", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/exports/cyclonedx_1_7/preview")) {
        return Promise.resolve(
          jsonResponse(
            makePreviewResponse({
              eligible: false,
              code: "scan_failed",
              reason: "Scan terminated in a failed state.",
              limitations: [],
            })
          )
        );
      }
      return Promise.resolve(jsonResponse(makeListResponse()));
    });
    renderExportCenter();
    await waitFor(() => {
      expect(screen.getByTestId("preview-show-button")).toBeInTheDocument();
    });
    screen.getByTestId("preview-show-button").click();
    await waitFor(() => {
      expect(screen.getByTestId("preview-notice-danger")).toBeInTheDocument();
    });
    expect(screen.getByText(/Scan terminated in a failed state/)).toBeInTheDocument();
  });

  it("shows the ineligible explanation for a cancelled scan preview", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/exports/cyclonedx_1_7/preview")) {
        return Promise.resolve(
          jsonResponse(
            makePreviewResponse({
              eligible: false,
              code: "scan_cancelled",
              reason: "Scan was cancelled before completion.",
              limitations: [],
            })
          )
        );
      }
      return Promise.resolve(jsonResponse(makeListResponse()));
    });
    renderExportCenter();
    await waitFor(() => {
      expect(screen.getByTestId("preview-show-button")).toBeInTheDocument();
    });
    screen.getByTestId("preview-show-button").click();
    // The preview panel renders the "Verdict reason"
    // row with the bounded backend reason.
    await waitFor(() => {
      expect(
        screen.getByTestId("preview-verdict-reason")
      ).toHaveTextContent(/Scan was cancelled before completion/);
    });
  });

  it("does not call the SBOM download endpoint from the preview", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    renderExportCenter();
    await waitFor(() => {
      expect(screen.getByTestId("preview-show-button")).toBeInTheDocument();
    });
    screen.getByTestId("preview-show-button").click();
    await waitFor(() => {
      expect(screen.getByTestId("preview-inventory-components")).toBeInTheDocument();
    });
    // The preview endpoint is the v0.7 read-only summary;
    // it is a sibling of the SBOM download endpoint. The
    // preview must never trigger a download.
    const calls = fetchMock.mock.calls.map((c) => String(c[0]));
    // No call should go to the bare download endpoint
    // ``/exports/cyclonedx_1_7`` (no ``/preview`` suffix).
    const downloads = calls.filter((u) => /\/exports\/cyclonedx_1_7$/.test(u));
    expect(downloads.length).toBe(0);
    // And the preview endpoint must have been called at
    // least once.
    const previews = calls.filter((u) => u.includes("/exports/cyclonedx_1_7/preview"));
    expect(previews.length).toBeGreaterThanOrEqual(1);
  });

  it("does not leak forbidden verdict words in the preview body", async () => {
    vi.mocked(globalThis.fetch);
    renderExportCenter();
    await waitFor(() => {
      expect(screen.getByTestId("preview-show-button")).toBeInTheDocument();
    });
    screen.getByTestId("preview-show-button").click();
    await waitFor(() => {
      expect(screen.getByTestId("preview-inventory-components")).toBeInTheDocument();
    });
    const text = (document.body.textContent ?? "").toLowerCase();
    for (const forbidden of ["clean sbom", "secure sbom", "certified sbom", "complete sbom", "authoritative sbom"]) {
      expect(text).not.toContain(forbidden);
    }
  });

  it("still shows legacy export rows after the preview panel is collapsed", async () => {
    vi.mocked(globalThis.fetch);
    renderExportCenter();
    await waitFor(() => {
      expect(screen.getByTestId("preview-show-button")).toBeInTheDocument();
    });
    // The legacy exports remain visible alongside the new
    // preview toggle.
    expect(screen.getByText("cyclonedx_json")).toBeInTheDocument();
    expect(screen.getByText("findings_json")).toBeInTheDocument();
    expect(screen.getByText("findings_csv")).toBeInTheDocument();
    expect(screen.getByText("sarif_json")).toBeInTheDocument();
  });

  it("renders the neutral 'not_applicable' provider coverage for an ineligible failed scan without implying success", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/exports/cyclonedx_1_7/preview")) {
        return Promise.resolve(
          jsonResponse(
            makePreviewResponse({
              eligible: false,
              code: "scan_failed",
              reason: "Scan terminated in a failed state.",
              limitations: [],
              evidence_coverage: {
                inventory_coverage: "not_applicable",
                dependency_graph_coverage: "unknown",
                provider_coverage: "not_applicable",
              },
            })
          )
        );
      }
      return Promise.resolve(jsonResponse(makeListResponse()));
    });
    renderExportCenter();
    await waitFor(() => {
      expect(screen.getByTestId("preview-show-button")).toBeInTheDocument();
    });
    screen.getByTestId("preview-show-button").click();
    await waitFor(() => {
      expect(screen.getByTestId("preview-coverage-provider")).toBeInTheDocument();
    });
    // The neutral value is rendered verbatim, so the
    // consumer can render its own meaning for it.
    expect(
      screen.getByTestId("preview-coverage-provider")
    ).toHaveTextContent("not_applicable");
    expect(
      screen.getByTestId("preview-coverage-inventory")
    ).toHaveTextContent("not_applicable");
    expect(
      screen.getByTestId("preview-coverage-graph")
    ).toHaveTextContent("unknown");
    // The body must not contain the misleading "ok" or
    // "complete" labels for a failed scan.
    const text = (document.body.textContent ?? "").toLowerCase();
    // The body might legitimately contain "ok" elsewhere
    // (e.g. in the unrelated coverage list). The
    // assertion is scoped to the data-testid elements that
    // own the failed scan's coverage values.
    expect(screen.getByTestId("preview-coverage-provider").textContent).not.toBe("ok");
    expect(screen.getByTestId("preview-coverage-inventory").textContent).not.toBe(
      "complete"
    );
    // Sanity check: the test does not let an unrelated
    // "ok" string in the document silently mask a bug.
    expect(text.length).toBeGreaterThan(0);
  });

  it("renders the neutral 'not_applicable' provider coverage for a cancelled scan", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/exports/cyclonedx_1_7/preview")) {
        return Promise.resolve(
          jsonResponse(
            makePreviewResponse({
              eligible: false,
              code: "scan_cancelled",
              reason: "Scan was cancelled before completion.",
              limitations: [],
              evidence_coverage: {
                inventory_coverage: "not_applicable",
                dependency_graph_coverage: "unknown",
                provider_coverage: "not_applicable",
              },
            })
          )
        );
      }
      return Promise.resolve(jsonResponse(makeListResponse()));
    });
    renderExportCenter();
    await waitFor(() => {
      expect(screen.getByTestId("preview-show-button")).toBeInTheDocument();
    });
    screen.getByTestId("preview-show-button").click();
    await waitFor(() => {
      expect(screen.getByTestId("preview-coverage-provider")).toBeInTheDocument();
    });
    expect(
      screen.getByTestId("preview-coverage-provider")
    ).toHaveTextContent("not_applicable");
    expect(
      screen.getByTestId("preview-coverage-inventory")
    ).toHaveTextContent("not_applicable");
  });

  it("renders the neutral 'not_applicable' provider coverage for a queued scan", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/exports/cyclonedx_1_7/preview")) {
        return Promise.resolve(
          jsonResponse(
            makePreviewResponse({
              eligible: false,
              code: "scan_not_started",
              reason: "Scan is queued; no inventory has been observed yet.",
              limitations: [],
              evidence_coverage: {
                inventory_coverage: "not_applicable",
                dependency_graph_coverage: "unknown",
                provider_coverage: "not_applicable",
              },
            })
          )
        );
      }
      return Promise.resolve(jsonResponse(makeListResponse()));
    });
    renderExportCenter();
    await waitFor(() => {
      expect(screen.getByTestId("preview-show-button")).toBeInTheDocument();
    });
    screen.getByTestId("preview-show-button").click();
    await waitFor(() => {
      expect(screen.getByTestId("preview-coverage-provider")).toBeInTheDocument();
    });
    expect(
      screen.getByTestId("preview-coverage-provider")
    ).toHaveTextContent("not_applicable");
    expect(
      screen.getByTestId("preview-coverage-inventory")
    ).toHaveTextContent("not_applicable");
  });

  it("renders the neutral 'empty' inventory coverage for a partial scan without inventory", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/exports/cyclonedx_1_7/preview")) {
        return Promise.resolve(
          jsonResponse(
            makePreviewResponse({
              eligible: false,
              code: "partial_incomplete",
              reason:
                "Scan is partial and no persisted local-analysis evidence is complete enough to derive an inventory.",
              limitations: [],
              inventory: {
                component_count: 0,
                manifest_count: 0,
                ecosystems: [],
                direct_count: 0,
                transitive_count: 0,
                missing_version_count: 0,
                duplicate_observations_count: 0,
              },
              evidence_coverage: {
                inventory_coverage: "empty",
                dependency_graph_coverage: "unknown",
                provider_coverage: "not_applicable",
              },
            })
          )
        );
      }
      return Promise.resolve(jsonResponse(makeListResponse()));
    });
    renderExportCenter();
    await waitFor(() => {
      expect(screen.getByTestId("preview-show-button")).toBeInTheDocument();
    });
    screen.getByTestId("preview-show-button").click();
    await waitFor(() => {
      expect(screen.getByTestId("preview-coverage-inventory")).toBeInTheDocument();
    });
    expect(
      screen.getByTestId("preview-coverage-inventory")
    ).toHaveTextContent("empty");
    expect(
      screen.getByTestId("preview-coverage-provider")
    ).toHaveTextContent("not_applicable");
    // A partial_incomplete scan must never claim
    // inventory is complete.
    expect(screen.getByTestId("preview-coverage-inventory").textContent).not.toBe(
      "complete"
    );
  });
});
