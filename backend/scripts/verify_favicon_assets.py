"""Verify the generated favicon assets.

Checks that:
- The ICO file contains the expected sizes (16, 32, 48).
- The PNG files exist at the expected pixel dimensions.
- The SVG declares explicit fill colours (no currentColor)
  and the documented brand palette (Indigo 900 background,
  Teal 500 + Blue 600 gradient stops).
- The HTML references in frontend/index.html match the
  produced files.
"""

from __future__ import annotations

import re
import struct
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_DIR = REPO_ROOT / "frontend" / "public"
INDEX_HTML = REPO_ROOT / "frontend" / "index.html"
FAVICON_SVG = PUBLIC_DIR / "favicon.svg"

EXPECTED_ICO_SIZES = {16, 32, 48}
EXPECTED_PNG_FILES = {
    "favicon-16x16.png": 16,
    "favicon-32x32.png": 32,
    "favicon-48x48.png": 48,
    "apple-touch-icon.png": 180,
}


def check_png(path: Path, expected_size: int) -> str | None:
    if not path.is_file():
        return f"missing: {path}"
    try:
        from PIL import Image
    except ImportError:
        return "Pillow not available"
    with Image.open(path) as img:
        if img.size != (expected_size, expected_size):
            return f"{path.name}: expected {expected_size}x{expected_size}, got {img.size[0]}x{img.size[1]}"
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


def check_svg(path: Path) -> str | None:
    if not path.is_file():
        return f"missing: {path}"
    text = path.read_text(encoding="utf-8")
    # Must declare explicit fill / stroke colours; currentColor
    # is not allowed in any fill or stroke attribute. The check
    # matches the attribute form so a comment that mentions
    # the keyword does not trip the rule.
    if re.search(r'(?:fill|stroke)\s*=\s*"currentColor"', text):
        return f"{path.name}: references currentColor in fill/stroke (must be explicit)"
    # The background must use the documented Indigo 900.
    if not re.search(r'fill="#0[Bb]1324"', text):
        return f"{path.name}: missing Indigo 900 (#0B1324) background fill"
    # The mark must declare a vertical linear gradient with the
    # two documented colour stops. The palette section of the
    # brand board uses these exact hex values; the colour
    # names in the board's legend are unconventional but the
    # hex codes are the source of truth.
    if not re.search(r"<linearGradient\b", text):
        return f"{path.name}: missing <linearGradient> element"
    if not re.search(r'stop-color="#2[Ee]8[Bb][Ff]0"', text):
        return f"{path.name}: missing Teal 500 (#2E8BF0) gradient stop"
    if not re.search(r'stop-color="#14[Bb]8[Aa]6"', text):
        return f"{path.name}: missing Blue 600 (#14B8A6) gradient stop"
    return None


def check_index_html() -> list[str]:
    failures: list[str] = []
    if not INDEX_HTML.is_file():
        return [f"missing: {INDEX_HTML}"]
    text = INDEX_HTML.read_text(encoding="utf-8")
    expected_refs = [
        "/favicon.svg",
        "/favicon.ico",
        "/favicon-16x16.png",
        "/favicon-32x32.png",
        "/favicon-48x48.png",
        "/apple-touch-icon.png",
    ]
    for ref in expected_refs:
        if ref not in text:
            failures.append(f"index.html: missing reference to {ref}")
    if 'sizes="180x180"' not in text:
        failures.append("index.html: apple-touch-icon sizes=180x180 not declared")
    return failures


def main() -> int:
    failures: list[str] = []
    for filename, size in EXPECTED_PNG_FILES.items():
        err = check_png(PUBLIC_DIR / filename, size)
        if err:
            failures.append(err)
    err = check_ico(PUBLIC_DIR / "favicon.ico")
    if err:
        failures.append(err)
    err = check_svg(FAVICON_SVG)
    if err:
        failures.append(err)
    failures.extend(check_index_html())
    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    print("OK: all favicon assets present, correct size, and referenced from index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
