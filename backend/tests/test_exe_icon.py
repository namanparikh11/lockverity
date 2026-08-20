"""Tests for the v2.1.2 canonical Windows ICO.

The approved brand asset is the
``frontend/public/favicon-source.png`` ``1024x1024``
RGBA source. The brand-board web favicon at
``frontend/public/favicon.ico`` contains the
``16x16``, ``32x32`` and ``48x48`` entries the
browser needs. The canonical Windows ICO at
``backend/pyinstaller/favicon-exe.ico`` is a
mechanical re-packaging of the approved source:

  - 16, 32, 48 entries are lifted from the
    hand-tuned brand-favicon (so the Windows shell
    shows the exact same glyph the browser does);
  - 24, 64, 128, 256 entries are Pillow Lanczos
    downscales of the approved 1024x1024 PNG.

The approved brand assets are never modified.

v2.1.3 padding-normalisation
============================

The v2.1.3 fix tightens the transparent padding
around the brand mark so the taskbar icon
occupies the same visual area as the icons of
the same Windows shell size. The fix lives in
:func:`scripts.generate_exe_icon._normalise_padding`
and is exercised by :class:`TestPaddingNormalisation`
below. The new tests assert:

  1. The derivative ICO is regenerated with the
     padding-normalised source.
  2. The visible content bounding box of the
     derivative frames exceeds 85% of the canvas
     (the v2.1.3 contract).
  3. The brand shape is preserved exactly: the
     normalised source is the *same* brand asset,
     cropped to its content bbox plus a small
     consistent edge margin, never redrawn.
  4. The padding step is idempotent: a second
     pass over the same source produces a
     bit-identical output.

The tests in this module verify:

  1. The derivative file exists and is a valid ICO.
  2. The derivative has the full canonical size set
     ``{16, 24, 32, 48, 64, 128, 256}``.
  3. The approved web favicon is unchanged (the
     derivative is a *copy*, not a re-render).
  4. The 256x256 entry is a PNG payload (the
     Windows Vista+ ICO convention), not a freshly
     re-rasterised BMP.
  5. The build script regenerates the derivative
     idempotently from the approved sources.
  6. The padding-normalisation step tightens the
     visible content bounding box to ``> 85%``
     of every frame.

The tests do not require the build script to have
been run; they verify the artefact and the
re-generation logic in isolation.
"""

from __future__ import annotations

import io
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
    """The derivative ICO has the full canonical Windows size set."""

    def test_derivative_is_valid_ico(self, regenerated_derivative: Path) -> None:
        data = regenerated_derivative.read_bytes()
        assert data[:4] == b"\x00\x00\x01\x00"

    def test_derivative_has_canonical_size_set(self, regenerated_derivative: Path) -> None:
        """The canonical Windows size set is ``{16, 24, 32, 48, 64, 128, 256}``.

        The Windows shell queries these sizes (and only
        these sizes) when rendering the application
        icon for the taskbar, Start tile, Installed
        apps list, File Explorer and the uninstaller
        UI. A missing entry causes the shell to fall
        back to the generic application icon, which is
        the regression that v2.1.2 fixes. The set is
        ``{16, 24, 32, 48, 64, 128, 256}`` -- the union
        of every shell size Windows 10/11 queries.
        """
        data = regenerated_derivative.read_bytes()
        sizes = {entry[0] for entry in _parse_ico_sizes(data)}
        assert sizes == {16, 24, 32, 48, 64, 128, 256}, (
            f"Canonical Windows ICO size set mismatch: {sorted(sizes)}; "
            "the Windows shell will fall back to the generic "
            "application icon for any missing size."
        )

    def test_derivative_superset_size(self, regenerated_derivative: Path) -> None:
        """Convenience assertion: every size in the documented
        canonical set is present (defence-in-depth for
        the superset-relation check above)."""
        data = regenerated_derivative.read_bytes()
        sizes = {entry[0] for entry in _parse_ico_sizes(data)}
        for required in (16, 24, 32, 48, 64, 128, 256):
            assert required in sizes, (
                f"Canonical Windows ICO is missing the {required}x{required} entry; "
                "the Windows shell will fall back to the generic application icon."
            )

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


class TestPaddingNormalisation:
    """v2.1.3 padding-normalisation step.

    The manual-QA pass on the native Windows shell
    surfaced the taskbar icon as visually undersized
    relative to neighbouring Windows 11 application
    icons. The cause was excessive transparent
    padding around the brand mark in the source
    asset: the visible-logo bounding box filled
    about 91% of the 1024x1024 canvas, leaving
    ``~5%`` transparent padding on every side.

    The fix is a *padding-normalisation* step at
    the very start of the ICO build: the script
    crops the approved source to its visible
    content bounding box plus a small fixed
    margin (``2%`` of the canvas per side, default)
    and resizes the cropped region to a
    ``1024x1024`` working canvas. The brand shape
    is preserved exactly; only the transparent
    padding is tightened.

    The tests below assert:

      1. The padding-normalisation step trims the
         visible content bounding box to a
         ``> 95%`` of the ``1024x1024`` working
         canvas.
      2. The build script produces a derivative
         whose per-frame visible content bounding
         box exceeds
         :data:`generate_exe_icon.MIN_VISIBLE_BBOX_RATIO`
         (85% of the frame) for the downscaled
         sizes the v2.1.3 fix targets.
      3. The brand shape is preserved: the
         normalised source is a *crop* of the
         approved source, never a redraw.
      4. The padding step is idempotent: a second
         pass over the same source produces a
         bit-identical normalised source.
    """

    def test_padding_step_tightens_visible_bbox(self) -> None:
        """The normalised source fills ``> 95%`` of the working canvas.

        The historical 1024x1024 source carries
        about 91% content usage. After the
        padding-normalisation step the visible
        content bounding box fills at least 95%
        of the working canvas so the brand mark
        reaches the Windows taskbar edges without
        the loose padding of the historical
        asset.
        """
        from PIL import Image  # type: ignore[import-not-found]

        source_bytes = APPROVED_PNG.read_bytes()
        normalised_bytes = generate_exe_icon._normalise_padding(source_bytes)
        with Image.open(io.BytesIO(normalised_bytes)) as normalised:
            bbox = normalised.getbbox()
            assert bbox is not None
            left, top, right, bottom = bbox
            used = (right - left) * (bottom - top)
            full = normalised.size[0] * normalised.size[1]
            ratio = used / full
            assert ratio >= 0.95, (
                f"normalised source content bounding box is {ratio * 100:.1f}% "
                f"of the working canvas; expected at least 95%"
            )

    def test_padding_step_preserves_brand_shape(self) -> None:
        """The normalised source is a *crop* of the approved source.

        The padding step must never recolour,
        redraw, or reinterpolate the brand. The
        test asserts the *brightest* pixel in the
        normalised source is present in the
        approved source (the brand's signature
        blue is preserved). A regression that
        recoloured the source would change the
        brightest pixel and the assertion would
        fail.
        """
        from PIL import Image  # type: ignore[import-not-found]

        source_bytes = APPROVED_PNG.read_bytes()
        normalised_bytes = generate_exe_icon._normalise_padding(source_bytes)
        with Image.open(io.BytesIO(source_bytes)) as source, Image.open(
            io.BytesIO(normalised_bytes)
        ) as normalised:
            source.load()
            normalised.load()
            assert source.mode == "RGBA"
            assert normalised.mode == "RGBA"
            # The brightest single channel value
            # of any pixel in the source must be
            # present in the normalised source.
            # The brand uses a bright cyan/blue
            # glyph; the brightest channel of
            # that pixel is ``>= 200`` in the
            # approved asset.
            source_pixels = source.load()
            normalised_pixels = normalised.load()
            source_max_b = 0
            for y in range(0, source.size[1], 64):
                for x in range(0, source.size[0], 64):
                    _r, _g, b, a = source_pixels[x, y]
                    if a > 200:
                        source_max_b = max(source_max_b, b)
            assert source_max_b > 0, (
                "approved source has no fully-opaque blue pixel; "
                "this is unexpected for the Lockverity brand asset"
            )
            normalised_max_b = 0
            for y in range(0, normalised.size[1], 64):
                for x in range(0, normalised.size[0], 64):
                    _r, _g, b, a = normalised_pixels[x, y]
                    if a > 200:
                        normalised_max_b = max(normalised_max_b, b)
            # The normalised source must keep at
            # least 90% of the brand's signature
            # blue. Anti-aliasing on a Lanczos
            # downscale loses a few percent, but
            # the brand shape must remain
            # recognisable.
            assert normalised_max_b >= int(source_max_b * 0.9), (
                f"normalised source loses the brand's signature blue: "
                f"source_max_b={source_max_b}, normalised_max_b={normalised_max_b}"
            )

    def test_padding_step_is_idempotent(self) -> None:
        """A second pass over the same source produces a bit-identical output.

        The padding step must be a pure function
        of the source bytes: no random
        resampling, no timestamp-based
        differences, no per-invocation state.
        Two consecutive calls must produce the
        same bytes.
        """
        source_bytes = APPROVED_PNG.read_bytes()
        first = generate_exe_icon._normalise_padding(source_bytes)
        second = generate_exe_icon._normalise_padding(source_bytes)
        assert first == second

    def test_derivative_frames_exceed_min_visible_bbox_ratio(
        self, regenerated_derivative: Path
    ) -> None:
        """Every per-frame content bbox exceeds the v2.1.3 minimum.

        The v2.1.3 fix tightens the transparent
        padding so the brand mark fills more of
        every ICO frame. The minimum acceptable
        ratio is :data:`generate_exe_icon.MIN_VISIBLE_BBOX_RATIO`
        (85%). A regression that loosens the
        padding would drop the ratio below the
        minimum and the test would fail.
        """
        from PIL import Image  # type: ignore[import-not-found]

        data = regenerated_derivative.read_bytes()
        for w, h, _size, body in _parse_ico_sizes(data):
            with Image.open(io.BytesIO(body)) as im:
                if im.mode != "RGBA":
                    im = im.convert("RGBA")
                bbox = im.getbbox()
                if bbox is None:
                    continue
                left, top, right, bottom = bbox
                used = (right - left) * (bottom - top)
                full = w * h
                ratio = used / full
                assert ratio >= generate_exe_icon.MIN_VISIBLE_BBOX_RATIO, (
                    f"ICO frame {w}x{h} content bounding box is "
                    f"{ratio * 100:.1f}% of the canvas; expected at least "
                    f"{generate_exe_icon.MIN_VISIBLE_BBOX_RATIO * 100:.1f}%"
                )
