# Contributing

Thank you for your interest in Lockverity. This document covers the
expectations for code, tests, migrations, and finding rules.

## Development setup

1. Install Python 3.12 and Node.js 20 or 22.
2. Backend: `cd backend && python -m venv .venv && pip install -e ".[dev]"`.
3. Frontend: `cd frontend && npm install`.
4. Run `alembic upgrade head` once after pulling.
5. `uvicorn app.main:app --reload` for the backend.
6. `npm run dev` for the frontend.

## Branching expectations

- `main` is the integration branch. Every commit on `main` must
  build and pass the full test suite.
- Feature branches: `feature/<short-topic>`.
- Bug fix branches: `fix/<short-topic>`.
- Documentation-only branches: `docs/<short-topic>`.
- Rule / analyzer branches: `rules/<rule-id>`.

We follow a trunk-based workflow. Long-lived branches are not
allowed. Squash-merge feature branches into `main`.

## Testing expectations

Every change must:

1. Add or update tests in `backend/tests/`.
2. Pass `pytest -q` locally.
3. Pass `npm run typecheck`, `npm run lint`, and `npm run build` in
   `frontend/`.
4. Not weaken existing tests. If a test is no longer valid, update
   it in the same change with a justification in the commit
   message.

The CI pipeline runs:

- `pytest` for the backend.
- `ruff check` and `ruff format --check` for the backend.
- `alembic upgrade head` against an empty database, then downgrade
  to base, then re-upgrade.
- `npm run typecheck` for the frontend.
- `npm run lint` for the frontend.
- `npm run build` for the frontend.

## Migration expectations

- New schema changes require a new Alembic revision.
- A migration must work both forward and backward.
- The CI pipeline re-runs the upgrade / downgrade / re-upgrade
  cycle for every revision.
- Database-portable SQL is required. Avoid `GLOB`, custom
  functions, or vendor-specific features. The service layer is the
  authoritative validator; CHECK constraints are defence in depth.
- Naming conventions are defined in `app/db/base.py`; the auto-
  generated constraint names must remain predictable.

## Finding-rule requirements

Each new rule must include:

- A unique `rule_id` (e.g. `LOCK-SUPPLY-001`).
- A precise `category` (one of `dependency`, `vulnerability`,
  `workflow`, `repository_posture`, `licence`, `provider`,
  `data_quality`).
- A deterministic evaluation: identical evidence must produce
  identical `stable_key`.
- Bounded evidence JSON (<= 64 KiB).
- A `remediation` string when one is available.
- Tests that include both positive and negative cases against
  synthetic fixtures.

Rules must not:

- Generate exploit code or payload skeletons.
- Reach for LLM-based generation of findings. Lockverity is
  deterministic.
- Make network calls; rules are pure functions over evidence.

## Fixture policy

Synthetic fixtures live under `fixtures/`. They are used only by
tests. The rules:

- A fixture must be clearly labelled as synthetic in its filename
  (e.g. `synthetic_npm_lockfile.txt`).
- A fixture must not be confused for a real-world sample. The
  contents should be obviously artificial.
- The application code path **never** falls back to fixtures in
  production. There is no "if no data, use fixture" code anywhere
  in `app/`.

## No offensive feature policy

Out of scope, today and in any future contribution:

- Generating, suggesting, or staging exploits, payloads, attack
  code, or offensive tooling.
- Active probing of public infrastructure beyond the documented
  provider APIs.
- Brute force, credential stuffing, or session hijacking.
- Adversarial ML, prompt injection, or LLM-driven offensive
  features.
- Any change that weakens the non-execution guarantee in
  `SECURITY.md`.

A pull request that adds any of the above will be closed without
merging.

## No production fake-data policy

The application must never silently fall back to fixture or mock
data in production. If a provider fails, the failure is recorded
and surfaced; it is not papered over with a cached or fabricated
response.

If you find yourself reaching for a "default to something" branch,
write the missing provider integration or leave the data
unavailable. See `docs/provider-honesty.md`.

## Commit messages

Use the form:

```
<scope>: <one-line summary>

<body explaining the why, not the what>
```

Examples of accepted scopes: `backend`, `frontend`, `docs`,
`ci`, `rules`, `providers`, `schema`, `migrations`.

## Code of conduct

Be kind. Disagreement is welcome; personal attacks are not. We
follow the spirit of the Contributor Covenant.
