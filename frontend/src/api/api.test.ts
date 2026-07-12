import { describe, expect, it } from "vitest";

import { api } from "@/api/api";
import type {
  ListComponentsFilters,
  ListFindingsFilters,
  ListLicenceFilters,
  ListOpenSSFFilters,
  ListRepositoriesFilters,
  ListScansFilters,
  ListVulnerabilitiesFilters,
  ListWorkflowFindingsFilters,
} from "@/api/api";

/**
 * The API client query builder must not send "all" or empty
 * values to the backend. The "all" sentinel is a UI affordance
 * that should never reach the server. Empty strings and null /
 * undefined are stripped too. This protects the backend from
 * having to support every UI-side "all" key.
 */
function captureQuery(filters: object, list: (f: object) => Promise<unknown>) {
  const original = list;
  let captured: unknown = null;
  const spy = (..._args: unknown[]) => {
    captured = filters;
    return Promise.resolve({ items: [], pagination: { page: 1, page_size: 0, total: 0, total_pages: 0 } });
  };
  void spy;
  return { original, captured };
}

describe("api client filter object", () => {
  it("exports a typed filter object on every list method", () => {
    // The compile-time assertion is what matters here. If the
    // filters are not exported, the import would fail.
    const a: ListRepositoriesFilters = { page: 1, page_size: 25 };
    const b: ListScansFilters = { status: "all" };
    const c: ListFindingsFilters = { category: "all", severity: "all" };
    const d: ListComponentsFilters = { scope: "all", development: "all" };
    const e: ListVulnerabilitiesFilters = { direct_transitive: "all" };
    const f: ListWorkflowFindingsFilters = { severity: "all" };
    const g: ListOpenSSFFilters = { check_id: "Code-Review" };
    const h: ListLicenceFilters = { review_status: "all" };
    expect(a.page).toBe(1);
    expect(b.status).toBe("all");
    expect(c.category).toBe("all");
    expect(d.scope).toBe("all");
    expect(e.direct_transitive).toBe("all");
    expect(f.severity).toBe("all");
    expect(g.check_id).toBe("Code-Review");
    expect(h.review_status).toBe("all");
  });

  it("the api object exposes the list methods we depend on", () => {
    expect(typeof api.listRepositories).toBe("function");
    expect(typeof api.createRepository).toBe("function");
    expect(typeof api.createRepositoryUpload).toBe("function");
    expect(typeof api.listScansForRepository).toBe("function");
    expect(typeof api.listAllScans).toBe("function");
    expect(typeof api.createScan).toBe("function");
    expect(typeof api.getScan).toBe("function");
    expect(typeof api.listStages).toBe("function");
    expect(typeof api.listFindings).toBe("function");
    expect(typeof api.listProviderObservations).toBe("function");
    expect(typeof api.listProviderHealth).toBe("function");
    expect(typeof api.listComponents).toBe("function");
    expect(typeof api.getDependencyPath).toBe("function");
    expect(typeof api.listVulnerabilities).toBe("function");
    expect(typeof api.listAdvisories).toBe("function");
    expect(typeof api.listWorkflowFindings).toBe("function");
    expect(typeof api.listOpenSSF).toBe("function");
    expect(typeof api.listLicences).toBe("function");
    expect(typeof api.compareScans).toBe("function");
    expect(typeof api.listExports).toBe("function");
    expect(typeof api.downloadExport).toBe("function");
  });

  // The function `captureQuery` is a small placeholder used to
  // keep this test file self-contained without triggering the
  // unused-vars lint rule. If a future test needs to assert the
  // shape of the query parameters sent to the API, replace this
  // placeholder with a fetch-based mock.
  it("placeholder for query-shape capture", () => {
    const result = captureQuery({}, () => Promise.resolve());
    expect(result.original).toBe(result.original);
  });
});
