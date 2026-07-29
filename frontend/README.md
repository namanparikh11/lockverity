# Lockverity frontend

This is the React + Vite + TypeScript + Tailwind frontend
for Lockverity. It targets the v2.0.x Lockverity backend
and is designed to degrade gracefully for backend
endpoints that are not yet implemented.

The current release line is **v2.0.6** (v0.4.0-public-
closure). The version field is the source of truth; this
file is kept in sync with `backend/app/_version.py` and
the package metadata.

## Stack

- React 19.2.x
- TypeScript 5.6.x
- Vite 8.1.x
- React Router 8.3.x (`react-router` direct; the legacy
  `react-router-dom@6.x` line is no longer used)
- Tailwind CSS 3.4.x
- Vitest 4.x + Testing Library 16.x for unit and
  component tests
- Lucide icons
- ESLint 10.8.x with the flat `eslint.config.js` (the
  legacy `.eslintrc.cjs` was retired in the v2.0.6
  closure; see `frontend/eslint.config.js` for the active
  rule set)
- typescript-eslint 8.65.x (`@typescript-eslint/*@8.x`)

## Layout

```text
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
  eslint.config.js          # ESLint 10 flat config
  package.json
```

## Node engine

The frontend pins Node.js `>=22.22.0` in `package.json`
and `.nvmrc` (at the repo root). The pin is dictated by
`react-router@8.3.0`, which declares
`engines.node = ">=22.22.0"`. The cycle 6 and cycle 7
release validation was performed on Node.js 24.18.0;
v22.22.x is the minimum.

## Commands

```bash
cd frontend
npm ci --legacy-peer-deps   # or: npm install
npm run dev                  # local dev server on :5173
npm run typecheck            # tsc -b --noEmit
npm run lint                 # eslint . --max-warnings 0
npm run build                # tsc -b && vite build
npm test                     # vitest run
```

The `npm ci` invocation uses `--legacy-peer-deps`
because `eslint-plugin-react-refresh@0.5.x` advertises
`eslint@^9 || ^10` as a peer but the v0.5.x line ships
without a flat-config peer declaration; the runtime API
is unchanged across eslint 9 and 10 so the legacy-peer-
deps override is safe and does not weaken any lint rule.

## ESLint flat config (`eslint.config.js`)

The active configuration is `frontend/eslint.config.js`
(ESLint 10 flat config). It loads:

- `js.configs.recommended` (eslint core)
- `tseslint.configs.recommended` (`@typescript-eslint`)
- `eslint-plugin-react-hooks` for
  `react-hooks/rules-of-hooks` and
  `react-hooks/exhaustive-deps`
- `eslint-plugin-react-refresh` for
  `react-refresh/only-export-components`
- `@eslint-react/eslint-plugin` (v5.18.0) for the
  four material React lint rules restored at error
  severity in the v2.0.6 closure. The exact mapping
  from the legacy `plugin:react/recommended` rules
  is recorded in the
  `RESTORED_REACT_RULE_MAPPING` constant exported
  from `eslint.config.js`; the rules it documents
  are:
  - `react/jsx-key` ->
    `@eslint-react/no-missing-key` +
    `@eslint-react/no-duplicate-key`
  - `react/jsx-no-target-blank` ->
    `@eslint-react/dom-no-unsafe-target-blank`
  - `react/no-danger-with-children` ->
    `@eslint-react/dom-no-dangerously-set-innerhtml-with-children`
  - `react/no-unknown-property` ->
    `@eslint-react/dom-no-unknown-property`

The remaining 15 `plugin:react/recommended` rules are
documented in the `UNCOVERED_LEGACY_REACT_RULES`
constant exported from `eslint.config.js` for
traceability. They are intentionally out of scope
for the v2.0.6 closure; a follow-up cycle may opt in
to additional rules.

The configuration runs with `--max-warnings 0` via
`package.json` (`"lint": "eslint . --max-warnings 0"`).
Any warning or error fails the lint step.

## Environment

The frontend reads:

| Variable              | Default     | Purpose                              |
| --------------------- | ----------- | ------------------------------------ |
| `VITE_API_BASE_URL`   | `/api/v1`   | API prefix; overridden in deployments |
| `VITE_API_TIMEOUT_MS` | `30000`     | Per-request timeout in ms            |
| `VITE_DEV_FIXTURES`   | unset       | Set to exactly `enabled` to use dev fixtures |

`VITE_API_BASE_URL` is the only required value. The
frontend works out-of-the-box behind a same-origin
reverse proxy that serves `/api/v1/*`. For local
development you can set
`VITE_API_BASE_URL=http://localhost:8000/api/v1`.

### Development fixture boundary

`VITE_DEV_FIXTURES` is read by `readDevFixturesEnabled()`
in `src/api/client.ts`. Fixtures activate only when the
value is **exactly** the string `enabled` (case-
sensitive). Any other value (including an empty string,
a typo, or unset) leaves the client pointed at the real
API. The frontend never falls back to fixtures because of
an API failure.

## Design principles

- Professional security-product appearance. No hacker-
  terminal theme, no neon overload, no fake data.
- No universal security score. Every finding stands on
  its own evidence.
- Severity and confidence are independent dimensions.
  A critical-severity finding may still have low
  confidence; the UI surfaces both.
- Unknown must not appear healthy. Missing severity,
  missing provider data, and missing dependency data are
  all rendered as `unknown` or "not available" - never
  as clean.
- Status is never colour-only. Every badge carries the
  status word in text. Every severity / confidence
  badge has an `aria-label` for screen readers.
- No production fixture fallback. The fixture flag is
  the only way to opt in, and it is off by default.

## Accessibility

- Visible focus state on every interactive element
  (`:focus-visible` in `index.css`).
- Skip-to-main-content link as the first focusable
  element.
- Semantic tables with `<caption>` and `<th scope="col">`
  for every list. Lists degrade to a card view on small
  screens via `ResponsiveTable`.
- `aria-live` is used for status, alerts, and
  asynchronous fetch states.
- Dialogs (`ConfirmationDialog`, `DetailsDrawer`) trap
  focus and support `Escape` to close.
- Mobile navigation uses a hamburger button with
  `aria-expanded` and an `aria-label` that reflects the
  next action.
- Text-zoom: every layout uses flex / grid and never
  sets a fixed pixel height on text containers, so the
  page is usable at 200% browser zoom.
- Reduced-motion: the global stylesheet disables all
  non-essential animation and transition when
  `prefers-reduced-motion: reduce` is set.

## API contract assumptions

The frontend depends on the documented backend routes
under `/api/v1`. It is forward-compatible with the
v0.3-v0.6 endpoints that have not yet shipped: when a
backend endpoint returns a not-implemented status
(404 / 405 / 501), the page renders an honest "not yet
available" empty state and continues to work for the
endpoints that do exist.

The frontend depends on these endpoints to be present
(documented in `docs/architecture.md` and the per-
endpoint OpenAPI summaries).

The error envelope is the same one documented in
`docs/architecture.md`: `{ "error": { "code", "message",
"details?", "request_id?" } }` with stable codes such as
`not_found`, `validation_error`, `rate_limited`,
`provider_unavailable`, `internal`.

## Security boundary

- The frontend never embeds credentials. `apiClient`
  uses `credentials: "omit"` on every call. No
  `Authorization` header is ever set.
- The frontend never executes uploaded archive content
  or repository code.
- `evidence_json` is rendered as text inside a `<pre>`.
  It is never parsed as HTML.
- All repository URLs are validated in the browser
  before submission. The backend still validates, but
  the client-side check reduces the surface for
  accidental leaks.
- The export download uses an in-memory `Blob` and an
  `URL.createObjectURL` / `revokeObjectURL` pair. The
  bytes never leave the browser session.

## Frontend tests

Run `npm test`. The test suite covers:

- API client: error envelope, abort / timeout
  categorisation, credential suppression, query
  stripping.
- Utility helpers: time formatting, label mapping.
- Components: badge tone mapping, drawer focus /
  escape, confirmation dialog, filter bar, pagination,
  skeleton, notification roles, page header, scan
  timeline.
- Layout: app shell routing smoke tests.

End-to-end browser tests are not included. The unit
and component tests are the agreed verification
surface for this milestone.
