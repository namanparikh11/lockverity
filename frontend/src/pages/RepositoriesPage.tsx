import { Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "@/api/api";
import type { PageMeta, Repository } from "@/api/types";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { ResponsiveTable } from "@/components/ResponsiveTable";
import { StatusBadge } from "@/components/StatusBadge";
import { formatRelative } from "@/utils/time";

export function RepositoriesPage() {
  const [repos, setRepos] = useState<Repository[] | null>(null);
  const [meta, setMeta] = useState<PageMeta | null>(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    const controller = new AbortController();
    setRepos(null);
    setError(null);
    api
      .listRepositories(page, 25)
      .then((r) => {
        setRepos(r.items);
        setMeta(r.pagination);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(err);
      });
    return () => controller.abort();
  }, [page]);

  return (
    <>
      <PageHeader
        title="Repositories"
        description="Public GitHub repositories registered for analysis."
        actions={
          <Link to="/repositories/new" className="btn-primary">
            <Plus aria-hidden="true" className="h-4 w-4" />
            Add repository
          </Link>
        }
      />
      {error ? (
        <ErrorState error={error} />
      ) : !repos || !meta ? (
        <LoadingState label="Loading repositories" />
      ) : repos.length === 0 ? (
        <EmptyState
          title="No repositories yet"
          description="Add a public GitHub repository to register it for analysis. The URL is normalized, the canonical form is stored, and no repository code is fetched or executed."
          action={
            <Link to="/repositories/new" className="btn-primary">
              <Plus aria-hidden="true" className="h-4 w-4" />
              Add your first repository
            </Link>
          }
        />
      ) : (
        <>
          <ResponsiveTable
            headers={["Repository", "Visibility", "Provider", "Added"]}
          >
            {repos.map((repo) => (
              <tr key={repo.id} className="table-row">
                <td className="table-cell">
                  <Link
                    to={`/repositories/${repo.id}`}
                    className="block font-medium text-ink-900 hover:text-accent-700"
                  >
                    <span className="font-mono text-xs text-ink-400">
                      {repo.owner}/
                    </span>
                    {repo.name}
                  </Link>
                  {repo.canonical_url ? (
                    <p className="mt-0.5 text-xs text-ink-500">
                      {repo.canonical_url}
                    </p>
                  ) : null}
                </td>
                <td className="table-cell">
                  <StatusBadge status={repo.visibility} />
                </td>
                <td className="table-cell">{repo.provider}</td>
                <td className="table-cell text-ink-500">
                  {formatRelative(repo.created_at)}
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
