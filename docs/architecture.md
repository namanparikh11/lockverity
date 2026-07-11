# Architecture

Lockverity v0.1 is built as a single deployable backend and a single
frontend. There is no Kubernetes, Redis, Celery, or message broker;
the architecture is intentionally simple enough that one engineer
can run, audit, and modify it.

## High-level shape

```
                +-----------------------+
   Browser  --> |  Frontend (Vite SPA)  |
                +-----------+-----------+
                            |  HTTPS (JSON)
                            v
                +-----------------------+
                | FastAPI (uvicorn)     |
                |  - routes             |
                |  - services           |
                |  - repositories       |
                |  - providers/analyzers|
                +-----------+-----------+
                            |
            +---------------+----------------+
            v                                v
   +-------------------+            +------------------+
   | SQLAlchemy / ORM  |            | Workspace root   |
   | (SQLite / PG)     |            | (uploads, caches)|
   +---------+---------+            +------------------+
             |
             v
   +-------------------+
   | Alembic migrations|
   +-------------------+
```

## Backend layers

The backend is organized into eight layers; each layer depends only
on the ones below it.

1. **Configuration** - `app/core/config.py` and `app/core/errors.py`.
   Strict Pydantic settings, structured error envelope.
2. **Database** - `app/db/base.py` and `app/db/session.py`.
   SQLAlchemy 2 declarative base with naming conventions; one
   engine and one sessionmaker.
3. **ORM models** - `app/models/`. Ten models covering the
   repository, scan, stage, manifest, component, edge, advisory,
   association, finding, and provider observation.
4. **Schemas** - `app/schemas/`. Pydantic v2 request and response
   types. The wire format is the contract.
5. **Repositories** - `app/repositories/`. Thin SQLAlchemy queries
   with stable ordering and pagination.
6. **Services** - `app/services/`. Business rules. Lifecycle
   transitions, URL normalization, idempotency, error translation.
7. **API** - `app/api/`. FastAPI routers, request/response
   mapping, dependency injection. Mounts under
   `Settings.api_prefix`.
8. **Application** - `app/main.py`. Lifespan, CORS, request-id
   middleware, exception handler registration.

Two cross-cutting packages are also present:

- `app/utils/` - pure, dependency-light helpers (datetime, hashing,
  paths, JSON, redaction, finding keys, archive validation, errors).
- `app/providers/contracts.py` and `app/providers/results.py` -
  typed contracts and result objects for providers, parsers,
  analyzers, rules, and exporters. Concrete implementations arrive
  in later milestones.

## Frontend

The frontend is a Vite + React + TypeScript SPA styled with
Tailwind CSS. It uses React Router for navigation and Lucide for
icons. The pages and components live under `src/` with the
following layout:

```
src/
  api/           typed API client and shared types
  components/    PageHeader, StatusBadge, SeverityBadge, ...
  layouts/       AppShell (header, sidebar, content)
  pages/         Dashboard, Repositories, Scan, Findings, ...
  routes/        React Router configuration
  types/         reserved for shared cross-cutting types
  utils/         time formatting and small helpers
```

The frontend never embeds credentials. The API client uses
`credentials: "omit"` and `Authorization` is not used anywhere in
the bundle.

## Database

The schema is documented in detail in `docs/finding-model.md`. The
high-level shape:

```
repositories 1---* scan_runs 1---* scan_stages
scan_runs 1---* manifests 1---* components
components 1---* dependency_edges *---1 components
scan_runs 1---* component_advisories *---1 advisories
scan_runs 1---* findings
scan_runs 1---* provider_observations
```

Alembic is the source of truth for migrations. The initial revision
creates all ten tables; subsequent revisions must be tested with
the upgrade / downgrade / re-upgrade cycle in CI.

## Provider model

Lockverity talks to a small set of external providers. The
provider contracts in `app/providers/contracts.py` are intentionally
narrow: each provider declares the methods it supports, and the
service layer composes the calls.

Every provider call produces a `ProviderSuccess`, a
`ProviderPartialResult`, or a `ProviderUnavailable`. Exceptions are
never used to represent expected unavailability. The
`ProviderObservation` model records the call, and the API
`/scans/{id}/providers` endpoint exposes the record.

## Scan lifecycle

A scan moves through a strict state machine. The transitions are
enforced in `app/services/scan_service.py` and stored in the
`scan_runs.status` column.

```
queued   -> running -> completed
                  \-> partial
                  \-> failed
                  \-> cancelled
queued   -> cancelled
```

Terminal states are immutable. The transition table is
single-sourced: the service layer is the only code that mutates
`status`, and it asserts the legal transition before doing so.

## Configuration

Configuration is loaded from environment variables with the
`LOCKVERITY_` prefix. Production validation is strict:
`archive_suspicious_ratio` must be positive, `pagination_max_page_size`
must be <= 1000, and wildcard CORS is rejected when
`LOCKVERITY_ENV=production`.

The full settings model lives in `app/core/config.py`. The example
file is `.env.example`.

## Cross-cutting security

- The workspace root is not served by the API or the frontend.
- Provider credentials live in environment variables and are
  consumed by server-side code only.
- Structured error envelopes never leak stack traces, internal
  paths, or provider secrets.
- All timestamps are timezone-aware UTC.
- All paths are normalized relative paths.

See `docs/threat-model.md` and `docs/archive-safety.md` for the
operational details.
