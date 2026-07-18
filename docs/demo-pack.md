# Lockverity — Private Portfolio Demo Pack

This is the v1.3 portfolio demo pack. It is a one-page
reviewer reference: the current version, the demo command
flow, the screenshot list, the 60-second demo script, the
"what to say" + "what not to claim" framing, and the current
public / private recommendation.

For the full reviewer walkthrough see
[`docs/demo-walkthrough.md`](demo-walkthrough.md). For the
screenshot checklist and manual capture instructions see
[`docs/screenshots.md`](screenshots.md).

## Current version

`v1.5` — Guided intake / scan launch.

The current milestone is a product-usability milestone.
The release adds an in-app `/analyze` page that wraps the
existing intake APIs (`POST /api/v1/repositories/github`
for a public GitHub URL and
`POST /api/v1/repositories/upload` for a `zip` source
archive). The page navigates to the new scan, polls
status using the existing `usePolling` hook, and
surfaces the bounded non-execution / archive-hostility
wording. No new backend endpoints, no new providers, no
new export standards, no new evidence contracts, no
migration. The v1.4 release added the in-app `/demo`
page and the `Demo` AppShell primary nav entry.

## How to run the demo

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

After both servers are up, open **`http://127.0.0.1:5173/demo`**
in a browser. The `/demo` page is the in-app reviewer
walkthrough: it lists the demo dataset's nature, the five
links a reviewer should click, the "what to look for" and
"what not to claim" framings, and a short command reminder.
The same five URLs are listed below for direct navigation.

The v1.5 release adds **`http://127.0.0.1:5173/analyze`**
as a guided intake page that wraps the existing intake
APIs. Reviewers who want to register a public GitHub
repository or upload a `zip` source archive on top of the
seeded demo can use it. The page is read-only before any
submission; submission calls
`POST /api/v1/repositories/github` or
`POST /api/v1/repositories/upload` and navigates to the
newly-created scan. The synthetic-dataset notice on the
scan list still applies to demo data; the analyze flow
produces real evidence exports.

The loader's success-path output already prints all five
demo URLs and the cross-platform startup commands. The
five URLs are:

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

The demo dataset is **synthetic persisted evidence**: the
fixture repository is
`https://github.com/example-org/lockverity-fixture`, the
resolved commit SHA is the `deadbeef` repeated fill, every
package name is from a documented six-name set
(`alpha`, `beta`, `gamma`, `left-pad`, `right-pad`, `stay`),
and Lockverity makes no provider calls during the demo.

## Screenshot list (manual capture, ~10 minutes total)

The 9 reviewer captures are described in detail in
[`docs/screenshots.md`](screenshots.md). The filenames
sort alphabetically into the intended review order:

```
01-scan-list-demo-notice.png
02-dependency-explorer-default.png
03-dependency-explorer-filtered-left.png
04-component-evidence-drawer.png
05-export-center-cyclonedx-preview.png
06-export-center-evidence-report-preview.png
07-markdown-evidence-report.png
08-failed-scan-bounded-empty-state.png
09-about-boundaries.png
```

The captures are intentionally **manual**, not auto-
captured: see `Status of the screenshot assets` in
`docs/screenshots.md` for the rationale. The captures are
the reviewer's local portfolio folder, not a tracked
artifact of the repository.

## 60-second demo script

This is the canonical 60-second walkthrough a reviewer can
deliver without preparation. Time it once on a laptop; if
the walkthrough consistently runs over 90 seconds, cut a
section.

1. **0:00 – 0:10.** Open `http://127.0.0.1:5173/`. Point
   at the four rows and the demo-dataset notice above
   them. *Say*: "This is a synthetic demo dataset generated
   by Lockverity's demo loader. The four scan states are
   honest — failed and cancelled do not claim a clean
   result." **Do not** say "Lockverity found zero
   vulnerabilities in this scan."
2. **0:10 – 0:20.** Click scan 1. Open
   `http://127.0.0.1:5173/scans/1/dependencies`. *Say*:
   "The dependency explorer has 9 evidence filter fields
   and 13 facet counts. The vocabulary is evidence-honest:
   missing evidence is rendered as missing, never as a
   clean bill of health."
3. **0:20 – 0:30.** Type `left` in the search box.
   *Say*: "The table narrows to one row, the facets
   update, the Clear button appears." Click `View evidence`
   on `left-pad`. *Say*: "The v0.8 evidence drilldown has
   six sections plus an evidence-honesty markers list.
   The component is what it is — not a verdict."
4. **0:30 – 0:45.** Close the drawer. Open
   `http://127.0.0.1:5173/scans/1/exports`. Click
   `Show CycloneDX 1.7 evidence preview`. *Say*: "The
   export is eligible, schema-validated, and the omissions
   block names the things the export does not claim."
   Click `Download`. The browser saves
   `lockverity-scan-1.cdx.json`.
5. **0:45 – 0:55.** Click `Show report summary` on the
   Evidence report card. *Say*: "The v1.0 evidence report
   has seven sections plus a bounded disclaimer: not a
   security verdict, not a certification, not a compliance
   pass-or-fail." Click `Download Markdown`. The browser
   saves `lockverity-scan-1.evidence-report.md`.
6. **0:55 – 1:00.** Open
   `http://127.0.0.1:5173/scans/3/exports`. *Say*: "A
   failed scan returns 200 with a bounded `not_applicable`
   empty state. The UI does not fabricate a clean verdict
   for a failed or cancelled scan." End on the About page.

The script is intentionally short and bounded. If a
reviewer asks for a deep dive, switch to the full
[`docs/demo-walkthrough.md`](demo-walkthrough.md).

## What to say

- "Lockverity is an evidence-first, defensive-only,
  read-only software-supply-chain analyzer."
- "Every claim the UI makes is backed by a file path, a
  manifest, a provider response, or an explicit omission
  marker."
- "The demo dataset is synthetic persisted evidence.
  Lockverity makes no provider calls during the demo."
- "Failed and cancelled scans return a bounded
  `not_applicable` empty state. The UI does not fabricate
  a clean verdict for a failed or cancelled scan."
- "A missing provider is rendered as `not_persisted` or
  `not_observed` — never as a clean bill of health."

## What not to claim

- **Do not** call the report "a security scan result". It
  is an evidence report.
- **Do not** call the SBOM "a certified bill of materials".
  It is evidence. The schema validates, but the export
  is not signed and does not carry a trust assertion.
- **Do not** say "the dependency graph is complete" unless
  a positive persisted signal exists. The v0.6 helper
  returns `partial` for the demo dataset.
- **Do not** say "no findings" because a provider was
  unavailable, rate-limited, or skipped. The demo's three
  provider observations are explicit `AVAILABLE` or
  `RATE_LIMITED` rows, never silent omissions.
- **Do not** say the demo dataset is a real provider scan
  result. The fixture repository is
  `https://github.com/example-org/lockverity-fixture`, the
  resolved commit SHA is the `deadbeef` fill, and
  Lockverity makes no provider calls during the demo.
- **Do not** call Lockverity "production-ready" or "a
  hosted SaaS". The current status is a private portfolio-
  ready baseline.

## Public / private recommendation

**Current recommendation: keep the repository private.**

The application is a private portfolio-ready baseline, not a
production SaaS, not a hosted service, and not a CI vendor.
A reviewer or future public visitor can clone the
repository, run the demo, and verify every claim in
5 minutes. The codebase, the docs, and the demo dataset are
all internally consistent and free of secrets.

The same wording is in `RELEASE_NOTES.md` under
`## Status — private portfolio-ready baseline`. If a future
release changes this status (e.g. adds hosted deployment),
this section will be the first thing rewritten and the
change will be called out in `CHANGELOG.md`.

## What the demo does not show

The demo deliberately does not show:

- A **real provider scan result.** The demo dataset is
  synthetic; production scanning would require a real
  GitHub URL and (optionally) a `LOCKVERITY_GITHUB_TOKEN`
  for public rate limits. The current v1.3 demo cannot
  reach an external provider.
- A **multi-tenant deployment.** The application has no
  authentication, no per-tenant data, and no hosted
  control plane. See "What v1.2.1 does not include" in
  the About page or `RELEASE_NOTES.md`.
- A **vulnerability verdict.** The CycloneDX 1.7 export
  and the Markdown report are evidence exports, not
  verdicts. The bounded disclaimer in the report
  repeats this verbatim.

## Cross-references

- Demo walkthrough: [`docs/demo-walkthrough.md`](demo-walkthrough.md)
- Screenshot checklist: [`docs/screenshots.md`](screenshots.md)
- Security boundaries: [`docs/security-boundaries.md`](security-boundaries.md)
- Provider-honesty policy: [`docs/provider-honesty.md`](provider-honesty.md)
- Changelog: [`../CHANGELOG.md`](../CHANGELOG.md)
- Release notes: [`../RELEASE_NOTES.md`](../RELEASE_NOTES.md)
- README `Run the demo`: [`../README.md`](../README.md)
