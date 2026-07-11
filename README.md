# Lockverity

> Evidence-first software supply-chain assurance.

Lockverity analyzes the software supply chain of public GitHub
repositories and uploaded source archives. It does not execute
analyzed code.

## What Lockverity does

- Inventories direct and transitive dependencies across ecosystems.
- Cross-references dependencies with public vulnerability intelligence.
- Inspects GitHub Actions and CI/CD workflow definitions for risky
  patterns.
- Records repository security-posture observations (visibility,
  default branch, archived flag, etc.).
- Maintains a scan history with side-by-side comparison.
- Tracks provider availability and data completeness.
- Exports CycloneDX SBOM, SARIF, JSON, and CSV reports.

## Intended users

- **Developers** who want a quiet, evidence-based view of the supply
  chain of a repository they depend on.
- **Maintainers** who want a deterministic baseline before a release.
- **Security teams** at small organizations who need a self-hostable,
  defensive-only analyzer with no surprise outbound calls.
- **Auditors and reviewers** who need every observation backed by a
  file path, manifest, provider response, or configuration knob.

## Current milestone

**v0.1 - architecture baseline.**

The repository ships a complete, runnable architecture: a persistent
data model, a safe scan lifecycle, an API foundation, a frontend
shell, a documentation set, an Alembic-managed migration cycle, a
test suite, and CI workflows.

v0.1 deliberately does **not** implement:

- Live GitHub repository downloads.
- Archive extraction.
- Manifest parsing for any ecosystem.
- OSV, deps.dev, or OpenSSF integration.
- GitHub Actions rule analysis.
- CycloneDX SBOM, SARIF, JSON, or CSV exports.
- Scan comparison or detailed product dashboards.

Those belong to later milestones. The contracts, types, and database
columns they will use already exist so the next milestones can
implement against stable interfaces.

## Defensive-only scope

Lockverity is a defensive security product. It must not be used to
attack, exploit, or otherwise weaponize the repositories it inspects.
Out of scope, today and in any future release:

- Generating, suggesting, or staging exploits, payloads, or attack
  code.
- Active probing of public infrastructure beyond the documented
  provider APIs.
- Brute force, credential stuffing, or session hijacking.
- Adversarial ML, prompt injection, or LLM-driven offensive features.

## Non-execution security boundary

Lockverity never executes analyzed repository code. Specifically, it
never invokes:

- `npm install` / `npm` scripts
- `pip install` against repository requirements
- `poetry install`, `yarn install`, `pnpm install`
- `setup.py` or any Python install entrypoint
- `Makefile` targets
- Repository shell scripts
- Arbitrary subprocess commands based on repository content

Manifests, lockfiles, workflows, and source metadata are treated as
hostile untrusted input. Uploaded archives are validated before
extraction; see `docs/archive-safety.md` for the threat model.

## Planned data sources

The following providers are planned; v0.1 implements the contracts
but not the network calls:

- **OSV** for vulnerability intelligence.
- **deps.dev** for dependency enrichment and resolution.
- **OpenSSF Scorecard** for repository posture signals.
- **GitHub REST API** for public repository metadata and Actions
  workflow definitions.
- **GitHub Security Advisories** as an alternative vulnerability feed.

Provider-honesty policy: a missing or unavailable provider is never
represented as "no vulnerabilities found." See `docs/provider-honesty.md`.

## Architecture overview

```
backend/        FastAPI service, SQLAlchemy 2 + Alembic, Pydantic v2
frontend/       React + Vite + TypeScript + Tailwind
docs/           Threat model, provider honesty, finding model, etc.
fixtures/       Synthetic test data (NEVER used in production)
scripts/        Local development helpers
.github/        CI workflows
```

A single deployable backend talks to a single frontend. There is no
Redis, Celery, or Kubernetes in v0.1 by design; the architecture
must remain simple enough that a single engineer can run, audit, and
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
uvicorn app.main:app --reload --port 8000
```

The default SQLite database is `./lockverity.sqlite`. To use
PostgreSQL instead, set `LOCKVERITY_DATABASE_URL` to a SQLAlchemy
URL like `postgresql+psycopg://user:pass@host:5432/lockverity`.

### Frontend

```bash
cd frontend
npm install
npm run dev                       # http://localhost:5173
```

The frontend reads `VITE_API_BASE_URL` to find the backend. The
default is `/api/v1`, which works out of the box when the frontend
and backend are reverse-proxied from the same host. For local
development you can leave the default and let Vite proxy through,
or set `VITE_API_BASE_URL=http://localhost:8000/api/v1`.

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
pytest tests/test_utils/ -q        # targeted utility tests
pytest tests/test_api/ -q          # targeted API tests
```

```bash
cd frontend
npm run typecheck                  # TypeScript
npm run lint                       # ESLint
npm run build                      # production build
```

## Limitations

- v0.1 records but does not execute scans. The provider calls,
  manifest parsers, and analyzers are not wired up.
- The frontend is a shell: pages render and the API client is fully
  typed, but most lists will be empty until later milestones.
- Lockverity accepts only public GitHub repositories. Private
  repositories and uploaded archives are not yet supported.
- No authentication, no multi-tenancy, no billing. v0.1 is intended
  for self-hosted use by a small team.

## Roadmap

- v0.2: GitHub metadata fetch, archive validation, manifest discovery.
- v0.3: Ecosystem parsers (npm, PyPI, Maven, Go, Cargo).
- v0.4: OSV and deps.dev integration; finding-rule engine.
- v0.5: GitHub Actions rule analysis; OpenSSF Scorecard integration.
- v0.6: CycloneDX SBOM, SARIF, JSON, CSV exports.
- v0.7: Scan comparison, trend dashboards, scheduled scans.

## Provider-honesty policy

Lockverity never reports "no vulnerabilities found" because a
provider was unavailable, rate-limited, or skipped. Every provider
call is recorded with its outcome, and the UI surfaces
"unavailable" and "partial" states explicitly. See
`docs/provider-honesty.md`.

## License

MIT. See `LICENSE`.
