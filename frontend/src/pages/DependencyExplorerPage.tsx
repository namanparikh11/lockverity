import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "@/api/api";
import { ApiClientError, describeError } from "@/api/client";
import { isNotImplemented } from "@/api/fallback";
import type {
  Component,
  ComponentEvidenceResponse,
  DependencyPath,
  PageMeta,
} from "@/api/types";
import { ComponentIdentity, DependencyPathView } from "@/components/DependencyPath";
import { DetailsDrawer } from "@/components/DetailsDrawer";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { FilterBar, SelectFilter } from "@/components/FilterBar";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { ResponsiveTable } from "@/components/ResponsiveTable";
import { Skeleton } from "@/components/Skeleton";

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
  // v0.8 evidence drilldown: a second side drawer surfaces
  // the read-only evidence summary for the same component.
  // The evidence fetch is lazy: it only fires when the user
  // clicks the "View evidence" button on a row. The fetch
  // is aborted on unmount.
  const [evidence, setEvidence] = useState<ComponentEvidenceResponse | null>(null);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);

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

  // v0.8 evidence drilldown: a separate, lazy fetch that
  // surfaces the read-only evidence summary for the
  // currently selected component. The fetch is aborted on
  // unmount and on component change.
  useEffect(() => {
    if (!selected) {
      setEvidence(null);
      setEvidenceError(null);
      return;
    }
    if (!Number.isFinite(sid)) return;
    const controller = new AbortController();
    setEvidenceLoading(true);
    setEvidenceError(null);
    api
      .getComponentEvidence(sid, selected.id)
      .then((response) => {
        if (controller.signal.aborted) return;
        setEvidence(response);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        if (err instanceof ApiClientError) {
          if (err.apiError.httpStatus === 404) {
            setEvidenceError("Evidence is not available for this component.");
            return;
          }
          setEvidenceError(describeError(err));
          return;
        }
        setEvidenceError("Evidence is not available for this component.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setEvidenceLoading(false);
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
            headers={["Package", "Ecosystem", "Version", "Source", "Direct?", "Scope", "Evidence"]}
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
                  <span className="font-mono">{component.direct ? "yes" : "no"}</span>
                </td>
                <td className="table-cell text-ink-500">
                  {component.scope ?? "—"}
                </td>
                <td className="table-cell">
                  <button
                    type="button"
                    className="rounded border border-ink-300 bg-white px-2 py-1 text-xs font-medium text-ink-800"
                    onClick={(e) => {
                      e.stopPropagation();
                      setSelected(component);
                      // The drawer effect picks up the
                      // selected component and fetches
                      // the evidence summary.
                    }}
                    data-testid={`component-evidence-button-${component.id}`}
                    aria-label={`View evidence for ${component.package_name}`}
                  >
                    View evidence
                  </button>
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
            <div>
              <h3 className="label">Component evidence</h3>
              <ComponentEvidencePanel
                evidence={evidence}
                error={evidenceError}
                loading={evidenceLoading}
              />
            </div>
          </div>
        ) : null}
      </DetailsDrawer>
    </>
  );
}

/**
 * v0.8 component evidence panel.
 *
 * Renders the read-only evidence summary for the currently
 * selected component inside the existing DetailsDrawer. The
 * panel surfaces every documented section (identity, manifest,
 * licence, provider, dependency, export implications, omissions)
 * with the evidence-honesty wording the contract guarantees.
 *
 * The panel never:
 *
 * - describes the component as clean / secure / fixed;
 * - claims the dependency graph is complete;
 * - claims the SBOM is a security verdict;
 * - fabricates missing values.
 */
function ComponentEvidencePanel({
  evidence,
  error,
  loading,
}: {
  evidence: ComponentEvidenceResponse | null;
  error: string | null;
  loading: boolean;
}) {
  if (error) {
    return (
      <p
        className="mt-1 rounded border border-rose-200 bg-rose-50 p-2 text-xs text-rose-900"
        data-testid="component-evidence-error"
      >
        {error}
      </p>
    );
  }
  if (loading && !evidence) {
    return (
      <p
        className="mt-1 text-xs text-ink-500"
        data-testid="component-evidence-loading"
      >
        Loading evidence…
      </p>
    );
  }
  if (!evidence) {
    return (
      <p
        className="mt-1 text-xs text-ink-500"
        data-testid="component-evidence-empty"
      >
        Evidence is not yet available.
      </p>
    );
  }
  const c = evidence.component;
  const impl = evidence.export_implications;
  return (
    <div className="mt-1 space-y-3 text-xs" data-testid="component-evidence-panel">
      <div>
        <p className="text-[10px] uppercase tracking-wide text-ink-500">Identity</p>
        <ul className="mt-1 space-y-0.5 text-ink-700">
          <li>
            <span className="text-ink-500">Package:</span>{" "}
            <span className="font-mono" data-testid="ce-package-name">
              {c.package_name}
            </span>
          </li>
          <li>
            <span className="text-ink-500">Ecosystem:</span>{" "}
            <span className="font-mono">{c.ecosystem ?? "—"}</span>
          </li>
          <li>
            <span className="text-ink-500">Version:</span>{" "}
            <span className="font-mono">{c.version ?? "—"}</span>{" "}
            <span className="text-ink-500">(source: {c.version_source ?? "—"})</span>
          </li>
          <li>
            <span className="text-ink-500">Direct:</span>{" "}
            <span className="font-mono">{c.direct ? "yes" : "no"}</span>
          </li>
          <li>
            <span className="text-ink-500">PURL:</span>{" "}
            <span className="font-mono" data-testid="ce-purl">
              {c.package_url ?? "—"}
            </span>
            {c.package_url_well_formed === false ? (
              <span className="ml-2 text-rose-700">persisted PURL malformed</span>
            ) : null}
            {c.package_url === null && c.purl_constructible ? (
              <span className="ml-2 text-ink-500">
                PURL omitted from persistence but constructible from ecosystem + name + version.
              </span>
            ) : null}
          </li>
        </ul>
      </div>
      <EvidenceManifestBlock manifest={evidence.manifest} />
      <EvidenceLicenceBlock licence={evidence.licence_evidence} />
      <EvidenceProviderBlock provider={evidence.provider_evidence} />
      <EvidenceDependencyBlock dependency={evidence.dependency_evidence} />
      <EvidenceExportImplications impl={impl} />
      <EvidenceOmissions omissions={evidence.omissions} />
    </div>
  );
}

function EvidenceManifestBlock({
  manifest,
}: {
  manifest: ComponentEvidenceResponse["manifest"];
}) {
  if (!manifest.available) {
    return (
      <div>
        <p className="text-[10px] uppercase tracking-wide text-ink-500">
          Manifest evidence
        </p>
        <p className="mt-1 text-ink-700" data-testid="ce-manifest-empty">
          No persisted manifest association available.
        </p>
      </div>
    );
  }
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-ink-500">
        Manifest evidence
      </p>
      <ul className="mt-1 space-y-0.5 text-ink-700" data-testid="ce-manifest">
        <li>
          <span className="text-ink-500">Path:</span>{" "}
          <span className="font-mono">{manifest.path ?? "—"}</span>
        </li>
        <li>
          <span className="text-ink-500">Type:</span>{" "}
          <span className="font-mono">{manifest.manifest_type ?? "—"}</span>
        </li>
        <li>
          <span className="text-ink-500">Parse status:</span>{" "}
          <span className="font-mono">{manifest.parse_status ?? "—"}</span>
        </li>
        <li>
          <span className="text-ink-500">Warnings:</span>{" "}
          <span className="font-mono">{manifest.parse_warning_count ?? 0}</span>
        </li>
      </ul>
    </div>
  );
}

function EvidenceLicenceBlock({
  licence,
}: {
  licence: ComponentEvidenceResponse["licence_evidence"];
}) {
  if (!licence.available) {
    return (
      <div>
        <p className="text-[10px] uppercase tracking-wide text-ink-500">
          Licence evidence
        </p>
        <p className="mt-1 text-ink-700" data-testid="ce-licence-empty">
          No persisted licence evidence available.
        </p>
      </div>
    );
  }
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-ink-500">
        Licence evidence
      </p>
      <ul className="mt-1 space-y-0.5 text-ink-700" data-testid="ce-licence">
        {licence.observations.map((o, idx) => (
          <li key={`${o.finding_id}-${idx}`}>
            <span className="font-mono">{o.value}</span>{" "}
            <span className="text-ink-500">
              ({o.classification}, {o.provenance})
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function EvidenceProviderBlock({
  provider,
}: {
  provider: ComponentEvidenceResponse["provider_evidence"];
}) {
  if (!provider.available) {
    return (
      <div>
        <p className="text-[10px] uppercase tracking-wide text-ink-500">
          Provider / advisory evidence
        </p>
        <p className="mt-1 text-ink-700" data-testid="ce-provider-empty">
          No provider observations or advisories were recorded for this
          component.
        </p>
      </div>
    );
  }
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-ink-500">
        Provider / advisory evidence
      </p>
      <ul className="mt-1 space-y-0.5 text-ink-700" data-testid="ce-provider">
        {provider.observations.map((o) => (
          <li key={o.id}>
            <span className="font-mono">{o.provider}</span>{" "}
            <span className="text-ink-500">({o.operation}):</span>{" "}
            <span className="font-mono">{o.status}</span>{" "}
            {o.http_status ? (
              <span className="text-ink-500">http {o.http_status}</span>
            ) : null}
          </li>
        ))}
        {provider.advisories.map((a) => (
          <li key={a.advisory_id}>
            <span className="font-mono">
              {a.canonical_id ?? a.source_advisory_id ?? a.advisory_id}
            </span>{" "}
            <span className="text-ink-500">
              ({a.severity_label ?? "unknown"})
            </span>{" "}
            {a.confidence === null ? (
              <span className="text-ink-500">no confidence supplied</span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function EvidenceDependencyBlock({
  dependency,
}: {
  dependency: ComponentEvidenceResponse["dependency_evidence"];
}) {
  const coverage = dependency.graph_coverage;
  if (dependency.no_edges_observed) {
    return (
      <div>
        <p className="text-[10px] uppercase tracking-wide text-ink-500">
          Dependency evidence
        </p>
        <p className="mt-1 text-ink-700" data-testid="ce-dependency-empty">
          No persisted dependency edges for this component. The
          dependency graph coverage is reported as <span className="font-mono">{coverage}</span>;
          a partial / unknown graph is not the same as &ldquo;no dependencies&rdquo;.
        </p>
      </div>
    );
  }
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-ink-500">
        Dependency evidence
      </p>
      <p className="mt-1 text-ink-700" data-testid="ce-dependency">
        Incoming: {dependency.incoming.length}, outgoing:{" "}
        {dependency.outgoing.length}. Coverage:{" "}
        <span className="font-mono">{coverage}</span>.
      </p>
    </div>
  );
}

function EvidenceExportImplications({
  impl,
}: {
  impl: ComponentEvidenceResponse["export_implications"];
}) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-ink-500">
        Export implications
      </p>
      <ul className="mt-1 space-y-0.5 text-ink-700" data-testid="ce-export">
        <li>
          Appears in CycloneDX 1.7:{" "}
          <span className="font-mono">{impl.appears_in_cyclonedx_17 ? "yes" : "no"}</span>
        </li>
        <li>
          Version omitted from export:{" "}
          <span className="font-mono">{impl.version_omitted ? "yes" : "no"}</span>
          {impl.version_omitted ? (
            <span className="text-ink-500">
              {" "}
              — no concrete version was persisted, so the export
              leaves the version field empty.
            </span>
          ) : null}
        </li>
        <li>
          PURL emitted in export:{" "}
          <span className="font-mono">{impl.purl_emitted ? "yes" : "no"}</span>
        </li>
        <li>
          Dependency relationships emitted:{" "}
          <span className="font-mono">
            {impl.dependency_relationships_emitted ? "yes" : "no"}
          </span>{" "}
          <span className="text-ink-500">
            (graph coverage {impl.graph_coverage})
          </span>
        </li>
      </ul>
    </div>
  );
}

function EvidenceOmissions({ omissions }: { omissions: string[] }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-ink-500">
        Evidence-honesty markers
      </p>
      <ul
        className="mt-1 list-disc space-y-0.5 pl-5 text-ink-700"
        data-testid="ce-omissions"
      >
        {omissions.map((marker) => (
          <li key={marker}>
            <span className="font-mono">{marker}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
