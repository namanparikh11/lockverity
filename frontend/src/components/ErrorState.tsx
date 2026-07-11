import { AlertTriangle } from "lucide-react";

import { describeError } from "@/api/client";

export function ErrorState({
  error,
  title = "Something went wrong",
}: {
  error: unknown;
  title?: string;
}) {
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
          <p className="mt-1 text-sm text-rose-700">{describeError(error)}</p>
        </div>
      </div>
    </div>
  );
}
