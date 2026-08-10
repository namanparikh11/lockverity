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
- a stable version bump to `2.0.6` (subsequent releases
  continued this work through `2.1.0`).

v2.0 introduces **no new product feature** and **no new
provider**. The version bump signals that the prior milestones
have been audited, regression-tested, and verified end-to-end
on a single command.

## 2. Supported local workflow

The supported review workflow is the v2.1.0 demo flow, which
v2.0 did not change and v2.1.0 extended (the v2.1 single-port
runtime, the v2.1 cross-platform CLI, the v2.1 Windows
portable, and the v2.1 Windows installer are additive on top
of the v0.5–v2.0.6 surface):

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
| Local runtime CLI (v2.1 Part B2) | `lockverity start` / `lockverity stop` / `lockverity status` / `lockverity open` / `lockverity doctor` / `lockverity logs` |

## 4a. Single-port production runtime (v2.1 Part B1)

The v2.1 Part B1 milestone adds an opt-in single-port
production runtime. The FastAPI app can host the built
React UI from the same host and port as the API when
``LOCKVERITY_SERVE_FRONTEND=true`` is set in a production
environment. The two-port development workflow above is
unchanged.

### Build before start

The backend never executes npm or runs the Vite build.
The build is a separate, dependency-light Python step:

```powershell
python scripts/prepare_frontend_dist.py
```

The script verifies the Node.js toolchain
(``node >= 22.22.0``), runs ``npm ci`` and ``npm run build``,
and confirms the Vite output exists at
``frontend/dist/index.html`` along with the approved favicon
and brand assets. The ``--skip-install`` flag skips
``npm ci`` for repeated local builds.

### Single-port start command

```powershell
$env:LOCKVERITY_ENVIRONMENT = "production"
$env:LOCKVERITY_SERVE_FRONTEND = "true"
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The configuration settings:

| Setting | Default | Notes |
| --- | --- | --- |
| ``LOCKVERITY_SERVE_FRONTEND`` | ``false`` | Opt-in. Refused in development and test environments. |
| ``LOCKVERITY_FRONTEND_DIST`` | ``frontend/dist`` | Relative to the repository root, not the CWD. Absolute paths are accepted. |

### Route order

The single-port runtime serves the following routes from
the configured host and port:

1. ``/openapi.json`` and ``/docs`` (FastAPI's built-in
   docs, registered first so they take priority).
2. ``/api/v1/*`` (every API route under the configured
   prefix).
3. Static assets: ``/assets/{file_path}``, ``/favicon.ico``,
   the versioned favicon PNGs, ``/apple-touch-icon.png``,
   and ``/brand/{file_path}``.
4. The SPA fallback at ``/{full_path:path}`` serves
   ``index.html`` for extension-less, non-API, non-dotfile
   paths. File-like requests and API-like paths receive a
   clean 404 instead of the React shell.

### Cache and security headers

Every response carries the documented defensive headers:

- ``X-Content-Type-Options: nosniff``
- ``Referrer-Policy: same-origin``
- ``X-Frame-Options: DENY``
- ``X-Request-Id`` (the existing correlation header)

The cache policy:

- ``index.html``: ``Cache-Control: no-cache, no-store,
  must-revalidate`` (every navigation reloads the manifest).
- Hashed Vite assets (``assets/<name>-<hash>.<ext>``):
  ``Cache-Control: public, max-age=31536000, immutable``.
- Favicon and brand PNGs: ``Cache-Control: public,
  max-age=86400`` (the ``?v=3`` query in ``index.html``
  busts the cache when the assets change).

### Path-traversal protection

The serving rejects:

- ``..`` segments (forward-slash or backslash).
- URL-encoded traversal (``%2e%2e``, ``%2e%2e%2f``,
  ``%2e%2e%5c``).
- Dotfile probes (``.env``, ``.git/HEAD``).
- Any file outside the configured dist directory
  (verified with ``Path.is_relative_to`` after
  symlink resolution).

The serving cannot expose workspace files. The
``workspace_root`` setting is unrelated to the dist;
the static-file root is the configured dist directory
only.

### HTTPS / TLS

The single-port runtime does not terminate TLS.
HTTPS/TLS must be provided by a reverse proxy or the
packaged desktop boundary when the application is
exposed beyond localhost. The reverse proxy must
forward the original host and protocol to the backend
(via ``X-Forwarded-Proto`` and ``X-Forwarded-Host``)
so the application can apply the correct
security-policy response headers.

### Build-before-start requirement

The backend refuses to start when
``LOCKVERITY_SERVE_FRONTEND=true`` and the configured
dist directory is missing or missing ``index.html``.
A stale or partial build aborts startup so the operator
notices immediately instead of serving a half-broken
SPA. The error message references
``scripts/prepare_frontend_dist.py``.

### Repository-controlled code is never executed

The serving is read-only. The backend never invokes
``npm``, never runs the Vite build, and never writes to
the dist directory. Build preparation is the operator's
explicit step. The repository-controlled code path
(executing analyzed repositories) is unchanged: the
backend does not execute any code from the dist or the
uploaded archives.

## 4b. Local runtime CLI (v2.1 Part B2)

The v2.1 Part B2 milestone adds the cross-platform
``lockverity`` command, the supported operator path for
the single-port production runtime. The CLI wraps the
existing application factory and the Part B1 settings;
it is the documented entry point for starting, stopping,
and inspecting the local instance on Windows, macOS,
and Linux. The two-port development workflow and the
direct Uvicorn invocation documented in §4a remain
supported; the CLI is additive.

### Build before start

The CLI does not execute ``npm`` or run the Vite
build. Build preparation is the documented
``scripts/prepare_frontend_dist.py`` step; the CLI
requires a valid built dist at the configured path
and aborts startup otherwise.

### Single-port start command

```powershell
python scripts/prepare_frontend_dist.py
$env:LOCKVERITY_ENVIRONMENT = "production"
lockverity start
```

The CLI's default host is ``127.0.0.1`` and the default
port is ``8000``. A non-loopback host requires the
explicit ``--allow-remote`` flag; the built-in server
does not terminate TLS, so the operator is responsible
for a reverse proxy in front of any remote exposure.

### Runtime home and state file

The CLI persists state under an operator-controlled
runtime home with the documented precedence:

  1. ``--home <path>`` (global CLI option).
  2. ``LOCKVERITY_HOME`` environment variable.
  3. OS-appropriate default:
     - Windows: ``%LOCALAPPDATA%\\Lockverity``.
     - macOS: ``~/Library/Application Support/Lockverity``.
     - Linux: ``${XDG_DATA_HOME:-~/.local/share}/lockverity``.

The runtime home has four sub-directories
(``data/``, ``logs/``, ``run/``, ``config/``) created
with safe permissions. The instance state file
``<home>/run/lockverity.state.json`` records the
child PID, the child's process creation time, the
``--instance-id`` UUID the supervisor generated and
passed to the child, the bound host / port, the
module, the runtime paths, and a short
identity-token. The state file is written
atomically (``tempfile + os.replace``) after the
child reports healthy and intentionally contains
no secrets: no full command line, no database URL,
no provider token, no environment dump. The live
command line is read at verification time to
confirm the ``--instance-id`` token is present but
the live command line is never written to disk.

The same state file is published by both the
background (``start``) and foreground
(``start --foreground``) paths. In foreground
mode the supervisor is attached to the child in
the same console so ``Ctrl+C`` propagates to both
processes; ``lockverity status`` /
``status --json`` / ``open --print-url`` /
``logs`` / ``stop`` work from a second terminal
against the same instance, exactly as in
background mode.

### Process identity and PID-reuse protection

The CLI never terminates a process solely on the basis
of a PID. The ``stop`` and ``status`` commands verify
the recorded process identity (PID + creation time +
``--instance-id`` token + module) against the live
process before any signal is sent. The cross-platform
identity read uses ``psutil``: the standard library
alone cannot reliably identify a PID on Windows
(``/proc`` is not available on macOS, the ``wmic``
CLI is deprecated and may be missing on modern
Windows, ``tasklist`` does not return creation time
or the full command line). ``psutil`` ships as a
wheel on Windows, macOS, and Linux and gives a
uniform API for every dimension the identity check
needs (PID existence, creation time, command line,
module extraction, zombie detection, termination).
The CLI never uses ``shell=True``, never shells out
to ``wmic`` or ``tasklist`` for normal operation, and
never assumes ``/proc`` is available.

A PID that has been recycled for an unrelated process
never matches the recorded identity; the runner
refuses to terminate the unrelated process and
returns the documented ``error`` outcome with a
clear explanation.

The state file stores only the non-secret
``instance_id`` UUID, the recorded PID, the
recorded creation time, the host / port, the
module, and the runtime paths. The full command
line, the database URL, and any provider tokens
are never persisted; the live command line is
*read* at verification time to confirm the
``--instance-id <UUID>`` token is present, but the
live command line is never written to disk.

### Migrations and bounded log

``lockverity start`` runs ``alembic upgrade head`` in a
clean subprocess before launching Uvicorn. The CLI
aborts startup if the migration fails, so a stale
schema never reaches the running process. The runtime
log uses ``logging.handlers.RotatingFileHandler`` with
``maxBytes`` of 10 MiB and ``backupCount`` of 5
(bounded total footprint ~50 MiB). The handler is
UTF-8 and never logs provider tokens, request
authorization headers, or other secrets.

### Command reference

| Command | Purpose |
| --- | --- |
| ``lockverity start`` | Run Alembic migrations, launch Uvicorn (detached by default; in the same console with ``--foreground``), wait for ``/api/v1/health`` to respond, write the state file. |
| ``lockverity start --foreground`` | Run the server in the current TTY. The supervisor publishes the state file with the *child* identity and stays attached until the child exits. ``status`` / ``open`` / ``logs`` / ``stop`` from a second terminal manage the same instance. |
| ``lockverity stop`` | Verify the recorded identity, send ``SIGTERM`` (POSIX) or ``CTRL_BREAK_EVENT`` (Windows), wait for the process to exit, clear the state file and release the start lock. |
| ``lockverity status`` | Show the current instance state in human-readable text or in the documented ``--json`` schema. |
| ``lockverity open`` | Open the local URL in the default browser via the platform ``webbrowser`` facility. |
| ``lockverity doctor`` | Run a read-only diagnostic checklist and report each check as PASS / WARN / FAIL. |
| ``lockverity logs`` | Show the rotating runtime log (bounded tail, optional ``--follow``). |

### Exit codes

| Exit | Meaning |
| --- | --- |
| 0 | Success. |
| 1 | Generic error. |
| 2 | ``--allow-remote`` guard / health timeout / blocking doctor failure. |
| 64 | Command-line usage error. |

The ``status`` subcommand follows a separate,
documented contract:

| Exit | Meaning |
| --- | --- |
| 0 | Running and healthy. |
| 1 | Stopped (no state file or process gone). |
| 2 | Unhealthy, stale, or misconfigured. |

### Configuration precedence

The CLI honours a deterministic precedence:

  1. Explicit CLI option (``--host``, ``--port``,
     ``--home``, ``--frontend-dist``, ``--allow-remote``,
     ``--database-url``, ``--timeout``, ``--log-level``).
  2. Environment variable (``LOCKVERITY_HOME``,
     ``LOCKVERITY_DATABASE_URL``,
     ``LOCKVERITY_FRONTEND_DIST``,
     ``LOCKVERITY_ENVIRONMENT``,
     ``LOCKVERITY_SERVE_FRONTEND``).
  3. Existing Lockverity configuration mechanism
     (the cached :class:`app.core.config.Settings`).
  4. Platform default (loopback ``127.0.0.1``, port
     ``8000``, OS-appropriate runtime home).

### Boundary with the single-port runtime

The CLI is additive to the Part B1 single-port
runtime. The Part B1 settings and route order are
unchanged; the CLI is a process supervisor that wires
the Part B1 production posture (``serve_frontend=true``,
``environment=production``, ``frontend_dist`` set,
``database_url`` set, ``host`` / ``port`` / ``log_level``
set) before launching Uvicorn. The CLI does not modify
the application factory, the route order, the cache
policy, the security headers, or the path-traversal
protections.

### What the CLI does not do

The Part B2 CLI is a process supervisor for
source-based installations. It does **not**:

  - create Windows services, systemd units, launchd
    agents, scheduled tasks, or any other OS-level
    supervisor;
  - produce MSI / EXE / DMG / PKG / AppImage / DEB /
    RPM packages;
  - perform backup / restore of user data;
  - call external cloud providers;
  - implement authentication;
  - implement multi-tenant isolation;
  - rewrite the source repository.

Those deliverables are intentionally out of scope
for Part B2 and belong to later milestones (Part B3
and beyond).

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

The script runs the documented 11-step plan in order:

1. `backend:pytest` — `python -m pytest tests --ignore=tests/test_cli.py`
2. `backend:cli-tests` — `python -m pytest tests/test_cli.py` in default collection order
3. `backend:ruff-check` — `python -m ruff check app tests scripts`
4. `backend:ruff-format` — `python -m ruff format --check app tests scripts`
5. `backend:pip-check` — `python -m pip check`
6. `frontend:test` — `npm test -- --run`
7. `frontend:typecheck` — `npm run typecheck`
8. `frontend:lint` — `npm run lint`
9. `frontend:build` — `npm run build`
10. `frontend:audit-omit-dev` — `npm audit --omit=dev`
11. `frontend:audit` — `npm audit`

The script **exits non-zero immediately on the first failed
step** and prints a concise per-step summary at the end. It
uses argv-only subprocess construction; it does not install
dependencies, delete files, or mutate Git.

The expected baseline is:

- backend: at least **1,283 tests** (1,206 baseline +
  77 v2.1 Part B2 CLI tests; the exact total from the
  most recent accepted verifier run). The test count
  is reported by the verifier itself; the release
  gate is "verifier fully green" rather than a
  specific test count.
- frontend: at least **349 tests**;
- the ``backend:cli-tests`` step runs the
  ``tests/test_cli.py`` module in default
  collection order on every supported host.
  Order independence is a design goal: every test
  isolates its runtime home, the conftest's
  autouse fixtures (settings cache reset, network
  guard, fake providers) clean up after themselves,
  and the cross-platform process-identity checks
  use ``psutil`` instead of the fragile
  ``os.kill`` / ``subprocess.run`` interleaving
  that historically required a hand-curated class
  order on Windows.
- both `npm audit` runs: **0 vulnerabilities**.

The exact step plan is defined in
`backend/scripts/verify_release.py` as the single source of
truth. If the step plan changes, this document and the
script's test suite are updated in the same change.

## 7. External release-checklist commands

The eleven-stage verifier covers the automated
regression suite and the lint / format / audit
gates. Two operator-driven manual commands
complement the verifier. They are not part of the
eleven-stage verifier (the verifier does not run
them); the operator runs them as explicit
release-checklist steps. Both are documented here
by their exact command form so the release
checklist names the scripts the verifier docstring
references.

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

The smoke flow is not part of the eleven-stage
verifier. The operator runs the v0.5 integrated
smoke explicitly:

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
      reflects the v2.1 step plan, prerequisites, and
      boundaries.
- [ ] **Version bumped.** `backend/app/_version.py` and the
      frontend version/about test agree on `2.1.0`. The
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
- [ ] **Release script runs to completion.** The 11-step plan
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
- `README.md` — current milestone, download and install
  instructions, and the "What v2.1.0 does not include" list.
- `CHANGELOG.md` — version history.
- `RELEASE_NOTES.md` — reviewer-facing status.

## 14. Release-process rule: artifact provenance is immutable

The v2.1.1 and v2.1.2 publication cycles both produced
self-induced churn: the public release tag was moved
through one or more hash-alignment commits after the
first build, the release assets were re-uploaded, and
the README / CHANGELOG / install-document placeholders
were edited to match the new hash. The result is three
different "source commit" values describing one
release (the manifest field, the README placeholder,
and the release body), and a publication cycle that
is harder to defend than a single immutable build.

The rule below is binding for every release from
v2.1.3 onward. Its purpose is to keep the published
artefacts, the source-commit references, and the
documentation all pointing at exactly one immutable
commit per release.

- **Finalize source and release documents before
  tagging.** No README, CHANGELOG, ``RELEASE_NOTES``,
  ``docs/install.md``, ``docs/release-checklist.md``,
  or other tracked documentation edit that changes a
  number (source commit, hash, version, published
  date) is allowed after the public tag is created.
  The release documentation is the *last* thing
  edited before tagging, not the *first* thing
  edited after tagging.
- **Choose one immutable release source commit.** Pick
  the final main HEAD that the release tag and the
  release body will reference. The manifest
  ``source_commit`` field, the README "Source commit"
  placeholder, the release body, and the
  ``INSTALLER-MANIFEST`` ``installer_source_commit`` /
  ``payload_source_commit`` fields must all equal
  that one commit. The release tag, the tag object,
  the release body, and the published assets are
  then permanently attached to that commit.
- **Build all artifacts from that commit.** Run
  ``build_windows_portable.py`` and
  ``build_windows_installer.py`` (and any future
  package-format build) from a clean worktree whose
  HEAD equals the chosen release source commit. The
  embedded manifest ``source_commit`` is read from
  ``git rev-parse HEAD`` at build time; any drift
  between the manifest field and the build HEAD
  fails the build.
- **Create the public tag once.** Tag the merge
  commit with a single ``git tag -a`` invocation
  and push it with a single ``git push origin
  refs/tags/<tag>``. Do not run ``git tag -d``,
  ``git push origin :refs/tags/<tag>``, or
  ``git push --force`` against a published tag.
  Once ``releases/latest`` is bound to the tag, the
  tag is permanent.
- **Never move a published tag.** A published tag is
  immutable. If a documentation change is needed
  after publication, it lands on ``main`` as a
  separate commit and is described in the README /
  CHANGELOG as a later documentation update; the
  tag, the release body, and the release assets are
  never re-pointed.
- **Never replace published release assets.** A new
  release is a new tag + a new release id. Do not
  delete an asset from a published release and
  re-upload a different file under the same name.
  The original SHA-256 in
  ``Lockverity-<version>-SHA256SUMS.txt`` and the
  per-asset digest in
  ``Lockverity-<version>-windows-x64-portable-SHA256SUMS.txt``
  bind the assets to the release they ship with.
- **Later documentation commits on ``main`` are
  allowed.** The README "Source commit" placeholder
  and the CHANGELOG v2.1.2 narrative identify the
  *release tag target / artifact source* commit;
  this value does not need to equal the current
  ``main`` HEAD after the release is published.
  The release body, the manifest, the
  ``SHA256SUMS.txt`` files, and the
  ``INSTALLER-MANIFEST.json`` remain authoritative.
  ``main`` may legitimately advance past the
  release tag target; the published artefacts are
  unchanged.
- **Artifact hashes live in the release assets and
  release body.** The canonical SHA-256 of every
  artefact is in
  ``Lockverity-<version>-SHA256SUMS.txt`` and
  ``Lockverity-<version>-windows-x64-portable-SHA256SUMS.txt``
  (uploaded to the release alongside the binaries),
  the structured manifest, and the GitHub release
  body. README and install-document placeholders
  are descriptive aids, not the canonical record.
- **Do not create a self-reference loop.** The chain
  is one-directional: commit → build → manifest hash
  → release asset → checksum file → release body.
  A commit must never reference a hash that was
  produced by a build that depended on a
  documentation commit that came after the build
  HEAD. The rule that closes the loop is "build
  from the final source commit, then tag once,
  then stop editing the source commit field."
