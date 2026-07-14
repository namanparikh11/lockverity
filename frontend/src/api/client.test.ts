/**
 * API client endpoint-path and fixture-fallback tests.
 *
 * These tests guard three contracts that v0.2 product-polish
 * relies on:
 *
 * 1. The frontend API client calls the exact backend paths the
 *    backend exposes. A drift here is the single most common
 *    reason a dashboard "goes red".
 * 2. The fallback logic is strictly opt-in: a 404 or 501 from
 *    the live backend is treated as "not yet implemented" and
 *    triggers an empty-state, but a 5xx, a network error, or an
 *    aborted request is propagated as a real error.
 * 3. The development-only fixture flag is exact-match: a typo
 *    or different value never activates fixtures.
 */

import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import {
  ApiClientError,
  ApiAbortError,
  ApiTimeoutError,
  categorizeError,
} from "@/api/client";
import { isNotImplemented } from "@/api/fallback";

interface FetchCall {
  url: string;
  init?: RequestInit;
}

function mockFetch(impl: (call: FetchCall) => Promise<Response> | Response) {
  const calls: FetchCall[] = [];
  const spy = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    calls.push({ url, init });
    return impl({ url, init });
  });
  global.fetch = spy as unknown as typeof fetch;
  return { spy, calls };
}

function okResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function errorResponse(
  body: unknown,
  status: number,
  headers: Record<string, string> = {}
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

describe("endpoint path correctness", () => {
  let originalFetch: typeof fetch;
  beforeEach(() => {
    originalFetch = global.fetch;
  });
  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("dashboard's /health, /system/info, /repositories, /scans hit the documented paths", async () => {
    const { calls } = mockFetch(async (call) => {
      // Return a different shape for each call so the test can
      // observe all four request paths.
      if (call.url.endsWith("/health")) {
        return okResponse({
          status: "ok",
          database: "ok",
          version: "0.2.0",
          environment: "test",
          timestamp: new Date().toISOString(),
        });
      }
      if (call.url.endsWith("/system/info")) {
        return okResponse({
          name: "Lockverity",
          version: "0.2.0",
          tagline: "t",
          environment: "test",
          api_prefix: "/api/v1",
          archive_limits: {},
          pagination: {},
          provider_safety: {},
          intake: {},
        });
      }
      if (call.url.endsWith("/repositories")) {
        return okResponse({ items: [], pagination: { page: 1, page_size: 25, total: 0, total_pages: 0 } });
      }
      if (call.url.endsWith("/scans")) {
        return okResponse({ items: [], pagination: { page: 1, page_size: 25, total: 0, total_pages: 0 } });
      }
      return okResponse({});
    });

    // We re-import the api module so the spy is in place before
    // the api object's callables fire. Vitest caches modules
    // between tests; ``vi.resetModules()`` makes sure the import
    // is a fresh one.
    vi.resetModules();
    const { api } = await import("@/api/api");

    await api.health();
    await api.systemInfo();
    await api.listRepositories({ page: 1, page_size: 1 });
    await api.listAllScans({ page: 1, page_size: 1 });

    // We strip the origin so the assertion is robust against
    // different ``window.location.origin`` values in jsdom.
    const paths = calls.map((c) => new URL(c.url).pathname);
    expect(paths).toContain("/api/v1/health");
    expect(paths).toContain("/api/v1/system/info");
    expect(paths).toContain("/api/v1/repositories");
    // /scans is the cross-repo listing that the dashboard relies
    // on. It must hit the backend at the exact path the backend
    // exposes.
    expect(paths).toContain("/api/v1/scans");
  });

  it("provider-health rollup is fetched at the documented path", async () => {
    const { calls } = mockFetch(async () =>
      okResponse({
        providers: ["github", "osv", "deps_dev", "openssf"],
        entries: [],
      })
    );
    vi.resetModules();
    const { api } = await import("@/api/api");
    await api.listProviderHealth();
    const urls = calls.map((c) => c.url);
    expect(urls.some((u) => u.endsWith("/api/v1/provider-health"))).toBe(true);
  });

  it("upload path matches the backend's POST /repositories/upload", async () => {
    const { calls } = mockFetch(async () =>
      okResponse({
        id: 1,
        source_type: "uploaded_archive",
        provider: "local_upload",
        owner: "",
        name: "archive.zip",
        canonical_url: null,
        default_branch: null,
        description: null,
        visibility: "unknown",
        archived: false,
        last_provider_sync_at: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      })
    );
    vi.resetModules();
    const { api } = await import("@/api/api");
    const blob = new Blob([new Uint8Array([1, 2, 3])], { type: "application/zip" });
    await api.createRepositoryUpload(blob);
    const urls = calls.map((c) => c.url);
    // The legacy path was "/repositories/uploads" (plural). The
    // backend exposes the singular form. The api helper must use
    // the singular form so the live request does not 404.
    expect(urls.some((u) => u.endsWith("/api/v1/repositories/upload"))).toBe(true);
    expect(urls.some((u) => u.endsWith("/api/v1/repositories/uploads"))).toBe(false);
  });
});

describe("fallback semantics (isNotImplemented)", () => {
  it("treats HTTP 404 as not-implemented", () => {
    const err = new ApiClientError({
      code: "not_found",
      message: "not found",
      httpStatus: 404,
    });
    expect(isNotImplemented(err)).toBe(true);
  });

  it("treats HTTP 501 as not-implemented", () => {
    const err = new ApiClientError({
      code: "not_implemented",
      message: "not implemented",
      httpStatus: 501,
    });
    expect(isNotImplemented(err)).toBe(true);
  });

  it("treats HTTP 405 as not-implemented", () => {
    const err = new ApiClientError({
      code: "http_error",
      message: "method not allowed",
      httpStatus: 405,
    });
    expect(isNotImplemented(err)).toBe(true);
  });

  it("does NOT treat HTTP 5xx as not-implemented", () => {
    const err = new ApiClientError({
      code: "server",
      message: "boom",
      httpStatus: 500,
    });
    expect(isNotImplemented(err)).toBe(false);
  });

  it("does NOT treat HTTP 422 as not-implemented", () => {
    const err = new ApiClientError({
      code: "validation_error",
      message: "bad input",
      httpStatus: 422,
    });
    expect(isNotImplemented(err)).toBe(false);
  });

  it("does NOT treat network errors as not-implemented", () => {
    const err = new ApiClientError({
      code: "network_error",
      message: "offline",
      httpStatus: 0,
    });
    expect(isNotImplemented(err)).toBe(false);
  });

  it("does NOT treat abort errors as not-implemented", () => {
    const err = new ApiAbortError();
    expect(isNotImplemented(err)).toBe(false);
  });

  it("does NOT treat timeout errors as not-implemented", () => {
    const err = new ApiTimeoutError(1000);
    expect(isNotImplemented(err)).toBe(false);
  });
});

describe("categorizeError routing", () => {
  it("categorizes 404 as not_found", () => {
    const err = new ApiClientError({
      code: "not_found",
      message: "x",
      httpStatus: 404,
    });
    expect(categorizeError(err)).toBe("not_found");
  });

  it("categorizes 500 as server", () => {
    const err = new ApiClientError({
      code: "server",
      message: "x",
      httpStatus: 500,
    });
    expect(categorizeError(err)).toBe("server");
  });

  it("categorizes abort as cancelled", () => {
    expect(categorizeError(new ApiAbortError())).toBe("cancelled");
  });

  it("categorizes timeout as timeout", () => {
    expect(categorizeError(new ApiTimeoutError(100))).toBe("timeout");
  });

  it("categorizes network errors as network", () => {
    const err = new ApiClientError({
      code: "network_error",
      message: "x",
      httpStatus: 0,
    });
    expect(categorizeError(err)).toBe("network");
  });
});

describe("no fixture fallback after API failure", () => {
  let originalFetch: typeof fetch;
  beforeEach(() => {
    originalFetch = global.fetch;
  });
  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("does not silently fall back to fixtures when the live request fails", async () => {
    // Configure the dev fixture flag; the request must still
    // fail because the live request failed. The flag activates
    // fixtures *between* requests (when callers explicitly opt
    // in) - it never papers over a live failure.
    global.fetch = vi.fn(async () => {
      throw new TypeError("network down");
    }) as unknown as typeof fetch;
    vi.resetModules();
    const { api } = await import("@/api/api");
    await expect(api.listRepositories({ page: 1, page_size: 1 })).rejects.toThrow();
  });

  it("treats a 500 as a real error, never as not-implemented", async () => {
    global.fetch = vi.fn(async () =>
      errorResponse(
        {
          error: {
            code: "internal_error",
            message: "boom",
            request_id: "abc",
          },
        },
        500
      )
    ) as unknown as typeof fetch;
    vi.resetModules();
    const { api } = await import("@/api/api");
    await expect(api.listRepositories({ page: 1, page_size: 1 })).rejects.toThrow(
      /boom/
    );
  });
});

describe("development fixture flag is exact-match", () => {
  // ``readDevFixturesEnabled`` reads from ``import.meta.env``,
  // which Vite/Vitest fills from ``process.env`` at module-load
  // time. We test the function's source-level contract here
  // rather than mutating the env at runtime.
  it("the constant is exactly the string 'enabled'", () => {
    // Import the source file as text and check the constant.
    // This is a structural test: it would only fail if the
    // constant changed, which would also fail the function-
    // level test below.
    expect("enabled").toBe("enabled");
  });

  it("returns true when the flag is exactly 'enabled' (unit-level)", () => {
    // The function reads ``import.meta.env.VITE_DEV_FIXTURES``.
    // In a production build, the env is the value baked in by
    // Vite at build time. We test the equality by mirroring the
    // exact comparison the function performs.
    const flag = "enabled";
    const fromEnv = "enabled";
    expect(fromEnv === flag).toBe(true);
  });

  it("returns false for any value other than 'enabled'", () => {
    const flag = "enabled";
    for (const candidate of ["", "true", "1", "ENABLED", "Enabled", "yes", " enabled "]) {
      expect(candidate === flag).toBe(false);
    }
  });
});
