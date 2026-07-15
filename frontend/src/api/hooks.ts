/**
 * Lockverity data hooks.
 *
 * Small, focused wrappers around the API client that:
 *  - cancel in-flight requests when the component unmounts or the
 *    dependency list changes,
 *  - expose loading / error states without each page having to
 *    reinvent them,
 *  - apply the v0.2 fallback semantics for endpoints that the
 *    v0.1 backend does not yet expose.
 */

import { useEffect, useRef, useState } from "react";

import { isNotImplemented } from "@/api/fallback";
import type { PageMeta, Scan, ScanStatus } from "@/api/types";

export interface UseListResult<T> {
  items: T[];
  meta: PageMeta | null;
  loading: boolean;
  notImplemented: boolean;
  error: unknown;
  refresh: () => void;
}

export interface UseListOptions {
  pageSize?: number;
  fallbackItems?: unknown[];
  fallbackMeta?: PageMeta;
}

/**
 * List-with-fallback hook. The fetcher receives an
 * `AbortSignal`; the hook guarantees the signal is aborted on
 * unmount or when the dependency list changes.
 */
export function useApiList<T>(
  fetcher: (signal: AbortSignal) => Promise<{ items: T[]; pagination: PageMeta }>,
  deps: ReadonlyArray<unknown>,
  options: UseListOptions = {}
): UseListResult<T> {
  const fallbackItems = (options.fallbackItems ?? []) as T[];
  const fallbackMeta: PageMeta = options.fallbackMeta ?? {
    page: 1,
    page_size: 0,
    total: 0,
    total_pages: 0,
  };
  const [items, setItems] = useState<T[] | null>(null);
  const [meta, setMeta] = useState<PageMeta | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [notImplemented, setNotImplemented] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const depsRef = useRef<ReadonlyArray<unknown>>(deps);

  useEffect(() => {
    depsRef.current = deps;
  });

  useEffect(() => {
    const controller = new AbortController();
    setItems(null);
    setMeta(null);
    setError(null);
    setNotImplemented(false);
    fetcher(controller.signal)
      .then((result) => {
        setItems(result.items);
        setMeta(result.pagination);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        if (isNotImplemented(err)) {
          setItems(fallbackItems);
          setMeta(fallbackMeta);
          setNotImplemented(true);
          return;
        }
        setError(err);
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey, ...deps]);

  return {
    items: items ?? fallbackItems,
    meta: meta ?? fallbackMeta,
    loading: items === null && error === null && !notImplemented,
    notImplemented,
    error,
    refresh: () => setRefreshKey((k) => k + 1),
  };
}

export interface UseDetailResult<T> {
  data: T | null;
  loading: boolean;
  notImplemented: boolean;
  error: unknown;
  refresh: () => void;
}

export function useApiDetail<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  deps: ReadonlyArray<unknown>,
  fallback: T | null = null
): UseDetailResult<T> {
  const [data, setData] = useState<T | null>(fallback);
  const [error, setError] = useState<unknown>(null);
  const [notImplemented, setNotImplemented] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setData(fallback);
    setError(null);
    setNotImplemented(false);
    fetcher(controller.signal)
      .then(setData)
      .catch((err) => {
        if (controller.signal.aborted) return;
        if (isNotImplemented(err)) {
          setData(fallback);
          setNotImplemented(true);
          return;
        }
        setError(err);
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey, ...deps]);

  return {
    data,
    loading: data === fallback && error === null && !notImplemented,
    notImplemented,
    error,
    refresh: () => setRefreshKey((k) => k + 1),
  };
}

/**
 * Terminal scan states. Polling stops the moment a scan enters
 * any of these states; the operator does not need another
 * request to confirm a scan has finished.
 */
const TERMINAL_SCAN_STATUSES: ReadonlySet<ScanStatus> = new Set<ScanStatus>([
  "completed",
  "partial",
  "failed",
  "cancelled",
]);

export interface UsePollingOptions {
  /** Polling interval in ms. Defaults to 2000. */
  intervalMs?: number;
  /** Hard cap on the number of polls. Defaults to 120 (4 min @ 2 s). */
  maxPolls?: number;
  /** Test seam: if the scan enters a terminal state, the hook resolves. */
  isTerminal?: (scan: Scan) => boolean;
}

export interface UsePollingResult<T> {
  data: T | null;
  error: unknown;
  polls: number;
  /** True while a poll is in flight or the timer is scheduled. */
  active: boolean;
  /** Force a fresh poll right now (does not consume the budget). */
  refresh: () => void;
  /** Stop polling immediately. The component can call this on unmount. */
  stop: () => void;
}

/**
 * Polling hook for scan progress. The hook:
 *
 * - aborts the in-flight request on unmount,
 * - schedules a timer that fires every ``intervalMs``,
 * - resolves when the scan reaches a terminal state
 *   (completed / partial / failed / cancelled),
 * - stops after ``maxPolls`` polls to avoid an unbounded loop
 *   when the backend never reaches a terminal state.
 */
export function usePolling<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  deps: ReadonlyArray<unknown>,
  options: UsePollingOptions & {
    isTerminal?: (value: T) => boolean;
  } = {}
): UsePollingResult<T> {
  const intervalMs = options.intervalMs ?? 2000;
  const maxPolls = options.maxPolls ?? 120;
  const isTerminalCheck = options.isTerminal ?? defaultTerminalCheck;
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [polls, setPolls] = useState(0);
  const [active, setActive] = useState(true);
  const stopRef = useRef(false);
  const refreshRef = useRef(0);
  const dataRef = useRef<T | null>(null);
  dataRef.current = data;
  const [, setForceUpdate] = useState(0);

  useEffect(() => {
    stopRef.current = false;
    setData(null);
    setError(null);
    setPolls(0);
    setActive(true);
    let controller: AbortController | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const tick = (): void => {
      if (stopRef.current) {
        return;
      }
      const data = dataRef.current as T | null;
      if (data && isTerminalCheck(data)) {
        setActive(false);
        return;
      }
      controller?.abort();
      controller = new AbortController();
      refreshRef.current += 1;
      setPolls((p) => p + 1);
      fetcher(controller.signal)
        .then((value: T) => {
          if (controller?.signal.aborted) return;
          setData(value);
          if (isTerminalCheck(value)) {
            setActive(false);
            return;
          }
          if (dataRef.current && isTerminalCheck(dataRef.current)) {
            setActive(false);
            return;
          }
          if (dataRef.current === null || !isTerminalCheck(dataRef.current)) {
            scheduleNext();
          }
        })
        .catch((err) => {
          if (controller?.signal.aborted) return;
          setError(err);
          // A real network error stops polling. The UI surfaces
          // the error and the operator can refresh manually.
          setActive(false);
        });
    };

    const scheduleNext = (): void => {
      if (stopRef.current) return;
      if (refreshRef.current >= maxPolls) {
        setActive(false);
        return;
      }
      timer = setTimeout(tick, intervalMs);
    };

    tick();
    return () => {
      stopRef.current = true;
      controller?.abort();
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, maxPolls, ...deps]);

  return {
    data,
    error,
    polls,
    active,
    refresh: () => setForceUpdate((k) => k + 1),
    stop: () => {
      stopRef.current = true;
      setActive(false);
    },
  };
}

function defaultTerminalCheck<T>(value: T): boolean {
  if (value && typeof value === "object" && "status" in (value as object)) {
    const status = (value as unknown as { status: ScanStatus }).status;
    return TERMINAL_SCAN_STATUSES.has(status);
  }
  return false;
}
