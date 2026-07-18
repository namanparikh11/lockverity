# Changelog

All notable changes to Lockverity are documented here. Versions
follow [Semantic Versioning](https://semver.org/). Lockverity is
pre-1.0 in the sense that the public API may evolve; the
underlying data model and Alembic migrations are stable.

## v1.2.1 — GitHub portfolio final pass (current)

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
