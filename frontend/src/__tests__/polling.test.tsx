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
});
