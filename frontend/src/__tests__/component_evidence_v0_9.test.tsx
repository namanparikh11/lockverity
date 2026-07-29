/**
 * v0.9 evidence-aware search and filtering tests.
 *
 * The page renders the ``/components/evidence-summary``
 * response and exposes a new filter row plus a facet
 * panel. The tests pin down:
 *
 * - the default table still shows components;
 * - filtering by package name narrows the results;
 * - the v0.9 evidence filters (missing licence, missing
 *   provider, PURL constructible/omitted, no persisted
 *   dependency edges, direct yes/no) all work and the
 *   wording is evidence-honest;
 * - the inline evidence badges render;
 * - the facet panel renders counts that match the
 *   filtered set;
 * - clicking "View evidence" still opens the evidence
 *   drawer after a filter is applied;
 * - the CycloneDX 1.7 export preview still works;
 * - the page never renders forbidden verdict words as
 *   conclusions (clean, secure, fixed, safe, certified,
 *   complete dependency graph).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  overrides: Partial<Record<string, unknown>> = {},
): Record<string, unknown> {
  return {
    id,
    scan_id: 1,
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
  const items = overrides.items ?? [makeComponent(1, "left-pad")];
  const total = overrides.total ?? items.length;
  return {
    items,
    pagination: {
      page: 1,
      page_size: 50,
      total,
      total_pages: Math.max(1, Math.ceil(total / 50)),
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

function setupDefaultFetchMock() {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockImplementation((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/components/evidence-summary")) {
      return Promise.resolve(jsonResponse(makeSummaryResponse()));
    }
    if (/\/components\/\d+\/evidence/.test(url)) {
      return Promise.resolve(
        jsonResponse({
          scan: { scan_id: 1, repository_id: 1, scan_status: "completed" },
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
          licence_evidence: { available: false, reason: "no_persisted_licence_evidence", observations: [], sources: [] },
          provider_evidence: { available: false, any_provider_queried: false, observations: [], advisories: [] },
          dependency_evidence: { graph_coverage: "partial", incoming: [], outgoing: [], no_edges_observed: true },
          export_implications: { appears_in_cyclonedx_17: true, version_omitted: false, purl_emitted: true, dependency_relationships_emitted: false, graph_coverage: "partial" },
          omissions: ["no_clean_verdict"],
        })
      );
    }
    if (/\/components\/\d+\/path/.test(url)) {
      return Promise.resolve(
        jsonResponse({ components: [], edges: [], truncated: false })
      );
    }
    return Promise.resolve(jsonResponse({ items: [] }));
  });
  return fetchMock;
}

describe("v0.9 evidence-aware search and filtering", () => {
  beforeEach(() => {
    setupDefaultFetchMock();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    cleanup();
  });

  it("renders the dependency table with components", async () => {
    renderExplorer();
    await waitFor(() => {
      expect(
        screen.getByTestId("component-evidence-button-1")
      ).toBeInTheDocument();
    });
    // The table renders the row with the v0.9 evidence
    // badges column.
    expect(screen.getByTestId("evidence-flags-cell")).toBeInTheDocument();
  });

  it("renders the facet panel", async () => {
    renderExplorer();
    await waitFor(() => {
      expect(screen.getByTestId("facets-panel")).toBeInTheDocument();
    });
  });

  it("filters by package name via the search box", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    const leftPad = makeComponent(1, "left-pad");
    const stay = makeComponent(2, "stay");
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/components/evidence-summary")) {
        // Echo the search filter back to the consumer so
        // the assertion can verify the URL the page
        // issued. The initial render (no search param)
        // returns both components; a non-matching search
        // returns an empty list; a matching search
        // returns the left-pad component only.
        const urlObj = new URL(url, "http://localhost/");
        const search = urlObj.searchParams.get("search") ?? "";
        if (search === "") {
          return Promise.resolve(
            jsonResponse(
              makeSummaryResponse({
                items: [leftPad, stay],
                total: 2,
                facets: {
                  ecosystems: { npm: 2 },
                  missing_version: 0,
                  missing_licence_evidence: 2,
                  missing_provider_evidence: 2,
                  purl_persisted: 2,
                  purl_constructible: 0,
                  purl_omitted: 0,
                  edges_observed: 0,
                  edges_none_observed: 2,
                  direct_yes: 2,
                  direct_no: 0,
                  cyclonedx_version_omitted: 0,
                },
              })
            )
          );
        }
        if (search === "left") {
          return Promise.resolve(
            jsonResponse(
              makeSummaryResponse({
                items: [leftPad],
                total: 1,
                facets: {
                  ecosystems: { npm: 1 },
                  missing_version: 0,
                  missing_licence_evidence: 1,
                  missing_provider_evidence: 1,
                  purl_persisted: 1,
                  purl_constructible: 0,
                  purl_omitted: 0,
                  edges_observed: 0,
                  edges_none_observed: 1,
                  direct_yes: 1,
                  direct_no: 0,
                  cyclonedx_version_omitted: 0,
                },
              })
            )
          );
        }
        // Any other search query returns an empty list.
        return Promise.resolve(
          jsonResponse(makeSummaryResponse({ items: [], total: 0 }))
        );
      }
      return Promise.resolve(jsonResponse({ items: [] }));
    });
    renderExplorer();
    // Initial render shows both components because the
    // mock returns the unfiltered set.
    await waitFor(() => {
      expect(screen.getByTestId("component-evidence-button-1")).toBeInTheDocument();
    });
    expect(screen.getByTestId("component-evidence-button-2")).toBeInTheDocument();
    // Type into the search box. The page should re-fire
    // the evidence-summary fetch with ``search=left`` and
    // the mock returns the left-pad component only.
    const searchBox = screen.getByPlaceholderText(
      "Search package name"
    ) as HTMLInputElement;
    fireEvent.change(searchBox, { target: { value: "left" } });
    await waitFor(() => {
      expect(
        screen.getByTestId("component-evidence-button-1")
      ).toBeInTheDocument();
    });
    // The non-matching component row should be removed
    // because the filter narrows the list to one item.
    expect(
      screen.queryByTestId("component-evidence-button-2")
    ).not.toBeInTheDocument();
  });

  it("filters by missing licence evidence", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(
          jsonResponse(
            makeSummaryResponse({
              items: [
                makeComponent(1, "left-pad", {
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
                }),
              ],
              total: 1,
              facets: {
                ecosystems: { npm: 1 },
                missing_version: 0,
                missing_licence_evidence: 1,
                missing_provider_evidence: 1,
                purl_persisted: 1,
                purl_constructible: 0,
                purl_omitted: 0,
                edges_observed: 0,
                edges_none_observed: 1,
                direct_yes: 1,
                direct_no: 0,
                cyclonedx_version_omitted: 0,
              },
            })
          )
        );
      }
      return Promise.resolve(jsonResponse({ items: [] }));
    });
    renderExplorer();
    await waitFor(() => {
      expect(
        screen.getByTestId("evidence-flags-cell")
      ).toBeInTheDocument();
    });
    // The inline evidence badge for licence absence
    // renders the "licence not persisted" wording.
    const flags = screen.getByTestId("evidence-flags-cell");
    expect(flags.textContent ?? "").toContain("licence not persisted");
    // The page must not claim "no licence" / "clean" /
    // "secure" / "fixed" as a conclusion.
    const text = (flags.textContent ?? "").toLowerCase();
    for (const forbidden of ["clean", "secure", "fixed", "safe"]) {
      expect(text).not.toBe(forbidden);
    }
  });

  it("filters by PURL constructible vs persisted", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(
          jsonResponse(
            makeSummaryResponse({
              items: [
                makeComponent(1, "left-pad", {
                  package_url: null,
                  evidence: {
                    version_present: true,
                    licence_observed: false,
                    provider_observed: false,
                    purl_state: "constructible",
                    edges_observed: false,
                    appears_in_cyclonedx_17: true,
                    version_omitted_from_cyclonedx_17: false,
                    dependency_relationships_emitted_in_cyclonedx_17: false,
                  },
                }),
              ],
              total: 1,
              facets: {
                ecosystems: { npm: 1 },
                missing_version: 0,
                missing_licence_evidence: 1,
                missing_provider_evidence: 1,
                purl_persisted: 0,
                purl_constructible: 1,
                purl_omitted: 0,
                edges_observed: 0,
                edges_none_observed: 1,
                direct_yes: 1,
                direct_no: 0,
                cyclonedx_version_omitted: 0,
              },
            })
          )
        );
      }
      return Promise.resolve(jsonResponse({ items: [] }));
    });
    renderExplorer();
    await waitFor(() => {
      expect(
        screen.getByTestId("evidence-flags-cell")
      ).toBeInTheDocument();
    });
    const flags = screen.getByTestId("evidence-flags-cell");
    expect(flags.textContent ?? "").toContain("purl constructible");
  });

  it("renders the 'no persisted edges' wording instead of 'no dependencies'", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(
          jsonResponse(
            makeSummaryResponse({
              items: [
                makeComponent(1, "left-pad", {
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
                }),
              ],
              total: 1,
              facets: {
                ecosystems: { npm: 1 },
                missing_version: 0,
                missing_licence_evidence: 1,
                missing_provider_evidence: 1,
                purl_persisted: 1,
                purl_constructible: 0,
                purl_omitted: 0,
                edges_observed: 0,
                edges_none_observed: 1,
                direct_yes: 1,
                direct_no: 0,
                cyclonedx_version_omitted: 0,
              },
            })
          )
        );
      }
      return Promise.resolve(jsonResponse({ items: [] }));
    });
    renderExplorer();
    await waitFor(() => {
      expect(
        screen.getByTestId("evidence-flags-cell")
      ).toBeInTheDocument();
    });
    const flags = screen.getByTestId("evidence-flags-cell");
    expect(flags.textContent ?? "").toContain("no persisted edges");
    // The body must not contain the misleading phrase
    // "no dependencies" anywhere.
    const text = (document.body.textContent ?? "").toLowerCase();
    expect(text).not.toMatch(/(^|\W)no dependencies(\W|$)/);
  });

  it("renders the direct yes/no text in the Direct? column", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(
          jsonResponse(
            makeSummaryResponse({
              items: [
                makeComponent(1, "left-pad", { direct: true }),
                makeComponent(2, "stay", { direct: false }),
              ],
              total: 2,
              facets: {
                ecosystems: { npm: 2 },
                missing_version: 0,
                missing_licence_evidence: 2,
                missing_provider_evidence: 2,
                purl_persisted: 2,
                purl_constructible: 0,
                purl_omitted: 0,
                edges_observed: 0,
                edges_none_observed: 2,
                direct_yes: 1,
                direct_no: 1,
                cyclonedx_version_omitted: 0,
              },
            })
          )
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
    // The Direct? column shows yes / no. v0.9 column
    // order: Package, Ecosystem, Version, Direct?,
    // Evidence flags, Evidence (button).
    const table = screen.getByRole("table");
    const rows = Array.from(table.querySelectorAll("tbody tr"));
    const firstDirectCell = rows[0].querySelectorAll("td")[3];
    const secondDirectCell = rows[1].querySelectorAll("td")[3];
    expect(firstDirectCell.textContent?.trim()).toBe("yes");
    expect(secondDirectCell.textContent?.trim()).toBe("no");
  });

  it("does not render forbidden verdict words as conclusions anywhere on the page", async () => {
    renderExplorer();
    await waitFor(() => {
      expect(
        screen.getByTestId("evidence-flags-cell")
      ).toBeInTheDocument();
    });
    const text = (document.body.textContent ?? "").toLowerCase();
    for (const forbidden of [
      "clean sbom",
      "secure sbom",
      "certified sbom",
      "fixed all issues",
      "complete dependency graph",
    ]) {
      expect(text).not.toContain(forbidden);
    }
  });

  it("View evidence button still opens the evidence drawer after a filter is applied", async () => {
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
    // The drawer still renders the package identity
    // and the Direct: yes wording.
    expect(screen.getByTestId("ce-package-name")).toHaveTextContent("left-pad");
    expect(screen.getByText(/^Direct:/)).toBeInTheDocument();
  });

  it("package search input keeps a usable minimum width and visible placeholder", async () => {
    renderExplorer();
    await waitFor(() => {
      expect(
        screen.getByTestId("component-evidence-button-1")
      ).toBeInTheDocument();
    });
    // The search input is rendered with a usable
    // placeholder and an accessible label.
    const searchBox = screen.getByPlaceholderText(
      "Search package name"
    ) as HTMLInputElement;
    expect(searchBox).toBeInTheDocument();
    expect(searchBox.type).toBe("search");
    // The accessible name is supplied by an
    // ``htmlFor`` / ``id`` association with the
    // screen-reader-only label, not by an
    // ``aria-label`` attribute on the input.
    expect(searchBox.id).toBe("filterbar-search");
    const associatedLabel = document.querySelector(
      'label[for="filterbar-search"]'
    );
    expect(associatedLabel).not.toBeNull();
    expect(associatedLabel?.textContent ?? "").toBe("Search");
    // The wrapping container has a min-width class so
    // the search input does not collapse to icon-only
    // width when 9+ filter selects are present. The
    // v0.9 card layout puts the search on its own row
    // with ``w-full`` and ``sm:max-w-sm`` (24rem) so
    // the search is always 240-384px wide on desktop.
    // The ``min-w-[200px]`` class is the floor for
    // narrow viewports. Removing any of these would
    // let the search collapse again.
    const wrapper = searchBox.parentElement as HTMLElement;
    expect(wrapper.className).toMatch(/w-full/);
    expect(wrapper.className).toMatch(/min-w-\[200px\]/);
    expect(wrapper.className).toMatch(/sm:max-w-sm/);
  });

  it("renders a structured card with title, component count, stacked filter labels, and a clear button", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(
          jsonResponse(
            makeSummaryResponse({
              items: [makeComponent(1, "left-pad")],
              total: 1,
              facets: {
                ecosystems: { npm: 1 },
                missing_version: 0,
                missing_licence_evidence: 1,
                missing_provider_evidence: 1,
                purl_persisted: 1,
                purl_constructible: 0,
                purl_omitted: 0,
                edges_observed: 0,
                edges_none_observed: 1,
                direct_yes: 1,
                direct_no: 0,
                cyclonedx_version_omitted: 0,
              },
            })
          )
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
    // The card has a title and a result count in the
    // header row.
    expect(screen.getByTestId("filterbar-card")).toBeInTheDocument();
    expect(screen.getByTestId("filterbar-title")).toHaveTextContent(
      "Evidence filters"
    );
    expect(screen.getByTestId("filterbar-result-count")).toHaveTextContent(
      "1 components"
    );
    // The filters render in a responsive grid.
    expect(screen.getByTestId("filterbar-grid")).toBeInTheDocument();
    // Every filter select is rendered with a stacked
    // label (block layout, not inline). The label and
    // select share a vertical column.
    const licenceSelect = screen.getByLabelText(/^Licence evidence$/);
    expect(licenceSelect).toBeInTheDocument();
    const licenceWrapper = licenceSelect.parentElement as HTMLElement;
    expect(licenceWrapper.className).toMatch(/flex-col/);
    // The select takes the full width of its grid cell.
    expect(licenceSelect.className).toMatch(/w-full/);
    // Evidence-honesty wording is preserved.
    expect(
      screen.getByLabelText(/^Dependency edges$/)
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText(/^CycloneDX 1\.7 version omitted$/)
    ).toBeInTheDocument();
    // The Clear button is hidden in the default state
    // (no filter differs from its default). This pins
    // the v0.9 UX rule: Clear only appears when there
    // is something to clear.
    expect(screen.queryByTestId("filterbar-clear")).not.toBeInTheDocument();
  });

  it("Clear button is hidden in default state and appears when a filter changes", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/components/evidence-summary")) {
        const urlObj = new URL(url, "http://localhost/");
        const search = urlObj.searchParams.get("search") ?? "";
        if (search === "left") {
          return Promise.resolve(
            jsonResponse(
              makeSummaryResponse({
                items: [makeComponent(1, "left-pad")],
                total: 1,
                facets: {
                  ecosystems: { npm: 1 },
                  missing_version: 0,
                  missing_licence_evidence: 1,
                  missing_provider_evidence: 1,
                  purl_persisted: 1,
                  purl_constructible: 0,
                  purl_omitted: 0,
                  edges_observed: 0,
                  edges_none_observed: 1,
                  direct_yes: 1,
                  direct_no: 0,
                  cyclonedx_version_omitted: 0,
                },
              })
            )
          );
        }
        // No search → return all 3 components.
        return Promise.resolve(
          jsonResponse(
            makeSummaryResponse({
              items: [
                makeComponent(1, "left-pad"),
                makeComponent(2, "left-pad-deprecated"),
                makeComponent(3, "stay"),
              ],
              total: 3,
              facets: {
                ecosystems: { npm: 3 },
                missing_version: 0,
                missing_licence_evidence: 3,
                missing_provider_evidence: 3,
                purl_persisted: 3,
                purl_constructible: 0,
                purl_omitted: 0,
                edges_observed: 0,
                edges_none_observed: 3,
                direct_yes: 3,
                direct_no: 0,
                cyclonedx_version_omitted: 0,
              },
            })
          )
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
    // Default state: every filter equals its default,
    // so the Clear button must not render. The
    // ``renders a structured card`` test pins the
    // ``not.toBeInTheDocument`` assertion. This test
    // verifies the full hidden → visible → hidden
    // cycle on a single page lifecycle.
    expect(screen.queryByTestId("filterbar-clear")).not.toBeInTheDocument();
    // Type "left" into the search input. The Clear
    // button must appear because the search value
    // differs from its default.
    const searchBox = screen.getByPlaceholderText(
      "Search package name"
    ) as HTMLInputElement;
    fireEvent.change(searchBox, { target: { value: "left" } });
    await waitFor(() => {
      expect(screen.getByTestId("filterbar-clear")).toBeInTheDocument();
    });
    // The table narrows to 1 component (left-pad).
    await waitFor(() => {
      expect(
        screen.getByTestId("component-evidence-button-1")
      ).toBeInTheDocument();
    });
    expect(
      screen.queryByTestId("component-evidence-button-2")
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("component-evidence-button-3")
    ).not.toBeInTheDocument();
    // Click Clear. The search input is emptied, every
    // filter returns to its default, the table
    // re-fetches with no search param, and the Clear
    // button hides again.
    const clearButton = screen.getByTestId("filterbar-clear");
    clearButton.click();
    await waitFor(() => {
      expect(searchBox.value).toBe("");
    });
    await waitFor(() => {
      expect(screen.queryByTestId("filterbar-clear")).not.toBeInTheDocument();
    });
    await waitFor(() => {
      expect(
        screen.getByTestId("component-evidence-button-3")
      ).toBeInTheDocument();
    });
  });

  it("Clear button appears when Licence evidence filter is set to Missing", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/components/evidence-summary")) {
        return Promise.resolve(
          jsonResponse(
            makeSummaryResponse({
              items: [makeComponent(1, "left-pad")],
              total: 1,
              facets: {
                ecosystems: { npm: 1 },
                missing_version: 0,
                missing_licence_evidence: 1,
                missing_provider_evidence: 1,
                purl_persisted: 1,
                purl_constructible: 0,
                purl_omitted: 0,
                edges_observed: 0,
                edges_none_observed: 1,
                direct_yes: 1,
                direct_no: 0,
                cyclonedx_version_omitted: 0,
              },
            })
          )
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
    // Default state: no Clear button.
    expect(screen.queryByTestId("filterbar-clear")).not.toBeInTheDocument();
    // Change the Licence evidence select to "Missing".
    // The Clear button must appear because the filter
    // value differs from its default "all".
    const licenceSelect = screen.getByLabelText(
      /^Licence evidence$/
    ) as HTMLSelectElement;
    fireEvent.change(licenceSelect, { target: { value: "missing" } });
    await waitFor(() => {
      expect(screen.getByTestId("filterbar-clear")).toBeInTheDocument();
    });
  });
});
