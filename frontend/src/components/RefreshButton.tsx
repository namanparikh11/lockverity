import { Loader2, RefreshCw } from "lucide-react";
import { useId } from "react";

import type { UseRefreshResult } from "@/hooks/useRefresh";

/**
 * v2.1.3 application-data refresh button.
 *
 * The button is the single visual chokepoint for the
 * "click here to refetch the visible payload" UX.
 * The component is intentionally a "dumb" renderer:
 * the state, the guard, the accessibility, and the
 * failure-preservation logic live in
 * :func:`useRefresh`. The button renders the current
 * state and routes click events back to the parent
 * hook. Passing the state down (rather than creating
 * a hook inside the component) lets a page share
 * the refresh state between the action button and
 * the page-level error banner.
 *
 * The component:
 *
 *  - Renders a ``RefreshCw`` icon when idle and a
 *    spinning ``Loader2`` icon while the request is
 *    in flight so the operator can see the request
 *    is making progress.
 *  - Updates the visible label to ``"Refreshing…"``
 *    while the request is in flight, so the change
 *    is unambiguous without relying on the icon
 *    alone (the manual-QA pass required the
 *    accessible-name change).
 *  - Disables itself while a refresh is in flight
 *    so duplicate clicks cannot stack. The
 *    :func:`useRefresh` hook also enforces a
 *    synchronous guard at the state level, so the
 *    disabled attribute is a belt-and-braces
 *    defence.
 *  - Preserves the ``aria-busy`` attribute while
 *    the request is in flight so screen readers
 *    announce the state change.
 *
 * The component never claims a refresh succeeded
 * when the in-flight request raised. The component
 * never erases the visible screen on a refresh
 * failure; the parent renders the preserved data
 * and the page-level failure banner.
 */

export interface RefreshButtonProps {
  /** The shared refresh state from :func:`useRefresh`. */
  state: Pick<
    UseRefreshResult<unknown>,
    "refresh" | "isRefreshing" | "state" | "error" | "label" | "ariaBusy" | "disabled"
  >;
  /** Optional override for the visible label. The default is ``"Refresh"``. */
  label?: string;
  /** Optional aria-label for the button. Defaults to ``label``. */
  ariaLabel?: string;
  /**
   * Optional test id. The default is
   * ``"refresh-button"`` so existing diagnostic
   * selectors keep working.
   */
  testId?: string;
  /**
   * Optional className applied to the rendered
   * ``<button>``. The default is
   * ``"btn-secondary"`` to match the historical
   * look on the diagnostics page.
   */
  className?: string;
  /**
   * Optional callback fired when the button is
   * clicked. The default is to call
   * ``state.refresh``; the prop is exposed so a
   * parent can interpose its own telemetry
   * without re-implementing the click guard.
   */
  onClick?: () => void;
}

export function RefreshButton({
  state,
  label = "Refresh",
  ariaLabel,
  testId = "refresh-button",
  className = "btn-secondary",
  onClick,
}: RefreshButtonProps) {
  const { refresh, isRefreshing, state: refreshState, error } = state;
  const liveRegionId = useId();
  const visibleLabel = isRefreshing ? "Refreshing…" : label;
  const effectiveAriaLabel = ariaLabel ?? visibleLabel;
  const showInlineError = refreshState === "error" && error !== undefined;
  return (
    <span className="inline-flex items-center gap-2">
      <button
        type="button"
        className={className}
        onClick={() => {
          if (onClick) {
            onClick();
            return;
          }
          refresh();
        }}
        disabled={isRefreshing}
        aria-busy={isRefreshing}
        aria-label={effectiveAriaLabel}
        data-testid={testId}
      >
        {isRefreshing ? (
          <Loader2
            aria-hidden="true"
            className="h-4 w-4 animate-spin"
            data-testid={`${testId}-spinner`}
          />
        ) : (
          <RefreshCw aria-hidden="true" className="h-4 w-4" />
        )}
        <span aria-live="polite" aria-atomic="true">
          {visibleLabel}
        </span>
      </button>
      {showInlineError ? (
        <span
          role="status"
          id={liveRegionId}
          className="text-xs text-rose-700"
          data-testid={`${testId}-inline-error`}
        >
          Refresh failed
        </span>
      ) : (
        // The ``sr-only`` live region stays even
        // when no error is visible so screen
        // readers can announce the loading state
        // change without a visible label shift.
        <span
          id={liveRegionId}
          aria-live="polite"
          aria-atomic="true"
          className="sr-only"
        >
          {isRefreshing ? "Refreshing" : ""}
        </span>
      )}
    </span>
  );
}
