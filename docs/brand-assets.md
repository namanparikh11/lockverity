# Brand assets

This document is the canonical reference for the Lockverity
brand assets. The v2.1 release is the first version where
the assets are derived from a single approved source: the
exact raster extractions of the brand design board
supplied as three PNGs. No asset is redrawn, traced, or
reinterpreted; every compatibility file is produced by
``backend/scripts/generate_favicon_assets.py``.

## Source files (single source of truth)

| Role | Path | Use |
| --- | --- | --- |
| Favicon / app icon | ``frontend/public/favicon-source.png`` | The approved "Rounded App Icon" from section 02 of the brand design board. The source of truth for every favicon and app-icon derivative. |
| Standalone product symbol | ``frontend/public/brand/lockverity-symbol.png`` | The approved primary symbol from section 01. Used in the AppShell header, sidebar footer, and About hero where a larger brand symbol is required. |
| Horizontal logo lockup | ``frontend/public/brand/lockverity-horizontal-logo.png`` | The approved primary symbol, Lockverity wordmark, and "EVIDENCE. INTEGRITY. ASSURANCE." tagline. Used in marketing and header surfaces where the full horizontal brand lockup is appropriate. |

The three source files are never derived from each other
and the geometry is never re-drawn. The Pillow rasteriser
produces only the compatibility sizes listed below; it
never interprets or traces the source.

## Originality and ownership

The v2.1 mark and the v2.1 standalone product symbol are
exact raster extractions of the approved brand design
board. The source files are the single source of truth;
no derivative in the repository is a re-trace, a
re-interpretation, or a generative reconstruction of the
geometry.

Lockverity is an **unregistered open-source brand**. No
trademark registration has been filed and no claim of
trademark registration is made in this repository. The
mark and symbol are released under the same licence as
the rest of the project. If you re-use the mark, you must
comply with the project licence; the mark is not a
registered trademark and confers no legal rights on the
project or on you.

## Compatibility assets

The favicon and app-icon derivatives are produced by
``backend/scripts/generate_favicon_assets.py`` from
``frontend/public/favicon-source.png`` using Pillow's
Lanczos resampling. Transparency (alpha channel) and
aspect ratio are preserved at every size.

| File | Size | Source |
| --- | ---: | --- |
| ``frontend/public/favicon-16x16.png`` | 16x16 | derived |
| ``frontend/public/favicon-32x32.png`` | 32x32 | derived |
| ``frontend/public/favicon-48x48.png`` | 48x48 | derived |
| ``frontend/public/favicon-180x180.png`` | 180x180 | derived |
| ``frontend/public/favicon-256x256.png`` | 256x256 | derived |
| ``frontend/public/favicon-512x512.png`` | 512x512 | derived |
| ``frontend/public/favicon.ico`` | 16+32+48 | derived |
| ``frontend/public/apple-touch-icon.png`` | 180x180 | derived (iOS home-screen pin) |

## React component

The standalone product symbol is exposed to the React
tree via ``frontend/src/components/LockveritySymbol.tsx``.
The component renders the approved PNG via a plain
``<img>`` element; the source is the single source of
truth and the component never draws the geometry itself.

```tsx
<LockveritySymbol size={28} decorative ariaLabel="Lockverity" />
```

The component honours the source PNG's transparency,
preserves the aspect ratio, and supports ``decorative``
(hides the symbol from the accessibility tree when the
product name is rendered adjacent) and ``ariaLabel``
(announces the symbol when it is the only identity
element).

## Sizing

The source PNG is supplied at 1024x1024 so every
derivative is a downscaling, never an upscaling. The
favicon derivatives cover the standard web and OS app-icon
sizes:

- 16 pixels (favicon slot, browser tab)
- 32 pixels (browser tab on high-DPI displays)
- 48 pixels (Windows taskbar pin, PWA install icon)
- 180 pixels (iOS home-screen pin, ``apple-touch-icon``)
- 256 pixels (PWA install icon large)
- 512 pixels (OS application icon)

The ICO file embeds the 16, 32, and 48 pixel sizes in a
single multi-resolution container for legacy browsers and
taskbar pinning.

## Palette

The brand board's section 03 palette is the source of
truth. The hex codes in the board's legend are the
canonical values; the colour names follow the board's
naming convention.

- **Indigo 900**: ``#0B1324`` (background)
- **Indigo 700**: ``#1E293B``
- **Blue 600**: ``#2563EB`` (gradient start, top of the mark)
- **Teal 500**: ``#14B8A6`` (gradient end, bottom of the mark)
- **Slate 200**: ``#E2E8F0``
- **Slate 100**: ``#F1F5F9``
- **White**: ``#FFFFFF``

Status colours (used in the UI, not in the mark):

- Success: ``#16A34A``
- Warning: ``#F59E0B``
- Error:   ``#DC2626``
- Info:    ``#3B82F6``

The design tokens (colour, typography, spacing, focus,
motion) are documented in ``docs/design-tokens.md``.

## What not to do

- Do not trace or re-render the mark or the symbol. The
  source PNGs are the canonical reference; the React
  component renders them as ``<img>`` and the Pillow
  rasteriser scales them.
- Do not derive one asset from another (for example, do
  not create the standalone symbol from the favicon
  source, and do not create the horizontal logo by
  compositing the symbol with text). Each source file is
  the design board's own raster extraction and is used
  as-is.
- Do not introduce a new colour outside the documented
  palette.
- Do not recolour the mark or the symbol outside the
  documented gradient stops.
- Do not animate the mark or the symbol. The
  ``LockveritySymbol`` component is inert: no
  transitions, no transforms, no decorative motion.
- Do not claim the mark or the symbol is a registered
  trademark. Neither is registered.
