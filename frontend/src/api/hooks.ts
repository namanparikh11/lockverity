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
import type { PageMeta } from "@/api/types";

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
