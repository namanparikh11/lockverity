import { PageHeader } from "@/components/PageHeader";

/**
 * About page copy.
 *
 * Every claim on this page is derived from code that ships in the
 * repository - the parser list, the rule list, the analyzer list,
 * the exporter list, and the API surface are all sourced from
 * ``backend/app/parsers``, ``backend/app/rules``,
 * ``backend/app/analyzers``, ``backend/app/exporters``, and
 * ``backend/app/api``.
 *
 * Implemented vs planned capabilities are listed in two separate
 * sections so a reader cannot mistake a forward-looking roadmap
 * item for a working feature.
 */
export function AboutPage() {
  return (
    <>
      <PageHeader
        title="About Lockverity"
        description="Evidence-first software supply-chain assurance."
      />
      <div className="prose prose-sm max-w-3xl text-ink-700">
        <p>
          Lockverity inspects the software supply chain of public GitHub
          repositories and uploaded source archives. It does not execute
          analyzed code; it never calls <code>npm install</code>,{" "}
          <code>pip install</code>, <code>poetry install</code>, or any
          Makefile / shell script from a repository.
        </p>

        <h2 className="mt-6 text-base font-semibold text-ink-900">
          What v0.9 implements today
        </h2>
        <p className="text-xs uppercase tracking-wide text-ink-500">
          All items in this list have direct, exercised code paths in this
          repository. None of them are aspirational.
        </p>
        <ul className="ml-5 list-disc space-y-1">
          <li>
            <strong>Persistent data model</strong> for repositories, scans,
            stages, findings, advisories, components, dependency edges,
            provider observations, scan jobs, workspaces, and provider
            cache.
          </li>
          <li>
            <strong>Defensive utilities</strong> for path normalization,
            archive-entry validation, bounded HTTP, bounded JSON,
            provider-error redaction, finding-key derivation, and
            spreadsheet-safe CSV writing.
          </li>
          <li>
            <strong>Two intake paths</strong>:{" "}
            <code>POST /api/v1/repositories/github</code> (public GitHub URL)
            and <code>POST /api/v1/repositories/upload</code> (ZIP archive
            upload with streaming, validation, and quarantine).
          </li>
          <li>
            <strong>Manifest parsers</strong> for npm
            (<code>package.json</code>, <code>package-lock.json</code>),
            pnpm, Yarn, Poetry,{" "}
            <code>pyproject.toml</code>, and <code>requirements.txt</code>.
          </li>
          <li>
            <strong>Vulnerability rules</strong> (direct, transitive, no
            fixed version, withdrawn advisory, unresolved version, partial
            provider data, provider unavailable, multiple dependency
            paths, vulnerable development dependency, missing lockfile).
          </li>
          <li>
            <strong>Licence rules</strong> (unknown licence, multiple
            assertions, review required, provider unavailable, full
            inventory).
          </li>
          <li>
            <strong>GitHub Actions workflow analysis</strong> with a
            manifest-discovery pass and a dependency-graph pass.
          </li>
          <li>
            <strong>Provider integrations</strong> for GitHub, OSV,
            deps.dev, and OpenSSF Scorecard, plus a bounded HTTP client
            and a provider-cache layer with TTL.
          </li>
          <li>
            <strong>Exporters</strong> for CycloneDX 1.5 and 1.7 SBOM
            (JSON), SARIF 2.1.0 (JSON), findings JSON, and findings CSV.
          </li>
          <li>
            <strong>CycloneDX 1.7 SBOM evidence preview</strong> on the
            Export Center page: a read-only summary at{" "}
            <code>{"GET /api/v1/scans/{id}/exports/cyclonedx_1_7/preview"}</code>{" "}
            that surfaces scan identity, eligibility verdict, inventory
            summary, evidence coverage, SBOM output facts, omissions,
            and the legacy-export relationship note before the user
            downloads the SBOM. The preview is generated from the
            existing v0.6 eligibility helper and never produces a full
            BOM; the actual download endpoint is the one that runs the
            official JSON 1.7 schema validator.
          </li>
          <li>
            <strong>Component evidence drilldown</strong> on the
            Dependency Explorer page: a read-only summary at{" "}
            <code>{"GET /api/v1/scans/{id}/components/{cid}/evidence"}</code>{" "}
            that surfaces component identity, manifest evidence,
            licence evidence, provider observations, advisories, and
            the CycloneDX 1.7 export implications for one component.
            The endpoint reuses the v0.6 CycloneDX exporter helpers
            for PURL, bom-ref, licence classification, and graph
            coverage, so the evidence block never disagrees with the
            actual SBOM. Missing licence evidence, missing provider
            evidence, missing dependency edges, and missing versions
            are surfaced as bounded omissions rather than fabricated
            values.
          </li>
          <li>
            <strong>Evidence search and filtering</strong> on the
            Dependency Explorer page: a read-only surface at{" "}
            <code>{"GET /api/v1/scans/{id}/components/evidence-summary"}</code>{" "}
            that lets the operator narrow the component list by text
            search, ecosystem, direct / transitive, version present /
            missing, licence evidence present / missing, provider
            evidence present / missing, PURL persisted / constructible
            / omitted, dependency edges observed / none observed, and
            CycloneDX 1.7 export implications (appears, version
            omitted, dependency relationships emitted). The endpoint
            reuses the v0.6 and v0.8 helpers for PURL, bom-ref,
            licence classification, and graph coverage, so the filter
            state cannot disagree with the detail drawer or the
            CycloneDX 1.7 SBOM. The summary vocabulary is
            evidence-honest: missing evidence is rendered as
            &ldquo;not persisted&rdquo; / &ldquo;none observed&rdquo;,
            dependency edges use the wording &ldquo;no persisted
            edges&rdquo; (never &ldquo;no dependencies&rdquo;), and
            the PURL filter distinguishes a deliberately omitted PURL
            from a reconstructed one. Facet counts are informational
            only; the endpoint never returns a verdict.
          </li>
          <li>
            <strong>Local scan worker</strong> with a 10-stage pipeline,
            per-stage status, scan cancellation, and per-scan heartbeat
            monitoring.
          </li>
          <li>
            <strong>API surface</strong>: repositories, scans, stages,
            findings, provider observations, provider health rollup,
            scan comparison, exports (including a CycloneDX 1.7 SBOM
            that is validated against the official 1.7 schema and
            surfaced with deterministic serial numbers, an evidence
            preview summary, and explicit evidence-coverage
            properties), system info, system provider limits, and
            administrative workspace cleanup. All errors use a stable
            envelope and never leak stack traces.
          </li>
          <li>
            <strong>Frontend</strong> shell with a typed API client,
            request cancellation, structured error parsing, reduced-motion
            support, visible focus states, and explicit first-run empty
            states that distinguish &ldquo;no data&rdquo; from
            &ldquo;verified clean&rdquo;.
          </li>
        </ul>

        <h2 className="mt-6 text-base font-semibold text-ink-900">
          What v0.9 does <em>not</em> include
        </h2>
        <p className="text-xs uppercase tracking-wide text-ink-500">
          Planned for later milestones, not implemented today.
        </p>
        <ul className="ml-5 list-disc space-y-1">
          <li>Authentication, multi-tenancy, billing, or self-service signup.</li>
          <li>Continuous / scheduled scans. v0.5 scans are explicit operator actions.</li>
          <li>Private GitHub repository analysis (v0.5 is public-only; the
            <code>LOCKVERITY_GITHUB_TOKEN</code> environment variable is
            honoured for public rate limits but private endpoints are out of
            scope).
          </li>
          <li>
            LLM-driven analysis, exploit generation, or any other offensive
            feature.
          </li>
          <li>
            Dependency-path visualisation for transitive vulnerabilities
            in the frontend (the data is on the wire; the page is not yet
            wired in).
          </li>
        </ul>

        <h2 className="mt-6 text-base font-semibold text-ink-900">
          Provider-honesty policy
        </h2>
        <p>
          Lockverity never represents a missing or unavailable provider as
          &ldquo;no vulnerabilities found.&rdquo; A provider&rsquo;s unavailable
          result is recorded as such and surfaced on the{" "}
          <a href="/providers">Provider health</a> page. See{" "}
          <code>docs/provider-honesty.md</code> for the full policy.
        </p>

        <h2 className="mt-6 text-base font-semibold text-ink-900">
          Non-execution guarantee
        </h2>
        <p>
          Lockverity never invokes <code>npm install</code>,{" "}
          <code>pip install</code>, <code>poetry install</code>,{" "}
          <code>yarn install</code>, <code>pnpm install</code>,{" "}
          <code>setup.py</code>, or any Makefile / shell script present in
          an analyzed repository. See <code>SECURITY.md</code> for the full
          threat model.
        </p>

        <h2 className="mt-6 text-base font-semibold text-ink-900">
          Source-honest product positioning
        </h2>
        <p>
          Lockverity does not publish a single &ldquo;security score&rdquo; and
          will not. Severity, confidence, provider availability, and data
          completeness are independent dimensions in the data model and in
          the UI. The frontend renders each dimension separately so that
          a low-data result cannot be mistaken for a clean bill of health.
        </p>
      </div>
    </>
  );
}
