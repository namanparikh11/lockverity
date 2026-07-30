"""Generate the favicon PNG and ICO assets from the canonical SVG geometry.

The v2.1 Part A favicon is the Rounded App Icon variant from
the brand design board, defined in
``frontend/public/favicon.svg``. The PNG and ICO files in
``frontend/public/`` are rasterisations of the same geometry
produced by this script, not screenshots or third-party
assets.

Geometry (16x16 viewBox, integer-aligned):

    Background: rounded square, rx = 3.5 (~22% of side),
                fill = #0B1324 (Indigo 900).
    Mark:       two cubic Bezier curves forming an
                interlocking chain-link pattern:
                  Curve 1: M 4 4 C 4 8, 12 8, 12 12
                  Curve 2: M 12 4 C 12 8, 4 8, 4 12
                Both curves are 2 units thick with round
                caps and a vertical gradient from #2E8BF0
                (Teal 500, top) to #14B8A6 (Blue 600,
                bottom).

The Pillow rasterisation pipeline:

  1. Build a vertical gradient strip (1px wide, full height).
  2. Build a binary mask: white where the curves are,
     transparent elsewhere. The mask is drawn at 8x
     supersampling with round caps (circles at each
     endpoint plus polyline segments).
  3. Composite the gradient onto the mask, then alpha-
     composite the result onto the rounded-square
     background.
  4. Downscale with the Lanczos resampling filter to the
     target size.

The script is intentionally self-contained and dependency-
light (only Pillow). The ``gradient_color`` helper applies
the same colour-stop interpolation the SVG linearGradient
defines, so the rasterised output is faithful to the
vector at every target size.

Outputs:

    frontend/public/favicon-16x16.png
    frontend/public/favicon-32x32.png
    frontend/public/favicon-48x48.png
    frontend/public/favicon.ico          (16 + 32 + 48)
    frontend/public/apple-touch-icon.png (180x180)
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

# Brand colours (matching the reference design board, section
# 03 PALETTE; documented in docs/brand-assets.md).
COLOR_BACKGROUND = (11, 19, 36, 255)  # #0B1324 Indigo 900
COLOR_GRADIENT_TOP = (46, 139, 240, 255)  # #2E8BF0 Teal 500
COLOR_GRADIENT_BOTTOM = (20, 184, 166, 255)  # #14B8A6 Blue 600

# Geometry in 16x16 viewBox units. These coordinates are
# the canonical reference; ``frontend/public/favicon.svg``
# must use the same numbers.
VIEWBOX = 16
BACKGROUND_RX_UNITS = 3.5
STROKE_WIDTH_UNITS = 2.0
MARK_INSET_UNITS = 4  # mark spans x/y = 4..12 in the viewBox

# Supersampling factor. 8x gives a clean 16x16 result; the
# downscaled image is composited onto a fresh target so the
# rounding is deterministic.
SUPERSAMPLE = 8

# Mark path: two cubic Bezier curves in 16-unit viewBox
# coordinates. (start, control1, control2, end).
CURVES = [
    ((4.0, 4.0), (4.0, 8.0), (12.0, 8.0), (12.0, 12.0)),
    ((12.0, 4.0), (12.0, 8.0), (4.0, 8.0), (4.0, 12.0)),
]


def _scale(value: float, target: int) -> float:
    """Return ``value`` scaled from a 16-unit viewBox to ``target`` pixels."""
    return value * target / VIEWBOX


def _scale_point(point: tuple[float, float], target: int) -> tuple[float, float]:
    """Scale a 16-unit-viewBox point to ``target`` pixels."""
    x, y = point
    return (_scale(x, target), _scale(y, target))


def _cubic_bezier(t: float, p0, p1, p2, p3) -> tuple[float, float]:
    """Evaluate a cubic Bezier curve at parameter ``t``."""
    u = 1.0 - t
    x = u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0]
    y = u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1]
    return x, y


def _bezier_points(p0, p1, p2, p3, n: int) -> list[tuple[float, float]]:
    """Return ``n + 1`` points along a cubic Bezier curve."""
    return [_cubic_bezier(i / n, p0, p1, p2, p3) for i in range(n + 1)]


def _interpolate_color(t: float, top, bottom) -> tuple[int, int, int, int]:
    """Linear-interpolate between two RGBA colours at parameter ``t``."""
    t = max(0.0, min(1.0, t))
    return tuple(round(top[i] + t * (bottom[i] - top[i])) for i in range(4))


def _build_gradient_strip(width: int, height: int) -> Image.Image:
    """Return a vertical gradient image (top to bottom) of the given size."""
    strip = Image.new("RGBA", (width, height))
    for y in range(height):
        t = y / max(1, height - 1)
        color = _interpolate_color(t, COLOR_GRADIENT_TOP, COLOR_GRADIENT_BOTTOM)
        for x in range(width):
            strip.putpixel((x, y), color)
    return strip


def _build_curve_mask(
    big: int,
    scale: float,
) -> Image.Image:
    """Return a binary mask image with the mark curves filled in.

    The mask is drawn at ``big`` resolution (the supersampled
    target). Each curve is a polyline of 64 segments with
    round caps rendered as filled circles at the start and
    end points.
    """
    mask = Image.new("L", (big, big), 0)
    draw = ImageDraw.Draw(mask)
    stroke_px = max(1, round(STROKE_WIDTH_UNITS * scale))
    for p0, p1, p2, p3 in CURVES:
        scaled = [_scale_point(pt, big) for pt in _bezier_points(p0, p1, p2, p3, n=64)]
        # Polyline segments.
        for i in range(len(scaled) - 1):
            draw.line(
                [scaled[i], scaled[i + 1]],
                fill=255,
                width=stroke_px,
            )
        # Rounded caps as filled circles at the endpoints.
        radius = stroke_px / 2.0
        for endpoint in (scaled[0], scaled[-1]):
            cx, cy = endpoint
            draw.ellipse(
                (cx - radius, cy - radius, cx + radius, cy + radius),
                fill=255,
            )
    return mask


def _build_background(big: int) -> Image.Image:
    """Return the rounded-square background at the given supersampled size."""
    bg = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(bg)
    rx_big = _scale(BACKGROUND_RX_UNITS, big)
    draw.rounded_rectangle(
        (0, 0, big - 1, big - 1),
        radius=rx_big,
        fill=COLOR_BACKGROUND,
    )
    return bg


def render_icon(size: int) -> Image.Image:
    """Render the favicon at ``size`` x ``size`` pixels.

    The image is rendered with 8x supersampling and downscaled
    with the Lanczos resampling filter. The gradient is
    applied per-pixel based on the y-coordinate, so the
    downscaled output is a faithful rasterisation of the SVG
    linear gradient at every target size.
    """
    big = size * SUPERSAMPLE
    background = _build_background(big)
    gradient = _build_gradient_strip(big, big)
    mask = _build_curve_mask(big, scale=big / VIEWBOX)
    # ``Image.composite`` replaces pixels where the mask is
    # white with the gradient and leaves the rest transparent.
    mark = Image.composite(gradient, Image.new("RGBA", (big, big), (0, 0, 0, 0)), mask)
    # Alpha-composite the mark onto the background, then
    # downscale with Lanczos for a clean result.
    return Image.alpha_composite(background, mark).resize((size, size), Image.LANCZOS)


def write_png(image: Image.Image, path: Path) -> None:
    """Write ``image`` to ``path`` as a deterministic PNG."""
    image.save(path, format="PNG", optimize=True)


def write_ico(sizes: list[int], path: Path) -> None:
    """Write a multi-resolution ICO file containing ``sizes``.

    The Pillow ICO writer accepts a single source image and
    a ``sizes=`` parameter; it rasterises the source to each
    requested size and embeds every resolution.
    """
    source = render_icon(max(sizes))
    source.save(
        path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
    )


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    public_dir = repo_root / "frontend" / "public"
    if not public_dir.is_dir():
        print(f"ERROR: public directory not found: {public_dir}", file=sys.stderr)
        return 1
    targets = [
        ("favicon-16x16.png", 16),
        ("favicon-32x32.png", 32),
        ("favicon-48x48.png", 48),
    ]
    for filename, size in targets:
        path = public_dir / filename
        write_png(render_icon(size), path)
        print(f"wrote {path} ({size}x{size}, {path.stat().st_size} bytes)")
    apple_path = public_dir / "apple-touch-icon.png"
    write_png(render_icon(180), apple_path)
    print(f"wrote {apple_path} (180x180, {apple_path.stat().st_size} bytes)")
    ico_path = public_dir / "favicon.ico"
    write_ico([16, 32, 48], ico_path)
    print(f"wrote {ico_path} (16+32+48, {ico_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
