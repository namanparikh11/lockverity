import { Plus, ScanSearch } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "@/api/api";
import { isNotImplemented } from "@/api/fallback";
import type { PageMeta, Repository, Scan } from "@/api/types";
import { CopyableIdentifier } from "@/components/CopyableIdentifier";
import { DataCompletenessNotice } from "@/components/DataCompletenessNotice";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Notification } from "@/components/Notification";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { ResponsiveTable } from "@/components/ResponsiveTable";
import { Skeleton } from "@/components/Skeleton";
import { StatusBadge } from "@/components/StatusBadge";
import { SummaryCard } from "@/components/SummaryCard";
import { Timestamp } from "@/components/Timestamp";
import { repositoryProviderLabel, repositorySourceLabel, repositoryVisibilityLabel } from "@/utils/labels";
import { formatTimestamp } from "@/utils/time";

export function RepositoryDetailsPage() {
  const { repositoryId } = useParams<{ repositoryId: string }>();
  const repoId = Number.parseInt(repositoryId ?? "", 10);
  const [repo, setRepo] = useState<Repository | null>(null);
  const [scans, setScans] = useState<Scan[] | null>(null);
  const [scansMeta, setScansMeta] = useState<PageMeta | null>(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState<unknown>(null);
  const [triggering, setTriggering] = useState(false);
  const [lastCreatedScanId, setLastCreatedScanId] = useState<number | null>(null);
  const [, setNotImplemented] = useState({ scans: false, summary: false });

  useEffect(() => {
    if (!Number.isFinite(repoId)) {
      setError(new Error("Invalid repository id."));
      return;
    }
    const controller = new AbortController();
    setError(null);
    setRepo(null);
    api
      .getRepository(repoId)
      .then((r) => {
        if (controller.signal.aborted) return;
        setRepo(r);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        setError(err);
      });
    return () => controller.abort();
  }, [repoId]);

  useEffect(() => {
    if (!Number.isFinite(repoId)) return;
    const controller = new AbortController();
    setScans(null);
    api
      .listScansForRepository(repoId, { page, page_size: 10 })
      .then((r) => {
        if (controller.signal.aborted) return;
        setScans(r.items);
        setScansMeta(r.pagination);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        if (isNotImplemented(err)) {
          setScans([]);
          setScansMeta({
            page: 1,
            page_size: 0,
            total: 0,
            total_pages: 0,
          });
          setNotImplemented((prev) => ({ ...prev, scans: true }));
          return;
        }
        setError(err);
      });
    return () => controller.abort();
  }, [repoId, page]);

  async function handleCreateScan() {
    if (!Number.isFinite(repoId)) return;
    setTriggering(true);
    setError(null);
    try {
      const scan = await api.createScan(repoId);
      setPage(1);
      const r = await api.listScansForRepository(repoId, { page: 1, page_size: 10 });
      setScans(r.items);
      setScansMeta(r.pagination);
      setLastCreatedScanId(scan.id);
    } catch (err) {
      setError(err);
    } finally {
      setTriggering(false);
    }
  }

  if (error) {
    return (
      <>
        <PageHeader
          title="Repository"
          breadcrumbs={[
            { label: "Repositories", to: "/repositories" },
            { label: "Not found" },
          ]}
        />
        <ErrorState error={error} title="Could not load repository" />
      </>
    );
  }
  if (!repo) {
    return (
      <>
        <PageHeader title="Repository" />
        <Skeleton rows={6} />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title={`${repo.owner}/${repo.name}`}
        description={repo.description ?? "No description."}
        breadcrumbs={[
          { label: "Repositories", to: "/repositories" },
          { label: `${repo.owner}/${repo.name}` },
        ]}
        actions={
          <button
            type="button"
            className="btn-primary"
            onClick={handleCreateScan}
            disabled={triggering}
          >
            <Plus aria-hidden="true" className="h-4 w-4" />
            {triggering ? "Queueing scan..." : "Queue new scan"}
          </button>
        }
      />
      {lastCreatedScanId ? (
        <div className="mb-4">
          <Notification
            tone="ok"
            title={`Scan #${lastCreatedScanId} queued`}
            description="The scan starts in the queued state and progresses through the pipeline. Open the scan to follow its stages."
            onDismiss={() => setLastCreatedScanId(null)}
          />
        </div>
      ) : null}
      <section className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <SummaryCard label="Identity" tone="muted">
          <p className="text-base font-semibold">
            <span className="font-mono text-ink-500">{repo.owner}/</span>
            {repo.name}
          </p>
          <p className="mt-1 break-all text-sm text-ink-700">
            {repo.canonical_url ?? "—"}
          </p>
          <p className="mt-1 text-xs text-ink-500">
            Default branch: <span className="font-mono">{repo.default_branch ?? "—"}</span>
          </p>
        </SummaryCard>
        <SummaryCard label="Source &amp; provider" tone="muted">
          <p className="text-sm text-ink-700">
            {repositorySourceLabel[repo.source_type]} ·{" "}
            {repositoryProviderLabel[repo.provider]}
          </p>
          <p className="mt-1 flex items-center gap-2 text-sm text-ink-700">
            <StatusBadge status={repo.visibility} />
            <span className="text-xs text-ink-500">
              {repositoryVisibilityLabel[repo.visibility]}
            </span>
            {repo.archived ? (
              <span className="rounded-full bg-ink-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-500">
                archived
              </span>
            ) : null}
          </p>
        </SummaryCard>
        <SummaryCard label="Identifiers" tone="muted">
          <CopyableIdentifier label="id" value={String(repo.id)} />
          <p className="mt-1 text-xs text-ink-500">
            Last provider sync: {formatTimestamp(repo.last_provider_sync_at)}
          </p>
          <Timestamp prefix="Added" value={repo.created_at} mode="both" />
        </SummaryCard>
      </section>

      <DataCompletenessNotice
        title="About this view"
        tone="muted"
        description="Repository identity, scan history, and stage pipeline are sourced from the live API. Dependency, workflow, vulnerability, OpenSSF, and licence summaries populate as the corresponding scans and analyzers are enabled. Pages that depend on a not-yet-implemented endpoint render an honest empty state."
      />

      <section className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <CompareScansCard repositoryId={repo.id} />
        <ExportShortcutsCard repositoryId={repo.id} scans={scans} />
      </section>

      <h2 className="mb-2 mt-6 text-sm font-semibold text-ink-700">Scans</h2>
      {scans === null || scansMeta === null ? (
        <Skeleton rows={3} />
      ) : scans.length === 0 ? (
        <EmptyState
          icon={<ScanSearch aria-hidden="true" className="h-8 w-8" />}
          title="No scans yet"
          description="Queue a scan to create a queued scan run. Lockverity v0.1 does not run an executor; scans stay queued until a worker is connected."
          action={
            <button
              type="button"
              className="btn-primary"
              onClick={handleCreateScan}
              disabled={triggering}
            >
              Queue a scan
            </button>
          }
        />
      ) : (
        <>
          <ResponsiveTable headers={["Scan", "Status", "Trigger", "Created"]}>
            {scans.map((scan) => (
              <tr key={scan.id} className="table-row">
                <td className="table-cell">
                  <Link
                    to={`/scans/${scan.id}`}
                    className="text-ink-900 hover:text-accent-700"
                  >
                    #{scan.id}
                  </Link>
                </td>
                <td className="table-cell">
                  <StatusBadge status={scan.status} />
                </td>
                <td className="table-cell text-ink-500">{scan.trigger_type}</td>
                <td className="table-cell text-ink-500">
                  <Timestamp value={scan.created_at} mode="relative" />
                </td>
              </tr>
            ))}
          </ResponsiveTable>
          <div className="mt-4">
            <Pagination meta={scansMeta} onPageChange={setPage} />
          </div>
        </>
      )}
    </>
  );
}

function CompareScansCard({
  repositoryId,
}: {
  repositoryId: number;
}) {
  const [scans, setScans] = useState<Scan[] | null>(null);
  const [base, setBase] = useState<number | null>(null);
  const [head, setHead] = useState<number | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    api
      .listScansForRepository(repositoryId, { page: 1, page_size: 50 })
      .then((r) => {
        if (controller.signal.aborted) return;
        setScans(r.items);
        // Mirror the v0.5 comparator rule: only completed
        // and partial scans are eligible. failed and cancelled
        // scans are not trustworthy for comparison.
        const eligible = r.items.filter(
          (s) => s.status === "completed" || s.status === "partial"
        );
        if (eligible.length >= 2) {
          setBase(eligible[1].id);
          setHead(eligible[0].id);
        } else if (eligible.length === 1) {
          setHead(eligible[0].id);
        }
      })
      .catch(() => {
        // best effort
      });
    return () => controller.abort();
  }, [repositoryId]);

  return (
    <div className="card">
      <h3 className="text-sm font-semibold text-ink-700">Compare scans</h3>
      <p className="mt-1 text-xs text-ink-500">
        Pick two scans to see added, removed, and persisting findings. Findings
        from a newer scan are not marked resolved when the older provider data
        is unavailable.
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <div className="flex flex-col">
          <label htmlFor="base-scan" className="text-xs text-ink-500">
            Base scan
          </label>
          <select
            id="base-scan"
            className="input mt-1"
            value={base ?? ""}
            onChange={(e) => setBase(Number.parseInt(e.target.value, 10))}
          >
            <option value="">— select —</option>
            {(scans ?? [])
              .filter(
                (scan) => scan.status === "completed" || scan.status === "partial"
              )
              .map((scan) => (
                <option key={scan.id} value={scan.id}>
                  #{scan.id} · {scan.status}
                </option>
              ))}
          </select>
        </div>
        <div className="flex flex-col">
          <label htmlFor="head-scan" className="text-xs text-ink-500">
            Head scan
          </label>
          <select
            id="head-scan"
            className="input mt-1"
            value={head ?? ""}
            onChange={(e) => setHead(Number.parseInt(e.target.value, 10))}
          >
            <option value="">— select —</option>
            {(scans ?? [])
              .filter(
                (scan) => scan.status === "completed" || scan.status === "partial"
              )
              .map((scan) => (
                <option key={scan.id} value={scan.id}>
                  #{scan.id} · {scan.status}
                </option>
              ))}
          </select>
        </div>
        <Link
          to={
            base && head
              ? `/scans/${head}/compare/${base}`
              : "/scans"
          }
          className={`btn-primary ${base && head ? "" : "pointer-events-none opacity-50"}`}
          aria-disabled={!(base && head)}
        >
          Compare
        </Link>
      </div>
    </div>
  );
}

function ExportShortcutsCard({
  repositoryId,
  scans,
}: {
  repositoryId: number;
  scans: Scan[] | null;
}) {
  const headScan = scans?.find(
    (s) => s.status === "completed" || s.status === "partial"
  );
  if (!headScan) {
    return (
      <div className="card">
        <h3 className="text-sm font-semibold text-ink-700">Exports</h3>
        <p className="mt-1 text-xs text-ink-500">
          Exports are available after at least one scan reaches a complete or
          partial state. Queue a scan to begin.
        </p>
      </div>
    );
  }
  return (
    <div className="card">
      <h3 className="text-sm font-semibold text-ink-700">Exports</h3>
      <p className="mt-1 text-xs text-ink-500">
        Generate a CycloneDX SBOM, SARIF, findings JSON, or findings CSV from
        the most recent completed scan.
      </p>
      <Link
        to={`/scans/${headScan.id}/exports`}
        className="btn-primary mt-3 inline-flex"
        data-repository={repositoryId}
      >
        Open export center
      </Link>
    </div>
  );
}
