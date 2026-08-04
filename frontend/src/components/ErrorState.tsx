import { AlertTriangle } from "lucide-react";

import { describeError } from "@/api/client";

export function ErrorState({
  error,
  title = "Something went wrong",
  description,
}: {
  error: unknown;
  title?: string;
  /**
   * Optional override for the description line. When
   * provided, the override is shown instead of the
   * backend's safe message. v2.1.1 uses the override
   * to append the ``correlation_id`` for
   * ``internal_unexpected`` envelopes so the operator
   * can grep the local log.
   */
  description?: string;
}) {
  const body = description ?? describeError(error);
  return (
    <div
      className="card border-rose-200 bg-rose-50"
      role="alert"
      aria-live="assertive"
    >
      <div className="flex items-start gap-3">
        <AlertTriangle aria-hidden="true" className="mt-0.5 h-5 w-5 text-rose-600" />
        <div>
          <h2 className="text-sm font-semibold text-rose-800">{title}</h2>
          <p className="mt-1 text-sm text-rose-700">{body}</p>
        </div>
      </div>
    </div>
  );
}
