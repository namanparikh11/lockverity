import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "@/api/api";
import type { Scan, ScanStage } from "@/api/types";
import { CopyableIdentifier } from "@/components/CopyableIdentifier";
import { DataCompletenessNotice } from "@/components/DataCompletenessNotice";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { PageHeader } from "@/components/PageHeader";
import { ResponsiveTable } from "@/components/ResponsiveTable";
import { StatusBadge } from "@/components/StatusBadge";
import { formatRelative, formatTimestamp } from "@/utils/time";

export function ScanDetailsPage() {
  const { scanId } = useParams<{ scanId: string }>();
  const sid = Number.parseInt(scanId ?? "", 10);
  const [scan, setScan] = useState<Scan | null>(null);
  const [stages, setStages] = useState<ScanStage[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!Number.isFinite(sid)) {
      setError(new Error("Invalid scan id."));
      return;
    }
    const controller = new AbortController();
    setError(null);
    setScan(null);
    setStages(null);
    Promise.all([api.getScan(sid), api.listStages(sid)])
      .then(([s, st]) => {
        setScan(s);
        setStages(st.items);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(err);
      });
    return () => controller.abort();
  }, [sid]);

  if (error) {
    return (
      <>
        <PageHeader
          title="Scan"
          breadcrumbs={[{ label: "Scan", to: "/scans" }, { label: "Not found" }]}
        />
        <ErrorState error={error} title="Could not load scan" />
      </>
    );
  }
  if (!scan || stages === null) {
    return (
      <>
        <PageHeader title="Scan" />
        <LoadingState label="Loading scan" />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title={`Scan #${scan.id}`}
        description={`Repository #${scan.repository_id} · ${scan.trigger_type}`}
        breadcrumbs={[
          {
            label: "Repository",
            to: `/repositories/${scan.repository_id}`,
          },
          { label: `Scan #${scan.id}` },
        ]}
        actions={
          <Link
            to={`/scans/${scan.id}/findings`}
            className="btn-secondary"
          >
            View findings
          </Link>
        }
      />
      <div className="card mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <div>
          <p className="label">Status</p>
          <p className="mt-1">
            <StatusBadge status={scan.status} />
          </p>
        </div>
        <div>
          <p className="label">Identifiers</p>
          <p className="mt-1">
            <CopyableIdentifier label="scan id" value={String(scan.id)} />
          </p>
        </div>
        <div>
          <p className="label">Requested ref</p>
          <p className="mt-1 font-mono text-sm text-ink-700">
            {scan.requested_ref ?? "—"}
          </p>
        </div>
        <div>
          <p className="label">Started at</p>
          <p className="mt-1 text-sm text-ink-700">
            {formatTimestamp(scan.started_at)}
          </p>
        </div>
        <div>
          <p className="label">Completed at</p>
          <p className="mt-1 text-sm text-ink-700">
            {formatTimestamp(scan.completed_at)}
          </p>
        </div>
        <div>
          <p className="label">Created</p>
          <p className="mt-1 text-sm text-ink-500">
            {formatRelative(scan.created_at)}
          </p>
        </div>
      </div>
      <h2 className="mb-2 text-sm font-semibold text-ink-700">Pipeline</h2>
      <DataCompletenessNotice
        title="Stages show intent, not execution"
        description="Every scan starts with a complete, deterministic stage pipeline. v0.1 does not run any of these stages - they remain pending until a worker is connected."
        tone="muted"
      />
      <div className="mt-3">
        <ResponsiveTable headers={["#", "Stage", "Status", "Provider", "Records"]}>
          {stages.map((stage, idx) => (
            <tr key={stage.id} className="table-row">
              <td className="table-cell text-ink-400">{idx + 1}</td>
              <td className="table-cell font-mono text-xs text-ink-700">
                {stage.stage_type}
              </td>
              <td className="table-cell">
                <StatusBadge status={stage.status} />
              </td>
              <td className="table-cell text-ink-500">
                {stage.provider ?? "—"}
              </td>
              <td className="table-cell text-ink-500">
                {stage.records_processed}
              </td>
            </tr>
          ))}
        </ResponsiveTable>
      </div>
    </>
  );
}
