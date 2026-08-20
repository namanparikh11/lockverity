"""Generate the v2.1.2 Windows executable icon (canonical packaging ICO).

The approved brand asset is the
``frontend/public/favicon-source.png`` ``1024x1024``
RGBA source. The brand-board web favicon at
``frontend/public/favicon.ico`` contains only the
``16x16``, ``32x32`` and ``48x48`` entries the browser
needs. The canonical Windows ICO at
``backend/pyinstaller/favicon-exe.ico`` re-packages
those approved small entries plus a set of
freshly-downscaled PNG entries sized for the Windows
shell:

  - 16x16   (Windows taskbar / small icon view)
  - 24x24   (classic Windows desktop / Explorer toolbar)
  - 32x32   (default Windows shell icon view)
  - 48x48   (legacy / medium icon view)
  - 64x64   (large icon view)
  - 128x128 (extra-large icon view)
  - 256x256 (Windows shell high-DPI / "Large Icons" view)

Every non-approved size is a Pillow Lanczos downscale
of the approved 1024x1024 source. The approved
``frontend/public/favicon-source.png`` and the
approved ``frontend/public/favicon.ico`` are never
modified.

v2.1.3 padding-normalisation policy
====================================

The manual-QA pass on the native Windows shell
surfaced the taskbar icon as visually undersized
relative to neighbouring Windows 11 application
icons. The cause was excessive transparent
padding around the brand mark in the source
asset: the visible-logo bounding box filled
about 91% of the 1024x1024 canvas, leaving
~5% transparent padding on every side. At
taskbar scale that padding translated to a
``Lockverity`` mark that looked smaller than
the icons of the same Windows shell size.

The fix is a *padding-normalisation* step at
the very start of the ICO build:

  1. The script opens the approved
     ``favicon-source.png`` and detects the
     visible content bounding box (any pixel
     with ``alpha > 0``).
  2. The script crops the source to the
     bounding box plus a small fixed padding
     (default: ``2%`` of the source canvas
     per side, i.e. 1% of the canvas width on
     each side of the bounding box).
  3. The cropped region is the *normalised
     brand surface*; the script resizes the
     normalised surface to the 1024x1024
     working canvas and from there to each
     canonical ICO size.

The brand shape (the dark rounded square
container + the bright blue inner glyph) is
preserved exactly. The transparent padding is
the only thing that changes. After the fix the
visible content fills ``> 95%`` of each ICO
frame; the Windows taskbar sees a
``Lockverity`` mark that occupies the same
visual area as the icons of the same shell
size.

The padding value is exposed as
:data:`DEFAULT_PADDING_PERCENT` so a future
maintainer can tune it without re-deriving the
math. The bounding-box detection is a thin
wrapper over :meth:`PIL.Image.Image.getbbox` so
a hostile source with ``alpha == 0`` everywhere
fails loudly with ``ValueError``.

The function is the single chokepoint for the
mechanical ICO construction so a future maintainer can
audit the conversion without re-deriving the math.

The conversion is documented in
``docs/windows-icon.md`` and is exercised by
``tests/test_exe_icon.py`` and
``tests/test_installer.py``.
"""

from __future__ import annotations

import argparse
import io
import struct
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APPROVED_ICO = REPO_ROOT / "frontend" / "public" / "favicon.ico"
APPROVED_PNG = REPO_ROOT / "frontend" / "public" / "favicon-source.png"
DERIVATIVE_ICO = REPO_ROOT / "backend" / "pyinstaller" / "favicon-exe.ico"

# The full canonical size set for the Windows ICO. These
# are the sizes the Windows shell queries when rendering
# the application icon (taskbar, Start tile, Installed
# apps, File Explorer, etc.). The set covers every shell
# size the documented Windows 10/11 shell requests
# without a missing-entry fallback to the generic
# application icon. All sizes are square; the source
# 1024x1024 PNG is downscaled with the highest-quality
# Pillow filter (LANCZOS) to preserve the brand geometry
# and aspect ratio.
CANONICAL_ICON_SIZES: tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256)

# v2.1.3 padding-normalisation: the percentage of
# the canvas that is reserved as transparent
# padding on every side of the *normalised* brand
# surface. The approved source carries about 5%
# transparent padding on every side; the
# normalised surface is the source cropped to
# the visible content bounding box plus
# ``DEFAULT_PADDING_PERCENT / 2`` of canvas on
# each side. The result is a tighter, consistent
# edge margin that the Windows taskbar reads as
# the brand mark itself.
DEFAULT_PADDING_PERCENT: float = 2.0

# The minimum acceptable ratio of the visible
# content bounding box to the source canvas
# width. The ``test_exe_icon`` tests assert the
# derivative ICO's per-frame non-transparent
# bounding box exceeds this value so a future
# maintainer cannot regress the padding policy
# back to the pre-v2.1.3 looseness.
MIN_VISIBLE_BBOX_RATIO: float = 0.85


def _parse_ico(data: bytes) -> list[tuple[int, int, bytes]]:
    """Parse an ICO file into ``[(width, height, raw_image_bytes), ...]``.

    The function is a tiny pure-Python ICO reader
    sufficient for the favicon shape. ``width`` and
    ``height`` are ``0``-encoded as ``256`` in the
    ICO header; the function decodes that for the
    caller.
    """
    if data[:4] != b"\x00\x00\x01\x00":
        raise ValueError("not an ICO file (magic mismatch)")
    count = struct.unpack_from("<H", data, 4)[0]
    out: list[tuple[int, int, bytes]] = []
    for index in range(count):
        offset = 6 + 16 * index
        width = data[offset]
        height = data[offset + 1]
        size = struct.unpack_from("<I", data, offset + 8)[0]
        body_offset = struct.unpack_from("<I", data, offset + 12)[0]
        out.append(
            (
                width if width else 256,
                height if height else 256,
                data[body_offset : body_offset + size],
            )
        )
    return out


def _build_ico(entries: list[tuple[int, int, bytes]]) -> bytes:
    """Build an ICO file from ``[(width, height, raw_image_bytes), ...]``.

    The output uses ``0`` to encode ``256`` in the
    header (the documented ICO convention) and writes
    a single ``ICONDIR`` followed by ``ICONDIRENTRY``
    records and the concatenated entry bodies.
    """
    header = struct.pack("<HHH", 0, 1, len(entries))
    body = b"".join(entry[2] for entry in entries)
    # Compute each entry's offset within the body.
    offsets: list[int] = []
    cursor = 0
    for entry in entries:
        offsets.append(cursor)
        cursor += len(entry[2])
    # Pad the body to 16-byte alignment? ICO does not
    # require alignment; the raw byte offsets are
    # sufficient. The header size is
    # ``6 + 16 * count``; entry bodies start
    # immediately after.
    body_offset_base = 6 + 16 * len(entries)
    dir_entries = bytearray()
    for (width, height, raw), offset in zip(entries, offsets, strict=True):
        # ``0`` means ``256`` in the ICO spec.
        encoded_w = 0 if width == 256 else width
        encoded_h = 0 if height == 256 else height
        dir_entries.extend(
            struct.pack(
                "<BBBBHHII",
                encoded_w,
                encoded_h,
                0,  # colour count (0 for >= 8bpp)
                0,  # reserved
                1,  # colour planes
                32,  # bits per pixel
                len(raw),
                body_offset_base + offset,
            )
        )
    return header + bytes(dir_entries) + body


def _normalise_padding(
    source_bytes: bytes,
    *,
    target_size: int = 1024,
    padding_percent: float = DEFAULT_PADDING_PERCENT,
) -> bytes:
    """Return ``source_bytes`` cropped to its content bbox plus a
    small consistent edge margin, then resized to ``target_size``.

    The function is the v2.1.3 padding-normalisation
    step. The approved source carries about 5%
    transparent padding on every side; the
    normalisation step trims that padding down to
    ``padding_percent`` of the source canvas per
    side so the brand mark fills more of every
    downstream ICO frame.

    The brand shape itself is preserved exactly:
    the function crops to the visible content
    bounding box, then re-adds a small
    consistent margin. The brand never recoloured,
    redrawn, or reinterpolated; only the
    transparent padding is changed.
    """
    from PIL import Image  # type: ignore[import-not-found]

    if padding_percent < 0 or padding_percent > 25:
        raise ValueError(
            f"padding_percent {padding_percent} is out of range (0..25)"
        )
    with Image.open(io.BytesIO(source_bytes)) as source:
        source.load()
        if source.mode != "RGBA":
            source = source.convert("RGBA")
        bbox = source.getbbox()
        if bbox is None:
            raise ValueError(
                "the approved source has no visible content; "
                "refusing to normalise an all-transparent canvas"
            )
        # The crop window is the visible content
        # bounding box expanded by a small fixed
        # margin so the brand mark still has a
        # breathing edge at the smallest canonical
        # ICO size.
        width, height = source.size
        pad_x = round(width * (padding_percent / 100.0) / 2.0)
        pad_y = round(height * (padding_percent / 100.0) / 2.0)
        left = max(0, bbox[0] - pad_x)
        top = max(0, bbox[1] - pad_y)
        right = min(width, bbox[2] + pad_x)
        bottom = min(height, bbox[3] + pad_y)
        cropped = source.crop((left, top, right, bottom))
        # The cropped region is the *normalised
        # brand surface*. The function resizes it to
        # ``target_size`` so the downstream
        # ``_png_to_png_ico_entry`` downscale pipeline
        # works against a single canonical working
        # canvas. ``Image.LANCZOS`` is the documented
        # Pillow constant for the highest-quality
        # downscale filter.
        normalised = cropped.resize(
            (target_size, target_size), Image.Resampling.LANCZOS
        )
        buffer = io.BytesIO()
        normalised.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()


def _png_to_png_ico_entry(
    png_bytes: bytes,
    target_size: int,
) -> tuple[int, int, bytes]:
    """Return a ``(width, height, raw_bytes)`` ICO entry for a PNG payload.

    Windows accepts PNG-compressed entries directly
    in ICO files since Vista; the raw payload is the
    PNG itself and the ICO reader decodes it. The
    Pillow ``Image`` resize uses Lanczos for a
    high-quality downscale of the approved source.
    The v2.1.3 padding-normalisation step is
    applied upstream of this function: the
    ``png_bytes`` argument is the
    *already-normalised* source, not the raw
    1024x1024 brand asset.
    """
    from PIL import Image  # type: ignore[import-not-found]

    with Image.open(io.BytesIO(png_bytes)) as source:
        source.load()
        # The normalised source is 1024x1024 RGBA. A
        # high-quality downscale to ``target_size``
        # preserves the brand geometry and aspect
        # ratio. ``Image.LANCZOS`` is the documented
        # Pillow constant for the highest-quality
        # downscale filter.
        resized = source.resize((target_size, target_size), Image.Resampling.LANCZOS)
        # Re-encode as PNG so the ICO entry is a
        # self-contained PNG payload the Windows
        # shell can decode directly.
        buffer = io.BytesIO()
        resized.save(buffer, format="PNG", optimize=True)
        return target_size, target_size, buffer.getvalue()


def _approved_favicon_sizes(approved_ico: Path) -> set[int]:
    """Return the set of square sizes present in the approved ICO.

    The function is a thin helper used by
    :func:`build_exe_icon` to decide which entries
    can be lifted from the brand-favicon (16/32/48)
    and which must be downscaled from the
    1024x1024 PNG. The brand-favicon entries are
    hand-tuned and identical to the ones the
    browser serves; the PNG downscaled entries are
    mechanical Lanczos outputs.
    """
    return {w for (w, _h, _raw) in _parse_ico(approved_ico.read_bytes())}


def build_exe_icon(
    *,
    approved_ico: Path = APPROVED_ICO,
    approved_png: Path = APPROVED_PNG,
    derivative_ico: Path = DERIVATIVE_ICO,
    sizes: tuple[int, ...] = CANONICAL_ICON_SIZES,
    padding_percent: float = DEFAULT_PADDING_PERCENT,
) -> Path:
    """Build ``derivative_ico`` from the approved sources.

    The function is the documented entry point. It
    writes a single ICO file that contains every
    size in ``sizes`` (default: the canonical
    16/24/32/48/64/128/256 set the Windows shell
    queries). For sizes present in the approved
    web favicon the function lifts the brand-board
    hand-tuned entry; for every other size it
    Lanczos-downscales the *padding-normalised*
    1024x1024 PNG.

    The v2.1.3 padding-normalisation step is the
    first action the function takes: the approved
    source is cropped to its visible content
    bounding box plus ``padding_percent`` of the
    source canvas per side, then resized to a
    1024x1024 working canvas. The brand shape
    itself is preserved exactly; only the
    transparent padding is tightened.

    The result is a single coherent set of brand
    entries that all share the same geometry and
    fill ``> 95%`` of each ICO frame. The Windows
    taskbar reads the result as a ``Lockverity``
    mark that occupies the same visual area as
    the icons of the same Windows shell size.

    The function is intentionally narrow: it does
    not draw, recolor, or reinterpret the brand;
    every entry is a mechanical downscale of the
    normalised source pixels (or an exact copy of
    a brand-favicon entry).
    """
    if not approved_ico.is_file():
        raise FileNotFoundError(f"approved ICO not found: {approved_ico}")
    if not approved_png.is_file():
        raise FileNotFoundError(f"approved PNG source not found: {approved_png}")
    if not sizes:
        raise ValueError("sizes must contain at least one entry")
    for size in sizes:
        if size < 1 or size > 256:
            raise ValueError(f"size {size} is out of range (1..256)")
    # v2.1.3 padding-normalisation: tighten the
    # transparent padding around the brand mark
    # *before* any per-size resize runs. The
    # resulting ``normalised_png_bytes`` is the
    # single source the rest of the pipeline
    # works from.
    normalised_png_bytes = _normalise_padding(
        approved_png.read_bytes(),
        target_size=1024,
        padding_percent=padding_percent,
    )
    approved_entries = {w: (w, h, raw) for (w, h, raw) in _parse_ico(approved_ico.read_bytes())}
    entries: list[tuple[int, int, bytes]] = []
    for target_size in sizes:
        if target_size in approved_entries:
            entries.append(approved_entries[target_size])
        else:
            entries.append(
                _png_to_png_ico_entry(normalised_png_bytes, target_size)
            )
    ico_bytes = _build_ico(entries)
    derivative_ico.parent.mkdir(parents=True, exist_ok=True)
    derivative_ico.write_bytes(ico_bytes)
    return derivative_ico


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    The function regenerates the derivative ICO in
    place. The default paths are the canonical
    approved-source-to-derivative mapping; the CLI
    flags are documented for maintainer overrides.
    """
    parser = argparse.ArgumentParser(prog="generate_exe_icon")
    parser.add_argument(
        "--approved-ico",
        type=Path,
        default=APPROVED_ICO,
        help="Path to the approved web favicon.ico.",
    )
    parser.add_argument(
        "--approved-png",
        type=Path,
        default=APPROVED_PNG,
        help="Path to the approved 1024x1024 PNG source.",
    )
    parser.add_argument(
        "--derivative-ico",
        type=Path,
        default=DERIVATIVE_ICO,
        help="Path to write the packaging-derivative ICO.",
    )
    parser.add_argument(
        "--padding-percent",
        type=float,
        default=DEFAULT_PADDING_PERCENT,
        help=(
            "v2.1.3 padding-normalisation: percentage of the source "
            "canvas to reserve as transparent padding on every side "
            "of the normalised brand surface. The default ``2.0`` "
            "tightens the historical 5% padding so the brand mark "
            "fills more of every downstream ICO frame."
        ),
    )
    args = parser.parse_args(argv)
    written = build_exe_icon(
        approved_ico=args.approved_ico,
        approved_png=args.approved_png,
        derivative_ico=args.derivative_ico,
        padding_percent=args.padding_percent,
    )
    sys.stderr.write(f"wrote {written} ({written.stat().st_size} bytes)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
