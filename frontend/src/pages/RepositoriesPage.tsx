import { Plus, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "@/api/api";
import type { PageMeta, Repository, RepositoryProvider, RepositorySourceType } from "@/api/types";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { FilterBar, SelectFilter } from "@/components/FilterBar";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { ResponsiveTable } from "@/components/ResponsiveTable";
import { Skeleton } from "@/components/Skeleton";
import { StatusBadge } from "@/components/StatusBadge";
import { Timestamp } from "@/components/Timestamp";
import { repositoryProviderLabel, repositorySourceLabel, repositoryVisibilityLabel } from "@/utils/labels";

const PROVIDER_OPTIONS = [
  { value: "all", label: "All providers" },
  { value: "github", label: repositoryProviderLabel.github },
  { value: "local_upload", label: repositoryProviderLabel.local_upload },
];

const SOURCE_OPTIONS = [
  { value: "all", label: "All sources" },
  { value: "github", label: repositorySourceLabel.github },
  { value: "uploaded_archive", label: repositorySourceLabel.uploaded_archive },
];

const ARCHIVE_OPTIONS = [
  { value: "all", label: "All" },
  { value: "active", label: "Active only" },
  { value: "archived", label: "Archived only" },
];

/**
 * Lockverity repository portfolio. Search, provider / source
 * filters, archive filter, pagination, and clear empty /
 * filtered-empty states.
 */
export function RepositoriesPage() {
  const [repos, setRepos] = useState<Repository[] | null>(null);
  const [meta, setMeta] = useState<PageMeta | null>(null);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [provider, setProvider] = useState<"all" | RepositoryProvider>("all");
  const [source, setSource] = useState<"all" | RepositorySourceType>("all");
  const [archive, setArchive] = useState<"all" | "archived" | "active">("all");
  const [error, setError] = useState<unknown>(null);

  // Reset to page 1 when filters change.
  useEffect(() => {
    setPage(1);
  }, [search, provider, source, archive]);

  useEffect(() => {
    const controller = new AbortController();
    setRepos(null);
    setError(null);
    api
      .listRepositories({
        page,
        page_size: 25,
        search: search || undefined,
        provider: provider === "all" ? undefined : provider,
        source_type: source === "all" ? undefined : source,
        archived: archive,
      })
      .then((r) => {
        if (controller.signal.aborted) return;
        setRepos(r.items);
        setMeta(r.pagination);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        setError(err);
      });
    return () => controller.abort();
  }, [page, search, provider, source, archive]);

  const filtersActive = Boolean(
    search || provider !== "all" || source !== "all" || archive !== "all"
  );

  function clearAll() {
    setSearch("");
    setProvider("all");
    setSource("all");
    setArchive("all");
  }

  return (
    <>
      <PageHeader
        title="Repositories"
        description="Public GitHub repositories and uploaded source archives registered for analysis."
        actions={
          <div className="flex flex-wrap gap-2">
            <Link to="/repositories/upload" className="btn-secondary">
              <Upload aria-hidden="true" className="h-4 w-4" />
              Upload archive
            </Link>
            <Link to="/repositories/new" className="btn-primary">
              <Plus aria-hidden="true" className="h-4 w-4" />
              Add repository
            </Link>
          </div>
        }
      />
      <div className="mb-4">
        <FilterBar
          search={search}
          onSearchChange={setSearch}
          searchPlaceholder="Search by name, owner, or canonical URL"
          onClear={filtersActive ? clearAll : undefined}
          resultCount={meta?.total}
          resultLabel="repositories"
        >
          <SelectFilter
            id="provider-filter"
            label="Provider"
            value={provider}
            onChange={(v) => setProvider(v as "all" | RepositoryProvider)}
            options={PROVIDER_OPTIONS}
          />
          <SelectFilter
            id="source-filter"
            label="Source"
            value={source}
            onChange={(v) => setSource(v as "all" | RepositorySourceType)}
            options={SOURCE_OPTIONS}
          />
          <SelectFilter
            id="archive-filter"
            label="Archive state"
            value={archive}
            onChange={(v) => setArchive(v as "all" | "archived" | "active")}
            options={ARCHIVE_OPTIONS}
          />
        </FilterBar>
      </div>
      {error ? (
        <ErrorState error={error} title="Could not load repositories" />
      ) : !repos || !meta ? (
        <Skeleton rows={6} />
      ) : repos.length === 0 ? (
        filtersActive ? (
          <EmptyState
            title="No repositories match your filters"
            description="Clear the filters to see every registered repository, or refine the search."
            action={
              <button type="button" className="btn-secondary" onClick={clearAll}>
                Clear filters
              </button>
            }
          />
        ) : (
          <EmptyState
            title="No repositories yet"
            description="Add a public GitHub repository or upload a source archive to register it for analysis. The URL is normalized, the canonical form is stored, and no repository code is fetched or executed."
            action={
              <div className="flex flex-wrap justify-center gap-2">
                <Link to="/repositories/new" className="btn-primary">
                  <Plus aria-hidden="true" className="h-4 w-4" />
                  Add your first repository
                </Link>
                <Link to="/repositories/upload" className="btn-secondary">
                  <Upload aria-hidden="true" className="h-4 w-4" />
                  Upload archive
                </Link>
              </div>
            }
          />
        )
      ) : (
        <>
          <ResponsiveTable
            headers={["Repository", "Source", "Provider", "Visibility", "Last sync", "Added"]}
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
                    {repo.archived ? (
                      <span className="ml-2 inline-block rounded-full bg-ink-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-500">
                        archived
                      </span>
                    ) : null}
                  </Link>
                  {repo.canonical_url ? (
                    <p className="mt-0.5 text-xs text-ink-500">
                      {repo.canonical_url}
                    </p>
                  ) : repo.default_branch ? (
                    <p className="mt-0.5 text-xs text-ink-500">
                      default branch {repo.default_branch}
                    </p>
                  ) : null}
                </td>
                <td className="table-cell text-ink-500">
                  {repositorySourceLabel[repo.source_type]}
                </td>
                <td className="table-cell text-ink-500">
                  {repositoryProviderLabel[repo.provider]}
                </td>
                <td className="table-cell">
                  <StatusBadge status={repo.visibility} />
                  <span className="sr-only">
                    {repositoryVisibilityLabel[repo.visibility]}
                  </span>
                </td>
                <td className="table-cell text-ink-500">
                  <Timestamp value={repo.last_provider_sync_at} mode="relative" />
                </td>
                <td className="table-cell text-ink-500">
                  <Timestamp value={repo.created_at} mode="relative" />
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
