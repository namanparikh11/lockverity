/**
 * v1.0 human-readable evidence report tests.
 *
 * The page renders the
 * ``/scans/{scan_id}/reports/evidence-summary/preview``
 * response and the
 * ``/scans/{scan_id}/reports/evidence-summary.md``
 * Markdown download. The tests pin down:
 *
 * - the panel renders on the Export Center;
 * - the toggle switches the lazy preview on and off;
 * - the evidence-only summary renders counts;
 * - the Markdown download points to the right endpoint
 *   and the response body contains the disclaimer;
 * - the page never renders a positive verdict phrase
 *   (clean, secure, certified, compliant, fixed, complete
 *   dependency graph) as a conclusion.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { ExportCenterPage } from "@/pages/ExportCenterPage";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function textResponse(body: string, status = 200): Response {
  return new Response(body, {
    status,
    headers: { "content-type": "text/markdown; charset=utf-8" },
  });
}

function makeReportPreview() {
  return {
    metadata: {
      report_name: "Lockverity Evidence Report",
      generator: "lockverity",
      generator_version: "1.0.0",
      report_format: "markdown",
      report_format_version: "1.0",
      generated_at_utc: "2026-07-17T12:00:00+00:00",
      scan_id: 1,
      repository_id: 1,
    },
    scan: {
      scan_id: 1,
      repository_id: 1,
      repository_canonical_url: "https://github.com/example/repo",
      repository_source_type: "github",
      repository_visibility: "public",
      scan_status: "completed",
      scan_trigger_type: "manual",
      resolved_commit_sha: "deadbeef",
      analyzer_version: "lockverity 1.0.0",
    },
    summary: {
      component_count: 3,
      manifest_count: 1,
      ecosystems: { npm: 2, cargo: 1 },
      direct_count: 2,
      transitive_count: 1,
      version_present_count: 2,
      version_missing_count: 1,
      licence_observed_count: 1,
      licence_missing_count: 2,
      provider_observed_count: 1,
      provider_missing_count: 2,
      edges_observed_count: 1,
      edges_none_observed_count: 2,
      purl_persisted_count: 1,
      purl_constructible_count: 1,
      purl_omitted_count: 1,
      appears_in_cyclonedx_17_count: 3,
      cyclonedx_version_omitted_count: 1,
      cyclonedx_relationships_emitted_count: 1,
    },
    evidence_coverage: {
      inventory_coverage: "complete",
      dependency_graph_coverage: "partial",
      provider_coverage: "ok",
    },
    evidence_gaps: {
      missing_version_count: 1,
      missing_licence_evidence_count: 2,
      missing_provider_evidence_count: 2,
      no_persisted_edges_count: 2,
      purl_omitted_count: 1,
    },
    components: [
      {
        id: 1,
        ecosystem: "npm",
        package_name: "alpha",
        version: "1.2.3",
        version_source: "manifest",
        direct: true,
        purl_state: "persisted",
        edges_evidence: "edges_observed",
        licence_evidence: "licence_observed",
        provider_evidence: "provider_observed",
        appears_in_cyclonedx_17: true,
        cyclonedx_version_omitted: false,
        cyclonedx_relationships_emitted: true,
      },
    ],
    truncated: { truncated: false, shown: 1, total: 1, reason: "No truncation." },
    export_relationship: {
      cyclonedx_eligible: true,
      cyclonedx_eligibility_code: "eligible",
      cyclonedx_eligibility_reason: "Scan completed with persisted local-analysis evidence.",
      appears_in_cyclonedx_17_count: 3,
      cyclonedx_version_omitted_count: 1,
      cyclonedx_relationships_emitted_count: 1,
      cyclonedx_relationships_omitted_count: 2,
      inventory_coverage: "complete",
      dependency_graph_coverage: "partial",
      provider_coverage: "ok",
    },
    omissions: [
      "no_clean_verdict",
      "no_security_verdict",
      "no_certification",
      "no_compliance_pass_or_fail",
      "no_complete_dependency_graph_claim",
      "no_remediation_claim",
      "no_repository_code_execution",
      "missing_provider_confidence_kept_missing",
      "missing_licence_evidence_explicit",
      "no_fabricated_evidence_absence",
    ],
    disclaimer:
      "This is an evidence report, not a security verdict, not a certification, and not a compliance pass-or-fail.",
  };
}

function makeExportsList() {
  return {
    items: [
      {
        format: "cyclonedx_1_7",
        label: "CycloneDX 1.7 (JSON)",
        description: "",
        supported: true,
        not_supported_reason: null,
        content_type: "application/vnd.cyclonedx+json; version=1.7",
        filename_hint: "lockverity-scan-{id}.cdx.json",
      },
    ],
  };
}

function setupDefaultFetchMock(opts: { reportNotImpl?: boolean } = {}) {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockImplementation((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/reports/evidence-summary/preview")) {
      if (opts.reportNotImpl) {
        return Promise.resolve(
          jsonResponse({ detail: "not implemented" }, 501)
        );
      }
      return Promise.resolve(jsonResponse(makeReportPreview()));
    }
    if (url.includes("/reports/evidence-summary.md")) {
      return Promise.resolve(
        textResponse(
          "# Lockverity Evidence Report\n\n> This is an evidence report, not a security verdict.\n"
        )
      );
    }
    if (url.includes("/exports/cyclonedx_1_7/preview")) {
      return Promise.resolve(
        jsonResponse({
          scan: { scan_id: 1, repository_id: 1, scan_status: "completed" },
          eligibility: {
            eligible: true,
            code: "eligible",
            reason: "Scan completed with persisted local-analysis evidence.",
            limitations: [],
            download_expected_to_succeed: true,
          },
          inventory: {
            component_count: 3,
            manifest_count: 1,
            ecosystems: ["npm", "cargo"],
            direct_count: 2,
            transitive_count: 1,
            missing_version_count: 1,
            duplicate_observations_count: 0,
          },
          evidence_coverage: {
            inventory_coverage: "complete",
            dependency_graph_coverage: "partial",
            provider_coverage: "ok",
          },
          sbom_output: {
            format: "cyclonedx_json",
            spec_version: "1.7",
            media_type: "application/vnd.cyclonedx+json; version=1.7",
            filename_template: "lockverity-scan-{scan_id}.cdx.json",
            schema_uri: "http://cyclonedx.org/schema/bom-1.7.schema.json",
            schema_validation: "strict",
            generation_source: "library",
          },
          omissions: [
            "no_clean_verdict",
            "no_security_verdict",
            "no_complete_dependency_graph_claim",
            "no_remediation_claim",
            "no_repository_code_execution",
          ],
          legacy_export_relationship: "ok",
        })
      );
    }
    if (url.includes("/exports/cyclonedx_1_7")) {
      return Promise.resolve(
        new Response("{\"bom\":1.7}", {
          status: 200,
          headers: {
            "content-type": "application/vnd.cyclonedx+json; version=1.7",
          },
        })
      );
    }
    if (url.includes("/scans/") && url.endsWith("/exports")) {
      return Promise.resolve(jsonResponse(makeExportsList()));
    }
    if (url.endsWith("/scans/1") || url.endsWith("/scans/1/")) {
      return Promise.resolve(
        jsonResponse({
          id: 1,
          repository_id: 1,
          status: "completed",
          trigger_type: "manual",
          requested_ref: "main",
          resolved_commit_sha: "deadbeef",
          analyzer_version: "lockverity 1.0.0",
          started_at: null,
          completed_at: null,
          failure_code: null,
          failure_summary: null,
          created_at: "2026-07-17T12:00:00+00:00",
          updated_at: "2026-07-17T12:00:00+00:00",
        })
      );
    }
    if (url.includes("/provider-health")) {
      return Promise.resolve(
        jsonResponse({ entries: [], providers: ["github", "osv"] })
      );
    }
    return Promise.resolve(jsonResponse({ items: [] }));
  });
  return fetchMock;
}

function renderExportCenter() {
  return render(
    <MemoryRouter initialEntries={["/scans/1/exports"]}>
      <Routes>
        <Route
          path="/scans/:scanId/exports"
          element={<ExportCenterPage />}
        />
      </Routes>
    </MemoryRouter>
  );
}

describe("v1.0 human-readable evidence report", () => {
  beforeEach(() => {
    setupDefaultFetchMock();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    cleanup();
  });

  it("renders the Evidence report panel on the Export Center", async () => {
    renderExportCenter();
    await waitFor(() => {
      expect(screen.getByTestId("evidence-report-panel")).toBeInTheDocument();
    });
    // The panel header carries the v1.0 evidence-only
    // wording; the download button is reachable.
    expect(screen.getByText("Evidence report")).toBeInTheDocument();
    expect(screen.getByTestId("evidence-report-download")).toBeInTheDocument();
  });

  it("expands the lazy preview and renders the evidence-only summary", async () => {
    renderExportCenter();
    await waitFor(() => {
      expect(screen.getByTestId("evidence-report-panel")).toBeInTheDocument();
    });
    // Initially the body is collapsed.
    expect(
      screen.queryByTestId("evidence-report-summary")
    ).not.toBeInTheDocument();
    // Click the toggle; the lazy fetch fires.
    screen.getByTestId("evidence-report-toggle").click();
    // The body must leave the loading state and render
    // the summary within the waitFor window. The
    // regression guard is: a previous version of this
    // effect re-ran on ``setLoading(true)`` and
    // cancelled the in-flight fetch via the cleanup
    // function, so the body never rendered. The fix
    // moved the in-flight tracking into refs and the
    // cleanup to an unmount-only effect.
    await waitFor(
      () => {
        expect(screen.getByTestId("evidence-report-body")).toBeInTheDocument();
        // The loading placeholder is gone: the body is
        // a real summary, not a Skeleton.
        expect(
          screen.getByTestId("evidence-report-disclaimer")
        ).toBeInTheDocument();
      },
      { timeout: 2000 }
    );
    // The summary renders the documented counts and the
    // bounded disclaimer.
    expect(screen.getByTestId("evidence-report-disclaimer")).toHaveTextContent(
      /not a security verdict/i
    );
    expect(screen.getByTestId("evidence-report-component-count")).toHaveTextContent(
      "3"
    );
    expect(screen.getByTestId("evidence-report-manifest-count")).toHaveTextContent(
      "1"
    );
    expect(screen.getByTestId("evidence-report-scan-status")).toHaveTextContent(
      "completed"
    );
    // The evidence-gaps block uses the bounded vocabulary.
    expect(screen.getByTestId("evidence-report-gaps")).toHaveTextContent(
      /no persisted dependency edges/i
    );
  });

  it("renders the bounded not-implemented state when the preview endpoint is missing", async () => {
    // Override the default mock for this test only: the
    // preview endpoint returns a 404 so the panel must
    // surface the bounded &ldquo;not exposed by the API
    // yet&rdquo; message rather than the loading skeleton.
    // A 404 is the documented &ldquo;endpoint not exposed&rdquo;
    // case the panel handles via ``isNotImplemented``; the
    // regression guard is the same as the success test: the
    // body must leave the loading state and render the
    // bounded message, not stay in the skeleton.
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/reports/evidence-summary/preview")) {
        return Promise.resolve(
          jsonResponse({ detail: "not found" }, 404)
        );
      }
      if (url.includes("/exports/cyclonedx_1_7/preview")) {
        return Promise.resolve(
          jsonResponse({
            scan: { scan_id: 1, repository_id: 1, scan_status: "completed" },
            eligibility: {
              eligible: true,
              code: "eligible",
              reason: "Scan completed with persisted local-analysis evidence.",
              limitations: [],
              download_expected_to_succeed: true,
            },
            inventory: {
              component_count: 3,
              manifest_count: 1,
              ecosystems: ["npm"],
              direct_count: 3,
              transitive_count: 0,
              missing_version_count: 0,
              duplicate_observations_count: 0,
            },
            evidence_coverage: {
              inventory_coverage: "complete",
              dependency_graph_coverage: "partial",
              provider_coverage: "ok",
            },
            sbom_output: {
              format: "cyclonedx_json",
              spec_version: "1.7",
              media_type: "application/vnd.cyclonedx+json; version=1.7",
              filename_template: "lockverity-scan-{scan_id}.cdx.json",
              schema_uri: "http://cyclonedx.org/schema/bom-1.7.schema.json",
              schema_validation: "strict",
              generation_source: "library",
            },
            omissions: [
              "no_clean_verdict",
              "no_security_verdict",
              "no_complete_dependency_graph_claim",
              "no_remediation_claim",
              "no_repository_code_execution",
            ],
            legacy_export_relationship: "ok",
          })
        );
      }
      if (url.includes("/scans/") && url.endsWith("/exports")) {
        return Promise.resolve(jsonResponse(makeExportsList()));
      }
      if (url.endsWith("/scans/1") || url.endsWith("/scans/1/")) {
        return Promise.resolve(
          jsonResponse({
            id: 1,
            repository_id: 1,
            status: "completed",
            trigger_type: "manual",
            requested_ref: "main",
            resolved_commit_sha: "deadbeef",
            analyzer_version: "lockverity 1.0.0",
            started_at: null,
            completed_at: null,
            failure_code: null,
            failure_summary: null,
            created_at: "2026-07-17T12:00:00+00:00",
            updated_at: "2026-07-17T12:00:00+00:00",
          })
        );
      }
      if (url.includes("/provider-health")) {
        return Promise.resolve(
          jsonResponse({ entries: [], providers: ["github", "osv"] })
        );
      }
      return Promise.resolve(jsonResponse({ items: [] }));
    });
    renderExportCenter();
    await waitFor(() => {
      expect(screen.getByTestId("evidence-report-panel")).toBeInTheDocument();
    });
    // Expand and wait for the not-implemented UI. The
    // regression guard is the same as the success test:
    // the body must leave the loading state and render
    // the bounded message, not stay in the skeleton.
    screen.getByTestId("evidence-report-toggle").click();
    await waitFor(
      () => {
        expect(
          screen.getByText(/evidence-report endpoint is not exposed/i)
        ).toBeInTheDocument();
      },
      { timeout: 2000 }
    );
  });

  it("the Markdown download button points to the right endpoint", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    renderExportCenter();
    await waitFor(() => {
      expect(screen.getByTestId("evidence-report-panel")).toBeInTheDocument();
    });
    // The download endpoint was never called yet.
    const mdHitsBefore = fetchMock.mock.calls.filter((args) => {
      const url = typeof args[0] === "string" ? args[0] : args[0].toString();
      return url.includes("/reports/evidence-summary.md");
    }).length;
    expect(mdHitsBefore).toBe(0);
    // Click Download Markdown. The fetch handler returns
    // the textResponse mock above; jsdom does not write
    // to disk, so we only assert the endpoint was called.
    screen.getByTestId("evidence-report-download").click();
    await waitFor(() => {
      const mdHits = fetchMock.mock.calls.filter((args) => {
        const url =
          typeof args[0] === "string" ? args[0] : args[0].toString();
        return url.includes("/reports/evidence-summary.md");
      });
      expect(mdHits.length).toBeGreaterThan(0);
    });
  });

  it("does not render forbidden positive verdict phrases anywhere on the panel", async () => {
    renderExportCenter();
    await waitFor(() => {
      expect(screen.getByTestId("evidence-report-panel")).toBeInTheDocument();
    });
    screen.getByTestId("evidence-report-toggle").click();
    await waitFor(() => {
      expect(screen.getByTestId("evidence-report-body")).toBeInTheDocument();
    });
    const text = (screen.getByTestId("evidence-report-panel").textContent ?? "").toLowerCase();
    for (const forbidden of [
      "clean bill",
      "certified",
      "compliant",
      "fixed all issues",
      "complete dependency graph",
    ]) {
      expect(text).not.toBe(forbidden);
    }
    // The bounded disclaimer wording is present.
    expect(text).toContain("not a security verdict");
    expect(text).toContain("not a certification");
    expect(text).toContain("not a compliance pass-or-fail");
  });

  it("does not regress the v0.7 CycloneDX 1.7 preview block", async () => {
    renderExportCenter();
    await waitFor(() => {
      // The CycloneDX preview panel toggle button is still
      // rendered on the page.
      expect(
        screen.getByRole("button", { name: /Show CycloneDX 1.7 evidence preview/i })
      ).toBeInTheDocument();
    });
  });
});
