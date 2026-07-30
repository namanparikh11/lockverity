"""Verify the generated favicon assets.

The v2.1 favicon is the approved "Rounded App Icon" from the
brand design board, supplied as a 1024x1024 PNG
(``frontend/public/favicon-source.png``). Every compatibility
asset is derived from the source by
``backend/scripts/generate_favicon_assets.py``. This script
verifies the source-of-truth chain.

Checks:

- The source PNG exists and is a transparent raster.
- The ICO file contains the expected sizes (16, 32, 48).
- The PNG derivatives exist at the expected pixel
  dimensions.
- The standalone symbol and horizontal logo brand assets
  exist.
- The HTML references in ``frontend/index.html`` match the
  produced files and carry a versioned cache-busting query.
- No ``favicon.svg`` is referenced (the v2.1 design is
  PNG-only).
"""

from __future__ import annotations

import re
import struct
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_DIR = REPO_ROOT / "frontend" / "public"
INDEX_HTML = REPO_ROOT / "frontend" / "index.html"

EXPECTED_ICO_SIZES = {16, 32, 48}
EXPECTED_PNG_FILES = {
    "favicon-16x16.png": 16,
    "favicon-32x32.png": 32,
    "favicon-48x48.png": 48,
    "favicon-180x180.png": 180,
    "favicon-256x256.png": 256,
    "favicon-512x512.png": 512,
    "apple-touch-icon.png": 180,
}
EXPECTED_BRAND_FILES = (
    "brand/lockverity-symbol.png",
    "brand/lockverity-horizontal-logo.png",
)
EXPECTED_INDEX_REFS = [
    "/favicon.ico",
    "/favicon-16x16.png",
    "/favicon-32x32.png",
    "/favicon-48x48.png",
    "/favicon-180x180.png",
    "/favicon-256x256.png",
    "/favicon-512x512.png",
    "/apple-touch-icon.png",
]


def check_png(path: Path, expected_size: int) -> str | None:
    if not path.is_file():
        return f"missing: {path}"
    try:
        from PIL import Image
    except ImportError:
        return "Pillow not available"
    with Image.open(path) as img:
        if img.size != (expected_size, expected_size):
            return (
                f"{path.name}: expected {expected_size}x{expected_size}, "
                f"got {img.size[0]}x{img.size[1]}"
            )
    return None


def check_source(path: Path) -> str | None:
    if not path.is_file():
        return f"missing source: {path}"
    try:
        from PIL import Image
    except ImportError:
        return "Pillow not available"
    with Image.open(path) as img:
        # The source must support transparency (the rounded
        # corners depend on the alpha channel).
        if img.mode != "RGBA":
            return f"{path.name}: source must be RGBA (got {img.mode})"
        if img.size != (1024, 1024):
            return f"{path.name}: source must be 1024x1024 (got {img.size[0]}x{img.size[1]})"
        # The four corners must be transparent.
        for x, y in [
            (0, 0),
            (img.width - 1, 0),
            (0, img.height - 1),
            (img.width - 1, img.height - 1),
        ]:
            _r, _g, _b, a = img.getpixel((x, y))
            if a > 50:
                return f"{path.name}: corner ({x},{y}) is not transparent (a={a})"
    return None


def check_ico(path: Path) -> str | None:
    if not path.is_file():
        return f"missing: {path}"
    with path.open("rb") as fh:
        header = fh.read(6)
        if len(header) < 6:
            return f"{path.name}: header too short"
        _reserved, ico_type, count = struct.unpack("<HHH", header)
        if ico_type != 1:
            return f"{path.name}: not an ICO (type={ico_type})"
        if count < len(EXPECTED_ICO_SIZES):
            return f"{path.name}: expected at least {len(EXPECTED_ICO_SIZES)} sizes, got {count}"
        found = set()
        for _ in range(count):
            data = fh.read(16)
            if len(data) < 16:
                return f"{path.name}: truncated directory entry"
            w, h = data[0], data[1]
            if w == 0:
                w = 256
            if h == 0:
                h = 256
            found.add((w, h))
    missing = {(s, s) for s in EXPECTED_ICO_SIZES} - found
    if missing:
        return f"{path.name}: missing sizes {sorted(missing)}"
    return None


def check_index_html() -> list[str]:
    failures: list[str] = []
    if not INDEX_HTML.is_file():
        return [f"missing: {INDEX_HTML}"]
    text = INDEX_HTML.read_text(encoding="utf-8")
    for ref in EXPECTED_INDEX_REFS:
        if ref not in text:
            failures.append(f"index.html: missing reference to {ref}")
    # The v2.1 design is PNG-only. An SVG favicon reference
    # would be a regression.
    if re.search(r'href="/favicon\.svg', text):
        failures.append("index.html: references favicon.svg (v2.1 design is PNG-only)")
    if re.search(r'type="image/svg\+xml"', text):
        failures.append("index.html: declares an SVG icon (v2.1 design is PNG-only)")
    # Every icon href must carry a ?v= cache-busting query.
    hrefs = re.findall(r'<link\s+rel="(?:icon|apple-touch-icon)"[^>]*href="([^"]+)"', text)
    for href in hrefs:
        if not re.search(r"\?v=\d+", href):
            failures.append(f"index.html: icon href {href} is missing ?v= cache-busting")
    return failures


def main() -> int:
    failures: list[str] = []
    source_err = check_source(PUBLIC_DIR / "favicon-source.png")
    if source_err:
        failures.append(source_err)
    for filename, size in EXPECTED_PNG_FILES.items():
        err = check_png(PUBLIC_DIR / filename, size)
        if err:
            failures.append(err)
    ico_err = check_ico(PUBLIC_DIR / "favicon.ico")
    if ico_err:
        failures.append(ico_err)
    for filename in EXPECTED_BRAND_FILES:
        path = PUBLIC_DIR / filename
        if not path.is_file():
            failures.append(f"missing brand asset: {path}")
    failures.extend(check_index_html())
    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    print(
        "OK: source-of-truth chain intact; favicon, symbol, "
        "and horizontal-logo assets present and wired into "
        "index.html with cache-busting."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
