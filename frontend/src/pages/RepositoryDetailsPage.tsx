import { Plus, ScanSearch } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "@/api/api";
import { describeError } from "@/api/client";
import type { PageMeta, Repository, Scan } from "@/api/types";
import { CopyableIdentifier } from "@/components/CopyableIdentifier";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { ResponsiveTable } from "@/components/ResponsiveTable";
import { StatusBadge } from "@/components/StatusBadge";
import { formatRelative, formatTimestamp } from "@/utils/time";

export function RepositoryDetailsPage() {
  const { repositoryId } = useParams<{ repositoryId: string }>();
  const repoId = Number.parseInt(repositoryId ?? "", 10);
  const [repo, setRepo] = useState<Repository | null>(null);
  const [scans, setScans] = useState<Scan[] | null>(null);
  const [scansMeta, setScansMeta] = useState<PageMeta | null>(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState<unknown>(null);
  const [triggering, setTriggering] = useState(false);

  useEffect(() => {
    if (!Number.isFinite(repoId)) {
      setError(new Error("Invalid repository id."));
      return;
    }
    const controller = new AbortController();
    setError(null);
    setRepo(null);
    setScans(null);
    api
      .getRepository(repoId)
      .then(setRepo)
      .catch((err) => {
        if (!controller.signal.aborted) setError(err);
      });
    return () => controller.abort();
  }, [repoId]);

  useEffect(() => {
    if (!Number.isFinite(repoId)) return;
    const controller = new AbortController();
    setScans(null);
    api
      .listScansForRepository(repoId, page, 10)
      .then((r) => {
        setScans(r.items);
        setScansMeta(r.pagination);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(err);
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
      // Refresh scans list immediately.
      const r = await api.listScansForRepository(repoId, 1, 10);
      setScans(r.items);
      setScansMeta(r.pagination);
      // We don't auto-navigate; the user can pick the new scan.
      // Keep a small affordance via setting "last created id".
      setLastCreatedScanId(scan.id);
    } catch (err) {
      setError(err);
    } finally {
      setTriggering(false);
    }
  }

  const [lastCreatedScanId, setLastCreatedScanId] = useState<number | null>(null);

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
        <LoadingState label="Loading repository" />
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
      <div className="card mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <p className="label">Canonical URL</p>
          <p className="mt-1 break-all text-sm text-ink-700">
            {repo.canonical_url ?? "—"}
          </p>
        </div>
        <div>
          <p className="label">Provider</p>
          <p className="mt-1 text-sm text-ink-700">
            {repo.provider} ({repo.source_type})
          </p>
        </div>
        <div>
          <p className="label">Visibility</p>
          <p className="mt-1">
            <StatusBadge status={repo.visibility} />
          </p>
        </div>
        <div>
          <p className="label">Identifiers</p>
          <p className="mt-1">
            <CopyableIdentifier label="id" value={String(repo.id)} />
          </p>
        </div>
        <div>
          <p className="label">Last provider sync</p>
          <p className="mt-1 text-sm text-ink-700">
            {formatTimestamp(repo.last_provider_sync_at)}
          </p>
        </div>
        <div>
          <p className="label">Added</p>
          <p className="mt-1 text-sm text-ink-700">
            {formatTimestamp(repo.created_at)}
          </p>
        </div>
      </div>
      <h2 className="mb-2 text-sm font-semibold text-ink-700">Scans</h2>
      {lastCreatedScanId ? (
        <p className="mb-2 text-sm text-emerald-700">
          Scan #{lastCreatedScanId} queued.{" "}
          <Link
            to={`/scans/${lastCreatedScanId}`}
            className="text-accent-700 hover:text-accent-800"
          >
            View scan →
          </Link>
        </p>
      ) : null}
      {scans === null || scansMeta === null ? (
        <LoadingState label="Loading scans" />
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
          <ResponsiveTable
            headers={["Scan", "Status", "Trigger", "Created"]}
          >
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
                  {formatRelative(scan.created_at)}
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

// Keep the import alive for tsc isolatedModules.
void describeError;
