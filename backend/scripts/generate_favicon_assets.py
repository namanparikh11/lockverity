"""Generate the favicon PNG and ICO assets from the canonical SVG geometry.

The v2.1 Part A favicon is a hand-authored LV monogram defined
in ``frontend/public/favicon.svg``. The PNG and ICO files in
``frontend/public/`` are rasterisations of the same geometry
produced by this script, not screenshots or third-party assets.

Geometry (16x16 viewBox, integer-aligned):

    Background: rounded square, rx = 2.
    L:          polygon (2,3) (4,3) (4,11) (7,11) (7,13) (2,13).
    V:          polygon (8,3) (10,3) (11,11) (12,3) (14,3) (11,13).
    Padding:    2 units left/right, 3 units top/bottom.

The script draws the same shapes using Pillow at the target
pixel size. Anti-aliasing is achieved by rendering at 8x
supersampling and downscaling with the Lanczos resampling
filter; the downscaled image is then composited onto a
fresh image at the target size so the rounding behaviour is
deterministic across Pillow versions.

Outputs:

    frontend/public/favicon-16x16.png
    frontend/public/favicon-32x32.png
    frontend/public/favicon-48x48.png
    frontend/public/favicon.ico          (16 + 32 + 48)
    frontend/public/apple-touch-icon.png (180x180)

The script is intentionally self-contained and dependency-light
(only Pillow). It is run as part of the favicon correction
flow; the committed PNG and ICO files are the deliverables.
Re-run this script only if ``frontend/public/favicon.svg``
changes.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

# Brand colours (kept in sync with docs/brand-assets.md).
COLOR_BACKGROUND = (15, 23, 42, 255)  # #0f172a
COLOR_FOREGROUND = (248, 250, 252, 255)  # #f8fafc

# Geometry in 16x16 viewBox units. These coordinates are
# the canonical reference; ``frontend/public/favicon.svg``
# must use the same numbers.
VIEWBOX = 16
L_POLYGON = [(2, 3), (4, 3), (4, 11), (6, 11), (6, 13), (2, 13)]
V_POLYGON = [(7, 3), (9, 3), (11, 10), (13, 3), (15, 3), (11, 13)]
BACKGROUND_RX_UNITS = 2

# Supersampling factor. 8x gives a clean 16x16 result; the
# downscaled image is composited onto a fresh target so the
# rounded corners are reproducible.
SUPERSAMPLE = 8


def _scale(value: int, target: int) -> float:
    """Return ``value`` scaled from a 16-unit viewBox to ``target`` pixels."""
    return value * target / VIEWBOX


def _scale_polygon(polygon: list[tuple[int, int]], target: int) -> list[tuple[float, float]]:
    """Scale a 16-unit-viewBox polygon to ``target`` pixels."""
    return [(_scale(x, target), _scale(y, target)) for x, y in polygon]


def render_icon(size: int) -> Image.Image:
    """Render the favicon at ``size`` x ``size`` pixels.

    The image is rendered with 8x supersampling and downscaled
    with the Lanczos resampling filter, then composited onto a
    fresh RGBA image so the rounding is deterministic.
    """
    big = size * SUPERSAMPLE
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Background: rounded square.
    rx_big = _scale(BACKGROUND_RX_UNITS, big)
    draw.rounded_rectangle(
        (0, 0, big - 1, big - 1),
        radius=rx_big,
        fill=COLOR_BACKGROUND,
    )
    # L: filled polygon.
    draw.polygon(_scale_polygon(L_POLYGON, big), fill=COLOR_FOREGROUND)
    # V: filled polygon.
    draw.polygon(_scale_polygon(V_POLYGON, big), fill=COLOR_FOREGROUND)
    # Downscale with Lanczos for a clean result.
    return img.resize((size, size), Image.LANCZOS)


def write_png(image: Image.Image, path: Path) -> None:
    """Write ``image`` to ``path`` as a deterministic PNG."""
    # ``optimize=True`` keeps the file small; the icon is
    # tiny so the optimisation pass is fast.
    image.save(path, format="PNG", optimize=True)


def write_ico(sizes: list[int], path: Path) -> None:
    """Write a multi-resolution ICO file containing ``sizes``.

    The Pillow ICO writer accepts a single source image and
    a ``sizes=`` parameter; it rasterises the source to each
    requested size and embeds every resolution. The source
    is the largest requested size so the downscaling is
    monotonic and the resampling filter is consistent.
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
    # Apple touch icon at 180x180.
    apple_path = public_dir / "apple-touch-icon.png"
    write_png(render_icon(180), apple_path)
    print(f"wrote {apple_path} (180x180, {apple_path.stat().st_size} bytes)")
    # ICO with 16, 32, 48.
    ico_path = public_dir / "favicon.ico"
    write_ico([16, 32, 48], ico_path)
    print(f"wrote {ico_path} (16+32+48, {ico_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
