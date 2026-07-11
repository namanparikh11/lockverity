import { useEffect, useState } from "react";

import { api } from "@/api/api";
import { describeError } from "@/api/client";
import type { HealthResponse, Repository, Scan, SystemInfoResponse } from "@/api/types";
import { DataCompletenessNotice } from "@/components/DataCompletenessNotice";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { formatRelative } from "@/utils/time";

export function DashboardPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [info, setInfo] = useState<SystemInfoResponse | null>(null);
  const [repos, setRepos] = useState<Repository[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [h, i, r] = await Promise.all([
          api.health(),
          api.systemInfo(),
          api.listRepositories(1, 5),
        ]);
        if (cancelled) return;
        setHealth(h);
        setInfo(i);
        setRepos(r.items);
      } catch (err) {
        if (!cancelled) setError(err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <>
        <PageHeader title="Dashboard" />
        <ErrorState error={error} />
      </>
    );
  }
  if (!health || !info || !repos) {
    return (
      <>
        <PageHeader title="Dashboard" />
        <LoadingState label="Loading dashboard" />
      </>
    );
  }

  const recent = repos.slice(0, 5);

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="At-a-glance view of system health, recent repositories, and overall data completeness."
      />
      <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="card">
          <p className="label">Application</p>
          <p className="mt-1 text-lg font-semibold text-ink-900">{info.name}</p>
          <p className="text-sm text-ink-500">
            v{info.version} · {info.environment}
          </p>
        </div>
        <div className="card">
          <p className="label">Database</p>
          <p className="mt-1 text-lg font-semibold text-ink-900">
            <StatusBadge status={health.database === "ok" ? "available" : "unavailable"} />
          </p>
          <p className="mt-1 text-sm text-ink-500">Last checked {formatRelative(health.timestamp)}</p>
        </div>
        <div className="card">
          <p className="label">Registered repositories</p>
          <p className="mt-1 text-lg font-semibold text-ink-900">{repos.length}</p>
          <p className="text-sm text-ink-500">Across all sources</p>
        </div>
      </div>

      <div className="mb-6">
        <DataCompletenessNotice
          title="Lockverity is at architecture baseline (v0.1)"
          tone="muted"
          description="No vulnerability queries, archive extraction, or SBOM exports are wired up yet. Numbers above describe the operational state, not a security verdict."
        />
      </div>

      <section aria-labelledby="recent-repositories-heading" className="card">
        <h2
          id="recent-repositories-heading"
          className="text-sm font-semibold text-ink-700"
        >
          Recent repositories
        </h2>
        {recent.length === 0 ? (
          <p className="mt-2 text-sm text-ink-500">
            No repositories registered yet. Add one to start scheduling scans.
          </p>
        ) : (
          <ul className="mt-3 divide-y divide-ink-100 text-sm">
            {recent.map((repo) => (
              <li key={repo.id} className="flex items-center justify-between py-2">
                <a
                  href={`/repositories/${repo.id}`}
                  className="text-ink-700 hover:text-accent-700"
                >
                  <span className="font-mono text-xs text-ink-400">
                    {repo.owner}/
                  </span>
                  <span className="font-medium">{repo.name}</span>
                </a>
                <span className="text-xs text-ink-400">
                  added {formatRelative(repo.created_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2">
        <ScanSummaryCard />
      </section>
    </>
  );
}

function ScanSummaryCard() {
  // v0.1 has no aggregate scan endpoint; the card simply shows the
  // most recent scan from any repository, with a clear note that
  // counts are not yet available.
  const [recent, setRecent] = useState<Scan[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await api.listRepositories(1, 25);
        if (cancelled) return;
        const scansArrays = await Promise.all(
          r.items.map((repo) =>
            api.listScansForRepository(repo.id, 1, 1).catch(() => null)
          )
        );
        const flat: Scan[] = [];
        for (const item of scansArrays) {
          if (item) flat.push(...item.items);
        }
        flat.sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
        if (!cancelled) setRecent(flat.slice(0, 5));
      } catch (err) {
        if (!cancelled) setError(err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="card">
      <p className="label">Recent scans</p>
      {error ? (
        <p className="mt-2 text-sm text-rose-700">{describeError(error)}</p>
      ) : recent === null ? (
        <LoadingState label="Loading scans" />
      ) : recent.length === 0 ? (
        <p className="mt-2 text-sm text-ink-500">
          No scans queued yet. Add a repository and trigger a scan to see
          the lifecycle here.
        </p>
      ) : (
        <ul className="mt-2 divide-y divide-ink-100 text-sm">
          {recent.map((scan) => (
            <li key={scan.id} className="flex items-center justify-between py-2">
              <a
                href={`/scans/${scan.id}`}
                className="flex items-center gap-3 text-ink-700 hover:text-accent-700"
              >
                <StatusBadge status={scan.status} />
                <span className="font-mono text-xs text-ink-500">
                  scan #{scan.id}
                </span>
              </a>
              <span className="text-xs text-ink-400">
                {formatRelative(scan.created_at)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
