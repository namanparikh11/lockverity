# Lockverity — Release Notes

## What Lockverity is

Lockverity is an **evidence-first, defensive-only, read-only**
analyzer for the software supply chain of public GitHub
repositories and uploaded source archives. It never executes
analyzed code, never calls a Makefile / shell script / install
hook, and never claims that an absence of evidence is a clean
bill of health. Every claim the UI makes is backed by a file
path, a manifest, a provider response, or an explicit omission
marker.

The product is built around three guarantees:

- **Non-execution.** Lockverity never invokes `npm install`,
  `pip install`, `poetry install`, `yarn install`,
  `pnpm install`, `setup.py`, or any Makefile / shell script
  from an analyzed repository. See
  [`docs/security-boundaries.md`](docs/security-boundaries.md)
  for the full boundary statement.
- **Provider-honesty.** A missing or unavailable provider is
  recorded as such and surfaced explicitly; the UI never
  converts absence into "no findings". See
  [`docs/provider-honesty.md`](docs/provider-honesty.md).
- **Source-honest claims.** Severity, confidence, provider
  availability, and data completeness are independent
  dimensions in the data model and in the UI. A partial
  dependency graph is reported as `partial`, never
  `complete`.

## Status — local-first release candidate

The repository is a **local-first release candidate**,
not a production SaaS, not a hosted service, and not a
CI vendor. The current milestone (`v2.0.3`) is a focused
first-run reproducibility repair on top of `v2.0.2`.
v2.0.3 does not add a new product feature or a new
provider; it ships one real release-blocking defect
discovered during the v2.0.2 clean-state acceptance
gate (the documented one-command release-verification
script failed on a fresh clean checkout because
`backend/pyproject.toml` declared ``ruff>=0.4.0`` and
a clean ``pip install -e ".[dev]"`` resolved the latest
ruff, which produced a different format than the one
the committed files were last formatted against) and the
regression tests that pin the fix. The v2.0.3 contract
preserves the v2.0.2 boundary preservation in full. The
v2.0 release-validation script and the v2.0.1/v2.0.2
acceptance flows are documented in
[`docs/release-checklist.md`](docs/release-checklist.md).
The v2.0 surface area includes the v1.9
provider-health and operational-diagnostics page,
the v1.8 repository history and comparison workflow,
the v1.7 findings workbench, the v1.6.1 workspace-
preserving rescan repair, the v1.6 scan workbench, the
v1.5 guided intake, the v1.0 Markdown evidence
report, the v0.9 evidence search, the v0.8 component
drilldown, the v0.7 CycloneDX preview, the v0.6
CycloneDX 1.7 export, and the v0.5 evidence-aware
comparison. There is:

- **No multi-tenancy** and no authentication. A reviewer runs
  the application on their own laptop.
- **No hosted component.** The application is not deployed
  anywhere by the maintainers. There is no marketing site, no
  signup flow, and no telemetry.
- **No SaaS SLA.** This is a code-and-documentation baseline;
  the maintainers do not run the application on anyone else's
  behalf.
- **No production hardening.** The configuration defaults are
  safe for local development but the application has not been
  penetration-tested for multi-tenant production deployment.

If a future release changes this status (e.g. adds hosted
deployment), this section will be the first thing rewritten
and the change will be called out in `CHANGELOG.md`.

## What the demo can show today

A single engineer on a laptop can demonstrate every v0.5–v1.2
surface in under five minutes without any provider credentials
or hosted services. The flow is:

```powershell
cd "C:\Users\Naman Parikh\Documents\Minimax Projects\Lockverity\backend"
.\.venv\Scripts\python.exe scripts\load_demo.py --reset-demo-db
$env:LOCKVERITY_DATABASE_URL = "sqlite:///var/demo/lockverity-demo.sqlite"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8765

cd "C:\Users\Naman Parikh\Documents\Minimax Projects\Lockverity\frontend"
$env:VITE_API_PROXY_TARGET = "http://127.0.0.1:8765"
npm install
npm run dev
```

The five demo URLs a reviewer opens are:

- `http://127.0.0.1:5173/` — scan list (4 scans, all four
  terminal states).
- `http://127.0.0.1:5173/scans/1/dependencies` — Dependency
  Explorer, 6 components, evidence filters.
- `http://127.0.0.1:5173/scans/1/exports` — Export Center,
  CycloneDX 1.7 preview, evidence report.
- `http://127.0.0.1:5173/scans/3/exports` — bounded empty
  state for a failed scan.
- `http://127.0.0.1:5173/about` — About page + product
  boundaries.

The loader's success-path output already prints all of the
above plus the cross-platform startup commands. The full
reviewer walkthrough is in
[`docs/demo-walkthrough.md`](docs/demo-walkthrough.md). The
screenshot checklist is in
[`docs/screenshots.md`](docs/screenshots.md).

The demo dataset is **synthetic persisted evidence**: the
fixture repository is
`https://github.com/example-org/lockverity-fixture`, the
resolved commit SHA is the `deadbeef` repeated fill, every
package name is from a documented six-name set
(`alpha`, `beta`, `gamma`, `left-pad`, `right-pad`, `stay`),
and Lockverity makes no provider calls during the demo. The
demo is not a real provider scan result.

## Evidence boundaries — what Lockverity will not claim

Lockverity is **not**:

- A **security verdict**. The CycloneDX 1.7 SBOM, the
  evidence report, the component evidence drilldown, the
  search results, and the dependency-edge counts are evidence
  exports, not certifications.
- A **certification**. No export is signed; no export carries
  a trust assertion; no export is a substitute for human
  review.
- A **compliance pass / fail**. Lockverity does not score a
  repository against a regulatory framework.
- A **complete dependency-graph claim** unless a positive
  persisted signal exists. The dependency-graph coverage
  helper returns `partial` or `empty`; it never returns
  `complete` without proof.
- A **"no findings" verdict** when a provider was unavailable.
  Missing provider data is rendered as `not_persisted` /
  `not_observed`; the UI never converts absence into a clean
  bill of health.
- A **remediation workflow**. Lockverity reports findings; it
  does not stage pull requests, open issues, or contact
  maintainers on the operator's behalf.

The full boundary statement is in
[`docs/security-boundaries.md`](docs/security-boundaries.md).
The provider-honesty policy is in
[`docs/provider-honesty.md`](docs/provider-honesty.md).

## What is implemented

- **Persistent data model** for repositories, scans, stages,
  findings, advisories, components, dependency edges,
  provider observations, scan jobs, workspaces, and provider
  cache.
- **Two intake paths:** `POST /api/v1/repositories/github`
  (public GitHub URL) and `POST /api/v1/repositories/upload`
  (ZIP archive upload with streaming, validation, and
  quarantine).
- **Manifest parsers** for npm (`package.json`,
  `package-lock.json`), pnpm, Yarn, Poetry, `pyproject.toml`,
  and `requirements.txt`. Rust / Go parsers are intentionally
  not implemented; the security boundary document was
  corrected in v1.0.1 to remove the v0.1-era claim.
- **Vulnerability / licence / workflow / repository-posture
  rules** with bounded evidence JSON, deterministic
  `stable_key`, and explicit severity / confidence.
- **Provider integrations** for GitHub, OSV, deps.dev, and
  OpenSSF Scorecard, with a bounded HTTP client and a
  provider-cache layer.
- **Exports:** CycloneDX 1.5 and 1.7 SBOM (JSON, validated
  against the official 1.7 schema), SARIF 2.1.0 (JSON),
  findings JSON, findings CSV, and a deterministic Markdown
  evidence report.
- **Evidence search and filtering** at
  `GET /api/v1/scans/{id}/components/evidence-summary` (v0.9)
  and a **component evidence drilldown** at
  `GET /api/v1/scans/{id}/components/{cid}/evidence` (v0.8).
- **Evidence-aware scan comparison** at
  `GET /api/v1/scans/{head}/compare/{base}` (v0.5).
- **Local scan worker** with a 10-stage pipeline, per-stage
  status, scan cancellation, and per-scan heartbeat
  monitoring.
- **Frontend** shell with a typed API client, request
  cancellation, structured error parsing, reduced-motion
  support, and explicit first-run empty states.

## What is intentionally out of scope

- **Authentication, multi-tenancy, billing, or self-service
  signup.** The application runs on a single engineer's
  laptop.
- **Continuous / scheduled scans.** Scans are explicit
  operator actions (manual trigger, archive upload, or
  `api`).
- **Private GitHub repository analysis.** v1.3 is
  public-only; the `LOCKVERITY_GITHUB_TOKEN` environment
  variable is honoured for public rate limits but private
  endpoints are out of scope.
- **LLM-driven analysis, exploit generation, or any other
  offensive feature.** The `No offensive feature policy`
  in `CONTRIBUTING.md` codifies this; any change that
  weakens the non-execution guarantee in `SECURITY.md` is
  closed without merging.
- **PDF, DOCX, HTML, signed attestations, or certification
  exports** for the human-readable evidence report. The
  Markdown report is the only evidence-report export; the
  others are explicitly out of scope by design.
- **Public deployment of the application itself.** The
  application is a private portfolio baseline, not a hosted
  service. There is no marketing site, no signup flow, and
  no public deployment.

## Local development commands

```powershell
# Backend
cd "C:\Users\Naman Parikh\Documents\Minimax Projects\Lockverity\backend"
.\.venv\Scripts\python.exe -m pytest tests
.\.venv\Scripts\python.exe -m ruff check app tests scripts
.\.venv\Scripts\python.exe -m ruff format --check app tests scripts

# Frontend
cd "C:\Users\Naman Parikh\Documents\Minimax Projects\Lockverity\frontend"
npm.cmd test -- --run
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
```

## License

MIT. See [`LICENSE`](LICENSE).
