import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "@/api/api";
import type { Scan } from "@/api/types";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { PageHeader } from "@/components/PageHeader";
import { ResponsiveTable } from "@/components/ResponsiveTable";
import { StatusBadge } from "@/components/StatusBadge";
import { formatRelative } from "@/utils/time";

/**
 * Index of all known scans, paginated across repositories.
 * Used when a user lands on /scans without a specific id.
 */
export function ScansIndexPage() {
  const [items, setItems] = useState<Scan[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const params = useParams();

  useEffect(() => {
    if (params.scanId) return; // not our route
    const controller = new AbortController();
    (async () => {
      try {
        const repos = await api.listRepositories({ page: 1, page_size: 50 });
        const results = await Promise.all(
          repos.items.map((repo) =>
            api.listScansForRepository(repo.id, { page: 1, page_size: 5 }).catch(() => null)
          )
        );
        const flat: Scan[] = [];
        for (const r of results) {
          if (r) flat.push(...r.items);
        }
        flat.sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
        if (!controller.signal.aborted) setItems(flat);
      } catch (err) {
        if (!controller.signal.aborted) setError(err);
      }
    })();
    return () => controller.abort();
  }, [params.scanId]);

  if (error) {
    return (
      <>
        <PageHeader title="Scans" />
        <ErrorState error={error} />
      </>
    );
  }
  if (items === null) {
    return (
      <>
        <PageHeader title="Scans" />
        <LoadingState label="Loading scans" />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Scans"
        description="Recent scans across all repositories."
      />
      {items.length === 0 ? (
        <EmptyState
          title="No scans yet"
          description="Add a repository and queue a scan to populate this list."
          action={
            <Link to="/repositories" className="btn-primary">
              Go to repositories
            </Link>
          }
        />
      ) : (
        <ResponsiveTable headers={["Scan", "Status", "Repository", "Created"]}>
          {items.map((scan) => (
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
              <td className="table-cell text-ink-500">
                <Link
                  to={`/repositories/${scan.repository_id}`}
                  className="hover:text-accent-700"
                >
                  repo #{scan.repository_id}
                </Link>
              </td>
              <td className="table-cell text-ink-500">
                {formatRelative(scan.created_at)}
              </td>
            </tr>
          ))}
        </ResponsiveTable>
      )}
    </>
  );
}
