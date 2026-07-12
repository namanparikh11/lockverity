# Lockverity frontend (v0.2 — Professional Frontend Product)

This is the React + Vite + TypeScript + Tailwind frontend for
Lockverity. It targets the v0.1+ Lockverity backend and is
designed to degrade gracefully for backend endpoints that are
not yet implemented.

## Stack

- React 18, TypeScript 5, Vite 5
- React Router 6
- Tailwind CSS 3
- Vitest + Testing Library for unit and component tests
- Lucide icons

## Layout

```
frontend/
  src/
    api/        typed API client, types, hooks, fallback helpers
    components/ reusable presentational + interactive widgets
    layouts/    AppShell (header, sidebar, content)
    pages/      one file per route
    routes/     react-router configuration
    test/       vitest setup
    utils/      time formatting, enum labels
  index.html
  vite.config.ts
  tailwind.config.js
  postcss.config.js
  tsconfig.app.json
  tsconfig.node.json
  .eslintrc.cjs
  package.json
```

## Commands

```bash
cd frontend
npm install        # or: npm ci
npm run dev        # local dev server on :5173
npm run typecheck  # tsc --noEmit
npm run lint       # eslint . --max-warnings 0
npm run build      # tsc -b && vite build
npm test           # vitest run
```

## Environment

The frontend reads:

| Variable              | Default     | Purpose                              |
| --------------------- | ----------- | ------------------------------------ |
| `VITE_API_BASE_URL`   | `/api/v1`   | API prefix; overridden in deployments |
| `VITE_API_TIMEOUT_MS` | `30000`     | Per-request timeout in ms            |
| `VITE_DEV_FIXTURES`   | unset       | Set to exactly `enabled` to use dev fixtures |

`VITE_API_BASE_URL` is the only required value. The frontend
works out-of-the-box behind a same-origin reverse proxy that
serves `/api/v1/*`. For local development you can set
`VITE_API_BASE_URL=http://localhost:8000/api/v1`.

### Development fixture boundary

`VITE_DEV_FIXTURES` is read by `readDevFixturesEnabled()` in
`src/api/client.ts`. Fixtures activate only when the value is
**exactly** the string `enabled` (case-sensitive). Any other
value (including an empty string, a typo, or unset) leaves the
client pointed at the real API. The frontend never falls back
to fixtures because of an API failure.

## Design principles

- Professional security-product appearance. No hacker-terminal
  theme, no neon overload, no fake data.
- No universal security score. Every finding stands on its own
  evidence.
- Severity and confidence are independent dimensions. A
  critical-severity finding may still have low confidence; the
  UI surfaces both.
- Unknown must not appear healthy. Missing severity, missing
  provider data, and missing dependency data are all rendered
  as `unknown` or "not available" - never as clean.
- Status is never colour-only. Every badge carries the status
  word in text. Every severity / confidence badge has an
  `aria-label` for screen readers.
- No production fixture fallback. The fixture flag is the only
  way to opt in, and it is off by default.

## Accessibility

- Visible focus state on every interactive element
  (`:focus-visible` in `index.css`).
- Skip-to-main-content link as the first focusable element.
- Semantic tables with `<caption>` and `<th scope="col">` for
  every list. Lists degrade to a card view on small screens via
  `ResponsiveTable`.
- `aria-live` is used for status, alerts, and asynchronous
  fetch states.
- Dialogs (`ConfirmationDialog`, `DetailsDrawer`) trap focus
  and support `Escape` to close.
- Mobile navigation uses a hamburger button with
  `aria-expanded` and an `aria-label` that reflects the next
  action.
- Text-zoom: every layout uses flex / grid and never sets a
  fixed pixel height on text containers, so the page is usable
  at 200% browser zoom.
- Reduced-motion: the global stylesheet disables all
  non-essential animation and transition when
  `prefers-reduced-motion: reduce` is set.

## API contract assumptions

The frontend depends on the documented backend routes under
`/api/v1`. It is forward-compatible with the v0.3–v0.6
endpoints that have not yet shipped: when a backend endpoint
returns a not-implemented status (404 / 405 / 501), the page
renders an honest "not yet available" empty state and
continues to work for the endpoints that do exist.

The v0.2 frontend expects these endpoints to be present:

| Method | Path                                  | Status |
| ------ | ------------------------------------- | ------ |
| GET    | `/api/v1/health`                      | v0.1   |
| GET    | `/api/v1/system/info`                 | v0.1   |
| GET    | `/api/v1/repositories`                | v0.1   |
| POST   | `/api/v1/repositories`                | v0.1   |
| POST   | `/api/v1/repositories/uploads`        | v0.2   |
| GET    | `/api/v1/repositories/{id}`           | v0.1   |
| GET    | `/api/v1/repositories/{id}/scans`     | v0.1   |
| POST   | `/api/v1/repositories/{id}/scans`     | v0.1   |
| GET    | `/api/v1/scans`                       | v0.1   |
| GET    | `/api/v1/scans/{id}`                  | v0.1   |
| GET    | `/api/v1/scans/{id}/stages`           | v0.1   |
| GET    | `/api/v1/scans/{id}/findings`         | v0.1   |
| GET    | `/api/v1/scans/{id}/providers`        | v0.1   |
| GET    | `/api/v1/provider-health`             | v0.2   |

The frontend also uses these endpoints and degrades gracefully
when they are not yet implemented:

- `GET /api/v1/scans/{id}/components`
- `GET /api/v1/scans/{id}/components/{id}/path`
- `GET /api/v1/scans/{id}/vulnerabilities`
- `GET /api/v1/scans/{id}/advisories`
- `GET /api/v1/scans/{id}/workflows`
- `GET /api/v1/scans/{id}/openssf`
- `GET /api/v1/scans/{id}/licences`
- `GET /api/v1/scans/{id}/compare/{baseId}`
- `GET /api/v1/scans/{id}/exports`
- `GET /api/v1/scans/{id}/exports/{format}`

The error envelope is the same one documented in
`docs/architecture.md`: `{ "error": { "code", "message",
"details?", "request_id?" } }` with stable codes such as
`not_found`, `validation_error`, `rate_limited`,
`provider_unavailable`, `internal`.

## Security boundary

- The frontend never embeds credentials. `apiClient` uses
  `credentials: "omit"` on every call. No `Authorization`
  header is ever set.
- The frontend never executes uploaded archive content or
  repository code.
- `evidence_json` is rendered as text inside a `<pre>`. It is
  never parsed as HTML.
- All repository URLs are validated in the browser before
  submission. The backend still validates, but the
  client-side check reduces the surface for accidental leaks.
- The export download uses an in-memory `Blob` and an
  `URL.createObjectURL` / `revokeObjectURL` pair. The bytes
  never leave the browser session.

## Frontend tests

Run `npm test`. The test suite covers:

- API client: error envelope, abort / timeout categorisation,
  credential suppression, query stripping.
- Utility helpers: time formatting, label mapping.
- Components: badge tone mapping, drawer focus / escape,
  confirmation dialog, filter bar, pagination, skeleton,
  notification roles, page header, scan timeline.
- Layout: app shell routing smoke tests.

End-to-end browser tests are not included in v0.2. The unit
and component tests are the agreed verification surface for
this milestone.
