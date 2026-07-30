# Brand assets

This document is the canonical reference for the Lockverity
brand assets. It is the single source of truth for what the
mark looks like, who owns it, where it is used, and how it
should not be reused.

## Originality and ownership

The v2.1 mark is **hand-authored vector geometry**. It is
not generated from a raster concept, not traced from a
photograph, and not derived from any third-party logo
asset. The geometry is a 100x100 viewBox SVG with two
stroked paths:

- an L (vertical bar plus horizontal foot) that runs from
  ``(22, 16)`` to ``(22, 78)`` to ``(56, 78)``;
- a V (left arm, apex, right arm) that runs from
  ``(40, 16)`` to ``(56, 78)`` to ``(78, 16)``.

The two paths meet at ``(56, 78)`` and together read as an
interlocking L and V that suggests an evidence or chain
link. The stroke is 12 units wide, round-capped, and
round-joined.

Lockverity is an **unregistered open-source brand**. No
trademark registration has been filed and no claim of
trademark registration is made in this repository. The
mark is released under the same licence as the rest of the
project. If you re-use the mark, you must comply with the
project licence; the mark is not a registered trademark
and confers no legal rights on the project or on you.

## Asset inventory

| Variant | Path | Use |
| ------- | ---- | --- |
| Primary mark | ``frontend/public/brand/lockverity-mark.svg`` | Inline use. Foreground uses ``currentColor`` so the mark inherits the surrounding text colour. |
| Monochrome mark, dark | ``frontend/public/brand/lockverity-mark-mono-dark.svg`` | Light surface. Fixed dark stroke. |
| Monochrome mark, light | ``frontend/public/brand/lockverity-mark-mono-light.svg`` | Dark surface. Fixed light stroke. |
| Application icon | ``frontend/public/brand/lockverity-app-icon.svg`` | Rounded-square application icon (192x192 CSS pixels, 1024x1024 PNG). |
| Simplified favicon | ``frontend/public/favicon.svg`` | 16x16, 24x24, 32x32 favicon slots. |
| Apple touch icon | ``frontend/public/apple-touch-icon.svg`` | iOS app-icon convention. Source SVG; the packaging step rasterises it to the required PNG resolutions. |

The same geometry is mirrored in the
``frontend/src/components/BrandMark.tsx`` React component
so the AppShell header, sidebar footer, and About hero
share a single source of truth. The React component is
preferred for any in-page use; the SVG files are the
canonical source for the raster pipeline and for any
downstream packaging (installers, OS bundles, container
metadata).

## Sizing

The mark is hand-tuned to be legible at:

- 16 pixels (favicon slot, browser tab);
- 24 pixels (browser tab on high-DPI displays);
- 32 pixels (Windows taskbar pin, PWA install icon);
- 48 pixels (Apple touch icon small);
- 128 pixels (PWA install icon large);
- 256 pixels (OS application icon).

The favicon variant drops the L and keeps the V because the
L+V legibility collapses below 24 pixels on a typical
tab strip. The V carries the brand identity on its own at
small sizes; the L is recovered as soon as there is enough
pixel density to render it.

## Colour palette

- Deep ink (mark background, dark theme accent): ``#0f172a``
- Light foreground (mark stroke on dark surface, document
  text on light surface): ``#f8fafc``
- These two values are the canonical brand colours.
  Application surfaces that need a brand mark should use
  ``#0f172a`` as the background and ``#f8fafc`` as the
  foreground.

The rest of the product palette (accent, status, ink
scale) lives in ``docs/design-tokens.md``.

## What not to do

- Do not trace the mark from a raster image.
- Do not regenerate the geometry with a generative model
  and present the result as the canonical mark.
- Do not use a third-party logo asset as a substitute.
- Do not animate the mark. It is inert: no transitions, no
  transforms, no decorative motion.
- Do not recolour the mark outside the documented palette.
- Do not claim the mark is a registered trademark. It is
  not.
