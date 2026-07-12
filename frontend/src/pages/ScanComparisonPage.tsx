import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "@/api/api";
import { isNotImplemented } from "@/api/fallback";
import type { ScanComparison } from "@/api/types";
import { DataCompletenessNotice } from "@/components/DataCompletenessNotice";
import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/PageHeader";
import { ProviderStatusBadge } from "@/components/ProviderStatusBadge";
import { ResponsiveTable } from "@/components/ResponsiveTable";
import { SeverityBadge } from "@/components/SeverityBadge";
import { ConfidenceBadge } from "@/components/ConfidenceBadge";
import { Skeleton } from "@/components/Skeleton";
import { StatusBadge } from "@/components/StatusBadge";
import { SummaryCard } from "@/components/SummaryCard";
import { Timestamp } from "@/components/Timestamp";
import { formatTimestamp } from "@/utils/time";

/**
 * Scan comparison.
 *
 * Renders added, removed, updated, and persisting components
 * and findings between two scans. A finding is not marked
 * "resolved" when the newer provider data is unavailable -
 * the UI shows "unable to determine" instead, with the same
 * status applied to manifest, workflow, and provider diffs.
 */
export function ScanComparisonPage() {
  const { scanId, baseScanId } = useParams<{
    scanId: string;
    baseScanId: string;
  }>();
  const headId = Number.parseInt(scanId ?? "", 10);
  const baseId = Number.parseInt(baseScanId ?? "", 10);
  const [data, setData] = useState<ScanComparison | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [notImpl, setNotImpl] = useState(false);

  useEffect(() => {
    if (!Number.isFinite(headId) || !Number.isFinite(baseId)) {
      setError(new Error("Invalid scan ids."));
      return;
    }
    const controller = new AbortController();
    setData(null);
    setError(null);
    api
      .compareScans(baseId, headId)
      .then((d) => {
        if (controller.signal.aborted) return;
        setData(d);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        if (isNotImplemented(err)) {
          setNotImpl(true);
          return;
        }
        setError(err);
      });
    return () => controller.abort();
  }, [baseId, headId]);

  return (
    <>
      <PageHeader
        title={`Compare scans #${baseId} → #${headId}`}
        description="A side-by-side diff of two scans. Findings are only marked resolved when the newer scan has the same provider evidence; otherwise the row shows 'unable to determine'."
        breadcrumbs={[
          { label: "Scan", to: `/scans/${headId}` },
          { label: `Compare with #${baseId}` },
        ]}
      />
      {notImpl ? (
        <div className="mb-4">
          <DataCompletenessNotice
            title="Comparison endpoint not yet implemented"
            description="The diff structure below mirrors the future backend response: added / removed / updated / persisting components, findings, manifests, workflows, and providers."
            tone="info"
          />
        </div>
      ) : null}
      {error ? (
        <ErrorState error={error} title="Could not compare scans" />
      ) : data === null ? (
        <Skeleton rows={6} />
      ) : (
        <ComparisonBody data={data} />
      )}
    </>
  );
}

function ComparisonBody({ data }: { data: ScanComparison }) {
  const added = data.components.filter((c) => c.verdict === "added").length;
  const removed = data.components.filter((c) => c.verdict === "removed").length;
  const updated = data.components.filter((c) => c.verdict === "updated").length;
  const newFindings = data.findings.filter((f) => f.verdict === "new").length;
  const resolved = data.findings.filter((f) => f.verdict === "resolved").length;
  const persisting = data.findings.filter((f) => f.verdict === "persisting").length;
  const unable = data.findings.filter((f) => f.unable_to_determine).length;
  return (
    <>
      <section className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-7">
        <SummaryCard label="Added components" tone="info">
          <p className="text-2xl font-semibold">{added}</p>
        </SummaryCard>
        <SummaryCard label="Removed components" tone="warn">
          <p className="text-2xl font-semibold">{removed}</p>
        </SummaryCard>
        <SummaryCard label="Updated components" tone="muted">
          <p className="text-2xl font-semibold">{updated}</p>
        </SummaryCard>
        <SummaryCard label="New findings" tone="danger">
          <p className="text-2xl font-semibold">{newFindings}</p>
        </SummaryCard>
        <SummaryCard label="Resolved findings" tone="ok">
          <p className="text-2xl font-semibold">{resolved}</p>
        </SummaryCard>
        <SummaryCard label="Persisting findings" tone="muted">
          <p className="text-2xl font-semibold">{persisting}</p>
        </SummaryCard>
        <SummaryCard label="Unable to determine" tone="warn">
          <p className="text-2xl font-semibold">{unable}</p>
        </SummaryCard>
      </section>
      {data.unable_to_determine.length > 0 ? (
        <div className="mb-4">
          <DataCompletenessNotice
            title="Some rows are marked unable to determine"
            tone="warn"
            description="The newer scan did not have the same provider evidence as the base. These rows are NOT counted as resolved; they are listed as 'unable to determine' so the operator can decide what to do."
          >
            <ul className="mt-2 list-disc pl-5 text-xs">
              {data.unable_to_determine.map((label) => (
                <li key={label}>{label}</li>
              ))}
            </ul>
          </DataCompletenessNotice>
        </div>
      ) : null}
      <section className="mb-6">
        <h2 className="mb-2 text-sm font-semibold text-ink-700">Component diff</h2>
        <ResponsiveTable headers={["Package", "Ecosystem", "Verdict", "Base version", "Head version", "Direct base", "Direct head"]}>
          {data.components.map((row) => (
            <tr key={row.package_name} className="table-row">
              <td className="table-cell font-mono text-xs text-ink-700">{row.package_name}</td>
              <td className="table-cell text-ink-500">{row.ecosystem ?? "—"}</td>
              <td className="table-cell">
                <StatusBadge status={row.verdict} />
              </td>
              <td className="table-cell text-ink-500">{row.version_base ?? "—"}</td>
              <td className="table-cell text-ink-500">{row.version_head ?? "—"}</td>
              <td className="table-cell text-ink-500">
                {row.direct_base === null ? "—" : row.direct_base ? "yes" : "no"}
              </td>
              <td className="table-cell text-ink-500">
                {row.direct_head === null ? "—" : row.direct_head ? "yes" : "no"}
              </td>
            </tr>
          ))}
        </ResponsiveTable>
      </section>
      <section className="mb-6">
        <h2 className="mb-2 text-sm font-semibold text-ink-700">Finding diff</h2>
        <ResponsiveTable headers={["Rule", "Title", "Verdict", "Severity", "Confidence", "Unable?"]}>
          {data.findings.map((row) => (
            <tr key={row.stable_key} className="table-row">
              <td className="table-cell font-mono text-xs text-ink-500">{row.rule_id}</td>
              <td className="table-cell text-ink-800">{row.title}</td>
              <td className="table-cell">
                <StatusBadge status={row.verdict} />
              </td>
              <td className="table-cell">
                <SeverityBadge severity={row.severity_head ?? row.severity_base ?? "unknown"} />
              </td>
              <td className="table-cell">
                <ConfidenceBadge confidence={row.confidence_head ?? row.confidence_base ?? "unknown"} />
              </td>
              <td className="table-cell">
                <StatusBadge status={row.unable_to_determine ? "unknown" : "completed"} />
              </td>
            </tr>
          ))}
        </ResponsiveTable>
      </section>
      <section className="mb-6">
        <h2 className="mb-2 text-sm font-semibold text-ink-700">Manifest &amp; workflow changes</h2>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <div className="card">
            <h3 className="text-sm font-semibold text-ink-700">Manifests</h3>
            <ul className="mt-2 text-sm text-ink-700">
              {data.manifests.map((m) => (
                <li key={m.manifest_path} className="flex items-center justify-between border-b border-ink-100 py-1 last:border-b-0">
                  <span className="font-mono text-xs">{m.manifest_path}</span>
                  <StatusBadge status={m.change} />
                </li>
              ))}
              {data.manifests.length === 0 ? (
                <li className="text-xs text-ink-500">No manifest changes recorded.</li>
              ) : null}
            </ul>
          </div>
          <div className="card">
            <h3 className="text-sm font-semibold text-ink-700">Workflows</h3>
            <ul className="mt-2 text-sm text-ink-700">
              {data.workflows.map((w) => (
                <li key={w.workflow_path} className="flex items-center justify-between border-b border-ink-100 py-1 last:border-b-0">
                  <span className="font-mono text-xs">{w.workflow_path}</span>
                  <StatusBadge status={w.change} />
                </li>
              ))}
              {data.workflows.length === 0 ? (
                <li className="text-xs text-ink-500">No workflow changes recorded.</li>
              ) : null}
            </ul>
          </div>
        </div>
      </section>
      <section className="mb-6">
        <h2 className="mb-2 text-sm font-semibold text-ink-700">Provider diff</h2>
        <ResponsiveTable headers={["Provider", "Base status", "Head status", "Unable to determine?"]}>
          {data.providers.map((p) => (
            <tr key={p.provider} className="table-row">
              <td className="table-cell font-mono text-xs text-ink-700">{p.provider}</td>
              <td className="table-cell">
                {p.base_status ? <ProviderStatusBadge status={p.base_status} /> : "—"}
              </td>
              <td className="table-cell">
                {p.head_status ? <ProviderStatusBadge status={p.head_status} /> : "—"}
              </td>
              <td className="table-cell">
                <StatusBadge status={p.unable_to_determine ? "unknown" : "completed"} />
              </td>
            </tr>
          ))}
        </ResponsiveTable>
      </section>
      <p className="text-xs text-ink-500">
        Comparison generated at {formatTimestamp(data.generated_at)}. <Timestamp value={data.generated_at} mode="relative" />
      </p>
    </>
  );
}
