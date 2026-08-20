import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useRefresh } from "@/hooks/useRefresh";

/**
 * v2.1.3 shared application-data refresh hook tests.
 *
 * The manual-QA pass surfaced two issues with the
 * inline refresh implementation:
 *
 *  1. The button label did not change while a
 *     request was in flight, so the operator
 *     could not tell whether the click had
 *     registered.
 *  2. Two synchronous clicks could both enqueue
 *     a request because the React state is
 *     asynchronous and the guard ran after the
 *     first state had propagated.
 *
 * The new hook is the single chokepoint for the
 * guard, the label, the accessibility, and the
 * failure-preservation behaviour. The tests
 * below pin the contract so a future regression
 * cannot reintroduce the inline implementation.
 *
 * The tests use ``await act(async () => {...})`` to
 * let the Promise-based fetchers run their
 * microtasks before the assertion. A plain
 * ``act(() => {...})`` block does not flush
 * microtasks, so the fetcher would not yet have
 * been called when the assertion runs.
 */

describe("useRefresh", () => {
  it("returns the idle label and disabled=false on first render", () => {
    const { result } = renderHook(() =>
      useRefresh({ fetcher: () => Promise.resolve("v1") }),
    );
    expect(result.current.label).toBe("Refresh");
    expect(result.current.disabled).toBe(false);
    expect(result.current.ariaBusy).toBe(false);
    expect(result.current.isRefreshing).toBe(false);
    expect(result.current.data).toBeUndefined();
    expect(result.current.error).toBeUndefined();
  });

  it("transitions to refreshing while the fetcher is pending", async () => {
    const fetcher = vi.fn(() => new Promise<string>(() => undefined));
    const { result } = renderHook(() => useRefresh({ fetcher }));
    await act(async () => {
      result.current.refresh();
    });
    // Immediately after the click, the label
    // transitions to ``Refreshing…`` and the
    // button is disabled. The state change is
    // synchronous because the pending ref is set
    // *before* any setState call, so the very
    // next render is the in-flight state.
    expect(result.current.label).toBe("Refreshing…");
    expect(result.current.disabled).toBe(true);
    expect(result.current.ariaBusy).toBe(true);
    expect(result.current.isRefreshing).toBe(true);
  });

  it("blocks duplicate concurrent invocations", async () => {
    const fetcher = vi.fn(() => new Promise<number>(() => undefined));
    const { result } = renderHook(() => useRefresh({ fetcher }));
    await act(async () => {
      result.current.refresh();
      // The second click is synchronous with
      // the first. The ``pendingRef`` guard
      // inside the hook must drop it without
      // ever calling the fetcher again.
      result.current.refresh();
      result.current.refresh();
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("preserves the previous payload when the fetcher fails", async () => {
    const fetcher = vi.fn();
    fetcher.mockResolvedValueOnce("first");
    fetcher.mockRejectedValueOnce(new Error("boom"));
    const { result } = renderHook(() => useRefresh({ fetcher }));
    await act(async () => {
      result.current.refresh();
      await Promise.resolve();
    });
    expect(result.current.data).toBe("first");
    expect(result.current.error).toBeUndefined();
    await act(async () => {
      result.current.refresh();
      await Promise.resolve();
    });
    expect(result.current.data).toBe("first");
    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.state).toBe("error");
  });

  it("reports state=error and surfaces the error to onError", async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error("explode"));
    const onError = vi.fn();
    const { result } = renderHook(() =>
      useRefresh({ fetcher, onError }),
    );
    await act(async () => {
      result.current.refresh();
      await Promise.resolve();
    });
    expect(onError).toHaveBeenCalledWith(
      expect.any(Error),
      undefined,
    );
    expect(result.current.state).toBe("error");
    expect(result.current.label).toBe("Refresh");
  });

  it("never erases the data on failure", async () => {
    const fetcher = vi.fn();
    fetcher.mockResolvedValueOnce("seed");
    fetcher.mockRejectedValueOnce(new Error("down"));
    const { result } = renderHook(() => useRefresh({ fetcher }));
    await act(async () => {
      result.current.refresh();
      await Promise.resolve();
    });
    expect(result.current.data).toBe("seed");
    await act(async () => {
      result.current.refresh();
      await Promise.resolve();
    });
    expect(result.current.data).toBe("seed");
    expect(result.current.error).toBeInstanceOf(Error);
  });

  it("returns the initial data on first render when supplied", () => {
    const { result } = renderHook(() =>
      useRefresh({
        fetcher: () => Promise.resolve(""),
        initialData: "seed",
      }),
    );
    expect(result.current.data).toBe("seed");
    expect(result.current.hasLoaded).toBe(true);
  });

  it("forwards the fetcher result to onSuccess", async () => {
    const fetcher = vi.fn().mockResolvedValue("payload");
    const onSuccess = vi.fn();
    const { result } = renderHook(() =>
      useRefresh({ fetcher, onSuccess }),
    );
    await act(async () => {
      result.current.refresh();
      await Promise.resolve();
    });
    expect(onSuccess).toHaveBeenCalledWith("payload", undefined);
  });
});
