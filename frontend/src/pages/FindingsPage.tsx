import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "@/api/api";
import type { Finding, PageMeta } from "@/api/types";
import { DataCompletenessNotice } from "@/components/DataCompletenessNotice";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { ResponsiveTable } from "@/components/ResponsiveTable";
import { ConfidenceBadge } from "@/components/ConfidenceBadge";
import { SeverityBadge } from "@/components/SeverityBadge";
import { StatusBadge } from "@/components/StatusBadge";

export function FindingsPage() {
  const { scanId } = useParams<{ scanId: string }>();
  const sid = Number.parseInt(scanId ?? "", 10);
  const [findings, setFindings] = useState<Finding[] | null>(null);
  const [meta, setMeta] = useState<PageMeta | null>(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!Number.isFinite(sid)) {
      setError(new Error("Invalid scan id."));
      return;
    }
    const controller = new AbortController();
    setFindings(null);
    setError(null);
    api
      .listFindings(sid, page, 25)
      .then((r) => {
        setFindings(r.items);
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
        <PageHeader title="Findings" />
        <ErrorState error={error} />
      </>
    );
  }
  if (findings === null || meta === null) {
    return (
      <>
        <PageHeader title="Findings" />
        <LoadingState label="Loading findings" />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title={`Findings · scan #${sid}`}
        description="Each finding is evidence-backed, severity-tagged, and confidence-tagged. Severity and confidence are independent dimensions."
        breadcrumbs={[
          { label: "Scan", to: `/scans/${sid}` },
          { label: "Findings" },
        ]}
      />
      <div className="mb-4">
        <DataCompletenessNotice
          title="No findings yet"
          tone="muted"
          description="Lockverity v0.1 records findings tables but does not produce them. When analyzers are enabled, this page will show rule_id, location, evidence summary, severity, and confidence."
        />
      </div>
      {findings.length === 0 ? (
        <EmptyState
          title="No findings recorded"
          description="Analyzers, rules, and vulnerability providers are not yet enabled. When they are, this page will list each finding with its evidence summary."
        />
      ) : (
        <>
          <ResponsiveTable
            headers={[
              "Rule",
              "Title",
              "Category",
              "Severity",
              "Confidence",
              "Status",
            ]}
          >
            {findings.map((finding) => (
              <tr key={finding.id} className="table-row">
                <td className="table-cell font-mono text-xs text-ink-500">
                  {finding.rule_id}
                </td>
                <td className="table-cell">
                  <p className="font-medium text-ink-900">{finding.title}</p>
                  <p className="text-xs text-ink-500">{finding.summary}</p>
                </td>
                <td className="table-cell text-ink-500">
                  {finding.category}
                </td>
                <td className="table-cell">
                  <SeverityBadge severity={finding.severity} />
                </td>
                <td className="table-cell">
                  <ConfidenceBadge confidence={finding.confidence} />
                </td>
                <td className="table-cell">
                  <StatusBadge status={finding.status} />
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
