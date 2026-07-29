# Lockverity release checklist

This document is the operator-facing checklist for cutting a
defensible local-first release candidate of Lockverity. It
captures the v2.0 contract: a coherent, tested workflow that
covers every v0.5–v1.9 surface, with a single deterministic
verification entry point.

The v2.0.1 acceptance-repair pass preserves the v2.0 contract
verbatim; v2.0.1 ships a single defect fix (the v1.8
per-repository scan-history filter is now actually wired up
through the route, the service, and the repository) and the
regression tests that pin it. The v2.0.1 contract is identical
to the v2.0 contract documented here.

The v2.0.2 ecosystem-compatibility repair preserves the
v2.0.1 contract verbatim; v2.0.2 ships a single defect fix
(the orchestrator's nested-manifest discovery now uses the
basename lookup, so every nested manifest in a
monorepository is recorded as a ``Manifest`` row) and the
regression tests that pin it. The v2.0.2 contract is identical
to the v2.0.1 contract documented here.

The v2.0.3 first-run reproducibility repair preserves the
v2.0.2 contract verbatim; v2.0.3 ships a single defect fix
(``backend/pyproject.toml`` pins ``ruff==0.15.21`` in the
dev extras so the documented one-command release-verification
script passes on a fresh clean checkout) and the regression
tests that pin it. The v2.0.3 contract is identical to the
v2.0.2 contract documented here.

The checklist is intentionally short. Anything that depends
on a secret, a remote service, a destructive cleanup, or a
production deployment belongs in a separate deployment runbook
— not here.

## 1. What v2.0 is

`v2.0` is a **local-first release candidate**. It bundles:

- every v0.5–v1.9 surface (intake, scan execution, rescans,
  findings, dependencies, exports, comparison, diagnostics);
- a single bounded release-validation script that runs the
  full backend and frontend verification suites;
- a defect-fix pass on real release-blocking issues found in
  the v1.9 audit (rescan error-envelope mapping, dead code in
  the diagnostics service);
- a stable version bump to `2.0.6`.

v2.0 introduces **no new product feature** and **no new
provider**. The version bump signals that the prior milestones
have been audited, regression-tested, and verified end-to-end
on a single command.

## 2. Supported local workflow

The supported review workflow is the v2.0.6 demo flow, which
v2.0 does not change:

1. **Generate the demo database** with the deterministic
   loader:
   ```powershell
   cd backend
   .\.venv\Scripts\python.exe scripts/load_demo.py --reset-demo-db
   ```
2. **Start the backend** on `127.0.0.1:8765` with the
   generated SQLite file:
   ```powershell
   $env:LOCKVERITY_DATABASE_URL = "sqlite:///var/demo/lockverity-demo.sqlite"
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8765
   ```
3. **Start the frontend** on `127.0.0.1:5173` with the Vite
   proxy pointed at the backend:
   ```powershell
   cd frontend
   $env:VITE_API_PROXY_TARGET = "http://127.0.0.1:8765"
   npm install
   npm run dev
   ```
4. **Walk the primary routes**:
   `/`, `/analyze`, `/demo`, `/repositories`,
   `/repositories/:id`, `/repositories/:id/compare`,
   `/scans/:id`, `/scans/:id/findings`,
   `/scans/:id/dependencies`, `/scans/:id/exports`,
   `/diagnostics`, `/about`.
5. **Stop the demo** when done. The demo is local-only; the
   SQLite file is the only persistent state.

## 3. Prerequisites

- **Python 3.12** with a backend virtual environment
  (`backend/.venv`) created by `python -m venv .venv` and
  populated by `pip install -e ".[dev]"` (or by the
  bootstrap path the developer has been using).
- **Node.js >=22.22.0** with a frontend `node_modules/`
  populated by `npm install`. The Node.js floor is
  dictated by `react-router@8.3.0` (declared in
  `frontend/package.json` `engines.node` and confirmed
  in the lockfile). Earlier 22.x releases (22.0-22.21)
  and the entire 20.x line are not supported. The repo
  ships an `.nvmrc` pinning the floor; use `nvm use`
  (or `fnm use` / `volta pin`) to align your local
  runtime. Validation was performed on Node.js 24.18.0;
  v22.22.x is the minimum.
- A clean working tree: `git status --short` must report no
  tracked-file changes other than the v2.0 files.
- The local Git remote `origin` is the existing
  repository. The release does not change the remote URL
  or any global Git config. Repository visibility is
  changed only via the explicit ``gh repo edit --visibility``
  flow documented in the Phase 1 public-release closure
  report; this script does not touch visibility.

## 4. Backend and frontend start commands

These are the supported commands for the v2.0 demo. The
release does not change them; they are restated here for the
operator's convenience.

| Component | Command |
| --- | --- |
| Backend (uvicorn) | `python -m uvicorn app.main:app --host 127.0.0.1 --port 8765` |
| Frontend (Vite) | `npm run dev` (with `VITE_API_PROXY_TARGET=http://127.0.0.1:8765`) |
| Demo loader | `python scripts/load_demo.py --reset-demo-db` |
| Release validation | `python scripts/verify_release.py` |

## 5. Demo loader

The demo loader is the only safe way to seed a fresh
Lockverity database for review. It is committed to the
repository and is safe to commit: every value it persists is
an obviously-synthetic literal. It creates the four
documented scan states (completed / partial / failed /
cancelled) so every v0.5–v1.9 surface can be reviewed
end-to-end.

The loader refuses to overwrite an existing database unless
`--reset-demo-db` is passed, and it refuses to write outside
`backend/var/`. The schema is created by the same Alembic
migrations the application uses.

## 6. Full verification command

The single v2.0 entry point for verification is:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\verify_release.py
```

The script runs the documented 10-step plan in order:

1. `backend:pytest` — `python -m pytest tests`
2. `backend:ruff-check` — `python -m ruff check app tests scripts`
3. `backend:ruff-format` — `python -m ruff format --check app tests scripts`
4. `backend:pip-check` — `python -m pip check`
5. `frontend:test` — `npm test -- --run`
6. `frontend:typecheck` — `npm run typecheck`
7. `frontend:lint` — `npm run lint`
8. `frontend:build` — `npm run build`
9. `frontend:audit-omit-dev` — `npm audit --omit=dev`
10. `frontend:audit` — `npm audit`

The script **exits non-zero immediately on the first failed
step** and prints a concise per-step summary at the end. It
uses argv-only subprocess construction; it does not install
dependencies, delete files, or mutate Git.

The expected baseline is:

- backend: at least **828 tests** (with new regression tests
  for the v2.0 defect fixes);
- frontend: at least **295 tests**;
- both `npm audit` runs: **0 vulnerabilities**.

The exact step plan is defined in
`backend/scripts/verify_release.py` as the single source of
truth. If the step plan changes, this document and the
script's test suite are updated in the same change.

## 7. External release-checklist commands

The ten-stage verifier covers the automated regression
suite and the lint / format / audit gates. Two
operator-driven manual commands complement the
verifier. They are not part of the ten-stage verifier
(the verifier does not run them); the operator runs
them as explicit release-checklist steps. Both are
documented here by their exact command form so the
release checklist names the scripts the verifier
docstring references.

### 7.1 Operator-driven manual migration round-trip confirmation

The ``backend:pytest`` stage already runs the full
backend test suite, which includes the automated
migration tests:

- ``tests/test_migration_cycle.py`` exercises
  ``alembic upgrade head`` -> ``alembic downgrade base``
  -> ``alembic upgrade head`` against a fresh SQLite
  database (pytest entry point
  ``test_alembic_upgrade_downgrade_reupgrade``).
- ``tests/test_migration_f6a7b8c9d0e1.py`` pins the
  v2.0.6 cycle-7-final migration's local sanitiser,
  backfill, GitHub provenance preservation, and
  upgrade / downgrade / re-upgrade cycle.

The operator may additionally perform the manual
round-trip as an explicit confirmation:

```powershell
cd backend
.\.venv\Scripts\python.exe -m tests.manual_migration_cycle
```

This is an *additional* confirmation; the automated
pytest coverage above must be green for the verifier
to pass.

### 7.2 Smoke validation

The smoke flow is not part of the ten-stage verifier.
The operator runs the v0.5 integrated smoke
explicitly:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts_smoke_v0_5.py
```

The script exercises the alembic upgrade, two-scan
comparison, lifecycle events, comparison refresh,
cross-workspace rejection, evidence-envelope
validation, and provider-cache preservation flows.

## 8. Core security boundaries

The release validation does not weaken any of the existing
boundaries. It enforces them by running the same suites the
release process has always run, plus the new regression
tests for the v2.0 defect fixes.

The non-negotiable boundaries are restated below. Any change
to these requires a SECURITY.md update, a
`security-boundaries.md` update, and a manual review pass.

- Lockverity never executes analyzed repository or archive
  code (`npm install`, `pip install`, build scripts, shell
  scripts, Makefile targets, repository-defined subprocess
  invocations, etc.). Manifests, lockfiles, workflows, and
  source metadata are read as data only.
- Uploaded archives are treated as hostile input. Every
  archive entry is validated for path traversal, absolute
  paths, drive letters, UNC paths, symlinks, hard links,
  duplicate normalized entries, excessive depth, oversized
  entries, suspicious compression ratios, excessive file
  counts, and excessive cumulative size. The first failed
  entry fails the whole archive.
- Public GitHub only. `LOCKVERITY_GITHUB_TOKEN` is honoured
  for public rate limits; private endpoints are out of scope.
- Provider state, cache state, and evidence presence are
  three independent fields. They are never collapsed into
  one verdict.
- Missing evidence is rendered as missing (e.g.
  `version missing`, `provider_not_persisted`,
  `licence_not_persisted`, `no_persisted_edges`), never as a
  positive claim.
- Reports and SBOMs are evidence exports, not security
  verdicts. No export is signed; no export carries a trust
  assertion; no export is a substitute for human review.
- Historical scans are immutable. Rescans create a distinct
  scan and workspace; the original scan and workspace are
  never mutated.
- Partial, failed, and cancelled scans remain visibly
  incomplete. The UI never renders a non-terminal scan as
  "clean", "secure", "passed", or "certified".
- Provider-attributed severity is not a Lockverity-owned
  risk score. A removed finding does not prove remediation.
  A completed scan does not prove repository safety.
- No secrets, tokens, credentials, environment values, local
  filesystem paths, or raw stack traces are ever exposed by
  the API, the diagnostics endpoint, or the exports.

## 9. Release validation checklist

The operator must run every step below in order. A failed
step halts the release.

- [ ] **State verified.** `git status --short` is clean
      before the release branch is created.
- [ ] **Branch created.** `git switch -c feature/vX.Y-...`
      off `main`.
- [ ] **Defect fixes implemented and tested.** Each fix has
      a focused regression test; both the fix and the test
      land in the same commit.
- [ ] **Release validation script exists.** The step plan in
      `scripts/verify_release.py` is the canonical command
      sequence. There is no second source of truth.
- [ ] **`docs/release-checklist.md` updated.** This document
      reflects the v2.0 step plan, prerequisites, and
      boundaries.
- [ ] **Version bumped.** `backend/app/_version.py` and the
      frontend version/about test agree on `2.0.6`. The
      README, CHANGELOG, and RELEASE_NOTES reference the
      same version.
- [ ] **Backend verification passes.** `pytest`, `ruff
      check`, `ruff format --check`, and `pip check` are
      all clean. Alembic upgrades to head on a scratch
      database.
- [ ] **Frontend verification passes.** `npm test -- --run`,
      `npm run typecheck`, `npm run lint` (with the existing
      max-warnings=0 policy), `npm run build`, and both
      `npm audit` runs are clean.
- [ ] **Release script runs to completion.** The 10-step plan
      exits 0.
- [ ] **End-to-end local smoke passes.** Every primary route
      loads, the diagnostic summary returns 200, the
      `/health` endpoint reports the new version, the
      CycloneDX preview and download work, the Markdown
      evidence report preview and download work, the rescan
      endpoint returns the bounded error envelope, the
      comparison page renders, and the diagnostics page
      renders without secrets, paths, or stack traces.
- [ ] **Final inspection clean.** `git diff --check`,
      `git status --short`, and `git diff --name-status` show
      no secrets, no local paths, no tracked runtime
      artifacts, no connection strings, no environment
      dumps, no raw stack traces, no universal score, no
      "secure/clean/passed/certified" claim, and no
      cached-equals-live or provider-success-equals-security
      claim.
- [ ] **Feature commit + merge.** Committed on the feature
      branch with a multi-line message describing the audit
      and fixes. Merged into `main` with `--no-ff`.
- [ ] **Annotated tag.** `git tag -a checkpoint-vX.Y -m "..."`
      points at the merge commit. The previous
      `checkpoint-vX.Y-1` tag remains in place.
- [ ] **Push.** Only `git push origin main` and
      `git push origin checkpoint-vX.Y` run. No `--tags`. No
      feature-branch push. No `--force`. No remote URL
      change.

## 10. Known limitations

The release does not eliminate any of the following. They are
documented here so the operator does not have to guess.

- **No persistent analyst disposition.** `Finding.status` is
  read-only in the UI. False-positive / accepted-risk /
  remediated workflows are future work.
- **No continuous or scheduled scans.** Scans are explicit
  operator actions.
- **Public GitHub only.** Private GitHub repositories are out
  of scope; `LOCKVERITY_GITHUB_TOKEN` is honoured for public
  rate limits.
- **No LLM, exploit, or offensive features.** The product is
  defensive-only.
- **No PDF / DOCX / HTML / signed-attestation exports.** The
  Markdown evidence report and the CycloneDX 1.7 SBOM are
  the only human-readable exports.
- **No tracked screenshots.** The screenshot captures are
  manual and local; the v2.0.6 checklist remains the
  canonical guide.
- **In-process executor does not persist heartbeats.** The
  diagnostics page renders "Heartbeat not exposed by the
  current executor" rather than inventing a heartbeat.
- **No production deployment.** The local dev setup is the
  only supported deployment shape in the release; production
  deployment is a separate operational concern.
- **No remote-served API key.** The GitHub token is the only
  optional credential; it is read from the environment and
  is never persisted or exposed by the API.
- **No organisation-isolation migration.** The architecture
  supports organisations at the application level, but no
  organisation model is persisted; v2.0 stays at the
  single-tenant level.

## 11. What v2.0 does not claim

v2.0 is explicitly **not**:

- A **production release**. v2.0 is a local-first release
  candidate, not a production SaaS.
- A **security verdict**. The CycloneDX 1.7 export, the
  evidence report, the component evidence drilldown, the
  findings workbench, and the comparison page are evidence
  exports, not certifications.
- A **certification**. No export is signed; no export carries
  a trust assertion; no export is a substitute for human
  review.
- A **compliance pass / fail**. Lockverity does not score a
  repository against a regulatory framework.
- A **complete dependency-graph claim** unless a positive
  persisted signal exists. The dependency-graph coverage
  helper returns `partial` or `empty`; it never returns
  `complete`.
- A **"no findings" verdict** when a provider was
  unavailable. Missing provider data is rendered as
  `not_persisted` / `not_observed`; the UI never converts
  absence into a clean bill of health.
- A **remediation workflow**. Lockverity reports findings; it
  does not stage pull requests, open issues, or contact
  maintainers on the operator's behalf.
- A **universal health / risk / quality / security / uptime
  / reliability / compliance / production-readiness score**.
  The diagnostics page presents five independent bounded
  cards and explicitly states that operational state is not
  security state.

## 12. Repository visibility

The release does not change repository visibility. The
release does not change the remote URL or any global
Git configuration. The decision to change the visibility
is performed via the explicit ``gh repo edit
--visibility public|private|internal`` flow and is
external to the code release; the v2.0.6 candidate does
not perform that change.

## 13. Cross-links

- `docs/security-boundaries.md` — public-facing boundary
  statement.
- `docs/archive-safety.md` — hostile-archive model.
- `docs/provider-honesty.md` — provider availability policy.
- `docs/demo-pack.md` — 60-second reviewer walkthrough and
  the public/private recommendation.
- `README.md` — current milestone, run-the-demo steps, and
  the "What v2.0 does not include" list.
- `CHANGELOG.md` — version history.
- `RELEASE_NOTES.md` — reviewer-facing status.
