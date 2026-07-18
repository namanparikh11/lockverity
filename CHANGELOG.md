# Changelog

All notable changes to Lockverity are documented here. Versions
follow [Semantic Versioning](https://semver.org/). Lockverity is
pre-1.0 in the sense that the public API may evolve; the
underlying data model and Alembic migrations are stable.

## v1.6.1 — Workspace-preserving rescan repair (current)

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
