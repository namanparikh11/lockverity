import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "@/api/api";
import type { PageMeta, ProviderObservation } from "@/api/types";
import { DataCompletenessNotice } from "@/components/DataCompletenessNotice";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { ProviderStatusBadge } from "@/components/ProviderStatusBadge";
import { ResponsiveTable } from "@/components/ResponsiveTable";
import { formatTimestamp } from "@/utils/time";

export function ProvidersPage() {
  const { scanId } = useParams<{ scanId: string }>();
  const sid = Number.parseInt(scanId ?? "", 10);
  const [observations, setObservations] = useState<ProviderObservation[] | null>(
    null
  );
  const [meta, setMeta] = useState<PageMeta | null>(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!Number.isFinite(sid)) {
      setError(new Error("Invalid scan id."));
      return;
    }
    const controller = new AbortController();
    setObservations(null);
    setError(null);
    api
      .listProviderObservations(sid, page, 25)
      .then((r) => {
        setObservations(r.items);
        setMeta(r.pagination);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(err);
      });
    return () => controller.abort();
  }, [sid, page]);

  if (error) {
    return (
      <>
        <PageHeader title="Provider status" />
        <ErrorState error={error} />
      </>
    );
  }
  if (observations === null || meta === null) {
    return (
      <>
        <PageHeader title="Provider status" />
        <LoadingState label="Loading provider status" />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title={`Provider status · scan #${sid}`}
        description="Every provider call is recorded. 'No data' is never represented as 'no findings'."
        breadcrumbs={[
          { label: "Scan", to: `/scans/${sid}` },
          { label: "Providers" },
        ]}
      />
      <div className="mb-4">
        <DataCompletenessNotice
          title="No provider calls in v0.1"
          tone="muted"
          description="Lockverity v0.1 does not call any external provider. When vulnerability, dependency, and posture providers are enabled, this page will show availability, partial results, rate limits, and redactions per call."
        />
      </div>
      {observations.length === 0 ? (
        <EmptyState
          title="No provider observations"
          description="No external calls have been made for this scan yet. Each call will produce a row with its availability, status, and bounded error summary."
        />
      ) : (
        <>
          <ResponsiveTable
            headers={[
              "Provider",
              "Operation",
              "Status",
              "HTTP",
              "Records",
              "Last error",
              "Updated",
            ]}
          >
            {observations.map((obs) => (
              <tr key={obs.id} className="table-row">
                <td className="table-cell font-mono text-xs text-ink-700">
                  {obs.provider}
                </td>
                <td className="table-cell text-ink-500">{obs.operation}</td>
                <td className="table-cell">
                  <ProviderStatusBadge status={obs.status} />
                </td>
                <td className="table-cell text-ink-500">
                  {obs.http_status ?? "—"}
                </td>
                <td className="table-cell text-ink-500">
                  {obs.records_returned}
                </td>
                <td className="table-cell max-w-md">
                  <p className="text-xs text-ink-500">
                    {obs.error_summary ?? "—"}
                  </p>
                </td>
                <td className="table-cell text-xs text-ink-500">
                  {formatTimestamp(obs.completed_at ?? obs.created_at)}
                </td>
              </tr>
            ))}
          </ResponsiveTable>
          <div className="mt-4">
            <Pagination meta={meta} onPageChange={setPage} />
          </div>
        </>
      )}
    </>
  );
}
