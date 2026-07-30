"""Generate the favicon PNG and ICO derivatives from the approved source PNG.

The v2.1 favicon is the second "Rounded App Icon" from the brand
design board, supplied as ``frontend/public/favicon-source.png``.
This script is the canonical rasteriser: it derives every
compatibility asset from the source PNG using Pillow's Lanczos
resampling filter, with no redraw, trace, or reinterpretation.

Outputs (all derived only from the source PNG):

    frontend/public/favicon-16x16.png
    frontend/public/favicon-32x32.png
    frontend/public/favicon-48x48.png
    frontend/public/favicon-180x180.png
    frontend/public/favicon-256x256.png
    frontend/public/favicon-512x512.png
    frontend/public/favicon.ico          (16 + 32 + 48)
    frontend/public/apple-touch-icon.png (180x180, iOS pin)

The source PNG is the single source of truth and is never
re-derived from any other asset. The Pillow pipeline preserves
transparency (RGBA mode throughout) and aspect ratio
(Lanczos resampling, no crop). The output dimensions match
the standard web and OS app-icon sizes.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

# Canonical source: the approved "Rounded App Icon" from
# the brand design board. The source is committed to the
# repository so the script is reproducible from a clean
# checkout.
SOURCE_PNG = "favicon-source.png"

# Derivative targets: web favicon sizes, iOS app-icon size,
# and PWA / OS app-icon sizes.
PNG_SIZES = [
    (16, "favicon-16x16.png"),
    (32, "favicon-32x32.png"),
    (48, "favicon-48x48.png"),
    (180, "favicon-180x180.png"),
    (256, "favicon-256x256.png"),
    (512, "favicon-512x512.png"),
    (180, "apple-touch-icon.png"),  # iOS home-screen pin
]

# ICO entry sizes. The Pillow ICO writer picks the correct
# bit depth per size and embeds every entry.
ICO_SIZES = [16, 32, 48]


def render_size(source: Image.Image, size: int) -> Image.Image:
    """Return ``source`` resampled to ``size`` x ``size`` pixels.

    The source is resampled with the Lanczos filter, which
    preserves the anti-aliased edges of the original raster
    and avoids the blockiness of nearest-neighbour down-
    sampling. The output mode is RGBA so transparency is
    preserved.
    """
    if source.mode != "RGBA":
        source = source.convert("RGBA")
    return source.resize((size, size), Image.LANCZOS)


def write_png(image: Image.Image, path: Path) -> None:
    """Write ``image`` to ``path`` as a deterministic PNG."""
    image.save(path, format="PNG", optimize=True)


def write_ico(source: Image.Image, sizes: list[int], path: Path) -> None:
    """Write a multi-resolution ICO file containing ``sizes``.

    The Pillow ICO writer accepts a single source image and
    a ``sizes=`` parameter; it rasterises the source to each
    requested size and embeds every resolution. The source
    is the largest requested size so the downscaling is
    monotonic and the resampling filter is consistent.
    """
    source_for_ico = render_size(source, max(sizes))
    source_for_ico.save(
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
    source_path = public_dir / SOURCE_PNG
    if not source_path.is_file():
        print(
            f"ERROR: source PNG not found: {source_path}. "
            "The approved Rounded App Icon source must be "
            "committed to frontend/public/favicon-source.png "
            "before derivatives can be generated.",
            file=sys.stderr,
        )
        return 1
    with Image.open(source_path) as source_img:
        # Materialise the source into memory; the Pillow file
        # handle is a lazy view and would be closed below the
        # ``with`` block otherwise.
        source = source_img.copy()
    # The source is the single source of truth. Any pixel
    # value outside the rounded squircle is fully
    # transparent (alpha == 0) so the derivatives preserve
    # the transparency channel.
    print(
        f"source: {source_path} ({source.size[0]}x{source.size[1]}, "
        f"{source_path.stat().st_size} bytes, mode={source.mode})"
    )
    for size, filename in PNG_SIZES:
        path = public_dir / filename
        write_png(render_size(source, size), path)
        print(f"wrote {path} ({size}x{size}, {path.stat().st_size} bytes)")
    ico_path = public_dir / "favicon.ico"
    write_ico(source, ICO_SIZES, ico_path)
    print(
        f"wrote {ico_path} ({'+'.join(str(s) for s in ICO_SIZES)}, {ico_path.stat().st_size} bytes)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
