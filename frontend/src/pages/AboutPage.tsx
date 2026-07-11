import { PageHeader } from "@/components/PageHeader";

export function AboutPage() {
  return (
    <>
      <PageHeader
        title="About Lockverity"
        description="Evidence-first software supply-chain assurance."
      />
      <div className="prose prose-sm max-w-3xl text-ink-700">
        <p>
          Lockverity analyzes the software supply chain of public GitHub
          repositories and uploaded source archives. It does not execute
          analyzed code.
        </p>
        <h2 className="mt-6 text-base font-semibold text-ink-900">
          What v0.1 includes
        </h2>
        <ul className="ml-5 list-disc space-y-1">
          <li>Persistent data model for repositories, scans, stages, findings, and provider observations.</li>
          <li>Safe utilities for URL normalization, path normalization, archive-entry validation, JSON bounds, finding-key derivation, and provider-error redaction.</li>
          <li>Read and write API for the scan lifecycle.</li>
          <li>Frontend shell with explicit first-run empty states.</li>
          <li>Tests, Alembic migration cycle, and CI workflows.</li>
        </ul>
        <h2 className="mt-6 text-base font-semibold text-ink-900">
          What v0.1 does not include
        </h2>
        <ul className="ml-5 list-disc space-y-1">
          <li>Live GitHub repository downloading.</li>
          <li>Archive extraction.</li>
          <li>Manifest parsing for any ecosystem.</li>
          <li>OSV, deps.dev, or OpenSSF integration.</li>
          <li>GitHub Actions rule analysis.</li>
          <li>CycloneDX SBOM, SARIF, JSON, or CSV export.</li>
          <li>Scan comparison.</li>
          <li>Authentication, multi-tenancy, billing, or AI features.</li>
        </ul>
        <h2 className="mt-6 text-base font-semibold text-ink-900">
          Provider-honesty policy
        </h2>
        <p>
          Lockverity never represents a missing or unavailable provider as
          &ldquo;no vulnerabilities found.&rdquo; A provider&rsquo;s unavailable result is
          recorded as such and surfaced on the Provider status page. See{" "}
          <code>docs/provider-honesty.md</code> for the full policy.
        </p>
        <h2 className="mt-6 text-base font-semibold text-ink-900">
          Non-execution guarantee
        </h2>
        <p>
          Lockverity never invokes <code>npm install</code>, <code>pip install</code>,
          <code> poetry install</code>, <code>yarn install</code>,
          <code> pnpm install</code>, <code>setup.py</code>, or any
          Makefile / shell script present in an analyzed repository. See
          <code> SECURITY.md</code> for the full threat model.
        </p>
      </div>
    </>
  );
}
