import { usePolling } from "@/api/hooks";
import { api } from "@/api/api";
import type { Scan } from "@/api/types";

/**
 * Terminal scan statuses. The polling hook stops the
 * moment a scan enters one of these states; the workbench
 * then renders the terminal-state UI without further
 * polling.
 */
export const TERMINAL_SCAN_STATUSES: ReadonlySet<Scan["status"]> = new Set([
  "completed",
  "partial",
  "failed",
  "cancelled",
]);

/**
 * v1.6 polling wrapper for the workbench. Pinned to the
 * 2s interval the rest of the application uses for
 * terminal-state polling. Callers should pass the scan
 * id as the only dependency so the polling stops on
 * terminal status and restarts on a fresh scan id.
 */
export function useWorkbenchPolling(scanId: number) {
  return usePolling<Scan>(
    (signal) => api.getScan(scanId, signal ? { signal } : undefined),
    [scanId],
    {
      intervalMs: 2000,
      maxPolls: 300,
      isTerminal: (value) => TERMINAL_SCAN_STATUSES.has(value.status),
    }
  );
}
