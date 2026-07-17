# Lockverity

> Evidence-first software supply-chain assurance.

Lockverity inspects the software supply chain of public GitHub
repositories and uploaded source archives. It does not execute
analyzed code; it never calls `npm install`, `pip install`, or any
Makefile / shell script from a repository.

The product is **defensive-only**, **read-only for analyzed evidence**,
**source-honest**, and **provenance-preserving**. Every claim the UI
makes is backed by a file path, a manifest, a provider response, or
an explicit omission marker.

## What Lockverity does

- **Persistent data model** for repositories, scans, stages,
  findings, advisories, components, dependency edges, provider
  observations, scan jobs, workspaces, and provider cache.
- **Two intake paths**: `POST /api/v1/repositories/github` (public
  GitHub URL) and `POST /api/v1/repositories/upload` (ZIP archive
  upload with streaming, validation, and quarantine).
- **Manifest parsers** for npm (`package.json`,
  `package-lock.json`), pnpm, Yarn, Poetry, `pyproject.toml`, and
  `requirements.txt`.
- **Vulnerability rules** (direct, transitive, no fixed version,
  withdrawn advisory, unresolved version, partial provider data,
  provider unavailable, multiple dependency paths, vulnerable
  development dependency, missing lockfile).
- **Licence rules** (unknown licence, multiple assertions, review
  required, provider unavailable, full inventory).
- **GitHub Actions workflow analysis** with a manifest-discovery
  pass and a dependency-graph pass.
- **Provider integrations** for GitHub, OSV, deps.dev, and
  OpenSSF Scorecard, plus a bounded HTTP client and a
  provider-cache layer with TTL.
- **Exports**: CycloneDX 1.5 and 1.7 SBOM (JSON, validated
  against the official 1.7 schema), SARIF 2.1.0 (JSON), findings
  JSON, and findings CSV.
- **CycloneDX 1.7 SBOM evidence preview** on the Export Center
  page (`GET /api/v1/scans/{id}/exports/cyclonedx_1_7/preview`):
  a read-only JSON summary that surfaces scan identity,
  eligibility verdict, inventory summary, evidence coverage,
  SBOM output facts, omissions, and the legacy-export
  relationship note before the user downloads the SBOM.
- **Component evidence drilldown** on the Dependency Explorer
  page (`GET /api/v1/scans/{id}/components/{cid}/evidence`): a
  read-only summary that surfaces component identity, manifest
  evidence, licence evidence, provider observations, advisories,
  and the CycloneDX 1.7 export implications for one component.
  The endpoint reuses the v0.6 CycloneDX exporter helpers for
  PURL, bom-ref, licence classification, and graph coverage, so
  the evidence block never disagrees with the actual SBOM.
- **Evidence search and filtering** on the Dependency Explorer
  page (`GET /api/v1/scans/{id}/components/evidence-summary`): a
  read-only surface that lets the operator narrow the component
  list by text search, ecosystem, direct / transitive, version
  present / missing, licence evidence present / missing, provider
  evidence present / missing, PURL persisted / constructible /
  omitted, dependency edges observed / none observed, and
  CycloneDX 1.7 export implications (appears, version omitted,
  dependency relationships emitted). Facet counts and an inline
  per-row evidence badge cell make the search results
  self-explanatory.
- **Human-readable evidence report (Markdown)** on the Export
  Center page:
  - `GET /api/v1/scans/{id}/reports/evidence-summary/preview` —
    a lazy JSON summary.
  - `GET /api/v1/scans/{id}/reports/evidence-summary.md` — a
    deterministic Markdown download
    (`text/markdown; charset=utf-8`,
    `Content-Disposition: attachment; filename="lockverity-scan-{id}.evidence-report.md"`).
  The report surfaces scan identity, summary counts, evidence
  coverage, evidence gaps, a bounded component table, the
  CycloneDX 1.7 export relationship, and an explicit
  evidence-honesty block. PDF, DOCX, HTML, signed attestations,
  and certification exports are out of scope by design.
- **Scan comparison** (v0.5 evidence-aware) for diffing two
  scans of the same repository without inventing missing
  evidence.
- **Local scan worker** with a 10-stage pipeline, per-stage
  status, scan cancellation, and per-scan heartbeat monitoring.
- **API surface**: repositories, scans, stages, findings,
  provider observations, provider health rollup, scan
  comparison, exports (including a CycloneDX 1.7 SBOM that is
  validated against the official 1.7 schema and surfaced with
  deterministic serial numbers, an evidence preview summary,
  and explicit evidence-coverage properties), system info,
  system provider limits, and administrative workspace cleanup.
  All errors use a stable envelope and never leak stack traces.
- **Frontend** shell with a typed API client, request
  cancellation, structured error parsing, reduced-motion
  support, visible focus states, and explicit first-run empty
  states that distinguish "no data" from "verified clean".

## What Lockverity explicitly does not claim

Lockverity is **not**:

- A **security verdict**. The CycloneDX 1.7 export, the evidence
  report, the component evidence drilldown, and the search
  results are evidence exports, not certifications.
- A **certification**. No export is signed; no export carries a
  trust assertion; no export is a substitute for human review.
- A **compliance pass / fail**. Lockverity does not score a
  repository against a regulatory framework.
- A **complete dependency-graph claim** unless a positive
  persisted signal exists. The v0.6 dependency-graph coverage
  helper returns `partial` or `empty`; it never returns
  `complete`.
- A **"no findings" verdict** when a provider was unavailable.
  Missing provider data is rendered as `not_persisted` /
  `not_observed`; the UI never converts absence into a clean
  bill of health.
- A **remediation workflow**. Lockverity reports findings; it
  does not stage pull requests, open issues, or contact
  maintainers on the operator's behalf.

See `docs/security-boundaries.md` for the full boundary
statement and `docs/provider-honesty.md` for the provider
availability policy.

## Intended users

- **Developers** who want a quiet, evidence-based view of the
  supply chain of a repository they depend on.
- **Maintainers** who want a deterministic baseline before a
  release.
- **Security teams** at small organizations who need a
  self-hostable, defensive-only analyzer with no surprise
  outbound calls.
- **Auditors and reviewers** who need every observation backed
  by a file path, manifest, provider response, or configuration
  knob.
- **Portfolio / client review** — every claim the UI makes is
  backed by code that ships in this repository, never by a
  fixture or a mocked demo.

## Key v1.0 demo flow

1. Load the manual-review dataset
   (`backend/var/manual-review/review.sqlite`).
2. Open the dashboard or scan list.
3. Open the Dependency Explorer for a completed scan.
4. Use the evidence filter row (search, ecosystem, direct,
   version, licence evidence, provider evidence, PURL,
   dependency edges, CycloneDX 1.7 version omitted, sort).
5. Open a component row to view the read-only evidence
   drilldown (identity, manifest, licence, provider, dependency,
   export implications, omissions).
6. Open the Export Center.
7. Show the CycloneDX 1.7 evidence preview.
8. Download the CycloneDX 1.7 SBOM.
9. Show the evidence-report preview.
10. Download the Markdown evidence report.

See `docs/demo-walkthrough.md` for a step-by-step guide with
expected visible states and the local URLs.

## Architecture overview

```
backend/        FastAPI service, SQLAlchemy 2 + Alembic, Pydantic v2
frontend/       React + Vite + TypeScript + Tailwind
docs/           Threat model, provider honesty, finding model, demo, etc.
fixtures/       Synthetic test data (NEVER used in production)
scripts/        Local development helpers
.github/        CI workflows
```

A single deployable backend talks to a single frontend. There is no
Redis, Celery, or Kubernetes by design; the architecture must
remain simple enough that a single engineer can run, audit, and
modify it.

For more detail, see `docs/architecture.md`.

## Local setup

### Prerequisites

- Python 3.12
- Node.js 20 or 22
- A POSIX or Windows shell

### Backend

```bash
cd backend
python -m venv .venv
. .venv/bin/activate              # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 8765
```

The default SQLite database is `./lockverity.sqlite`. To use
PostgreSQL instead, set `LOCKVERITY_DATABASE_URL` to a SQLAlchemy
URL like `postgresql+psycopg://user:pass@host:5432/lockverity`.

For the v1.0 demo dataset, point the backend at the manual-review
SQLite file:

```bash
export LOCKVERITY_DATABASE_URL="sqlite:///var/manual-review/review.sqlite"
uvicorn app.main:app --reload --port 8765
```

The backend will log the resolved database path on startup.

### Frontend

```bash
cd frontend
npm install
npm run dev                       # http://localhost:5173
```

The frontend reads `VITE_API_BASE_URL` to find the backend. The
default is `/api/v1`, which works out of the box when the frontend
and backend are reverse-proxied from the same host. For local
development you can leave the default and let Vite proxy through
or set `VITE_API_PROXY_TARGET=http://127.0.0.1:8765` so Vite
proxies `/api` to a non-default backend port.

## Database migration commands

```bash
cd backend
alembic upgrade head              # apply all migrations
alembic downgrade -1              # roll back one revision
alembic downgrade base            # roll back everything
alembic revision --autogenerate -m "describe change"
```

`alembic upgrade head` against an empty SQLite database creates all
ten application tables and the `alembic_version` row. The reverse
direction is symmetric.

## Testing commands

```bash
cd backend
pytest -q                          # full backend suite
pytest tests/test_evidence_report.py -q  # v1.0 evidence report
pytest tests/test_cyclonedx_v17.py -q   # v0.6/v0.7 SBOM
pytest tests/test_evidence.py -q         # v0.8 evidence drilldown
pytest tests/test_evidence_summary.py -q # v0.9 search/filter
```

```bash
cd frontend
npm run typecheck                  # TypeScript
npm run lint                       # ESLint
npm run build                      # production build
npm test -- --run                  # full frontend suite
npm test -- --run src/__tests__/evidence_report_v1_0.test.tsx  # v1.0 evidence report
```

## Known ports

- **Backend (uvicorn)**: `http://127.0.0.1:8765` (recommended for
  local dev) or `http://127.0.0.1:8000` (uvicorn default). The
  Vite dev-server proxy must point to the port the backend is
  listening on.
- **Frontend (Vite)**: `http://127.0.0.1:5173` (Vite default).
  Vite proxies `/api` to the backend via `VITE_API_PROXY_TARGET`.
- **PostgreSQL** (optional): `5432` (Postgres default). The
  backend reads `LOCKVERITY_DATABASE_URL` to pick the database;
  SQLite is the default for local development.

## Current milestone

**v1.0 — Human-Readable Evidence Report.** The v1.0 release
adds a deterministic Markdown evidence report and a lazy JSON
preview endpoint, with no new providers, no new export
standards, and no change to the v0.6/v0.7/v0.8/v0.9 evidence
contracts.

`v1.0.1` is a public-readiness pass: documentation polish, demo
walkthrough, security-boundary note, and copy clarity. No new
features, no new providers, no new export standards.

## What v1.0 does not include

Planned for later milestones, not implemented today:

- Authentication, multi-tenancy, billing, or self-service
  signup.
- Continuous / scheduled scans. v0.5+ scans are explicit
  operator actions.
- Private GitHub repository analysis (v1.0 is public-only; the
  `LOCKVERITY_GITHUB_TOKEN` environment variable is honoured for
  public rate limits but private endpoints are out of scope).
- LLM-driven analysis, exploit generation, or any other
  offensive feature.
- PDF, DOCX, HTML, signed attestations, or certification
  exports for the human-readable evidence report.
- Dependency-path visualisation for transitive vulnerabilities
  in the frontend (the data is on the wire; the page is not yet
  wired in).

## Provider-honesty policy

Lockverity never reports "no vulnerabilities found" because a
provider was unavailable, rate-limited, or skipped. Every provider
call is recorded with its outcome, and the UI surfaces
"unavailable" and "partial" states explicitly. See
`docs/provider-honesty.md`.

## Non-execution security boundary

Lockverity never executes analyzed repository code. See
`docs/security-boundaries.md` for the full boundary statement
and `docs/threat-model.md` for the threat model.

## License

MIT. See `LICENSE`.
