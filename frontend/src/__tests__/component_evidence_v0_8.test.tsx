/**
 * v0.8 component evidence drilldown tests.
 *
 * The evidence panel is a sibling of the dependency-path
 * drawer on the existing DependencyExplorerPage. The tests
 * verify the contract:
 *
 * - a "View evidence" button appears on every component row;
 * - clicking the button opens the evidence drawer and
 *   renders every documented section (identity, manifest,
 *   licence, provider, dependency, export implications,
 *   omissions);
 * - missing evidence is rendered with the bounded wording
 *   the contract guarantees;
 * - the panel never uses forbidden verdict words
 *   (clean / secure / fixed / complete dependency graph /
 *   certified) as conclusions;
 * - the API call is the documented read-only endpoint;
 * - existing scan detail / export flows still work.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";

import { DependencyExplorerPage } from "@/pages/DependencyExplorerPage";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function makeComponent(
  id: number,
  package_name: string,
  overrides: Partial<Record<string, unknown>> = {}
): Record<string, unknown> {
  return {
    id,
    scan_run_id: 1,
    manifest_id: 1,
    ecosystem: "npm",
    package_name,
    version: "1.0.0",
    version_source: "manifest",
    direct: true,
    package_url: `pkg:npm/${package_name}@1.0.0`,
    evidence: {
      version_present: true,
      licence_observed: false,
      provider_observed: false,
      purl_state: "persisted",
      edges_observed: false,
      appears_in_cyclonedx_17: true,
      version_omitted_from_cyclonedx_17: false,
      dependency_relationships_emitted_in_cyclonedx_17: false,
    },
    ...overrides,
  };
}

function makeSummaryResponse(overrides: {
  items?: Record<string, unknown>[];
  total?: number;
  facets?: Record<string, unknown>;
} = {}) {
  const items =
    overrides.items ??
    [makeComponent(1, "left-pad")];
  return {
    items,
    pagination: {
      page: 1,
      page_size: 50,
      total: overrides.total ?? items.length,
      total_pages: Math.max(
        1,
        Math.ceil((overrides.total ?? items.length) / 50)
      ),
    },
    facets:
      overrides.facets ?? {
        ecosystems: { npm: items.length },
        missing_version: 0,
        missing_licence_evidence: items.length,
        missing_provider_evidence: items.length,
        purl_persisted: items.length,
        purl_constructible: 0,
        purl_omitted: 0,
        edges_observed: 0,
        edges_none_observed: items.length,
        direct_yes: items.length,
        direct_no: 0,
        cyclonedx_version_omitted: 0,
      },
    omissions: [
      "no_clean_verdict",
      "no_security_verdict",
      "no_complete_dependency_graph_claim",
      "no_remediation_claim",
      "no_repository_code_execution",
      "no_inferred_dependency_edges",
      "no_fabricated_evidence_absence",
    ],
  };
}

function makeEvidenceResponse(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    scan: {
      scan_id: 1,
      repository_id: 1,
      scan_status: "completed",
    },
    component: {
      id: 1,
      ecosystem: "npm",
      package_name: "left-pad",
      version: "1.0.0",
      version_source: "manifest",
      direct: true,
      development: false,
      optional: false,
      scope: "runtime",
      relationship: "runtime",
      integrity: null,
      package_url: "pkg:npm/left-pad@1.0.0",
      package_url_well_formed: true,
      purl_constructible: true,
      bom_ref: "pkg:npm/left-pad@1.0.0",
    },
    manifest: {
      available: true,
      id: 1,
      path: "package.json",
      manifest_type: "npm",
      ecosystem: "npm",
      parse_status: "parsed",
      parse_warning_count: 0,
    },
    licence_evidence: {
      available: true,
      reason: null,
      observations: [
        {
          value: "MIT",
          classification: "spdx-id",
          provenance: "local",
          source: "rule_engine",
          finding_id: 1,
          rule_id: "LOCK-LIC-INV",
        },
      ],
      sources: ["rule_engine"],
    },
    provider_evidence: {
      available: true,
      any_provider_queried: true,
      observations: [
        {
          id: 1,
          provider: "deps.dev",
          operation: "enrich",
          status: "available",
          cache_status: "miss",
          http_status: 200,
          records_returned: 1,
          requested_at: "2026-07-16T00:00:00Z",
          completed_at: "2026-07-16T00:00:01Z",
          error_code: null,
          error_summary: null,
          evidence_keys: ["licences", "dependency_count"],
        },
      ],
      advisories: [
        {
          advisory_id: 1,
          available: true,
          reason: null,
          canonical_id: "CVE-2021-1234",
          source_advisory_id: "OSV-1",
          source: "osv",
          severity_label: "high",
          severity_score: 7.5,
          severity_source: "osv",
          fixed_versions: ["1.0.1"],
          aliases: ["GHSA-xxxx-yyyy-zzzz"],
          confidence: null,
          provider_provenance: "osv",
          affected: true,
        },
      ],
    },
    dependency_evidence: {
      graph_coverage: "partial",
      incoming: [],
      outgoing: [],
      no_edges_observed: true,
    },
    export_implications: {
      appears_in_cyclonedx_17: true,
      version_omitted: false,
      purl_emitted: true,
      dependency_relationships_emitted: false,
      graph_coverage: "partial",
    },
    omissions: [
      "no_clean_verdict",
      "no_security_verdict",
      "no_complete_dependency_graph_claim",
      "no_remediation_claim",
      "no_repository_code_execution",
      "missing_provider_confidence_kept_missing",
      "missing_licence_evidence_explicit",
    ],
    ...overrides,
  };
}

function renderExplorer() {
  return render(
    <MemoryRouter initialEntries={["/scans/1/dependencies"]}>
      <Routes>
        <Route
          path="/scans/:scanId/dependencies"
          element={<DependencyExplorerPage />}
        />
      </Routes>
    </MemoryRouter>
  );
}

describe("v0.8 component evidence drilldown", () => {
  beforeEach(() => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    // Default: components list returns a single row; the
    // evidence endpoint returns a populated summary. Tests
    // can override the evidence response to cover edge
    // cases.
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(jsonResponse(makeSummaryResponse()));
      }
      if (/\/components\/\d+\/evidence/.test(url)) {
        return Promise.resolve(jsonResponse(makeEvidenceResponse()));
      }
      if (/\/components\/\d+\/path/.test(url)) {
        return Promise.resolve(
          jsonResponse({ components: [], edges: [], truncated: false })
        );
      }
      return Promise.resolve(jsonResponse({ items: [] }));
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    cleanup();
  });

  it("renders a 'View evidence' button on every component row", async () => {
    renderExplorer();
    await waitFor(() => {
      expect(
        screen.getByTestId("component-evidence-button-1")
      ).toBeInTheDocument();
    });
  });

  it("opens the evidence drawer and renders every documented section", async () => {
    renderExplorer();
    await waitFor(() => {
      expect(
        screen.getByTestId("component-evidence-button-1")
      ).toBeInTheDocument();
    });
    screen.getByTestId("component-evidence-button-1").click();
    await waitFor(() => {
      expect(
        screen.getByTestId("component-evidence-panel")
      ).toBeInTheDocument();
    });
    // Identity
    expect(screen.getByTestId("ce-package-name")).toHaveTextContent("left-pad");
    // Manifest
    expect(screen.getByTestId("ce-manifest")).toBeInTheDocument();
    // Licence
    expect(screen.getByTestId("ce-licence")).toBeInTheDocument();
    // Provider
    expect(screen.getByTestId("ce-provider")).toBeInTheDocument();
    // Dependency (no edges)
    expect(screen.getByTestId("ce-dependency-empty")).toBeInTheDocument();
    // Export implications
    expect(screen.getByTestId("ce-export")).toBeInTheDocument();
    // Omissions
    expect(screen.getByTestId("ce-omissions")).toBeInTheDocument();
  });

  it("renders the PURL truthfully when the persisted PURL is malformed", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(jsonResponse(makeSummaryResponse()));
      }
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(jsonResponse(makeSummaryResponse()));
      }
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(jsonResponse(makeSummaryResponse()));
      }
      if (url.includes("/evidence")) {
        return Promise.resolve(
          jsonResponse(
            makeEvidenceResponse({
              component: {
                id: 1,
                ecosystem: "npm",
                package_name: "left-pad",
                version: "1.0.0",
                version_source: "manifest",
                direct: true,
                development: false,
                optional: false,
                scope: "runtime",
                relationship: "runtime",
                integrity: null,
                package_url: "not-a-purl",
                package_url_well_formed: false,
                purl_constructible: true,
                bom_ref: "lockverity:component:1",
              },
            })
          )
        );
      }
      if (/\/components\/\d+\/path/.test(url)) {
        return Promise.resolve(
          jsonResponse({ components: [], edges: [], truncated: false })
        );
      }
      return Promise.resolve(jsonResponse({ items: [] }));
    });
    renderExplorer();
    await waitFor(() => {
      expect(
        screen.getByTestId("component-evidence-button-1")
      ).toBeInTheDocument();
    });
    screen.getByTestId("component-evidence-button-1").click();
    await waitFor(() => {
      expect(screen.getByTestId("ce-purl")).toBeInTheDocument();
    });
    // The panel surfaces the persisted PURL verbatim
    // and marks it malformed.
    expect(screen.getByTestId("ce-purl")).toHaveTextContent("not-a-purl");
    expect(screen.getByText(/persisted PURL malformed/)).toBeInTheDocument();
  });

  it("renders missing version with no placeholder string", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(jsonResponse(makeSummaryResponse()));
      }
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(jsonResponse(makeSummaryResponse()));
      }
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(jsonResponse(makeSummaryResponse()));
      }
      if (url.includes("/evidence")) {
        return Promise.resolve(
          jsonResponse(
            makeEvidenceResponse({
              component: {
                id: 1,
                ecosystem: "npm",
                package_name: "unresolved-pkg",
                version: null,
                version_source: "unresolved",
                direct: true,
                development: false,
                optional: false,
                scope: "runtime",
                relationship: "runtime",
                integrity: null,
                package_url: null,
                package_url_well_formed: null,
                purl_constructible: true,
                bom_ref: "lockverity:component:1",
              },
              export_implications: {
                appears_in_cyclonedx_17: true,
                version_omitted: true,
                purl_emitted: true,
                dependency_relationships_emitted: false,
                graph_coverage: "partial",
              },
            })
          )
        );
      }
      if (/\/components\/\d+\/path/.test(url)) {
        return Promise.resolve(
          jsonResponse({ components: [], edges: [], truncated: false })
        );
      }
      return Promise.resolve(jsonResponse({ items: [] }));
    });
    renderExplorer();
    await waitFor(() => {
      expect(
        screen.getByTestId("component-evidence-button-1")
      ).toBeInTheDocument();
    });
    screen.getByTestId("component-evidence-button-1").click();
    await waitFor(() => {
      expect(
        screen.getByTestId("component-evidence-panel")
      ).toBeInTheDocument();
    });
    const body = (document.body.textContent ?? "").toLowerCase();
    for (const placeholder of [
      "unspecified",
      '"unknown"',
      '"latest"',
      '"n/a"',
      "<missing>",
    ]) {
      expect(body).not.toContain(placeholder);
    }
    // The export implications block reports the omission
    // explicitly.
    expect(screen.getByText(/Version omitted from export/i)).toBeInTheDocument();
  });

  it("renders missing licence evidence as 'unavailable' rather than 'none'", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(jsonResponse(makeSummaryResponse()));
      }
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(jsonResponse(makeSummaryResponse()));
      }
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(jsonResponse(makeSummaryResponse()));
      }
      if (url.includes("/evidence")) {
        return Promise.resolve(
          jsonResponse(
            makeEvidenceResponse({
              licence_evidence: {
                available: false,
                reason: "no_persisted_licence_evidence",
                observations: [],
                sources: [],
              },
            })
          )
        );
      }
      if (/\/components\/\d+\/path/.test(url)) {
        return Promise.resolve(
          jsonResponse({ components: [], edges: [], truncated: false })
        );
      }
      return Promise.resolve(jsonResponse({ items: [] }));
    });
    renderExplorer();
    await waitFor(() => {
      expect(
        screen.getByTestId("component-evidence-button-1")
      ).toBeInTheDocument();
    });
    screen.getByTestId("component-evidence-button-1").click();
    await waitFor(() => {
      expect(screen.getByTestId("ce-licence-empty")).toBeInTheDocument();
    });
    expect(
      screen.getByTestId("ce-licence-empty")
    ).toHaveTextContent(/No persisted licence evidence available/);
  });

  it("renders provider unavailable and partial states", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(jsonResponse(makeSummaryResponse()));
      }
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(jsonResponse(makeSummaryResponse()));
      }
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(jsonResponse(makeSummaryResponse()));
      }
      if (url.includes("/evidence")) {
        return Promise.resolve(
          jsonResponse(
            makeEvidenceResponse({
              provider_evidence: {
                available: true,
                any_provider_queried: true,
                observations: [
                  {
                    id: 1,
                    provider: "osv.dev",
                    operation: "vulnerability_query",
                    status: "unavailable",
                    cache_status: null,
                    http_status: 503,
                    records_returned: 0,
                    requested_at: "2026-07-16T00:00:00Z",
                    completed_at: "2026-07-16T00:00:01Z",
                    error_code: "upstream_5xx",
                    error_summary: "upstream provider returned 503",
                    evidence_keys: [],
                  },
                ],
                advisories: [],
              },
            })
          )
        );
      }
      if (/\/components\/\d+\/path/.test(url)) {
        return Promise.resolve(
          jsonResponse({ components: [], edges: [], truncated: false })
        );
      }
      return Promise.resolve(jsonResponse({ items: [] }));
    });
    renderExplorer();
    await waitFor(() => {
      expect(
        screen.getByTestId("component-evidence-button-1")
      ).toBeInTheDocument();
    });
    screen.getByTestId("component-evidence-button-1").click();
    await waitFor(() => {
      expect(screen.getByTestId("ce-provider")).toBeInTheDocument();
    });
    const providerBlock = screen.getByTestId("ce-provider");
    expect(providerBlock).toHaveTextContent("osv.dev");
    expect(providerBlock).toHaveTextContent("unavailable");
    expect(providerBlock).toHaveTextContent("http 503");
  });

  it("renders dependency edges from persisted evidence only", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(jsonResponse(makeSummaryResponse()));
      }
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(jsonResponse(makeSummaryResponse()));
      }
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(jsonResponse(makeSummaryResponse()));
      }
      if (url.includes("/evidence")) {
        return Promise.resolve(
          jsonResponse(
            makeEvidenceResponse({
              dependency_evidence: {
                graph_coverage: "partial",
                incoming: [],
                outgoing: [
                  {
                    edge_id: 7,
                    component_id: 1,
                    other_component_id: 2,
                    direction: "outgoing",
                    relationship: "runtime",
                    depth: 1,
                  },
                ],
                no_edges_observed: false,
              },
              export_implications: {
                appears_in_cyclonedx_17: true,
                version_omitted: false,
                purl_emitted: true,
                dependency_relationships_emitted: true,
                graph_coverage: "partial",
              },
            })
          )
        );
      }
      if (/\/components\/\d+\/path/.test(url)) {
        return Promise.resolve(
          jsonResponse({ components: [], edges: [], truncated: false })
        );
      }
      return Promise.resolve(jsonResponse({ items: [] }));
    });
    renderExplorer();
    await waitFor(() => {
      expect(
        screen.getByTestId("component-evidence-button-1")
      ).toBeInTheDocument();
    });
    screen.getByTestId("component-evidence-button-1").click();
    await waitFor(() => {
      expect(screen.getByTestId("ce-dependency")).toBeInTheDocument();
    });
    const block = screen.getByTestId("ce-dependency");
    expect(block).toHaveTextContent(/outgoing: 1/);
    expect(block).toHaveTextContent(/partial/);
  });

  it("does not claim 'no dependencies' when the graph is empty", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(jsonResponse(makeSummaryResponse()));
      }
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(jsonResponse(makeSummaryResponse()));
      }
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(jsonResponse(makeSummaryResponse()));
      }
      if (url.includes("/evidence")) {
        return Promise.resolve(
          jsonResponse(
            makeEvidenceResponse({
              dependency_evidence: {
                graph_coverage: "unknown",
                incoming: [],
                outgoing: [],
                no_edges_observed: true,
              },
            })
          )
        );
      }
      if (/\/components\/\d+\/path/.test(url)) {
        return Promise.resolve(
          jsonResponse({ components: [], edges: [], truncated: false })
        );
      }
      return Promise.resolve(jsonResponse({ items: [] }));
    });
    renderExplorer();
    await waitFor(() => {
      expect(
        screen.getByTestId("component-evidence-button-1")
      ).toBeInTheDocument();
    });
    screen.getByTestId("component-evidence-button-1").click();
    await waitFor(() => {
      expect(screen.getByTestId("ce-dependency-empty")).toBeInTheDocument();
    });
    const text = (screen.getByTestId("ce-dependency-empty").textContent ?? "").toLowerCase();
    // The panel must surface the honest disclaimer
    // that an empty graph is not the same as "no
    // dependencies". The phrase "no dependencies" may
    // appear inside quotation marks (as the explicit
    // disclaimer the panel uses); it must not appear as
    // an affirmative claim.
    expect(text).toContain("not the same as");
    const sentence = text.split(/not the same as/i, 2)[1] ?? "";
    expect(sentence.toLowerCase()).toContain("no dependencies");
  });

  it("does not use forbidden verdict words as conclusions", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(jsonResponse(makeSummaryResponse()));
      }
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(jsonResponse(makeSummaryResponse()));
      }
      if (url.includes("/evidence")) {
        return Promise.resolve(jsonResponse(makeEvidenceResponse()));
      }
      if (/\/components\/\d+\/path/.test(url)) {
        return Promise.resolve(
          jsonResponse({ components: [], edges: [], truncated: false })
        );
      }
      return Promise.resolve(jsonResponse({ items: [] }));
    });
    renderExplorer();
    await waitFor(() => {
      expect(
        screen.getByTestId("component-evidence-button-1")
      ).toBeInTheDocument();
    });
    screen.getByTestId("component-evidence-button-1").click();
    await waitFor(() => {
      expect(
        screen.getByTestId("component-evidence-panel")
      ).toBeInTheDocument();
    });
    const text = (document.body.textContent ?? "").toLowerCase();
    for (const forbidden of [
      "clean sbom",
      "secure sbom",
      "certified sbom",
      "complete dependency graph",
      "fixed all issues",
    ]) {
      expect(text).not.toContain(forbidden);
    }
  });

  it("renders a bounded error when the evidence endpoint returns 404", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(jsonResponse(makeSummaryResponse()));
      }
      if (url.includes("/evidence")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({ error: { code: "not_found", message: "Component not found for this scan." } }),
            { status: 404, headers: { "content-type": "application/json" } }
          )
        );
      }
      if (/\/components\/\d+\/path/.test(url)) {
        return Promise.resolve(
          jsonResponse({ components: [], edges: [], truncated: false })
        );
      }
      return Promise.resolve(jsonResponse({ items: [] }));
    });
    renderExplorer();
    await waitFor(() => {
      expect(
        screen.getByTestId("component-evidence-button-1")
      ).toBeInTheDocument();
    });
    screen.getByTestId("component-evidence-button-1").click();
    await waitFor(() => {
      expect(
        screen.getByTestId("component-evidence-error")
      ).toBeInTheDocument();
    });
    expect(
      screen.getByTestId("component-evidence-error")
    ).toHaveTextContent(/not available/i);
  });

  it("does not call the SBOM download endpoint from the evidence panel", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    renderExplorer();
    await waitFor(() => {
      expect(
        screen.getByTestId("component-evidence-button-1")
      ).toBeInTheDocument();
    });
    screen.getByTestId("component-evidence-button-1").click();
    await waitFor(() => {
      expect(
        screen.getByTestId("component-evidence-panel")
      ).toBeInTheDocument();
    });
    const calls = fetchMock.mock.calls.map((c) => String(c[0]));
    const evidence = calls.filter((u) => u.includes("/components/1/evidence"));
    expect(evidence.length).toBeGreaterThanOrEqual(1);
    // The evidence endpoint is read-only and must not
    // trigger an SBOM download.
    const downloads = calls.filter((u) =>
      /\/exports\/cyclonedx_1_7(\?|$)/.test(u) || /\/exports\/cyclonedx_1_7$/.test(u)
    );
    expect(downloads.length).toBe(0);
  });

  // Column header / cell alignment regression test.
  //
  // The "Direct?" column must answer a yes/no question;
  // it must not render a green "available" pill that
  // conflates direct/transitive with availability. The
  // cell must also match the wording the drawer uses
  // ("Direct: yes" / "Direct: no") so the user is not
  // asked to reconcile two different representations of
  // the same fact.
  it("renders the 'Direct?' column as 'yes' / 'no' text, not as an availability badge", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(
          jsonResponse({
            items: [
              { ...makeComponent(1, "left-pad"), direct: true },
              { ...makeComponent(2, "stay"), direct: false },
            ],
            pagination: { page: 1, page_size: 50, total: 2, total_pages: 1 },
          })
        );
      }
      return Promise.resolve(jsonResponse({ items: [] }));
    });
    renderExplorer();
    await waitFor(() => {
      expect(
        screen.getByTestId("component-evidence-button-1")
      ).toBeInTheDocument();
    });
    // The table header must still ask the yes/no
    // question. The cell values must answer it with
    // the same wording the drawer uses.
    const table = screen.getByRole("table");
    const headers = Array.from(table.querySelectorAll("th")).map(
      (th) => th.textContent ?? ""
    );
    expect(headers).toContain("Direct?");
    // The first row is a direct dependency; the second
    // is transitive. The cells must say "yes" / "no"
    // verbatim and must not say "available" /
    // "unavailable" anywhere.
    const rows = Array.from(table.querySelectorAll("tbody tr"));
    const firstRowCells = Array.from(rows[0].querySelectorAll("td"));
    const secondRowCells = Array.from(rows[1].querySelectorAll("td"));
    // v0.9 column order: Package, Ecosystem, Version,
    // Direct?, Evidence flags, Evidence (button).
    const firstDirectCell = firstRowCells[3].textContent ?? "";
    const secondDirectCell = secondRowCells[3].textContent ?? "";
    expect(firstDirectCell.trim()).toBe("yes");
    expect(secondDirectCell.trim()).toBe("no");
    // The "available" badge must not appear in the
    // direct/transitive column. The Evidence column
    // also remains a button (not a "available" pill).
    expect(firstDirectCell).not.toMatch(/available/i);
    expect(secondDirectCell).not.toMatch(/available/i);
    expect(
      screen.getByTestId("component-evidence-button-1")
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("component-evidence-button-2")
    ).toBeInTheDocument();
  });

  it("clicking View evidence still opens the evidence drawer after the column repair", async () => {
    renderExplorer();
    await waitFor(() => {
      expect(
        screen.getByTestId("component-evidence-button-1")
      ).toBeInTheDocument();
    });
    screen.getByTestId("component-evidence-button-1").click();
    await waitFor(() => {
      expect(
        screen.getByTestId("component-evidence-panel")
      ).toBeInTheDocument();
    });
    // The drawer body still renders the package identity
    // and the "Direct: yes" wording the user already
    // trusts.
    expect(screen.getByTestId("ce-package-name")).toHaveTextContent("left-pad");
    expect(screen.getByText(/^Direct:/)).toBeInTheDocument();
  });
});
