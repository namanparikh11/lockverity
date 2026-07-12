import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "@/api/api";
import { isNotImplemented } from "@/api/fallback";
import type {
  Finding,
  FindingCategory,
  FindingConfidence,
  FindingSeverity,
  FindingStatus,
  PageMeta,
} from "@/api/types";
import { CodeLocation } from "@/components/CodeLocation";
import { ConfidenceBadge } from "@/components/ConfidenceBadge";
import { DataCompletenessNotice } from "@/components/DataCompletenessNotice";
import { DetailsDrawer } from "@/components/DetailsDrawer";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { FilterBar, SelectFilter } from "@/components/FilterBar";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { ResponsiveTable } from "@/components/ResponsiveTable";
import { SeverityBadge } from "@/components/SeverityBadge";
import { Skeleton } from "@/components/Skeleton";
import { StatusBadge } from "@/components/StatusBadge";
import { Timestamp } from "@/components/Timestamp";
import {
  findingCategoryLabel,
  findingConfidenceLabel,
  findingSeverityLabel,
  findingStatusLabel,
} from "@/utils/labels";

const CATEGORY_OPTIONS = [
  { value: "all", label: "All categories" },
  { value: "dependency", label: findingCategoryLabel.dependency },
  { value: "vulnerability", label: findingCategoryLabel.vulnerability },
  { value: "workflow", label: findingCategoryLabel.workflow },
  { value: "repository_posture", label: findingCategoryLabel.repository_posture },
  { value: "licence", label: findingCategoryLabel.licence },
  { value: "provider", label: findingCategoryLabel.provider },
  { value: "data_quality", label: findingCategoryLabel.data_quality },
];

const SEVERITY_OPTIONS = [
  { value: "all", label: "All severities" },
  { value: "critical", label: findingSeverityLabel.critical },
  { value: "high", label: findingSeverityLabel.high },
  { value: "medium", label: findingSeverityLabel.medium },
  { value: "low", label: findingSeverityLabel.low },
  { value: "informational", label: findingSeverityLabel.informational },
  { value: "unknown", label: findingSeverityLabel.unknown },
];

const CONFIDENCE_OPTIONS = [
  { value: "all", label: "All confidences" },
  { value: "confirmed", label: findingConfidenceLabel.confirmed },
  { value: "high", label: findingConfidenceLabel.high },
  { value: "medium", label: findingConfidenceLabel.medium },
  { value: "low", label: findingConfidenceLabel.low },
  { value: "unknown", label: findingConfidenceLabel.unknown },
];

const STATUS_OPTIONS = [
  { value: "all", label: "All statuses" },
  { value: "open", label: findingStatusLabel.open },
  { value: "resolved", label: findingStatusLabel.resolved },
  { value: "accepted", label: findingStatusLabel.accepted },
  { value: "suppressed", label: findingStatusLabel.suppressed },
];

const SCOPE_OPTIONS = [
  { value: "all", label: "All" },
  { value: "direct", label: "Direct" },
  { value: "transitive", label: "Transitive" },
];

/**
 * Findings explorer.
 *
 * Filters: search, category, severity, confidence, rule id, path,
 * status, direct / transitive, provider. The selected finding is
 * rendered in a side drawer with summary, evidence (rendered as
 * text - never as HTML), location, dependency path, advisories,
 * provider attribution, remediation, confidence explanation,
 * limitations, and scan context.
 */
export function FindingsPage() {
  const { scanId } = useParams<{ scanId: string }>();
  const sid = Number.parseInt(scanId ?? "", 10);
  const [findings, setFindings] = useState<Finding[] | null>(null);
  const [meta, setMeta] = useState<PageMeta | null>(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState<unknown>(null);
  const [selected, setSelected] = useState<Finding | null>(null);
  const [filters, setFilters] = useState<{
    search: string;
    category: "all" | FindingCategory;
    severity: "all" | FindingSeverity;
    confidence: "all" | FindingConfidence;
    rule_id: string;
    path: string;
    status: "all" | FindingStatus;
    direct_transitive: "all" | "direct" | "transitive";
    provider: string;
  }>({
    search: "",
    category: "all",
    severity: "all",
    confidence: "all",
    rule_id: "",
    path: "",
    status: "all",
    direct_transitive: "all",
    provider: "",
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
    setFindings(null);
    setError(null);
    api
      .listFindings(sid, {
        page,
        page_size: 25,
        search: filters.search || undefined,
        category: filters.category,
        severity: filters.severity,
        confidence: filters.confidence,
        rule_id: filters.rule_id || undefined,
        path: filters.path || undefined,
        status: filters.status,
        direct_transitive: filters.direct_transitive,
        provider: filters.provider || undefined,
      })
      .then((r) => {
        if (controller.signal.aborted) return;
        setFindings(r.items);
        setMeta(r.pagination);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        if (isNotImplemented(err)) {
          setFindings([]);
          setMeta({ page: 1, page_size: 0, total: 0, total_pages: 0 });
          setNotImpl(true);
          return;
        }
        setError(err);
      });
    return () => controller.abort();
  }, [sid, page, filters]);

  const activeFilterCount = useMemo(() => {
    return [
      filters.search,
      filters.category !== "all" ? filters.category : "",
      filters.severity !== "all" ? filters.severity : "",
      filters.confidence !== "all" ? filters.confidence : "",
      filters.rule_id,
      filters.path,
      filters.status !== "all" ? filters.status : "",
      filters.direct_transitive !== "all" ? filters.direct_transitive : "",
      filters.provider,
    ].filter(Boolean).length;
  }, [filters]);

  function clearFilters() {
    setFilters({
      search: "",
      category: "all",
      severity: "all",
      confidence: "all",
      rule_id: "",
      path: "",
      status: "all",
      direct_transitive: "all",
      provider: "",
    });
  }

  if (error) {
    return (
      <>
        <PageHeader
          title={`Findings · scan #${sid}`}
          breadcrumbs={[
            { label: "Scan", to: `/scans/${sid}` },
            { label: "Findings" },
          ]}
        />
        <ErrorState error={error} />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title={`Findings · scan #${sid}`}
        description="Each finding is evidence-backed, severity-tagged, and confidence-tagged. Severity and confidence are independent dimensions."
        breadcrumbs={[
          { label: "Scan", to: `/scans/${sid}` },
          { label: "Findings" },
        ]}
      />
      {notImpl ? (
        <div className="mb-4">
          <DataCompletenessNotice
            title="Findings list endpoint not yet implemented"
            description="The backend does not currently expose a paginated findings endpoint. The page renders the same shape it will once the endpoint is available, with the filter bar and detail drawer ready."
            tone="info"
          />
        </div>
      ) : null}
      <div className="mb-4 space-y-3">
        <FilterBar
          search={filters.search}
          onSearchChange={(v) => setFilters((f) => ({ ...f, search: v }))}
          searchPlaceholder="Search title, summary, evidence, or remediation"
          onClear={activeFilterCount > 0 ? clearFilters : undefined}
          resultCount={meta?.total}
          resultLabel="findings"
        >
          <SelectFilter
            id="category-filter"
            label="Category"
            value={filters.category}
            onChange={(v) => setFilters((f) => ({ ...f, category: v as "all" | FindingCategory }))}
            options={CATEGORY_OPTIONS}
          />
          <SelectFilter
            id="severity-filter"
            label="Severity"
            value={filters.severity}
            onChange={(v) => setFilters((f) => ({ ...f, severity: v as "all" | FindingSeverity }))}
            options={SEVERITY_OPTIONS}
          />
          <SelectFilter
            id="confidence-filter"
            label="Confidence"
            value={filters.confidence}
            onChange={(v) => setFilters((f) => ({ ...f, confidence: v as "all" | FindingConfidence }))}
            options={CONFIDENCE_OPTIONS}
          />
          <SelectFilter
            id="status-filter"
            label="Status"
            value={filters.status}
            onChange={(v) => setFilters((f) => ({ ...f, status: v as "all" | FindingStatus }))}
            options={STATUS_OPTIONS}
          />
          <SelectFilter
            id="scope-filter"
            label="Scope"
            value={filters.direct_transitive}
            onChange={(v) => setFilters((f) => ({ ...f, direct_transitive: v as "all" | "direct" | "transitive" }))}
            options={SCOPE_OPTIONS}
          />
        </FilterBar>
        <details className="rounded-md border border-ink-200 bg-white p-3 text-sm">
          <summary className="cursor-pointer text-ink-700">Advanced filters</summary>
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <label htmlFor="rule-id" className="label">Rule id</label>
              <input
                id="rule-id"
                className="input mt-1 font-mono"
                placeholder="LOCK-SUPPLY-001"
                value={filters.rule_id}
                onChange={(e) => setFilters((f) => ({ ...f, rule_id: e.target.value }))}
              />
            </div>
            <div>
              <label htmlFor="path-filter" className="label">Path</label>
              <input
                id="path-filter"
                className="input mt-1 font-mono"
                placeholder="src/ or package.json"
                value={filters.path}
                onChange={(e) => setFilters((f) => ({ ...f, path: e.target.value }))}
              />
            </div>
            <div>
              <label htmlFor="provider-filter" className="label">Provider</label>
              <input
                id="provider-filter"
                className="input mt-1 font-mono"
                placeholder="osv, deps.dev, ..."
                value={filters.provider}
                onChange={(e) => setFilters((f) => ({ ...f, provider: e.target.value }))}
              />
            </div>
          </div>
        </details>
      </div>
      {findings === null || meta === null ? (
        <Skeleton rows={5} />
      ) : findings.length === 0 ? (
        notImpl ? (
          <EmptyState
            title="Findings endpoint not exposed"
            description="When the backend exposes a paginated findings list, this table will appear automatically."
          />
        ) : activeFilterCount > 0 ? (
          <EmptyState
            title="No findings match the filters"
            description="Loosen the filters to see more results, or clear them entirely."
            action={
              <button type="button" className="btn-secondary" onClick={clearFilters}>
                Clear filters
              </button>
            }
          />
        ) : (
          <EmptyState
            title="No findings recorded"
            description="Analyzers, rules, and vulnerability providers are not yet enabled. When they are, this page will list each finding with its evidence summary."
          />
        )
      ) : (
        <>
          <ResponsiveTable
            headers={["Rule", "Title", "Category", "Severity", "Confidence", "Status", "Path", "Updated"]}
          >
            {findings.map((finding) => (
              <tr
                key={finding.id}
                className="table-row cursor-pointer focus-within:bg-ink-50 hover:bg-ink-50"
                onClick={() => setSelected(finding)}
              >
                <td className="table-cell font-mono text-xs text-ink-500">
                  <Link
                    to={`/scans/${finding.scan_run_id}/findings#finding-${finding.id}`}
                    onClick={(e) => e.stopPropagation()}
                    className="hover:text-accent-700"
                  >
                    {finding.rule_id}
                  </Link>
                </td>
                <td className="table-cell">
                  <p className="font-medium text-ink-900">{finding.title}</p>
                  <p className="line-clamp-2 text-xs text-ink-500">{finding.summary}</p>
                </td>
                <td className="table-cell text-ink-500">
                  {findingCategoryLabel[finding.category]}
                </td>
                <td className="table-cell">
                  <SeverityBadge severity={finding.severity} />
                </td>
                <td className="table-cell">
                  <ConfidenceBadge confidence={finding.confidence} />
                </td>
                <td className="table-cell">
                  <StatusBadge status={finding.status} />
                </td>
                <td className="table-cell text-ink-500">
                  <CodeLocation
                    path={finding.location_path}
                    startLine={finding.location_start_line}
                    endLine={finding.location_end_line}
                  />
                </td>
                <td className="table-cell text-ink-500">
                  <Timestamp value={finding.updated_at} mode="relative" />
                </td>
              </tr>
            ))}
          </ResponsiveTable>
          <div className="mt-4">
            <Pagination meta={meta} onPageChange={setPage} />
          </div>
        </>
      )}
      <FindingDrawer finding={selected} onClose={() => setSelected(null)} />
    </>
  );
}

function FindingDrawer({
  finding,
  onClose,
}: {
  finding: Finding | null;
  onClose: () => void;
}) {
  if (!finding) return null;
  return (
    <DetailsDrawer
      open={finding !== null}
      onClose={onClose}
      title={finding.title}
      ariaLabel={`Finding ${finding.rule_id}`}
    >
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs text-ink-500">{finding.rule_id}</span>
          <SeverityBadge severity={finding.severity} />
          <ConfidenceBadge confidence={finding.confidence} />
          <StatusBadge status={finding.status} />
          <span className="text-xs text-ink-500">
            {findingCategoryLabel[finding.category]}
          </span>
        </div>
        <section>
          <h3 className="label">Summary</h3>
          <p className="mt-1 text-sm text-ink-800">{finding.summary}</p>
        </section>
        <section>
          <h3 className="label">Location</h3>
          <div className="mt-1">
            <CodeLocation
              path={finding.location_path}
              startLine={finding.location_start_line}
              endLine={finding.location_end_line}
            />
          </div>
        </section>
        {finding.evidence_json ? (
          <section>
            <h3 className="label">Evidence</h3>
            <pre className="mt-1 max-h-64 overflow-auto rounded-md border border-ink-200 bg-ink-50 p-2 font-mono text-xs text-ink-800">
              {safePrettyJson(finding.evidence_json)}
            </pre>
          </section>
        ) : null}
        {finding.remediation ? (
          <section>
            <h3 className="label">Remediation</h3>
            <p className="mt-1 text-sm text-ink-800">{finding.remediation}</p>
          </section>
        ) : null}
        <section>
          <h3 className="label">Severity &amp; confidence</h3>
          <p className="mt-1 text-sm text-ink-700">
            Severity: <strong>{findingSeverityLabel[finding.severity]}</strong> ·
            Confidence: <strong>{findingConfidenceLabel[finding.confidence]}</strong>
          </p>
          <p className="mt-1 text-xs text-ink-500">
            Severity and confidence are independent dimensions. A critical
            finding with low confidence is not a confirmed vulnerability; a
            medium finding with confirmed confidence is.
          </p>
        </section>
        <section>
          <h3 className="label">Scan context</h3>
          <p className="mt-1 text-sm text-ink-700">
            Scan <Link to={`/scans/${finding.scan_run_id}`} className="text-accent-700 hover:text-accent-800">#{finding.scan_run_id}</Link>{" "}
            on repository #{finding.repository_id}.
          </p>
          <Timestamp prefix="Recorded" value={finding.created_at} mode="both" />
        </section>
        <section>
          <h3 className="label">Limitations</h3>
          <ul className="mt-1 list-disc pl-5 text-xs text-ink-500">
            <li>Evidence is rendered as text - it is never parsed as HTML.</li>
            <li>The stable key uniquely identifies this finding within the scan.</li>
            <li>Missing provider data is recorded as &ldquo;not requested&rdquo;, never as &ldquo;clean&rdquo;.</li>
          </ul>
        </section>
      </div>
    </DetailsDrawer>
  );
}

function safePrettyJson(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}
