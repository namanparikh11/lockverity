/**
 * Tests for the v0.3 polling hook.
 *
 * The polling hook is the single mechanism the ScanDetailsPage
 * uses to follow a scan from queued to terminal. It must:
 *
 * - stop polling the moment a scan reaches a terminal state
 *   (completed / partial / failed / cancelled);
 * - honour the hard cap on the number of polls so a
 *   never-completing scan does not poll forever;
 * - abort its in-flight request on unmount so the next
 *   render does not race;
 * - surface a real network error rather than silently
 *   falling back to a fixture.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

import { usePolling } from "@/api/hooks";
import type { Scan } from "@/api/types";

const SCAN_RUNNING: Scan = {
  id: 1,
  repository_id: 1,
  status: "running",
  trigger_type: "manual",
  requested_ref: null,
  resolved_commit_sha: null,
  analyzer_version: null,
  started_at: null,
  completed_at: null,
  failure_code: null,
  failure_summary: null,
  created_at: "2026-07-14T00:00:00Z",
  updated_at: "2026-07-14T00:00:00Z",
};

const SCAN_COMPLETED: Scan = {
  ...SCAN_RUNNING,
  status: "completed",
  completed_at: "2026-07-14T00:01:00Z",
};

function makeFetcher(
  responses: Scan[]
): (signal: AbortSignal) => Promise<Scan> {
  let i = 0;
  return (signal: AbortSignal) =>
    new Promise<Scan>((resolve, reject) => {
      signal.addEventListener("abort", () => reject(new Error("aborted")));
      if (i < responses.length) {
        const value = responses[i++];
        Promise.resolve().then(() => resolve(value));
      } else {
        // Return the last value again if we run out of canned
        // responses; this keeps the poll loop in flight.
        Promise.resolve().then(() => resolve(responses[responses.length - 1]));
      }
    });
}

describe("usePolling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("stops polling the moment the scan reaches a terminal state", async () => {
    const fetcher = makeFetcher([SCAN_RUNNING, SCAN_RUNNING, SCAN_COMPLETED]);
    const { result } = renderHook(() =>
      usePolling<Scan>(fetcher, [], {
        isTerminal: (v) =>
          v.status === "completed" ||
          v.status === "partial" ||
          v.status === "failed" ||
          v.status === "cancelled",
        intervalMs: 1000,
        maxPolls: 10,
      })
    );
    // First tick runs immediately.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.data?.status).toBe("running");
    expect(result.current.active).toBe(true);
    // Advance through two more ticks.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.data?.status).toBe("completed");
    expect(result.current.active).toBe(false);
  });

  it("honours the maxPolls cap", async () => {
    const fetcher = makeFetcher([SCAN_RUNNING]);
    const { result } = renderHook(() =>
      usePolling<Scan>(fetcher, [], {
        isTerminal: () => false,
        intervalMs: 100,
        maxPolls: 3,
      })
    );
    // First tick is immediate.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.polls).toBe(1);
    // Each subsequent tick is one interval later.
    for (let i = 0; i < 5; i++) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(100);
      });
    }
    // After the cap, polling stops.
    expect(result.current.polls).toBeLessThanOrEqual(3);
    expect(result.current.active).toBe(false);
  });

  it("surfaces network errors without falling back to a fixture", async () => {
    const fetcher = vi.fn(
      () =>
        new Promise<Scan>((_resolve, reject) => {
          setTimeout(() => reject(new Error("network down")), 0);
        })
    );
    const { result } = renderHook(() =>
      usePolling<Scan>(fetcher, [], {
        isTerminal: () => false,
        intervalMs: 1000,
        maxPolls: 5,
      })
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.active).toBe(false);
  });

  it("aborts the in-flight request on unmount", async () => {
    const abortSpy = vi.fn();
    const fetcher = (_signal: AbortSignal): Promise<Scan> =>
      new Promise<Scan>((_resolve, reject) => {
        // The signal is wired up by the hook; we listen for
        // aborts to confirm the hook called .abort() on
        // unmount.
        _signal.addEventListener("abort", () => {
          abortSpy();
          reject(new Error("aborted"));
        });
      });
    const { unmount } = renderHook(() =>
      usePolling<Scan>(fetcher, [], {
        isTerminal: () => false,
        intervalMs: 1000,
        maxPolls: 5,
      })
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    unmount();
    expect(abortSpy).toHaveBeenCalled();
  });

  // -------------------------------------------------------------------------
  // Dependency-cycle reset regression (v2.0.6 cycle-7-final)
  // -------------------------------------------------------------------------
  //
  // The polling hook stores the latest data in a ref so the
  // event-driven ``tick`` callback observes terminal state
  // without paying the render-cost of a state read. The ref
  // is updated by a ``useLayoutEffect`` (the canonical
  // "latest ref" pattern). When the polling hook's
  // dependency list changes (for example, the operator
  // switches from watching scan A to watching scan B, or
  // the page swaps the fetcher entirely), the cycle is
  // supposed to start fresh.
  //
  // The pre-correction implementation only cleared
  // ``dataRef.current`` via the layout effect, which runs
  // *after* the next render. The cycle effect's first
  // synchronous ``tick`` read the *prior* cycle's
  // terminal value from ``dataRef.current`` and short-
  // circuited without ever calling the new fetcher. A
  // disposable Codex probe observed zero calls to the
  // replacement fetcher in that state.
  //
  // The correction: ``dataRef.current = null`` is written
  // synchronously at the top of the cycle effect, before
  // the first ``tick``. The tests below pin the corrected
  // behaviour.
  it("invokes the new fetcher when a dependency changes after a prior cycle went terminal", async () => {
    let callCount = 0;
    let resolveNext: ((value: Scan) => void) | null = null;
    // Fetcher A returns terminal SCAN_COMPLETED once.
    // Fetcher B is the new fetcher after the dependency
    // change. We track both separately so we can assert
    // fetcher B was called.
    let activeFetcher: "A" | "B" = "A";
    const fetcherA = (_signal: AbortSignal): Promise<Scan> => {
      callCount += 1;
      activeFetcher = "A";
      return Promise.resolve(SCAN_COMPLETED);
    };
    const fetcherB = (_signal: AbortSignal): Promise<Scan> => {
      callCount += 1;
      activeFetcher = "B";
      return new Promise<Scan>((resolve) => {
        resolveNext = resolve;
      });
    };
    // A wrapper that switches the fetcher when the dep
    // changes. The dep here is the scan id; on the second
    // mount we use id=2 to trigger the cycle reset.
    const fetcher = (id: number) => (signal: AbortSignal) =>
      id === 1 ? fetcherA(signal) : fetcherB(signal);
    const { result, rerender } = renderHook(
      ({ id }: { id: number }) =>
        usePolling<Scan>(fetcher(id), [id], {
          isTerminal: (v) =>
            v.status === "completed" ||
            v.status === "partial" ||
            v.status === "failed" ||
            v.status === "cancelled",
          intervalMs: 1000,
          maxPolls: 5,
        }),
      { initialProps: { id: 1 } }
    );
    // First cycle: fetcher A returns terminal. Polling
    // stops; ``dataRef.current`` holds SCAN_COMPLETED.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.data?.status).toBe("completed");
    expect(result.current.active).toBe(false);
    const callsAfterA = callCount;
    expect(callsAfterA).toBe(1);
    // Switch the dep to trigger a new cycle. fetcher B
    // must be called immediately, not skipped because
    // the prior cycle's terminal data is still in
    // ``dataRef.current``.
    await act(async () => {
      await rerender({ id: 2 });
      // The first tick of the new cycle runs
      // synchronously inside the effect. We give the
      // microtask queue a chance to drain so the new
      // fetcher's Promise is captured.
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(callCount).toBeGreaterThan(callsAfterA);
    expect(activeFetcher).toBe("B");
    // The new cycle is now in flight; the operator can
    // resolve the new scan by hand. The data is still
    // null because the new fetcher has not resolved.
    expect(result.current.data).toBeNull();
    // Resolve the new fetcher with a non-terminal scan
    // and assert the hook scheduled a follow-up tick.
    await act(async () => {
      resolveNext?.(SCAN_RUNNING);
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.data?.status).toBe("running");
  });

  it("does not retain the prior cycle's terminal data after a dep change", async () => {
    // Regression: the pre-correction dataRef carried the
    // old terminal value into the new cycle's first tick,
    // which read it via the ``if (data && isTerminalCheck(data))``
    // guard and returned early. The corrected
    // implementation clears the ref synchronously, so the
    // guard fails on the first tick and the new fetcher
    // is invoked.
    let callCount = 0;
    const fetcher = (label: string) => (_signal: AbortSignal): Promise<Scan> => {
      callCount += 1;
      return label === "A" ? Promise.resolve(SCAN_COMPLETED) : Promise.resolve(SCAN_RUNNING);
    };
    const { result, rerender } = renderHook(
      ({ label }: { label: string }) =>
        usePolling<Scan>(fetcher(label), [label], {
          isTerminal: (v) =>
            v.status === "completed" ||
            v.status === "partial" ||
            v.status === "failed" ||
            v.status === "cancelled",
          intervalMs: 1000,
          maxPolls: 5,
        }),
      { initialProps: { label: "A" } }
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.data?.status).toBe("completed");
    expect(result.current.active).toBe(false);
    const callsAfterA = callCount;
    // Swap to fetcher B. The hook must clear the prior
    // cycle's terminal value and call fetcher B in the
    // very first tick of the new cycle.
    await act(async () => {
      await rerender({ label: "B" });
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(callCount).toBe(callsAfterA + 1);
    expect(result.current.data?.status).toBe("running");
  });

  it("aborts the prior cycle's pending request when a dep change fires", async () => {
    // The cycle effect must call ``controller.abort()`` on
    // its teardown, which fires for the prior cycle when a
    // new cycle mounts. The corrected implementation
    // preserves that behaviour while also resetting the
    // dataRef.
    const aborts: string[] = [];
    const fetcher = (label: string) => (signal: AbortSignal): Promise<Scan> =>
      new Promise<Scan>((_resolve, reject) => {
        signal.addEventListener("abort", () => {
          aborts.push(label);
          reject(new Error("aborted"));
        });
      });
    const { rerender } = renderHook(
      ({ label }: { label: string }) =>
        usePolling<Scan>(fetcher(label), [label], {
          isTerminal: () => false,
          intervalMs: 1000,
          maxPolls: 5,
        }),
      { initialProps: { label: "A" } }
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    // Swap to a new dep. The prior cycle's controller
    // must be aborted.
    await act(async () => {
      await rerender({ label: "B" });
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(aborts).toContain("A");
  });

  it("still stops polling when the dep list is unchanged and the scan goes terminal", async () => {
    // Sanity: the dataRef reset must not regress the
    // happy-path terminal-stopping behaviour. The hook
    // should still stop polling the moment a scan reaches
    // a terminal state when nothing in the dep list has
    // changed.
    const fetcher = makeFetcher([SCAN_RUNNING, SCAN_RUNNING, SCAN_COMPLETED]);
    const { result } = renderHook(() =>
      usePolling<Scan>(fetcher, [], {
        isTerminal: (v) =>
          v.status === "completed" ||
          v.status === "partial" ||
          v.status === "failed" ||
          v.status === "cancelled",
        intervalMs: 1000,
        maxPolls: 10,
      })
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.data?.status).toBe("completed");
    expect(result.current.active).toBe(false);
  });
});
