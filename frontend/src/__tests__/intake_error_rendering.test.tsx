/**
 * v2.1.1 frontend error-rendering tests.
 *
 * The intake error taxonomy distinguishes seven
 * classified failure modes that must never render as
 * "Unknown error" in the browser:
 *
 * - ``not_found`` (404) — repository not accessible
 * - ``invalid_ref`` (422) — branch / tag / SHA missing
 * - ``rate_limited`` (429) — GitHub rate limit reached
 * - ``forbidden`` (403) — denied
 * - ``archive_unsafe`` (400) — archive validation failure
 * - ``internal_unexpected`` (500) — internal error with correlation id
 * - ``validation_error`` (422) — generic rejection
 *
 * The frontend ``categorizeError`` must recognise the
 * stable error code on each response and the
 * ``errorTitleFor`` helper must return a category-
 * specific title (never the literal "Unknown error"
 * suffix). The ``correlationIdFromError`` helper must
 * extract the 16-character hex id from the response
 * ``details`` envelope for ``internal_unexpected``
 * envelopes and from nothing else.
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";

import { ErrorState } from "@/components/ErrorState";
import {
  ApiClientError,
  categorizeError,
  correlationIdFromError,
  describeError,
} from "@/api/client";

function makeApiError(
  code: string,
  message: string,
  httpStatus: number,
  details?: Record<string, unknown>
): ApiClientError {
  return new ApiClientError({
    code,
    message,
    httpStatus,
    details,
  });
}

describe("v2.1.1 error taxonomy mapping (frontend)", () => {
  it("classifies not_found as 'not_found'", () => {
    const err = makeApiError(
      "not_found",
      "Repository could not be accessed. Confirm that the URL exists and is public. Private repositories are not supported in this version.",
      404,
    );
    expect(categorizeError(err)).toBe("not_found");
  });

  it("classifies invalid_ref as 'invalid_ref'", () => {
    const err = makeApiError(
      "invalid_ref",
      "The requested branch, tag, or commit could not be found on the repository. Check the ref and try again.",
      422,
    );
    expect(categorizeError(err)).toBe("invalid_ref");
  });

  it("classifies rate_limited as 'rate_limited'", () => {
    const err = makeApiError(
      "rate_limited",
      "GitHub rate limit reached. Wait a few minutes and retry. Configure LOCKVERITY_GITHUB_TOKEN to lift the unauthenticated limit. The Diagnostics page shows the current rate-limit state.",
      429,
    );
    expect(categorizeError(err)).toBe("rate_limited");
  });

  it("classifies forbidden as 'forbidden'", () => {
    const err = makeApiError(
      "forbidden",
      "GitHub denied the request. The repository may be private, the URL may be wrong, or the configured token may lack access. Private repositories are not supported in this version.",
      403,
    );
    expect(categorizeError(err)).toBe("forbidden");
  });

  it("classifies archive_unsafe as 'validation' (rejection surfaces as a validation banner)", () => {
    const err = makeApiError(
      "archive_unsafe",
      "Archive was rejected: it contains more files than the configured cap. Reduce the archive size or split the upload.",
      400,
    );
    expect(categorizeError(err)).toBe("validation");
  });

  it("classifies internal_unexpected as 'internal_unexpected'", () => {
    const err = makeApiError(
      "internal_unexpected",
      "An internal error occurred. See Diagnostics for the correlation id and the runtime log for the full trace.",
      500,
      { correlation_id: "0123456789abcdef", kind: "github" },
    );
    expect(categorizeError(err)).toBe("internal_unexpected");
  });
});

describe("v2.1.1 correlation ID contract", () => {
  it("extracts a 16-character lowercase hex correlation id from internal_unexpected", () => {
    const err = makeApiError(
      "internal_unexpected",
      "An internal error occurred.",
      500,
      { correlation_id: "0123456789abcdef", kind: "github" },
    );
    expect(correlationIdFromError(err)).toBe("0123456789abcdef");
  });

  it("returns null for non-internal_unexpected errors", () => {
    const err = makeApiError("not_found", "nope", 404, {
      correlation_id: "0123456789abcdef",
    });
    expect(correlationIdFromError(err)).toBeNull();
  });

  it("returns null when the id is the wrong shape", () => {
    const err = makeApiError(
      "internal_unexpected",
      "An internal error occurred.",
      500,
      { correlation_id: "Z" },
    );
    expect(correlationIdFromError(err)).toBeNull();
  });

  it("returns null when the id is missing", () => {
    const err = makeApiError("internal_unexpected", "nope", 500);
    expect(correlationIdFromError(err)).toBeNull();
  });

  it("returns null for non-ApiClientError values", () => {
    expect(correlationIdFromError(new Error("boom"))).toBeNull();
    expect(correlationIdFromError(undefined)).toBeNull();
    expect(correlationIdFromError("string")).toBeNull();
  });
});

describe("v2.1.1 describeError never says 'Unknown error.'", () => {
  it("returns the backend's safe message for a classified error", () => {
    const err = makeApiError(
      "not_found",
      "Repository could not be accessed. Confirm that the URL exists and is public. Private repositories are not supported in this version.",
      404,
    );
    expect(describeError(err)).toContain("could not be accessed");
    expect(describeError(err)).not.toBe("Unknown error.");
  });

  it("returns the backend's safe message for an invalid_ref error", () => {
    const err = makeApiError(
      "invalid_ref",
      "The requested branch, tag, or commit could not be found on the repository. Check the ref and try again.",
      422,
    );
    expect(describeError(err)).toContain("Check the ref");
    expect(describeError(err)).not.toBe("Unknown error.");
  });

  it("returns the correlation-id-bearing message for internal_unexpected", () => {
    const err = makeApiError(
      "internal_unexpected",
      "An internal error occurred. See Diagnostics for the correlation id and the runtime log for the full trace.",
      500,
      { correlation_id: "0123456789abcdef" },
    );
    expect(describeError(err)).toContain("correlation id");
    expect(describeError(err)).not.toBe("Unknown error.");
  });
});

describe("v2.1.1 ErrorState never says 'Unknown error'", () => {
  // The title / description logic lives in AnalyzePage
  // and the lower-level ScanActions / NewRepositoryPage
  // helpers. The ErrorState component itself renders
  // the body line from either ``description`` (when
  // provided) or ``describeError(error)``. The hotfix
  // contract is: a classified backend envelope must
  // always render the backend's safe message; the
  // title is supplied by the caller so the absence of
  // the literal "Unknown error." suffix in the body is
  // what we verify here.

  function renderErrorState(err: ApiClientError, title: string, description?: string) {
    return render(
      <MemoryRouter initialEntries={["/analyze"]}>
        <Routes>
          <Route
            path="/analyze"
            element={<ErrorState error={err} title={title} description={description} />}
          />
        </Routes>
      </MemoryRouter>
    );
  }

  it("renders the actionable 'could not be accessed' body for a 404", () => {
    const err = makeApiError(
      "not_found",
      "Repository could not be accessed. Confirm that the URL exists and is public. Private repositories are not supported in this version.",
      404,
    );
    renderErrorState(err, "Repository could not be accessed");
    expect(
      screen.getByText(/Repository could not be accessed\./),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Unknown error\./)).toBeNull();
  });

  it("renders the 'Check the ref' body for an invalid_ref", () => {
    const err = makeApiError(
      "invalid_ref",
      "The requested branch, tag, or commit could not be found on the repository. Check the ref and try again.",
      422,
    );
    renderErrorState(
      err,
      "The requested branch, tag, or commit was not found",
    );
    expect(
      screen.getByText(/Check the ref and try again\./),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Unknown error\./)).toBeNull();
  });

  it("renders the rate-limit body for a 429", () => {
    const err = makeApiError(
      "rate_limited",
      "GitHub rate limit reached. Wait a few minutes and retry. Configure LOCKVERITY_GITHUB_TOKEN to lift the unauthenticated limit. The Diagnostics page shows the current rate-limit state.",
      429,
    );
    renderErrorState(err, "Rate limit reached");
    // Use getAllByText because the title and the body
    // both contain the phrase "rate limit reached".
    expect(
      screen.getAllByText(/rate limit reached/i).length,
    ).toBeGreaterThanOrEqual(2);
    expect(
      screen.getByText(/LOCKVERITY_GITHUB_TOKEN/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Unknown error\./)).toBeNull();
  });

  it("renders the forbidden body for a 403", () => {
    const err = makeApiError(
      "forbidden",
      "GitHub denied the request. The repository may be private, the URL may be wrong, or the configured token may lack access. Private repositories are not supported in this version.",
      403,
    );
    renderErrorState(err, "Repository not accessible");
    expect(screen.getByText(/GitHub denied/i)).toBeInTheDocument();
    expect(screen.queryByText(/Unknown error\./)).toBeNull();
  });

  it("renders the archive-rejection body for an archive_unsafe envelope", () => {
    const err = makeApiError(
      "archive_unsafe",
      "Archive was rejected: it contains more files than the configured cap. Reduce the archive size or split the upload.",
      400,
    );
    renderErrorState(err, "Archive rejected by the server");
    expect(screen.getByText(/more files than/i)).toBeInTheDocument();
    expect(screen.queryByText(/Unknown error\./)).toBeNull();
  });

  it("renders the correlation id and reference note for an internal_unexpected", () => {
    const err = makeApiError(
      "internal_unexpected",
      "An internal error occurred. See Diagnostics for the correlation id and the runtime log for the full trace.",
      500,
      { correlation_id: "0123456789abcdef", kind: "github" },
    );
    const description = `${describeError(err)} Reference: 0123456789abcdef. Open Diagnostics or inspect the local runtime log.`;
    renderErrorState(err, "An internal error occurred", description);
    // Use getAllByText because the title and the body
    // both start with "An internal error occurred".
    expect(
      screen.getAllByText(/An internal error occurred/).length,
    ).toBeGreaterThanOrEqual(2);
    expect(
      screen.getByText(/Reference: 0123456789abcdef\./),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Unknown error\./)).toBeNull();
  });
});
