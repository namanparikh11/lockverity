"""Generate the v2.1 Part B3A executable icon (packaging derivative).

The approved ``frontend/public/favicon.ico`` is the
brand-board web favicon and contains only the
``16x16``, ``32x32`` and ``48x48`` entries the
browser needs. The Windows executable resource
*also* needs a ``256x256`` entry to render correctly
in the Windows shell at high DPI. The brand assets
themselves are not modified; the function generates
a packaging-only ICO file at
``backend/pyinstaller/favicon-exe.ico`` that
re-packages the existing ``16/32/48`` entries plus a
freshly-downscaled ``256x256`` entry sourced from
the approved ``frontend/public/favicon-source.png``
(``1024x1024``).

The function is the single chokepoint for the
mechanical ICO construction so a future maintainer can
audit the conversion without re-deriving the math.

The conversion is documented in
``docs/windows-portable.md`` and is exercised by
``tests/test_exe_icon.py``.
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


def _png_to_png_ico_entry(png_bytes: bytes, target_size: int) -> tuple[int, int, bytes]:
    """Return a ``(width, height, raw_bytes)`` ICO entry for a PNG payload.

    Windows accepts PNG-compressed entries directly
    in ICO files since Vista; the raw payload is the
    PNG itself and the ICO reader decodes it. The
    Pillow ``Image`` resize uses Lanczos for a
    high-quality downscale of the approved source.
    """
    from PIL import Image  # type: ignore[import-not-found]

    with Image.open(io.BytesIO(png_bytes)) as source:
        source.load()
        # The approved source is 1024x1024 RGBA. A
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


def build_exe_icon(
    *,
    approved_ico: Path = APPROVED_ICO,
    approved_png: Path = APPROVED_PNG,
    derivative_ico: Path = DERIVATIVE_ICO,
) -> Path:
    """Build ``derivative_ico`` from the approved sources.

    The function is the documented entry point. It
    reads the approved web favicon (16/32/48), reads
    the approved 1024x1024 PNG, downscales the PNG
    to 256x256, and writes a single ICO file that
    contains all four entries.

    The function is intentionally narrow: it does
    not draw, recolor, or reinterpret the brand; the
    256x256 entry is a Lanczos downscale of the
    approved source pixels.
    """
    if not approved_ico.is_file():
        raise FileNotFoundError(f"approved ICO not found: {approved_ico}")
    if not approved_png.is_file():
        raise FileNotFoundError(f"approved PNG source not found: {approved_png}")
    original_entries = _parse_ico(approved_ico.read_bytes())
    small_entries = [(w, h, raw) for (w, h, raw) in original_entries if w < 256]
    if not small_entries:
        raise ValueError(f"approved ICO {approved_ico} has no < 256 entries; refusing to overwrite")
    png_bytes = approved_png.read_bytes()
    large_entry = _png_to_png_ico_entry(png_bytes, 256)
    all_entries = [*small_entries, large_entry]
    ico_bytes = _build_ico(all_entries)
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
    args = parser.parse_args(argv)
    written = build_exe_icon(
        approved_ico=args.approved_ico,
        approved_png=args.approved_png,
        derivative_ico=args.derivative_ico,
    )
    sys.stderr.write(f"wrote {written} ({written.stat().st_size} bytes)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
