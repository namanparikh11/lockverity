import { useCallback, useEffect, useMemo, useRef, useState } from "react";

/**
 * v2.1.3 shared application-data refresh hook.
 *
 * The lockverity product has several application-data
 * surfaces (operational diagnostics, scan detail
 * polling refresh, comparison selection data) that
 * all want the same ``fetch → display → preserve on
 * failure → guard duplicate clicks → render ``
 * Refreshing… `` label`` behaviour. The hook is the
 * single chokepoint that delivers:
 *
 *  - **Single-flight guard.** A synchronous
 *    ``pendingRef`` blocks duplicate concurrent
 *    invocations. The ``React`` state is
 *    asynchronous so two synchronous clicks could
 *    both pass the ``if (refreshing) return`` check
 *    before the state propagates; the ref check
 *    is synchronous and closes the window.
 *  - **Preserved previous data.** The previous
 *    payload is kept in state when the in-flight
 *    request fails. The caller renders the
 *    preserved payload and surfaces a separate
 *    "Refresh failed" indicator; the page does not
 *    blank.
 *  - **Accessible loading state.** The hook exposes
 *    ``aria-busy`` and the recommended label
 *    ``"Refreshing…"`` so the button's accessible
 *    name matches the visible label.
 *  - **One source of truth for the label.** The
 *    hook returns ``label`` and ``stateLabel`` so
 *    the caller does not hard-code the same string
 *    in two places.
 *  - **No full-page reload.** The hook only
 *    triggers the supplied fetcher; the caller is
 *    responsible for the rest.
 *
 * The hook never claims a refresh succeeded when
 * the in-flight request raised. The hook never
 * claims a refresh failed when the previous
 * payload was empty. The hook never erases the
 * visible screen on a refresh failure.
 */

export type RefreshState = "idle" | "refreshing" | "success" | "error";

export interface UseRefreshOptions<T> {
  /** The fetcher. May be a sync or async function. */
  fetcher: () => Promise<T> | T;
  /**
   * Optional callback fired when the fetcher
   * returns a fresh payload. The callback receives
   * the new value and the previous value (or
   * ``undefined`` if there was none). The callback
   * is invoked *after* the React state has been
   * updated so the caller can safely read the
   * latest snapshot.
   */
  onSuccess?: (value: T, previous: T | undefined) => void;
  /**
   * Optional callback fired when the fetcher
   * raises. The previous payload (if any) is
   * passed in so the caller can re-render the
   * preserved state. The callback is the right
   * place to wire a "Refresh failed" toast.
   */
  onError?: (error: unknown, previous: T | undefined) => void;
  /**
   * Optional initial data. When supplied, the
   * hook starts in the ``idle`` state with the
   * initial data already populated; the caller
   * does not need a separate initial-load
   * branch.
   */
  initialData?: T;
}

export interface UseRefreshResult<T> {
  /** The most recent successful payload, or the initial data. */
  data: T | undefined;
  /** The current refresh state. */
  state: RefreshState;
  /** Convenience flag: ``true`` while a refresh is in flight. */
  isRefreshing: boolean;
  /** Convenience flag: ``true`` after a refresh has succeeded at least once. */
  hasLoaded: boolean;
  /** The most recent error, or ``undefined``. */
  error: unknown | undefined;
  /** Trigger a refresh. Safe to call from a button ``onClick``. */
  refresh: () => void;
  /** Reset to the initial state. */
  reset: () => void;
  /** Visible label, ``"Refresh"`` when idle, ``"Refreshing…"`` when busy. */
  label: string;
  /** Stable aria-busy value for the trigger button. */
  ariaBusy: boolean;
  /** Stable disabled value for the trigger button. */
  disabled: boolean;
}

const IDLE_LABEL = "Refresh";
const REFRESHING_LABEL = "Refreshing…";

export function useRefresh<T>({
  fetcher,
  onSuccess,
  onError,
  initialData,
}: UseRefreshOptions<T>): UseRefreshResult<T> {
  const [data, setData] = useState<T | undefined>(initialData);
  const [state, setState] = useState<RefreshState>(
    initialData !== undefined ? "idle" : "idle",
  );
  const [error, setError] = useState<unknown | undefined>(undefined);
  // The synchronous guard is the actual lock. The
  // ``refreshing`` state is the visible mirror; the
  // ref is the truth.
  const pendingRef = useRef(false);
  const mountedRef = useRef(true);
  // The fetcher identity is captured at call time so
  // the refresh callback does not need to depend on
  // the latest closure each render.
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const onSuccessRef = useRef(onSuccess);
  onSuccessRef.current = onSuccess;
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const refresh = useCallback(() => {
    if (pendingRef.current) return;
    pendingRef.current = true;
    setState("refreshing");
    setError(undefined);
    Promise.resolve()
      .then(() => fetcherRef.current())
      .then((value) => {
        if (!mountedRef.current) return;
        setData(value);
        setState("success");
        setError(undefined);
        if (onSuccessRef.current) {
          onSuccessRef.current(value, data);
        }
      })
      .catch((err: unknown) => {
        if (!mountedRef.current) return;
        setState("error");
        setError(err);
        if (onErrorRef.current) {
          onErrorRef.current(err, data);
        }
      })
      .finally(() => {
        if (!mountedRef.current) {
          pendingRef.current = false;
          return;
        }
        pendingRef.current = false;
        // The visible ``isRefreshing`` flag falls
        // back to ``false`` when the state is
        // ``success`` or ``error``. We transition
        // back to ``idle`` for the next refresh so
        // the label reads ``"Refresh"`` again.
        setState((current) => (current === "refreshing" ? "idle" : current));
      });
  }, [data]);

  const reset = useCallback(() => {
    pendingRef.current = false;
    setData(initialData);
    setError(undefined);
    setState("idle");
  }, [initialData]);

  const isRefreshing = state === "refreshing";
  const hasLoaded = data !== undefined;
  const label = isRefreshing ? REFRESHING_LABEL : IDLE_LABEL;
  const ariaBusy = isRefreshing;
  const disabled = isRefreshing;

  return useMemo(
    () => ({
      data,
      state,
      isRefreshing,
      hasLoaded,
      error,
      refresh,
      reset,
      label,
      ariaBusy,
      disabled,
    }),
    [data, state, isRefreshing, hasLoaded, error, refresh, reset, label, ariaBusy, disabled],
  );
}
