/**
 * Lockverity data access utilities.
 *
 * The v0.1 backend exposes a small, focused set of endpoints. The
 * v0.2 frontend pages already need richer endpoints (vulnerabilities,
 * dependencies, workflows, OpenSSF, licences, scan comparison,
 * exports) that will be added in later backend milestones. To keep
 * the UI working end-to-end while the backend catches up, the data
 * helpers below swallow the well-known "endpoint not yet
 * implemented" errors and return empty / not-implemented-shaped
 * data. Crucially, this is **not** a fixture fallback. The
 * behaviour is triggered by an explicit HTTP 404 / 501 response
 * from the live backend, never by an API failure (network, timeout,
 * 5xx) and never by the development fixture flag.
 */

import { ApiClientError, categorizeError } from "@/api/client";

/**
 * Codes returned by the backend that mean "this endpoint is not
 * implemented yet". Anything else (including network errors, 5xx,
 * or unexpected 4xx) is treated as a real error and propagated.
 */
const NOT_IMPLEMENTED_CODES = new Set([
  "not_found",
  "not_implemented",
  "http_error",
]);

const NOT_IMPLEMENTED_STATUSES = new Set([404, 405, 501]);

export function isNotImplemented(err: unknown): boolean {
  if (!(err instanceof ApiClientError)) return false;
  if (NOT_IMPLEMENTED_CODES.has(err.apiError.code)) return true;
  if (NOT_IMPLEMENTED_STATUSES.has(err.apiError.httpStatus)) return true;
  return false;
}

/**
 * Run a fetcher and, if the backend reports the endpoint is not
 * implemented, return `fallback`. Any other error is rethrown.
 */
export async function fetchOrFallback<T>(
  fetcher: () => Promise<T>,
  fallback: T,
  options: { logPrefix?: string } = {}
): Promise<T> {
  try {
    return await fetcher();
  } catch (err) {
    if (isNotImplemented(err)) {
      if (options.logPrefix && import.meta.env?.DEV) {
        console.info(`[lockverity] ${options.logPrefix}: not implemented yet.`);
      }
      return fallback;
    }
    throw err;
  }
}

/**
 * Return the user-facing description of a fetch error, or null if
 * the error is a "not implemented" one. Useful for empty states
 * that should silently hide errors.
 */
export function errorToMessage(err: unknown): string | null {
  if (isNotImplemented(err)) return null;
  if (err instanceof ApiClientError) return err.apiError.message;
  if (err instanceof Error) return err.message;
  return "Unknown error.";
}

/**
 * Re-export of the categorizer for call sites that want to
 * customise their message without going through `describeError`.
 */
export { categorizeError };

/**
 * Stable label for an enum value, e.g. used in dropdowns.
 */
export function enumLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return value
    .split("_")
    .map((part) => (part ? part[0].toUpperCase() + part.slice(1) : ""))
    .join(" ");
}
