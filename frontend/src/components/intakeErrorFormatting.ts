/**
 * v2.1.1: shared intake-error formatting helpers.
 *
 * Both the legacy ``/repositories/new`` page and the v1.5
 * guided intake ``/analyze`` page submit to the same canonical
 * GitHub intake endpoint (``POST /api/v1/repositories/github``).
 * They must therefore render the same error taxonomy in the
 * same way: a category-specific title (never the literal
 * "Unknown error" suffix) and, for ``internal_unexpected``
 * envelopes, an operator-facing description line that
 * includes the 16-character lowercase hex correlation id
 * alongside the safe backend message.
 *
 * Centralising the helpers here removes the prior per-page
 * duplication, which had silently diverged (the
 * ``/repositories/new`` helper omitted the
 * ``internal_unexpected`` correlation id and the archive
 * intake was a separate code path again). Every page that
 * renders an intake error must import these helpers and
 * pass the result to :component:`ErrorState`.
 */

import {
  categorizeError,
  correlationIdFromError,
  describeError,
  type ErrorCategory,
} from "@/api/client";

/**
 * Map an :type:`ErrorCategory` to the user-facing title
 * rendered above the bounded backend message. The mapping
 * is identical for every intake page so the operator sees
 * a consistent banner regardless of which entry point
 * surfaced the failure.
 *
 * v2.1.1 contract: the default branch never returns the
 * literal string "Unknown error"; the bounded fallback
 * title is a generic catch-all that the body line
 * qualifies with the safe backend message.
 */
export function intakeErrorTitleFor(category: ErrorCategory): string {
  switch (category) {
    case "validation":
      return "The repository URL was rejected by the server";
    case "invalid_ref":
      // v2.1.1: a valid-looking branch, tag, or SHA that
      // does not exist on a known-existing repository is
      // a distinct failure mode from the generic
      // validation case. The title matches the
      // actionable backend message ("Check the ref and
      // try again.").
      return "The requested branch, tag, or commit was not found";
    case "rate_limited":
      return "GitHub rate limit reached";
    case "provider_unavailable":
      return "Could not reach GitHub";
    case "network":
    case "timeout":
      return "Network problem";
    case "duplicate":
      return "Repository already registered";
    case "forbidden":
    case "unauthorized":
      return "Repository not accessible";
    case "not_found":
      // v2.1.1: a 404 on the repository-metadata endpoint
      // means the URL is wrong, the repository is private,
      // or the repository does not exist. The actionable
      // backend message explains the three cases; the
      // title here is the category summary.
      return "Repository could not be accessed";
    case "internal_unexpected":
      // v2.1.1: an unhandled server failure. The backend
      // carries a non-PII ``correlation_id`` in
      // ``details``; the body line shows the id so the
      // operator can grep the local log.
      return "An internal error occurred";
    case "server":
      return "Server error";
    case "cancelled":
      return "Request cancelled";
    case "rescan_source_unavailable":
      return "Source is no longer available";
    case "unknown":
    default:
      // v2.1.1: the default title no longer claims
      // ``Unknown error`` when the backend has a
      // classified message. The body line below carries
      // the backend's safe message; the title is a
      // generic catch-all so the UI never renders the
      // literal string "Could not add repository
      // (Unknown error.)" when the backend has already
      // supplied a classified error.
      return "Could not submit the repository";
  }
}

/**
 * v2.1.1: the description line for an intake error banner.
 *
 * Carries the backend's safe message and, for
 * ``internal_unexpected`` envelopes, the operator-facing
 * correlation id. The correlation id is derived from the
 * response ``details`` envelope and is rendered as
 * ``Reference: <id>`` so the operator can grep the local
 * runtime log for the same id. The id is only appended
 * when it parses as a 16-character lowercase hex string;
 * envelopes that do not match the documented format
 * silently drop the reference line rather than render a
 * partial id.
 */
export function intakeErrorDescriptionFor(err: unknown): string {
  const base = describeError(err);
  if (!err) return base;
  const cid = correlationIdFromError(err);
  if (cid === null) return base;
  return `${base} Reference: ${cid}. Open Diagnostics or inspect the local runtime log.`;
}

// Re-export the category accessor so callers can use a
// single import line for the full intake-error contract.
export { categorizeError, correlationIdFromError, describeError };
export type { ErrorCategory };
