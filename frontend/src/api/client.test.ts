import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiAbortError,
  ApiClientError,
  ApiTimeoutError,
  apiClient,
  categorizeError,
  describeError,
  readDevFixturesEnabled,
} from "@/api/client";
import { isNotImplemented, fetchOrFallback } from "@/api/fallback";

describe("readDevFixturesEnabled", () => {
  it("returns false by default", () => {
    expect(readDevFixturesEnabled()).toBe(false);
  });
});

describe("categorizeError", () => {
  it("maps ApiAbortError to cancelled", () => {
    const err = new ApiAbortError();
    expect(categorizeError(err)).toBe("cancelled");
  });

  it("maps ApiTimeoutError to timeout", () => {
    const err = new ApiTimeoutError(1000);
    expect(categorizeError(err)).toBe("timeout");
  });

  it("maps a 429 to rate_limited", () => {
    const err = new ApiClientError({
      code: "rate_limited",
      message: "Too many",
      httpStatus: 429,
    });
    expect(categorizeError(err)).toBe("rate_limited");
  });

  it("maps a 404 to not_found", () => {
    const err = new ApiClientError({
      code: "not_found",
      message: "Not found",
      httpStatus: 404,
    });
    expect(categorizeError(err)).toBe("not_found");
  });

  it("maps a 422 to validation", () => {
    const err = new ApiClientError({
      code: "validation_error",
      message: "Bad",
      httpStatus: 422,
    });
    expect(categorizeError(err)).toBe("validation");
  });

  it("maps a 502 to provider_unavailable", () => {
    const err = new ApiClientError({
      code: "provider_unavailable",
      message: "Bad gateway",
      httpStatus: 502,
    });
    expect(categorizeError(err)).toBe("provider_unavailable");
  });

  it("maps a 500 to server", () => {
    const err = new ApiClientError({
      code: "internal",
      message: "Boom",
      httpStatus: 500,
    });
    expect(categorizeError(err)).toBe("server");
  });

  it("maps a 409 to duplicate", () => {
    const err = new ApiClientError({
      code: "duplicate",
      message: "Already exists",
      httpStatus: 409,
    });
    expect(categorizeError(err)).toBe("duplicate");
  });

  it("maps a network error to network", () => {
    const err = new ApiClientError({
      code: "network_error",
      message: "down",
      httpStatus: 0,
    });
    expect(categorizeError(err)).toBe("network");
  });

  it("falls back to unknown for non-Error inputs", () => {
    expect(categorizeError("nope")).toBe("unknown");
    expect(categorizeError(undefined)).toBe("unknown");
  });
});

describe("describeError", () => {
  it("returns the ApiClientError message", () => {
    const err = new ApiClientError({ code: "x", message: "nope", httpStatus: 400 });
    expect(describeError(err)).toBe("nope");
  });

  it("returns the Error message for plain errors", () => {
    expect(describeError(new Error("plain"))).toBe("plain");
  });

  it("returns the generic message for unknown inputs", () => {
    expect(describeError(null)).toBe("Unknown error.");
  });
});

describe("isNotImplemented", () => {
  it("treats a 404 as not implemented", () => {
    const err = new ApiClientError({ code: "not_found", message: "x", httpStatus: 404 });
    expect(isNotImplemented(err)).toBe(true);
  });

  it("treats a 501 as not implemented", () => {
    const err = new ApiClientError({ code: "x", message: "x", httpStatus: 501 });
    expect(isNotImplemented(err)).toBe(true);
  });

  it("treats a 405 as not implemented", () => {
    const err = new ApiClientError({ code: "x", message: "x", httpStatus: 405 });
    expect(isNotImplemented(err)).toBe(true);
  });

  it("does not treat a 500 as not implemented", () => {
    const err = new ApiClientError({ code: "internal", message: "x", httpStatus: 500 });
    expect(isNotImplemented(err)).toBe(false);
  });

  it("does not treat a network error as not implemented", () => {
    const err = new ApiClientError({ code: "network_error", message: "x", httpStatus: 0 });
    expect(isNotImplemented(err)).toBe(false);
  });
});

describe("fetchOrFallback", () => {
  it("returns the data on success", async () => {
    const out = await fetchOrFallback(async () => "value", "fallback");
    expect(out).toBe("value");
  });

  it("returns the fallback when the endpoint is not implemented", async () => {
    const err = new ApiClientError({ code: "not_found", message: "x", httpStatus: 404 });
    const out = await fetchOrFallback(async () => { throw err; }, "fallback");
    expect(out).toBe("fallback");
  });

  it("rethrows when the error is real", async () => {
    const err = new ApiClientError({ code: "internal", message: "boom", httpStatus: 500 });
    await expect(
      fetchOrFallback(async () => { throw err; }, "fallback")
    ).rejects.toBe(err);
  });
});

describe("apiClient", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("encodes query parameters safely", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);
    const result = await apiClient.get<{ ok: boolean }>("/repositories", {
      query: { page: 1, page_size: 25, search: undefined, archived: null },
    });
    expect(result.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("page=1");
    expect(url).toContain("page_size=25");
    expect(url).not.toContain("search=");
    expect(url).not.toContain("archived=");
  });

  it("throws a structured error envelope on non-2xx responses", async () => {
    const fetchMock = vi.fn().mockImplementation(
      () =>
        Promise.resolve(
          new Response(
            JSON.stringify({ error: { code: "not_found", message: "missing" } }),
            { status: 404, headers: { "content-type": "application/json" } }
          )
        )
    );
    vi.stubGlobal("fetch", fetchMock);
    let captured: ApiClientError | null = null;
    try {
      await apiClient.get("/missing");
    } catch (err) {
      captured = err as ApiClientError;
    }
    expect(captured).toBeInstanceOf(ApiClientError);
    if (captured) {
      expect(captured.apiError.code).toBe("not_found");
      expect(captured.apiError.httpStatus).toBe(404);
    }
  });

  it("uses credentials: 'omit' so no cookies are sent", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("null", { status: 200, headers: { "content-type": "application/json" } })
    );
    vi.stubGlobal("fetch", fetchMock);
    await apiClient.get("/x");
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.credentials).toBe("omit");
  });
});
