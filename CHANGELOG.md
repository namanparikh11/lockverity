# Changelog

All notable changes to Lockverity are documented here. Versions
follow [Semantic Versioning](https://semver.org/). Lockverity is
pre-1.0 in the sense that the public API may evolve; the
underlying data model and Alembic migrations are stable.

## v2.0.4 — UTF-8 BOM compatibility repair (current)

A narrowly scoped testing-driven patch that ships one real
defect uncovered by a v2.0.3 field-test run. No new
product feature, no new provider, no new export standard,
no new evidence contract, no migration, no new dependency.

- **UTF-8 BOM accepted in JSON dependency manifests.**
  v2.0.3 shipped with the ``PackageJsonParser`` and
  ``PackageLockJsonParser`` decoding the manifest bytes
  as plain UTF-8: ``content.decode("utf-8")``. A leading
  UTF-8 BOM (``EF BB BF``) — produced by Notepad on
  Windows and many other editors — is preserved as a
  literal ``\ufeff`` in the decoded string, which
  ``json.loads`` then rejects as
  ``Expecting value: line 1 column 1 (char 0)``. The
  orchestrator records the manifest with
  ``parse_status="FAILED"`` and zero components are
  produced. The field-test repro saw this twice on
  ``test-06-package-json-only.zip``: one manifest
  discovered, one parser failure, zero components. v2.0.4
  changes the decode to ``utf-8-sig``, which transparently
  strips a single leading UTF-8 BOM. The BOM does not
  become part of any name, version, PURL, or source
  path. The no-BOM control path is unchanged. The
  fix is bounded to the two JSON parsers; the TOML and
  YAML parsers are intentionally untouched (they are
  not JSON-based and the field-test repro did not
  surface a BOM regression there).
- **11 new backend tests** in
  ``backend/tests/test_parsers_npm_bom_v2_0_4.py`` cover:
  package.json with UTF-8 BOM parses successfully;
  the two expected direct dependencies
  (``axios 1.7.9`` and ``lodash 4.17.21``) survive the
  BOM exactly; names, versions, and PURLs do not
  contain a leading BOM codepoint or percent-escape;
  the relationship is ``direct`` with no
  development/optional side effects; the source path
  is preserved unchanged; the no-BOM control path is
  unchanged; ``package-lock.json`` with a UTF-8 BOM
  parses successfully; a BOM followed by invalid JSON
  is still rejected as a bounded parser failure;
  a BOM-like codepoint inside a string value is
  preserved (we do not over-strip); an end-to-end
  orchestrator scan with a BOM-prefixed
  ``package.json`` persists two components and
  records the manifest as ``PARSED``; and a nested
  BOM-prefixed ``package.json`` is discovered by the
  orchestrator's basename-based manifest discovery
  (the v2.0.2 fix) and parsed by the v2.0.4 BOM
  fix.
- **Field-test reacceptance.** The v2.0.3 field-test
  database is preserved. The BOM scan now produces
  the expected two components; the no-BOM control
  scan is unchanged. The historical scans that
  demonstrated the v2.0.3 defect are untouched.
- **Version.** Bumped ``__version__`` to ``2.0.4``. The
  frontend ``version_about`` test mock now expects
  ``2.0.4``.
- **Boundary preservation.** Two-line code change
  (``content.decode("utf-8")`` →
  ``content.decode("utf-8-sig")`` in
  ``PackageJsonParser.parse`` and
  ``PackageLockJsonParser.parse`` in
  ``backend/app/parsers/npm.py``). No new feature, no
  new endpoint, no new persisted field, no new
  export, no new organisation, no new provider, no
  new dependency, no migration, no global Git config
  change, no remote URL change, no destructive
  action, no production deployment, no source-file
  mutation, no malformed-JSON weakening, no broad
  encoding fallback. The repair is the smallest
  safe BOM-stripping change at the narrowest
  shared JSON-manifest boundary.

## v2.0.3 — First-run reproducibility repair

A focused defect-repair release that ships one real
release-blocking defect discovered during the v2.0.2
clean-state acceptance gate. The one-command
release-verification script documented in
[`docs/release-checklist.md`](docs/release-checklist.md) and
[`README.md`](README.md) failed on a fresh clean checkout.
No new product feature, no new provider, no new
export standard, no new evidence contract, no migration.

- **Release-validation script now works on a clean
  checkout.** v2.0.2 shipped with
  ``"ruff>=0.4.0"`` in the ``[project.optional-dependencies.dev]``
  extras of `backend/pyproject.toml`. A clean
  ``pip install -e ".[dev]"`` resolved the latest ruff
  release, which produces a different format than the one
  the committed files were last formatted against. The
  ``scripts/verify_release.py`` script runs
  ``python -m ruff format --check app tests scripts`` and
  failed with
  ``196 files would be reformatted``. The defect was
  reproducible on a clean clone from
  ``ed07e2f100248f9ca8689e7d7f103b78b71d3e69`` (the
  v2.0.2 release commit). v2.0.3 pins
  ``"ruff==0.15.21"`` in the dev extras — the exact
  patch that produced the committed format. The one-command
  verification now passes on a clean checkout.
- **3 new backend tests** in
  ``backend/tests/test_pyproject_ruff_pin_v2_0_3.py`` cover:
  the ruff spec in the dev extras is an exact
  ``==``-pinned semver (not a range that would silently
  regress); the dev extras still contain ``pytest``,
  ``ruff``, and ``mypy``; and
  ``scripts/verify_release.py`` invokes
  ``ruff format --check``.
- **Version.** Bumped ``__version__`` to ``2.0.3``. The
  frontend ``version_about`` test mock now expects
  ``2.0.3``.
- **Boundary preservation.** No new feature, no new
  endpoint, no new persisted field, no new export, no
  new organisation, no new provider, no migration, no
  global Git config change, no remote URL change, no
  destructive action, no production deployment. The
  release is a small, obvious correctness repair on the
  v2.0.2 surface.

## v2.0.2 — Ecosystem compatibility repair

A focused defect-repair release that ships one real defect
discovered during the v2.0.1 ecosystem-and-scale acceptance
gate. No new product feature, no new provider, no new
export standard, no new evidence contract, no migration.

- **Nested-manifest discovery in monorepos now works.** The
  v2.0.1 orchestrator stage
  ``backend/app/services/orchestrator_service.py:_discover_manifest_files``
  checked ``if rel in _MANIFEST_NAMES`` where ``rel`` is the
  full relative path (e.g. ``frontend/package.json``) but
  ``_MANIFEST_NAMES`` keys are basenames (e.g.
  ``package.json``). The full-path check only matched
  root-level manifests; every nested manifest in a
  monorepository was silently dropped, so the pipeline
  recorded zero ``Manifest`` rows and the analysis
  returned zero components. v2.0.2 changes the membership
  check to ``if manifest_type_for(rel) != "generic"``,
  which is the same basename lookup the
  ``app.utils.manifest_scanner`` path uses.
- **6 new backend tests** in
  ``backend/tests/test_orchestrator_manifest_discovery_v2_0_2.py``
  cover: the basename lookup for known and unknown
  filenames; nested ``frontend/package.json`` discovery in
  a single-namespace monorepo; a mixed-ecosystem
  monorepository (``frontend/``, ``backend/``,
  ``nested/service/``, ``tools/``); unknown-file rejection;
  the orchestrator's permissive behaviour re: nested
  ``node_modules`` paths (which the v0.3 dedupe handles);
  and the manifest row insertion shape.
- **Re-acceptance after the fix:** the
  ``11-mixed-monorepo`` fixture returns 7 components, 13
  findings, ``inventory_coverage: complete`` (was 0/0/
  empty). The ``12-monorepo-duplicate-versions`` fixture
  returns 4 components, 6 findings, with distinct
  ``manifest_id`` per source path (was 0/0/empty).
- **Version.** Bumped ``__version__`` to ``2.0.2``. The
  frontend ``version_about`` test mock now expects
  ``2.0.2``.
- **Boundary preservation.** No new feature, no new
  endpoint, no new persisted field, no new export, no
  new organisation, no new provider, no migration, no
  global Git config change, no remote URL change, no
  destructive action, no production deployment. The
  release is a small, obvious correctness repair on the
  v2.0.1 surface; the wider v0.3 dedupe
  (``(package_name, version, source_path)``) already
  prevents the new discoveries from duplicating existing
  components.

## v2.0.1 — Acceptance repair

A focused defect-repair release that ships one real defect fix
discovered during the v2.0 acceptance gate. No new product
feature, no new provider, no new export standard, no new
evidence contract, no migration.

- **Per-repository scan-history filter is now wired up.**
  v2.0 shipped with the v1.8 URL-persisted status / trigger
  filters on `GET /repositories/{id}/scans` documented but
  silently ignored: the route signature only accepted
  `page` / `page_size`, the `DataCompletenessNotice` and the
  "No scans match the filters" empty state implied the filter
  was working, and the table rendered every scan regardless of
  the active filter. v2.0.1 accepts `status` and
  `trigger_type` as `Query` parameters on the route (rejected
  with a bounded 422 envelope for unknown values), forwards
  them to `scan_service.list_scans_for_repository`, and the
  service forwards them to `scan_repo.list_scans_for_repository`.
  The repo layer adds the matching `WHERE` clauses before the
  `ORDER BY id DESC LIMIT/OFFSET` and the `COUNT` is computed
  against the filtered subquery. The result is the rendered
  table now actually matches the URL state.
- **7 new backend tests** in
  `backend/tests/test_api_repository_scan_filter_v2_0_1.py`
  cover the route accept/reject boundary, the combined-filter
  AND semantics, the no-filter control, the unknown-value 422
  envelope, and the service-to-repo kwargs forwarding.
- **5 new frontend tests** in
  `frontend/src/__tests__/repository_v2_0_1.test.tsx` use a
  filter-sensitive mock to assert the rendered table contains
  only the rows the API returned, including the
  "No scans match the filters" empty state when the filter
  has no matches. The v1.8 test only checked the request URL,
  not the rendered table.
- **Version.** Bumped `__version__` to `2.0.1`. The frontend
  `version_about` test mock now expects `2.0.1`.
- **Boundary preservation.** No new feature, no new endpoint,
  no new persisted field, no new export, no new
  organisation, no new provider, no migration, no global
  Git config change, no remote URL change, no destructive
  action, no production deployment. The release is a
  small, obvious correctness repair on the v2.0 surface.

## v2.0.0 — Local-first release candidate

A non-feature release candidate. The v2.0 contract bundles
the v0.5–v1.9 surface area under a single bounded
release-validation script, with two real defect fixes that
were uncovered during the v1.9 audit. The version bump
signals that the prior milestones have been audited,
regression-tested, and verified end-to-end on a single
command; it does **not** introduce a new product feature
or a new provider.

- **Local-first release candidate.** v2.0 is the first
  release line that explicitly markets itself as a
  local-first release candidate. The supported review
  workflow is unchanged from v1.9; the new
  `docs/release-checklist.md` documents the bounded
  operator-facing checklist, the prerequisites, the
  full verification command, the core security
  boundaries, the release-validation step plan, the
  known limitations, and what v2.0 does not claim.
- **Single release-validation entry point.** New
  `backend/scripts/verify_release.py` runs the
  documented 10-step plan in order: backend pytest,
  Ruff check, Ruff format check, pip check, frontend
  tests, frontend typecheck, frontend lint, frontend
  build, `npm audit --omit=dev`, and full `npm audit`.
  The script uses argv-only subprocess construction
  (no shell metacharacter concatenation), exits
  non-zero immediately on the first failed step, and
  prints a concise per-step summary. The step plan is
  the single source of truth for the release
  verification command; there is no second
  copy-pasteable command list. The script does not
  install dependencies, does not delete files, and
  does not mutate Git.
- **Defect fix — rescan error-envelope mapping.** The
  v1.8 rescan route used exact-match
  `exc.code == "github_error"` to decide between
  `PROVIDER_UNAVAILABLE` and `RESCAN_SOURCE_UNAVAILABLE`,
  but the rescan service wraps real `GitHubIntakeError`
  values with codes such as `github_not_found`,
  `github_rate_limited`, `github_unauthorized`,
  `github_invalid_response`, and
  `github_no_default_branch`. The result was that
  genuine GitHub errors were being mapped to
  `RESCAN_SOURCE_UNAVAILABLE` (HTTP 422) instead of
  `PROVIDER_UNAVAILABLE` (HTTP 502). v2.0 widens the
  mapping to match any `github_*` code against
  `PROVIDER_UNAVAILABLE` while keeping
  `RESCAN_SOURCE_UNAVAILABLE` for genuine source-side
  problems. Two new regression tests
  (`test_rescan_github_codes_map_to_provider_unavailable`
  and
  `test_rescan_non_github_codes_map_to_source_unavailable`)
  pin the new behavior.
- **Defect fix — dead code in diagnostics service.** The
  v1.9 `diagnostics_service` shipped a dead
  `executor_metadata_snapshot` function and an unused
  `typing.Any` import. Both are removed; the live
  service composes its summary from
  `build_summary(session, database_status)` plus the
  three section builders and never references the
  removed helper.
- **Focused tests for the release-validation script.**
  `backend/tests/test_verify_release.py` covers
  helper logic only (step plan shape, argv-only
  construction, working directories, non-zero timeouts,
  python executable resolved relative to the backend,
  tail truncation, `run_step` capturing stdout / stderr,
  `run_step` handling non-zero exit,
  `run_step_plan` stopping on the first failure, and
  `render_summary` marking the failed step). It does
  not execute the full release suite from pytest; that
  is the operator's job.
- **Boundary preservation.** The audit confirmed that
  every existing boundary from v0.5–v1.9 is preserved:
  no execution of analyzed code, no new providers, no
  new export standards, no new evidence contracts, no
  scheduled scans, no authentication, no organisation
  model, no universal score, no `secure/clean/passed/
  certified` claim, no cached-equals-live claim, no
  provider-success-equals-security claim, no tracked
  secrets, no tracked runtime artifacts, no global Git
  config change, and no production deployment.
- **Version.** Bumped `__version__` to `2.0.0`. The
  frontend `version_about` test mock now expects
  `2.0.0`.

## v1.9.0 — Provider health and operational diagnostics

- **Operational diagnostics page.** A new read-only
  `/diagnostics` route surfaces runtime reachability,
  executor state, per-provider persisted observations,
  recent partial / failed / cancelled scan issues, and
  aggregated persisted stage-state counts.
- **`/api/v1/diagnostics/summary` endpoint.** A new
  additive, read-only endpoint that composes the
  bounded summary from persisted state plus the
  existing `SELECT 1` database probe. The endpoint
  never triggers an external provider request and
  never exposes secrets, tokens, environment values,
  connection strings, or local filesystem paths.
- **Bounded provider diagnostics.** Per-provider rows
  surface the most-recent observation with cache state,
  evidence presence, last attempt, last success, and
  bounded error code / summary as independent fields.
  The page keeps cache state, evidence presence, and
  provider availability separate and never collapses
  them into a single verdict.
- **Bounded recent-issue list.** At most 25 partial /
  failed / cancelled scans are surfaced, ordered
  newest-first. Completed scans are intentionally
  excluded.
- **Bounded stage aggregation.** One row per
  `StageType` (the enum is fixed and small) with
  completed / partial / failed / skipped / running /
  pending counts. No percentage is invented; a zero
  count is rendered as "No matching persisted stage
  failures were found in the selected window" — never
  as "All stages are healthy."
- **Honest executor state.** The in-process executor
  does not persist heartbeats, so the page renders
  the explicit "Heartbeat not exposed by the current
  executor" notice rather than inventing a heartbeat
  from a wall-clock guess. Queued and running counts
  come from the persisted `scan_jobs` table.
- **Manual refresh only.** The page polls no faster
  than user-driven refresh. The refresh button blocks
  duplicate clicks through a synchronous `pendingRef`
  guard and preserves the last known payload on
  transient failure.
- **Boundary notice.** The page renders an explicit
  "Operational state is not security state" notice:
  a reachable backend does not imply providers are
  available; a provider unavailable does not imply a
  vulnerability is absent; cached evidence is not
  the same as live evidence; a successful provider
  request does not prove a repository is safe; a
  completed scan may still contain partial or
  degraded provider evidence.
- **No new providers, no new evidence contracts, no
  new external integrations, no migration.** The
  summary is composed from existing persisted
  observations and the existing scan-jobs table.

## v1.8.0 — Repository history, rescan, and evidence comparison

- **Repository history workbench.** The
  `/repositories/:repositoryId` page is upgraded into a
  coherent scan-history surface: scan rows are listed
  newest-first with status, ref, started/completed
  timestamps, and per-row cross-links to workbench /
  findings / dependencies / exports.
- **URL-persisted filters.** Status, trigger type, and
  page number are reflected in the URL query string so
  the history view is shareable and survives reload.
- **Bounded scan-state notices.** Filtering to partial,
  failed, or cancelled surfaces a `DataCompletenessNotice`
  with copy that does not claim a clean or complete
  result.
- **Run another scan uses the v1.6.1 rescan endpoint.**
  The "Run another scan" action calls
  `api.rescanRepository` (workspace-preserving) and never
  the low-level `api.createScan` path. The new scan is
  then started via `/scans/{id}/run` and the page
  navigates to the new workbench. The historical scan
  is never mutated.
- **Bounded rescan error rendering.** A
  `rescan_source_unavailable` error renders bounded
  guidance rather than a generic failure.
- **Repository-scoped comparison selector.** A new
  `/repositories/:repositoryId/compare` page hosts the
  baseline / comparison selector with URL state
  (`?baseline=&comparison=`). The selector preserves the
  v0.5 eligibility rules: only completed and partial
  scans are listed; same-scan selection is blocked;
  cross-repository ids are rejected as bounded errors.
- **Reuses the v0.5 comparison engine.** The selector
  page defers to the existing `ScanComparisonPage`
  with a "Repository → Compare" breadcrumb. The
  comparator itself is unchanged; v1.8 does not
  introduce a new comparison algorithm.
- **Removed-finding disclaimer and zero-improvement
  claim.** The v0.5 wording ("is not described as fixed
  or resolved") is preserved; the v1.8 page never
  claims security improved, security worsened, risk
  increased, risk decreased, fixed, or remediated.
- **No new backend endpoints.** The existing
  `/api/v1/repositories/{id}/rescan`,
  `/api/v1/repositories/{id}/scans`, and
  `/api/v1/scans/{id}/compare/{base}` routes are
  reused. No migration.

## v1.7.0 — Findings triage and evidence review

- **Findings triage and evidence review workbench.**
  The existing `/scans/:scanId/findings` page
  becomes a scan-scoped, evidence-first review
  surface. Reviewers can:
  - read a scan context header (scan id,
    repository, status, source type, finding
    count) with links back to the workbench,
    dependencies, and exports;
  - search findings server-side across title,
    summary, rule id, and the raw `evidence_json`
    (so package names, PURLs, advisories, and
    aliases are reachable from one search box);
  - filter server-side by category, severity,
    confidence, status, provider, rule id, and
    path; previous client-only filters are wired
    to the API;
  - sort by bounded fields (`id`, `rule_id`,
    `category`, `severity`, `confidence`,
    `status`, `updated_at`); Lockverity never
    invents a universal risk ranking;
  - open an evidence detail drawer that fetches
    the freshest payload via the single-finding
    endpoint, renders advisory identity (primary
    id, aliases, provider, source URL), shows
    the evidence provenance block, and surfaces
    cross-links to the workbench, dependencies,
    vulnerabilities, and exports;
  - persist filter / search / sort state in the
    URL so the analyst queue is shareable;
  - read a partial / failed / cancelled scan
    notice whenever the scan did not complete
    normally; the page never implies the
    finding set is complete in those cases.
- **Zero-result wording is bounded.** Empty
  states use "No finding records are available
  for the current filters. This does not
  establish that the repository is
  vulnerability-free." Lockverity never claims a
  clean / secure / safe / certified / compliant
  state.
- **Backend bounded additions.** New query
  parameters on
  `GET /api/v1/scans/{id}/findings`: `q`,
  `confidence`, `status`, `provider`, `rule_id`,
  `path`, `sort`. Page size is capped at 100.
  Invalid sort values map to `id` so paging stays
  deterministic. New
  `GET /api/v1/scans/{id}/findings/{finding_id}`
  route enforces scan-scoped isolation. No
  migration; all additions reuse existing
  persisted columns.
- **Persistent analyst disposition is not
  implemented.** v1.7 is read-only; review
  decisions are intentionally not stored in
  localStorage or in any new database column.
  This is reported as future work.

## v1.6.1 — Workspace-preserving rescan repair

- **Workspace-preserving rescan.** New
  `POST /api/v1/repositories/{id}/rescan` route and
  `RescanService` create a fresh scan, a fresh
  workspace, and re-materialise the source
  evidence (re-download the GitHub tarball or
  safely copy the previous upload workspace)
  before returning. The historical scan and
  workspace are never mutated.
- **Source-unavailable guard.** When the original
  uploaded source is no longer available, the
  route returns a bounded
  `rescan_source_unavailable` error before any
  queued row is persisted. The frontend renders
  the bounded guidance; the workbench never
  navigates to a new scan that is known to be
  unrunnable.
- **Action error carries its pending state.** The
  `ScanActions` component now stores the error
  alongside the action that produced it, so the
  bounded error title survives the
  `finally` block that resets the pending flag.
- **Frontend update.** `api.rescanRepository`
  wraps the new route; the v1.6 `api.createScan`
  still wraps the low-level route that creates
  only a queued scan row (kept for the orchestrator
  tests).
- **No new providers, no new export standards, no
  new evidence contracts, no migration.**

## v1.6 — Scan execution controls + live stage progress

- **Scan workbench at `/scans/:scanId`.** The existing
  scan detail page is upgraded with a truthful
  `ScanStatusExplanation` block (queued / running /
  completed / partial / failed / cancelled) and a
  `StageProgressSummary` block ("N of M stages reached
  a terminal state — terminal does not imply
  successful") that derives from persisted stage rows
  only. No percentage progress is ever shown.
- **Execution controls.** A new `ScanActions` component
  surfaces Start scan (`POST /api/v1/scans/{id}/run`),
  Cancel scan (`POST /api/v1/scans/{id}/cancel` with
  a destructive-styled confirmation dialog), and
  Run another scan / Retry as new scan (creates a
  fresh scan for the same repository; the historical
  scan is never mutated). The actions disable while
  pending so duplicate submissions are blocked.
- **Intake-to-execution flow.** The v1.5 `/analyze`
  page now calls `/scans/{id}/run` immediately after
  successful intake. If the start fails, the page
  surfaces a bounded partial-success card: the
  repository and scan are persisted, the worker did
  not start the scan, and a Retry start button is
  offered. The card never claims the scan started.
- **API client additions.** `api.runScan(scanId)` and
  `api.cancelScan(scanId, payload)` wrap the existing
  executor endpoints. No new backend endpoints.
- **Polling.** The workbench reuses the existing
  `usePolling` hook (2s interval, terminal-set stop,
  abort on unmount) via a new `useWorkbenchPolling`
  wrapper.
- **No new providers, no new export standards, no new
  evidence contracts, no migration.**

## v1.5 — Guided intake / scan launch

- **New `/analyze` route.** `frontend/src/pages/AnalyzePage.tsx`
  wraps the existing intake APIs in a guided flow with two
  clearly separated methods: a public GitHub URL form and a
  source archive (`zip`) upload. The page does not duplicate
  business logic; it calls
  `POST /api/v1/repositories/github` and
  `POST /api/v1/repositories/upload` and reads the returned
  `IntakeResultRead.scan.id` to navigate to the new scan.
- **AppShell nav entry.** New `Analyze` entry in the primary
  navigation, between `Dashboard` and `Demo`. The link
  points at `/analyze` and uses the `Sparkles` icon.
- **Bounded non-execution and archive-hostility copy.** The
  page repeats the "Lockverity never executes repository
  code" and "archives are treated as hostile input"
  guarantees inline on the form, plus the bounded
  "evidence exports, not a security verdict, certification,
  or compliance pass-or-fail" wording.
- **First-run empty state.** The scan list empty state now
  offers two clear actions: `Analyze repository` (linking
  to `/analyze`) and `Open demo guide` (linking to `/demo`).
  The synthetic-dataset notice on the scan list is
  unchanged.
- **Upload field-name bug fix.** The frontend `requestUpload`
  helper used to send the ZIP under the multipart `archive`
  field; the backend route declared `file: UploadFile = File(...)`
  so every upload silently bound `None` and the endpoint
  returned `422`. The v1.5 fix pins the field name to `file`
  matching the backend contract, so the existing
  `/repositories/upload` route (used by the new `/analyze`
  page) and the older `/repositories/upload` legacy page
  both work end-to-end. The pre-existing test in
  `frontend/src/__tests__/exports.test.tsx` only checks the
  URL path; the form-field change is verified by a new
  test in `frontend/src/__tests__/analyze_v1_5.test.tsx`.
- **Status / progress UX.** After intake succeeds, the
  page renders a status panel that polls the new scan
  using the existing `usePolling` hook. The reviewer can
  open the scan detail page at any time. Polling stops
  on terminal status (`completed` / `partial` / `failed`
  / `cancelled`).
- **No new backend endpoints.** v1.5 reuses the existing
  intake and scan routes. No new providers, no new export
  standards, no new evidence contracts, no migration.

## v1.4 — In-app demo home + reviewer flow

- **In-app reviewer flow.** New `/demo` route and
  `DemoHomePage` page. The page surfaces five sections
  (demo dataset status, reviewer flow, what to look for,
  what not to claim, quick command reminder) and a
  bounded "this is a demo, not a hosted service" footer.
  The page repeats the synthetic-dataset disclosure and
  the bounded "not a verdict / not a certification / not
  a compliance pass-or-fail" wording so a reviewer can
  never mistake the demo for a real provider scan result.
- **AppShell nav entry.** New `Demo` entry in the primary
  navigation, between `Dashboard` and `Repositories`. The
  link points at `/demo` and uses the `PlayCircle` icon.
- **New focused test** at
  `frontend/src/__tests__/demo_home_v1_4.test.tsx` covers
  all five sections, the five reviewer links, the bounded
  wording, the new nav entry, and the synthetic-dataset
  disclosure.
- **No product change.** No new providers, no new export
  standards, no new evidence contracts, no new API
  endpoints. The page is read-only and self-contained; it
  does not call any backend endpoint.
- **Docs.** `README.md` 30-second overview updated to
  mention `/demo`. `docs/demo-pack.md` "How to run the
  demo" section updated to point at `/demo` first.
- **Version.** Bumped `__version__` to `1.4.0`. The
  frontend `version_about` test mock now expects `1.4.0`.
- **Status.** Private portfolio-ready baseline. Not a
  production SaaS, not a hosted service, not a CI vendor.
  See `RELEASE_NOTES.md` for the full status.

## v1.3 — Screenshot assets + private portfolio demo pack

- **Demo pack.** New `docs/demo-pack.md` with the 60-second
  reviewer walkthrough script, the public/private
  recommendation, the "what to say" + "what not to claim"
  framing, and a cross-reference list to the other
  reviewer-facing docs.
- **Screenshot checklist rewrite.** `docs/screenshots.md`
  is now a 9-capture reviewer checklist with browser-
  agnostic manual capture instructions (macOS, Windows,
  Linux shortcuts), a pre-capture sensitive-data checklist,
  a post-capture sensitive-data checklist, and an explicit
  rationale for **not** shipping tracked image files. No
  headless-browser dependency is added; the live demo is
  the canonical evidence.
- **README polish.** New `## Screenshots` section under
  the existing `### What not to claim` block explaining the
  manual-capture strategy and pointing at
  `docs/demo-pack.md`. New `docs/demo-pack.md` entry in the
  `## Quick links` block.
- **No product change.** No new providers, no new export
  standards, no new evidence contracts, no new API
  endpoints. All v0.5–v1.2 surfaces continue to work
  unchanged. The application source tree is the same as
  v1.2.1.
- **Version.** Bumped `__version__` to `1.3.0`. The
  frontend `version_about` test mock now expects `1.3.0`.
- **Status.** Private portfolio-ready baseline. Not a
  production SaaS, not a hosted service, not a CI vendor.
  See `RELEASE_NOTES.md` for the full status.

## v1.2.1 — GitHub portfolio final pass

- **Repository presentation.** Added `CHANGELOG.md` (this file)
  and `RELEASE_NOTES.md` for a reviewer reading the repo on
  GitHub. Added a `Quick links` block to the top of `README.md`
  pointing to the demo walkthrough, the screenshot checklist,
  the security boundaries, the provider-honesty policy, the
  changelog, and the release notes.
- **No product change.** No new providers, no new export
  standards, no new evidence contracts, no new API endpoints.
  All v0.5–v1.2 surfaces continue to work unchanged.
- **Version.** Bumped `__version__` to `1.2.1`. The frontend
  `version_about` test mock now expects `1.2.1`.
- **Status.** Private portfolio-ready baseline. Not a
  production SaaS, not a hosted service, not a CI vendor. See
  `RELEASE_NOTES.md` for the full status.

## v1.2 — Demo UX polish

- **`backend/scripts/load_demo.py`**: rewrote the success-path
  console output to surface the dataset nature (synthetic
  persisted evidence, no provider calls), the four scan ids
  and their states, cross-platform startup commands, and the
  five reviewer-facing demo URLs in one place. New focused
  test pins the new output shape.
- **`docs/screenshots.md`**: new 10-capture reviewer
  checklist with exact URLs, expected visible states, what
  not to claim, and a reviewer-facing checkbox list.
- **`README.md`**: added a clean `## Run the demo` section
  with six numbered steps (generate DB → start backend →
  start frontend → open URLs → capture screenshots → stop
  demo) and a `### What not to claim` block. Updated
  `Current milestone` to v1.2.
- **`docs/demo-walkthrough.md`**: bumped v1.0/v1.1 references
  to v1.2; explicit "demo dataset is synthetic persisted
  evidence" wording.
- **`frontend/src/pages/ScansIndexPage.tsx`**: small neutral
  in-product demo-dataset notice gated on every listed scan
  belonging to the synthetic fixture repository. The notice
  does not appear for normal repositories.

## v1.1 — Demo loader + synthetic screenshot-ready dataset

- **`backend/scripts/load_demo.py`** (new, 462 lines): a
  deterministic, safe-to-commit seed script that creates a
  Lockverity demo SQLite database from hard-coded synthetic
  data. Refuses to overwrite an existing file unless
  `--reset-demo-db` is passed; refuses to write outside
  `backend/var/`. Runs Alembic migrations
  (`7efc41b356da` → `d4e5f6a7b8c9`); never calls
  `Base.metadata.create_all` as the primary schema creator.
- **Seed data:** one synthetic repository
  (`example-org/lockverity-fixture`), four scans
  (completed / partial / failed / cancelled) with
  hardcoded ids 1–4, synthetic package names only
  (`alpha`, `beta`, `gamma`, `left-pad`, `right-pad`, `stay`),
  the `deadbeef` repeated fill for the resolved commit SHA,
  and obviously-fake `a*64` / `b*64` content hashes.
- **Six new focused tests** in
  `backend/tests/test_load_demo.py` covering schema via
  Alembic, refusal to overwrite, refusal to write outside
  `backend/var/`, deterministic dataset shape, no-embedded-
  secrets invariant, and the failed-scan failure reason.

## v1.0.1 — Public/portfolio readiness docs

- **README rewrite** from a v0.1 baseline copy to the full
  v1.0 product description (10 "What Lockverity does"
  sections, 6 bounded "What Lockverity explicitly does not
  claim" sections, intended users, key v1.0 demo flow,
  architecture overview, local setup, database migration,
  testing commands, known ports, current milestone, what
  v1.0 does not include, provider-honesty policy,
  non-execution security boundary, license).
- **New `docs/demo-walkthrough.md`** (reviewer walkthrough)
  and **`docs/security-boundaries.md`** (public-facing
  statement of what Lockverity will and will not do).
- **Documentation correctness fix:** the v0.1-era `Cargo.toml`
  and `go.mod` parser claims were removed from
  `docs/security-boundaries.md` because the v1.0
  application only ships npm / pnpm / yarn / poetry /
  pyproject / requirements parsers; verified by listing
  `backend/app/parsers/`.
- **Version bump** to `1.0.1`; the `version_about` frontend
  test mock and three hardcoded `"1.0.0"` backend assertions
  were updated to read `__version__` dynamically.

## v1.0 — Human-readable evidence report

- **`backend/app/reports/`** (new module, 913 lines):
  `build_evidence_report` (pure projection) +
  `render_evidence_report_markdown` (deterministic renderer) +
  `EvidenceReportService(session_factory)` (session wrapper);
  reuses the v0.6 / v0.7 / v0.8 / v0.9 helpers verbatim.
- **API:** `GET /api/v1/scans/{id}/reports/evidence-summary/preview`
  (JSON) + `GET /api/v1/scans/{id}/reports/evidence-summary.md`
  (Markdown download with per-scan `Content-Disposition`).
- **Bounded 7-section Markdown:** metadata, scan identity,
  scan summary, evidence coverage, evidence gaps, component
  table (capped at 100 rows), export relationship, plus the
  10 evidence-honesty omission markers.
- **Frontend:** `EvidenceReportPanel` + `EvidenceReportSummary`
  on the Export Center page; the preview fetches lazily on
  the first expand.

## v0.9 — Evidence search and filtering

- **New endpoint**
  `GET /api/v1/scans/{scan_id}/components/evidence-summary`:
  text search, ecosystem, direct, version present / missing,
  licence evidence, provider evidence, PURL persisted /
  constructible / omitted, dependency edges, CycloneDX 1.7
  appears / version omitted / relationships emitted, plus
  6 sort options. Per-row evidence flags. Facet counts.
- **Lazy rewrite** of `DependencyExplorerPage` for the
  evidence-honest vocabulary ("not persisted" / "no
  persisted edges", never "no dependencies").

## v0.8 — Component evidence drilldown

- **New endpoint**
  `GET /api/v1/scans/{scan_id}/components/{component_id}/evidence`:
  per-component read-only summary with 6 sections
  (identity, manifest evidence, licence evidence, provider
  evidence, dependency evidence, export implications) plus
  an evidence-honesty markers list. Reuses the v0.6 CycloneDX
  exporter helpers for PURL, bom-ref, licence
  classification, and graph coverage.
- **Frontend:** `DetailsDrawer` side-panel on the Dependency
  Explorer.

## v0.7 — SBOM evidence preview and export explanation

- **New endpoint**
  `GET /api/v1/scans/{scan_id}/exports/cyclonedx_1_7/preview`:
  read-only JSON summary of the upcoming download (eligibility
  verdict, inventory summary, evidence coverage, SBOM
  output facts, omissions, legacy-export relationship note).
- **Frontend:** `CycloneDxPreviewPanel` on the Export Center;
  lazy fetch on first expand.

## v0.6 — CycloneDX 1.7 SBOM export

- **New endpoint**
  `GET /api/v1/scans/{scan_id}/exports/cyclonedx_1_7`:
  schema-validated CycloneDX 1.7 SBOM with deterministic
  serial numbers, evidence-coverage properties, and a
  per-scan `Content-Disposition`. Validated against the
  official `JsonStrictValidator(SchemaVersion.V1_7)`.
- **Eligibility helper** (`evaluate_export_eligibility`)
  with three states (`eligible`, `partial_evidence`,
  `ineligible`) and a bounded `not_applicable` coverage
  verdict for failed / cancelled / queued / running scans.

## v0.5 — Evidence-aware scan comparison

- **New endpoint**
  `GET /api/v1/scans/{head_scan_id}/compare/{base_scan_id}`:
  diffs two terminal scans of the same repository without
  inventing missing evidence. State vocabulary
  (`newly_observed`, `still_observed`, `no_longer_observed`,
  `changed_observation`, `coverage_changed`,
  `comparison_indeterminate`) is evidence-honest: missing
  provider data is never rendered as a clean bill of
  health.
- **Frontend:** `ScanComparisonPage` and
  `ScanCompareSelectPage`.

## Notes

- Pre-v0.5 history is not summarised here. The release-line
  tags are `checkpoint-v0.2`, `checkpoint-v0.2-polished`,
  `checkpoint-v0.2-vite8`, `checkpoint-v0.3`,
  `checkpoint-v0.4`, and the v0.5 onward tags listed above.
- Every release line has a corresponding annotated tag
  `checkpoint-vX.Y` in the repository.
