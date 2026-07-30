# Design tokens

This document is the canonical reference for the design
tokens the Lockverity frontend ships with. A design token is
a named, documented value that appears in more than one
surface; this file is the single source of truth so a colour
or spacing change can be made in one place.

The tokens below are derived from the Tailwind theme
configuration in ``frontend/tailwind.config.*`` and the
component classes in ``frontend/src/index.css``. They are
documented here so designers, contributors, and reviewers
can reason about the visual language without reading the
build output.

## Colour

Lockverity uses a calm, low-saturation palette. Green,
amber, and red are reserved for **status** semantics; the
product does not use them as brand or decorative colours.

### Ink scale (neutrals)

The ink scale is used for surfaces, text, borders, and
shadows. The hex codes match the brand design board's
section 03 palette exactly.

| Token | Value | Use |
| ----- | ----- | --- |
| ``ink-50`` | ``#f8fafc`` | Page background. |
| ``ink-100`` | ``#f1f5f9`` | Subtle surface, hover. |
| ``ink-200`` | ``#e2e8f0`` | Border, divider, card edge. |
| ``ink-400`` | ``#94a3b8`` | Muted icon. |
| ``ink-500`` | ``#64748b`` | Muted text, label, caption. |
| ``ink-700`` | ``#334155`` | Body text, primary content. |
| ``ink-800`` | ``#1e293b`` | Headline, important body. |
| ``ink-900`` | ``#0f172a`` | Strongest text. |

### Indigo (background)

The Indigo scale is the brand background palette. The
favicon / app-icon background uses Indigo 900 from the
brand board (``#0B1324``); the UI surfaces use the ink
scale above for ergonomic contrast.

| Token | Value | Use |
| ----- | ----- | --- |
| ``indigo-900`` | ``#0B1324`` | Brand app-icon background. |

### Accent (interaction)

The accent colour is used for interactive surfaces: links,
the primary action button, and focus rings. It is not used
for status.

| Token | Value | Use |
| ----- | ----- | --- |
| ``accent-50`` | ``#eff6ff`` | Active row background. |
| ``accent-500`` | ``#3b82f6`` | Focus ring. |
| ``accent-600`` | ``#2563eb`` | Link, primary button background. |
| ``accent-700`` | ``#1d4ed8`` | Link hover, primary button hover text. |
| ``accent-800`` | ``#1e40af`` | Active navigation text. |

### Brand gradient (mark and symbol)

The brand mark and the standalone product symbol use a
vertical blue-to-teal gradient. The hex codes match the
brand design board's section 03 palette exactly. The
gradient runs from Blue 600 at the top of the mark to
Teal 500 at the bottom.

| Token | Value | Use |
| ----- | ----- | --- |
| ``blue-600`` | ``#2563eb`` | Gradient start (top of the mark). |
| ``teal-500`` | ``#14b8a6`` | Gradient end (bottom of the mark). |

### Status (semantic)

Status colours are reserved for finding and scan status,
never for branding or decoration.

| Token | Value | Use |
| ----- | ----- | --- |
| ``status-success`` | ``#16a34a`` | Completed scan, resolved finding. |
| ``status-warn`` | ``#d97706`` | Partial scan, informational finding. |
| ``status-danger`` | ``#dc2626`` | Failed scan, critical finding. |
| ``status-info`` | ``#0284c7`` | Coverage note, advisory. |

## Typography

The product uses the system font stack so it renders
without a web-font download. The system stack is
documented in the Tailwind theme.

- **Sans** (UI): system-ui, -apple-system,
  ``Segoe UI``, Roboto, Helvetica, Arial, sans-serif.
- **Mono** (identifiers, hashes, paths, PURLs):
  ``ui-monospace``, ``SFMono-Regular``, Menlo, Consolas,
  monospace.

### Scale

| Token | Size | Line height | Use |
| ----- | ---- | ----------- | --- |
| ``text-xs`` | 12 px | 16 px | Caption, label, badge. |
| ``text-sm`` | 14 px | 20 px | Body, form control, table cell. |
| ``text-base`` | 16 px | 24 px | Long-form body. |
| ``text-lg`` | 18 px | 28 px | Section heading. |
| ``text-xl`` | 20 px | 28 px | Page sub-heading. |
| ``text-2xl`` | 24 px | 32 px | Page heading. |

## Spacing

The product uses Tailwind's default 4 px scale. The
components in ``index.css`` (``card``, ``btn``, ``input``,
``label``, ``table-row``, ``table-cell``, ``table-head``)
re-export a subset of the scale so the visual language is
consistent across the application.

| Token | Value | Use |
| ----- | ----- | --- |
| ``space-1`` | 4 px | Tight gap (icon and label). |
| ``space-2`` | 8 px | Inline gap (label and control). |
| ``space-3`` | 12 px | Card padding, table cell padding. |
| ``space-4`` | 16 px | Section padding, page block gap. |
| ``space-6`` | 24 px | Page section gap. |
| ``space-8`` | 32 px | Hero gap, page bottom margin. |

## Focus

The base layer in ``index.css`` sets a visible focus ring
on every focusable element:

- ring: ``2px`` solid ``accent-500``;
- offset: ``2px``;
- radius: ``border-radius.sm``.

This is a hard requirement, not a default. Keyboard users
must always see a visible focus indicator. The
``prefers-reduced-motion`` media query in ``index.css``
suppresses transitions and animations but does not
suppress the focus ring.

## Motion

The product does not use decorative animation. The only
transitions in the product are the standard browser
defaults (form control hover, link colour, focus ring)
and the Tailwind default transition utilities. The
``prefers-reduced-motion: reduce`` media query in
``index.css`` collapses all transitions to 0.001 ms so
the product respects the user's system setting.

## What not to do

- Do not use status colours for brand or decoration.
- Do not introduce a new colour outside the documented
  scale without updating this document.
- Do not use a custom font outside the documented stack.
- Do not use neon effects, excessive gradients, hacker
  imagery, or decorative animation.
- Do not remove the focus ring. Keyboard accessibility is a
  hard requirement.
- Do not redraw, trace, or reinterpret the brand mark or
  the standalone product symbol. The source PNGs in
  ``frontend/public/`` are the single source of truth.
