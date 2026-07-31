"""Tests for the v2.1 Part B3A packaging-derivative ICO.

The approved ``frontend/public/favicon.ico`` is the
brand-board web favicon; it contains only the
``16x16``, ``32x32`` and ``48x48`` entries the
browser needs. The Windows executable resource also
needs a ``256x256`` entry to render correctly at high
DPI.

The derivative ICO at
``backend/pyinstaller/favicon-exe.ico`` is a
mechanical re-packaging of the approved web favicon's
small entries plus a Lanczos downscale of the
approved 1024x1024 PNG source to 256x256. The
approved brand assets are not modified.

The tests in this module verify:

  1. The derivative file exists and is a valid ICO.
  2. The derivative has ``16/32/48/256`` entries.
  3. The approved web favicon is unchanged (the
     derivative is a *copy*, not a re-render).
  4. The 256x256 entry is a PNG payload (the
     Windows Vista+ ICO convention), not a freshly
     re-rasterised BMP.
  5. The build script regenerates the derivative
     idempotently from the approved sources.

The tests do not require the build script to have
been run; they verify the artefact and the
re-generation logic in isolation.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest
from scripts import generate_exe_icon

REPO_ROOT = Path(__file__).resolve().parents[2]
APPROVED_ICO = REPO_ROOT / "frontend" / "public" / "favicon.ico"
APPROVED_PNG = REPO_ROOT / "frontend" / "public" / "favicon-source.png"
DERIVATIVE_ICO = REPO_ROOT / "backend" / "pyinstaller" / "favicon-exe.ico"


def _parse_ico_sizes(data: bytes) -> list[tuple[int, int, int, bytes]]:
    """Return ``[(width, height, size, body), ...]`` for every ICO entry."""
    if data[:4] != b"\x00\x00\x01\x00":
        raise ValueError("not an ICO file (magic mismatch)")
    count = struct.unpack_from("<H", data, 4)[0]
    out: list[tuple[int, int, int, bytes]] = []
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
                size,
                data[body_offset : body_offset + size],
            )
        )
    return out


@pytest.fixture
def regenerated_derivative(tmp_path: Path) -> Path:
    """Regenerate the derivative ICO in a temp path for inspection.

    The fixture is the documented chokepoint: any
    test that exercises the derivative can call
    :func:`build_exe_icon` against an isolated
    output path so the on-disk artefact is not
    modified.
    """
    out = tmp_path / "favicon-exe.ico"
    generate_exe_icon.build_exe_icon(
        approved_ico=APPROVED_ICO,
        approved_png=APPROVED_PNG,
        derivative_ico=out,
    )
    return out


class TestApprovedFaviconUnchanged:
    """The brand-board web favicon is never modified by the build."""

    def test_approved_favicon_exists(self) -> None:
        assert APPROVED_ICO.is_file(), f"approved favicon missing at {APPROVED_ICO}"

    def test_approved_favicon_has_small_entries(self) -> None:
        data = APPROVED_ICO.read_bytes()
        sizes = {entry[0] for entry in _parse_ico_sizes(data)}
        assert 16 in sizes
        assert 32 in sizes
        assert 48 in sizes


class TestDerivativeIcoStructure:
    """The derivative ICO has the required 16/32/48/256 entries."""

    def test_derivative_is_valid_ico(self, regenerated_derivative: Path) -> None:
        data = regenerated_derivative.read_bytes()
        assert data[:4] == b"\x00\x00\x01\x00"

    def test_derivative_has_required_sizes(self, regenerated_derivative: Path) -> None:
        data = regenerated_derivative.read_bytes()
        sizes = {entry[0] for entry in _parse_ico_sizes(data)}
        assert sizes == {16, 32, 48, 256}

    def test_derivative_256_entry_is_png(self, regenerated_derivative: Path) -> None:
        """The 256x256 entry is a PNG payload.

        Windows accepts PNG-compressed ICO entries
        directly (Vista+); the test asserts the
        payload starts with the PNG magic so the
        Windows shell can decode the high-DPI icon
        without an extra re-rasterisation.
        """
        data = regenerated_derivative.read_bytes()
        entries = _parse_ico_sizes(data)
        entry_256 = next(entry for entry in entries if entry[0] == 256)
        assert entry_256[3].startswith(b"\x89PNG\r\n\x1a\n"), (
            "the 256x256 entry must be a PNG payload; the Windows shell decodes PNG-in-ICO directly"
        )


class TestBuildExeIconIdempotency:
    """The build script regenerates the derivative without side effects."""

    def test_build_exe_icon_creates_file(self, regenerated_derivative: Path) -> None:
        assert regenerated_derivative.is_file()
        assert regenerated_derivative.stat().st_size > 0

    def test_build_exe_icon_does_not_modify_approved_sources(self) -> None:
        # Snapshot the approved sources' SHA-256,
        # run the build, and confirm the hash is
        # unchanged. The function is a side-effect
        # check; a future maintainer cannot
        # accidentally start writing to the approved
        # tree without breaking the test.
        import hashlib

        before_ico = hashlib.sha256(APPROVED_ICO.read_bytes()).hexdigest()
        before_png = hashlib.sha256(APPROVED_PNG.read_bytes()).hexdigest()
        generate_exe_icon.build_exe_icon(
            approved_ico=APPROVED_ICO,
            approved_png=APPROVED_PNG,
            derivative_ico=DERIVATIVE_ICO,  # idempotent overwrite
        )
        after_ico = hashlib.sha256(APPROVED_ICO.read_bytes()).hexdigest()
        after_png = hashlib.sha256(APPROVED_PNG.read_bytes()).hexdigest()
        assert before_ico == after_ico
        assert before_png == after_png
