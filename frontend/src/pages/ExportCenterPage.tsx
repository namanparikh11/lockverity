import { Download } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "@/api/api";
import { ApiClientError, describeError } from "@/api/client";
import { isNotImplemented } from "@/api/fallback";
import type { ExportDescriptor, ExportFormat } from "@/api/types";
import { ConfirmationDialog } from "@/components/ConfirmationDialog";
import { DataCompletenessNotice } from "@/components/DataCompletenessNotice";
import { ErrorState } from "@/components/ErrorState";
import { Notification } from "@/components/Notification";
import { PageHeader } from "@/components/PageHeader";
import { ResponsiveTable } from "@/components/ResponsiveTable";
import { Skeleton } from "@/components/Skeleton";

const KNOWN_FORMATS: ExportFormat[] = [
  "cyclonedx_json",
  "cyclonedx_1_7",
  "findings_json",
  "findings_csv",
  "sarif_json",
];

const FALLBACK_DESCRIPTORS: ExportDescriptor[] = [
  {
    format: "cyclonedx_json",
    label: "CycloneDX SBOM (JSON)",
    description: "CycloneDX 1.5 SBOM of every discovered component.",
    supported: true,
    not_supported_reason: null,
    content_type: "application/vnd.cyclonedx+json",
    filename_hint: "lockverity-sbom.cdx.json",
  },
  {
    format: "cyclonedx_1_7",
    label: "CycloneDX 1.7 SBOM (JSON)",
    description:
      "CycloneDX 1.7 software bill of materials as JSON. Generated against the official 1.7 schema. Only completed and partial scans with persisted local inventory are eligible.",
    supported: true,
    not_supported_reason: null,
    content_type: "application/vnd.cyclonedx+json; version=1.7",
    filename_hint: "lockverity-scan.cdx.json",
  },
  {
    format: "findings_json",
    label: "Findings (JSON)",
    description: "Raw findings list as JSON, including evidence and location.",
    supported: true,
    not_supported_reason: null,
    content_type: "application/json",
    filename_hint: "lockverity-findings.json",
  },
  {
    format: "findings_csv",
    label: "Findings (CSV)",
    description: "One finding per row. Severity and confidence remain separate columns.",
    supported: true,
    not_supported_reason: null,
    content_type: "text/csv",
    filename_hint: "lockverity-findings.csv",
  },
  {
    format: "sarif_json",
    label: "SARIF",
    description: "Static Analysis Results Interchange Format, for IDE and CI integration.",
    supported: true,
    not_supported_reason: null,
    content_type: "application/sarif+json",
    filename_hint: "lockverity-findings.sarif.json",
  },
];

/**
 * Export center.
 *
 * Lists every export the backend supports, with a truthful
 * "not supported" state when a format is unavailable. The user
 * is never given a download link that will 404 silently.
 */
export function ExportCenterPage() {
  const { scanId } = useParams<{ scanId: string }>();
  const sid = Number.parseInt(scanId ?? "", 10);
  const [items, setItems] = useState<ExportDescriptor[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [downloading, setDownloading] = useState<ExportFormat | null>(null);
  const [confirm, setConfirm] = useState<ExportFormat | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const [lastSuccess, setLastSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (!Number.isFinite(sid)) {
      setError(new Error("Invalid scan id."));
      return;
    }
    const controller = new AbortController();
    setItems(null);
    setError(null);
    api
      .listExports(sid)
      .then((r) => {
        if (controller.signal.aborted) return;
        const seen = new Set(r.items.map((it) => it.format));
        const merged = [...r.items];
        for (const known of KNOWN_FORMATS) {
          if (!seen.has(known)) {
            merged.push({
              format: known,
              label: fallbackLabel(known),
              description: "",
              supported: false,
              not_supported_reason: "Not exposed by the API yet.",
              content_type: "application/octet-stream",
              filename_hint: "",
            });
          }
        }
        setItems(merged);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        if (isNotImplemented(err)) {
          setItems(
            FALLBACK_DESCRIPTORS.map((d) => ({
              ...d,
              supported: false,
              not_supported_reason: "Export endpoint not exposed by the API yet.",
            }))
          );
          return;
        }
        setError(err);
      });
    return () => controller.abort();
  }, [sid]);

  async function performDownload(format: ExportFormat) {
    if (!Number.isFinite(sid)) return;
    setConfirm(null);
    setLastError(null);
    setLastSuccess(null);
    setDownloading(format);
    try {
      const result = await api.downloadExport(sid, format);
      const blob = new Blob([result.body], { type: result.contentType });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = result.filename ?? `lockverity-${format}.bin`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setLastSuccess(`Downloaded ${link.download}.`);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setLastError(describeError(err));
      } else {
        setLastError("Download failed.");
      }
    } finally {
      setDownloading(null);
    }
  }

  return (
    <>
      <PageHeader
        title={`Exports · scan #${sid}`}
        description="Generate a CycloneDX SBOM, SARIF, findings JSON, or findings CSV. Unsupported exports are disabled and explained - the UI never offers a download that 404s."
        breadcrumbs={[
          { label: "Scan", to: `/scans/${sid}` },
          { label: "Exports" },
        ]}
      />
      {lastSuccess ? (
        <div className="mb-4">
          <Notification tone="ok" title={lastSuccess} onDismiss={() => setLastSuccess(null)} />
        </div>
      ) : null}
      {lastError ? (
        <div className="mb-4">
          <Notification tone="danger" title="Export failed" description={lastError} onDismiss={() => setLastError(null)} />
        </div>
      ) : null}
      {error ? (
        <ErrorState error={error} />
      ) : items === null ? (
        <Skeleton rows={4} />
      ) : (
        <ResponsiveTable
          headers={["Format", "Description", "State", "Action"]}
        >
          {items.map((item) => (
            <tr key={item.format} className="table-row">
              <td className="table-cell">
                <p className="font-medium text-ink-900">{item.label}</p>
                <p className="font-mono text-[11px] text-ink-500">{item.format}</p>
              </td>
              <td className="table-cell text-ink-700">
                {item.description || "—"}
                {item.not_supported_reason ? (
                  <p className="mt-1 text-xs text-rose-700">{item.not_supported_reason}</p>
                ) : null}
              </td>
              <td className="table-cell">
                {item.supported ? (
                  <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
                    available
                  </span>
                ) : (
                  <span className="rounded-full bg-ink-100 px-2 py-0.5 text-xs font-medium text-ink-600">
                    not available
                  </span>
                )}
              </td>
              <td className="table-cell">
                {item.supported ? (
                  <button
                    type="button"
                    className="btn-primary"
                    onClick={() => setConfirm(item.format)}
                    disabled={downloading !== null}
                  >
                    <Download aria-hidden="true" className="h-4 w-4" />
                    {downloading === item.format ? "Preparing..." : "Download"}
                  </button>
                ) : (
                  <button type="button" className="btn-secondary" disabled aria-disabled="true">
                    <Download aria-hidden="true" className="h-4 w-4" />
                    Unavailable
                  </button>
                )}
              </td>
            </tr>
          ))}
        </ResponsiveTable>
      )}
      {!error ? (
        <div className="mt-4">
          <DataCompletenessNotice
            title="About exports"
            description="Exports are generated from the current scan's database state. A scan that has not yet produced findings produces an empty-but-valid export. The bytes are downloaded directly in the browser; they are not sent to any third-party service."
            tone="muted"
          />
        </div>
      ) : null}
      <ConfirmationDialog
        open={confirm !== null}
        title="Download export?"
        description={
          confirm
            ? `Download the ${fallbackLabel(confirm)} file for scan #${sid}?`
            : "Download this export?"
        }
        confirmLabel="Download"
        onConfirm={() => confirm && performDownload(confirm)}
        onCancel={() => setConfirm(null)}
      />
    </>
  );
}

function fallbackLabel(format: ExportFormat): string {
  switch (format) {
    case "cyclonedx_json":
      return "CycloneDX SBOM (JSON)";
    case "cyclonedx_1_7":
      return "CycloneDX 1.7 SBOM (JSON)";
    case "findings_json":
      return "Findings (JSON)";
    case "findings_csv":
      return "Findings (CSV)";
    case "sarif_json":
      return "SARIF";
    default:
      return format;
  }
}
