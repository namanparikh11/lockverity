/**
 * Tests for the v0.3 export download flow.
 *
 * The export center is the single place that triggers a
 * browser download. It must:
 *
 * - use the ``filename`` the server returned in the
 *   ``Content-Disposition`` header (not a guessed name);
 * - respect the file size and content type the server sent;
 * - surface a real error rather than silently falling back
 *   to a fixture.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/api/api";

describe("export download shape", () => {
  const originalFetch = global.fetch;
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("downloadExport returns the body, content type, and filename from the server", async () => {
    global.fetch = vi.fn(async () => {
      return new Response(
        JSON.stringify({ findings: [] }),
        {
          status: 200,
          headers: {
            "content-type": "application/json",
            "content-disposition":
              'attachment; filename="lockverity-findings.json"',
          },
        }
      );
    }) as unknown as typeof fetch;
    const result = await api.downloadExport(1, "findings_json");
    expect(result.contentType).toBe("application/json");
    expect(result.filename).toBe("lockverity-findings.json");
    expect(result.body).toContain("findings");
  });

  it("downloadExport returns the right filename for the SBOM export", async () => {
    global.fetch = vi.fn(async () => {
      return new Response(
        JSON.stringify({ bomFormat: "CycloneDX", specVersion: "1.5" }),
        {
          status: 200,
          headers: {
            "content-type": "application/json",
            "content-disposition":
              'attachment; filename="lockverity-sbom.cdx.json"',
          },
        }
      );
    }) as unknown as typeof fetch;
    const result = await api.downloadExport(1, "cyclonedx_json");
    expect(result.filename).toBe("lockverity-sbom.cdx.json");
  });

  it("listExports returns the supported format descriptors", async () => {
    global.fetch = vi.fn(async () =>
      new Response(
        JSON.stringify({
          items: [
            {
              format: "cyclonedx_json",
              label: "CycloneDX 1.5 SBOM (JSON)",
              description: "CycloneDX 1.5 software bill of materials as JSON.",
              supported: true,
              not_supported_reason: null,
              content_type: "application/json",
              filename_hint: "lockverity-sbom.cdx.json",
            },
            {
              format: "findings_json",
              label: "Findings (JSON)",
              description: "Every finding, with evidence and location.",
              supported: true,
              not_supported_reason: null,
              content_type: "application/json",
              filename_hint: "lockverity-findings.json",
            },
            {
              format: "findings_csv",
              label: "Findings (CSV)",
              description: "One finding per row.",
              supported: true,
              not_supported_reason: null,
              content_type: "text/csv",
              filename_hint: "lockverity-findings.csv",
            },
            {
              format: "sarif_json",
              label: "SARIF 2.1.0 (JSON)",
              description: "Static analysis results in SARIF 2.1.0 format.",
              supported: true,
              not_supported_reason: null,
              content_type: "application/sarif+json",
              filename_hint: "lockverity.sarif.json",
            },
          ],
        }),
        { status: 200, headers: { "content-type": "application/json" } }
      )
    ) as unknown as typeof fetch;
    const result = await api.listExports(1);
    expect(result.items).toHaveLength(4);
    for (const descriptor of result.items) {
      expect(descriptor.supported).toBe(true);
      expect(descriptor.filename_hint).toMatch(/^lockverity/);
    }
  });

  it("surfaces a real download error rather than falling back to a fixture", async () => {
    global.fetch = vi.fn(async () =>
      new Response(
        JSON.stringify({
          error: {
            code: "provider_unavailable",
            message: "Export service is not yet wired up.",
            request_id: "test-1",
          },
        }),
        { status: 503, headers: { "content-type": "application/json" } }
      )
    ) as unknown as typeof fetch;
    await expect(api.downloadExport(1, "findings_json")).rejects.toThrow(
      /not yet wired up/i
    );
  });
});

describe("upload path is the singular /repositories/upload", () => {
  it("createRepositoryUpload POSTs to /repositories/upload", async () => {
    const calls: string[] = [];
    global.fetch = vi.fn(async (url: RequestInfo | URL) => {
      calls.push(typeof url === "string" ? url : url.toString());
      return new Response(
        JSON.stringify({
          id: 1,
          source_type: "uploaded_archive",
          provider: "local_upload",
          owner: "",
          name: "archive.zip",
          canonical_url: null,
          default_branch: null,
          description: null,
          visibility: "unknown",
          archived: false,
          last_provider_sync_at: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }),
        { status: 201, headers: { "content-type": "application/json" } }
      );
    }) as unknown as typeof fetch;
    const blob = new Blob([new Uint8Array([1, 2, 3])], {
      type: "application/zip",
    });
    await api.createRepositoryUpload(blob);
    const url = new URL(calls[0]);
    expect(url.pathname).toBe("/api/v1/repositories/upload");
    // The plural form is the legacy dead-end; the v0.3 wire
    // must use the singular.
    expect(url.pathname).not.toBe("/api/v1/repositories/uploads");
  });
});
