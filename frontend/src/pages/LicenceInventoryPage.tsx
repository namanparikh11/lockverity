import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "@/api/api";
import { isNotImplemented } from "@/api/fallback";
import type { LicenceAssertion, PageMeta } from "@/api/types";
import { DataCompletenessNotice } from "@/components/DataCompletenessNotice";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { FilterBar, SelectFilter } from "@/components/FilterBar";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { ResponsiveTable } from "@/components/ResponsiveTable";
import { Skeleton } from "@/components/Skeleton";
import { StatusBadge } from "@/components/StatusBadge";

const SCOPE_OPTIONS = [
  { value: "all", label: "All" },
  { value: "direct", label: "Direct" },
  { value: "transitive", label: "Transitive" },
];

const REVIEW_OPTIONS = [
  { value: "all", label: "All review states" },
  { value: "unreviewed", label: "Unreviewed" },
  { value: "review_required", label: "Review required" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "unknown", label: "Unknown" },
];

/**
 * Licence inventory.
 *
 * Per-component licence assertions, with review status,
 * provider attribution, and a non-legal-advice notice.
 */
export function LicenceInventoryPage() {
  const { scanId } = useParams<{ scanId: string }>();
  const sid = Number.parseInt(scanId ?? "", 10);
  const [items, setItems] = useState<LicenceAssertion[] | null>(null);
  const [meta, setMeta] = useState<PageMeta | null>(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState<unknown>(null);
  const [filters, setFilters] = useState<{
    search: string;
    provider: string;
    review_status: string;
    direct_transitive: "all" | "direct" | "transitive";
  }>({
    search: "",
    provider: "",
    review_status: "all",
    direct_transitive: "all",
  });
  const [notImpl, setNotImpl] = useState(false);

  useEffect(() => {
    setPage(1);
  }, [filters]);

  useEffect(() => {
    if (!Number.isFinite(sid)) {
      setError(new Error("Invalid scan id."));
      return;
    }
    const controller = new AbortController();
    setItems(null);
    setError(null);
    api
      .listLicences(sid, {
        page,
        page_size: 50,
        search: filters.search || undefined,
        provider: filters.provider || undefined,
        review_status: filters.review_status === "all" ? undefined : filters.review_status,
        direct_transitive: filters.direct_transitive,
      })
      .then((r) => {
        if (controller.signal.aborted) return;
        setItems(r.items);
        setMeta(r.pagination);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        if (isNotImplemented(err)) {
          setItems([]);
          setMeta({ page: 1, page_size: 0, total: 0, total_pages: 0 });
          setNotImpl(true);
          return;
        }
        setError(err);
      });
    return () => controller.abort();
  }, [sid, page, filters]);

  return (
    <>
      <PageHeader
        title={`Licence inventory · scan #${sid}`}
        description="Detected licence assertions per component, with provider attribution and review status."
        breadcrumbs={[
          { label: "Scan", to: `/scans/${sid}` },
          { label: "Licences" },
        ]}
      />
      <div className="mb-4">
        <DataCompletenessNotice
          title="Not legal advice"
          tone="warn"
          description="Lockverity surfaces detected licence assertions and their provider source. It does not interpret licence compatibility, provide legal advice, or substitute for human review by qualified counsel."
        />
      </div>
      <div className="mb-4">
        <FilterBar
          search={filters.search}
          onSearchChange={(v) => setFilters((f) => ({ ...f, search: v }))}
          searchPlaceholder="Search by package or licence"
          resultCount={meta?.total}
          resultLabel="assertions"
        >
          <div className="flex items-center gap-2">
            <label htmlFor="provider" className="text-xs text-ink-500">
              Provider
            </label>
            <input
              id="provider"
              className="input w-32 font-mono text-xs"
              placeholder="deps.dev, ..."
              value={filters.provider}
              onChange={(e) => setFilters((f) => ({ ...f, provider: e.target.value }))}
            />
          </div>
          <SelectFilter
            id="review"
            label="Review"
            value={filters.review_status}
            onChange={(v) => setFilters((f) => ({ ...f, review_status: v }))}
            options={REVIEW_OPTIONS}
          />
          <SelectFilter
            id="scope"
            label="Scope"
            value={filters.direct_transitive}
            onChange={(v) => setFilters((f) => ({ ...f, direct_transitive: v as "all" | "direct" | "transitive" }))}
            options={SCOPE_OPTIONS}
          />
        </FilterBar>
      </div>
      {error ? (
        <ErrorState error={error} />
      ) : items === null || meta === null ? (
        <Skeleton rows={6} />
      ) : items.length === 0 ? (
        <EmptyState
          title={notImpl ? "Licence endpoint not exposed" : "No licence assertions recorded"}
          description={
            notImpl
              ? "When the backend exposes a paginated licence endpoint, this table will appear automatically."
              : "No licence assertions were recorded for this scan. The dependency-enrichment stage may not have run yet."
          }
        />
      ) : (
        <>
          <ResponsiveTable
            headers={["Package", "Version", "Licence", "Provider", "Direct?", "Review", "Unknown?"]}
          >
            {items.map((assertion) => (
              <tr key={assertion.id} className="table-row">
                <td className="table-cell font-mono text-xs text-ink-700">
                  {assertion.package_name}
                </td>
                <td className="table-cell text-ink-500">
                  {assertion.version ?? "—"}
                </td>
                <td className="table-cell text-ink-700">
                  {assertion.licence}
                </td>
                <td className="table-cell text-ink-500">
                  {assertion.provider}
                </td>
                <td className="table-cell">
                  <StatusBadge status={assertion.direct ? "available" : "transitive"} />
                </td>
                <td className="table-cell">
                  <StatusBadge status={assertion.review_status} />
                </td>
                <td className="table-cell">
                  <StatusBadge status={assertion.unknown_licence ? "unknown" : "completed"} />
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
