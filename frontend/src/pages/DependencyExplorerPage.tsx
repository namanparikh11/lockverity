import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "@/api/api";
import { isNotImplemented } from "@/api/fallback";
import type { Component, DependencyPath, PageMeta } from "@/api/types";
import { ComponentIdentity, DependencyPathView } from "@/components/DependencyPath";
import { DetailsDrawer } from "@/components/DetailsDrawer";
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

const DEV_OPTIONS = [
  { value: "all", label: "All" },
  { value: "production", label: "Production" },
  { value: "development", label: "Development" },
];

const VULN_OPTIONS = [
  { value: "all", label: "All" },
  { value: "vulnerable", label: "Vulnerable only" },
];

/**
 * Dependency explorer.
 *
 * Inventory-first view: every component is a row. Filters
 * collapse the list to the subset the operator is investigating.
 * A dependency-path viewer opens in a side drawer.
 */
export function DependencyExplorerPage() {
  const { scanId } = useParams<{ scanId: string }>();
  const sid = Number.parseInt(scanId ?? "", 10);
  const [items, setItems] = useState<Component[] | null>(null);
  const [meta, setMeta] = useState<PageMeta | null>(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState<unknown>(null);
  const [filters, setFilters] = useState<{
    search: string;
    ecosystem: string;
    scope: "all" | "direct" | "transitive";
    development: "all" | "production" | "development";
    vulnerable_only: "all" | "vulnerable";
  }>({
    search: "",
    ecosystem: "",
    scope: "all",
    development: "all",
    vulnerable_only: "all",
  });
  const [selected, setSelected] = useState<Component | null>(null);
  const [path, setPath] = useState<DependencyPath | null>(null);
  const [pathLoading, setPathLoading] = useState(false);
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
      .listComponents(sid, {
        page,
        page_size: 50,
        search: filters.search || undefined,
        ecosystem: filters.ecosystem || undefined,
        scope: filters.scope,
        development: filters.development,
        vulnerable_only: filters.vulnerable_only,
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

  useEffect(() => {
    if (!selected) {
      setPath(null);
      return;
    }
    if (!Number.isFinite(sid)) return;
    const controller = new AbortController();
    setPathLoading(true);
    api
      .getDependencyPath(sid, selected.id)
      .then((p) => {
        if (controller.signal.aborted) return;
        setPath(p);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        if (isNotImplemented(err)) {
          setPath({ components: [selected], edges: [], truncated: false });
          return;
        }
        setPath(null);
      })
      .finally(() => {
        if (!controller.signal.aborted) setPathLoading(false);
      });
    return () => controller.abort();
  }, [sid, selected]);

  return (
    <>
      <PageHeader
        title={`Dependencies · scan #${sid}`}
        description="Inventory of every component discovered in this scan. Filters narrow the list; the dependency path viewer explains how a transitive component was reached."
        breadcrumbs={[
          { label: "Scan", to: `/scans/${sid}` },
          { label: "Dependencies" },
        ]}
      />
      <div className="mb-4">
        <FilterBar
          search={filters.search}
          onSearchChange={(v) => setFilters((f) => ({ ...f, search: v }))}
          searchPlaceholder="Search package name"
          resultCount={meta?.total}
          resultLabel="components"
        >
          <div className="flex items-center gap-2">
            <label htmlFor="ecosystem" className="text-xs text-ink-500">
              Ecosystem
            </label>
            <input
              id="ecosystem"
              className="input w-32 font-mono text-xs"
              placeholder="npm, PyPI, ..."
              value={filters.ecosystem}
              onChange={(e) => setFilters((f) => ({ ...f, ecosystem: e.target.value }))}
            />
          </div>
          <SelectFilter
            id="scope"
            label="Scope"
            value={filters.scope}
            onChange={(v) => setFilters((f) => ({ ...f, scope: v as "all" | "direct" | "transitive" }))}
            options={SCOPE_OPTIONS}
          />
          <SelectFilter
            id="development"
            label="Lifecycle"
            value={filters.development}
            onChange={(v) => setFilters((f) => ({ ...f, development: v as "all" | "production" | "development" }))}
            options={DEV_OPTIONS}
          />
          <SelectFilter
            id="vuln"
            label="Vulnerable"
            value={filters.vulnerable_only}
            onChange={(v) => setFilters((f) => ({ ...f, vulnerable_only: v as "all" | "vulnerable" }))}
            options={VULN_OPTIONS}
          />
        </FilterBar>
      </div>
      {error ? (
        <ErrorState error={error} />
      ) : items === null || meta === null ? (
        <Skeleton rows={6} />
      ) : items.length === 0 ? (
        <EmptyState
          title={notImpl ? "Dependency endpoint not exposed" : "No components recorded"}
          description={
            notImpl
              ? "When the backend exposes a paginated components endpoint, this table will appear automatically."
              : "No components were discovered for this scan. The manifest-discovery or dependency-parsing stage may not have run."
          }
        />
      ) : (
        <>
          <ResponsiveTable
            headers={["Package", "Ecosystem", "Version", "Source", "Direct?", "Scope"]}
          >
            {items.map((component) => (
              <tr
                key={component.id}
                className="table-row cursor-pointer hover:bg-ink-50"
                onClick={() => setSelected(component)}
              >
                <td className="table-cell">
                  <ComponentIdentity component={component} />
                </td>
                <td className="table-cell text-ink-500">
                  {component.ecosystem ?? "—"}
                </td>
                <td className="table-cell text-ink-500">
                  {component.version ?? "—"}
                </td>
                <td className="table-cell text-ink-500">
                  {component.version_source}
                </td>
                <td className="table-cell">
                  <StatusBadge status={component.direct ? "available" : "transitive"} />
                </td>
                <td className="table-cell text-ink-500">
                  {component.scope ?? "—"}
                </td>
              </tr>
            ))}
          </ResponsiveTable>
          <div className="mt-4">
            <Pagination meta={meta} onPageChange={setPage} />
          </div>
        </>
      )}
      <DetailsDrawer
        open={selected !== null}
        onClose={() => setSelected(null)}
        title={selected ? `${selected.package_name}` : ""}
        ariaLabel="Dependency details"
      >
        {selected ? (
          <div className="space-y-4">
            <div>
              <h3 className="label">Identity</h3>
              <p className="mt-1 text-sm text-ink-800">
                <ComponentIdentity component={selected} />
              </p>
              <p className="mt-1 text-xs text-ink-500">
                Ecosystem: <span className="font-mono">{selected.ecosystem ?? "—"}</span> ·
                Source: <span className="font-mono">{selected.version_source}</span>
              </p>
            </div>
            <div>
              <h3 className="label">Dependency path</h3>
              {pathLoading ? (
                <Skeleton rows={3} />
              ) : (
                <DependencyPathView path={path} />
              )}
            </div>
            {selected.optional || selected.development ? (
              <div>
                <h3 className="label">Lifecycle</h3>
                <ul className="mt-1 list-disc pl-5 text-sm text-ink-700">
                  {selected.optional ? <li>Optional dependency</li> : null}
                  {selected.development ? <li>Development-only dependency</li> : null}
                </ul>
              </div>
            ) : null}
          </div>
        ) : null}
      </DetailsDrawer>
    </>
  );
}
