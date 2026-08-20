"""Tests for the v2.1 Part B3A PyInstaller payload contract.

The frozen ``Lockverity.exe`` is the documented single
binary an operator runs on Windows. The v2.1 Part B3A
contract requires the frozen payload to contain every
native runtime the desktop shell actually uses; if a
hidden import is missing, the frozen build silently
fails at runtime with a ``ModuleNotFoundError`` that
the operator sees only as a message box.

The most-recent regression of this kind was the
``pywebview`` (``import webview``) packaging failure:
the build environment had ``pywebview`` uninstalled
and the static analysis did not see the deferred
``import webview`` inside ``_run_webview`` with the
expected error message. The user-facing symptom was
``Lockverity could not create its Microsoft Edge
WebView2 window`` with no traceback. The fix was to
install ``pywebview`` in the build environment, add
the package to ``HIDDENIMPORTS`` in the GUI spec, and
let the package's own ``__pyinstaller`` hook collect
the WebView2 interop DLLs.

The tests in this module are the regression guard:

  * :func:`test_pywebview_is_installed` ensures the
    build environment can import ``webview``; a
    missing install means the GUI spec's hidden
    imports will silently no-op.
  * :func:`test_gui_pyinstaller_spec_includes_webview`
    ensures the spec's ``HIDDENIMPORTS`` block
    includes ``webview`` and
    ``webview.platforms.edgechromium`` so the
    selected native renderer is pinned in the
    import graph.
  * :func:`test_frozen_gui_payload_contains_webview`
    inspects the most recent frozen ``Lockverity.exe``
    (or the most recent ``build/packaging`` portable
    root) and asserts the PYZ archive contains the
    ``webview`` module and the
    ``webview.platforms.edgechromium`` backend. The
    test is skipped if no built portable is on disk
    so the suite remains fast on dev machines that
    have not yet built.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUI_SPEC_PATH = REPO_ROOT / "backend" / "pyinstaller" / "lockverity.spec"
PORTABLE_NAME = "Lockverity-2.1.2-windows-x64-portable"
# Built artefacts are written under any of:
#   - ``backend/build/packaging/<name>/...`` (canonical)
#   - ``build/dev/packaging/<name>/...`` (developer)
#   - ``backend/build/dev/packaging/<name>/...`` (developer)
# The first existing root is the one we inspect.
CANDIDATE_PORTABLE_ROOTS: tuple[Path, ...] = (
    REPO_ROOT / "backend" / "build" / "dev" / "packaging" / PORTABLE_NAME,
    REPO_ROOT / "build" / "dev" / "packaging" / PORTABLE_NAME,
    REPO_ROOT / "backend" / "build" / "packaging" / PORTABLE_NAME,
    REPO_ROOT / "build" / "packaging" / PORTABLE_NAME,
)
CANDIDATE_FROZEN_EXES: tuple[Path, ...] = (
    *tuple(root / "Lockverity.exe" for root in CANDIDATE_PORTABLE_ROOTS),
    # PyInstaller ``dist`` layout (used by some CI / dev invocations).
    REPO_ROOT / "backend" / "build" / "dev" / "pyinstaller_out" / "Lockverity" / "Lockverity.exe",
    REPO_ROOT / "backend" / "pyinstaller_out" / "Lockverity" / "Lockverity.exe",
    REPO_ROOT / "build" / "dev" / "pyinstaller_out" / "Lockverity" / "Lockverity.exe",
    REPO_ROOT / "pyinstaller_out" / "Lockverity" / "Lockverity.exe",
)


# ---------------------------------------------------------------------------
# Build-environment guard: the GUI spec lists ``webview`` in
# ``HIDDENIMPORTS`` but the import can only resolve if ``pywebview`` is
# actually installed in the venv that runs PyInstaller. The check is a
# one-liner that fails fast with a clear remediation message.
# ---------------------------------------------------------------------------


def test_pywebview_is_installed() -> None:
    """``pywebview`` must be importable in the build environment.

    The GUI spec's hidden-import list for ``webview`` is only
    effective if the package is installed; PyInstaller's static
    analysis does not see a deferred ``import webview`` inside
    ``_run_webview`` when the import fails at scan time. A missing
    install was the documented root cause of the v2.1.2
    ``ModuleNotFoundError: No module named 'webview'`` regression.
    """
    try:
        import webview  # noqa: F401
    except Exception as exc:  # pragma: no cover - failure path
        pytest.fail(
            "pywebview is not importable in the build environment. "
            "Install it with `pip install pywebview` (the v2.1.2 GUI "
            "frozen payload requires the Microsoft Edge WebView2 "
            "renderer). "
            f"Underlying error: {type(exc).__name__}: {exc}"
        )


# ---------------------------------------------------------------------------
# Spec guard: the hidden-import list must pin the selected native
# renderer. The list is the documented control surface for what the
# frozen payload includes beyond the static scan.
# ---------------------------------------------------------------------------


def test_gui_pyinstaller_spec_includes_webview() -> None:
    """The GUI spec must list ``webview`` and ``webview.platforms.edgechromium`` in ``HIDDENIMPORTS``.

    pywebview selects the native renderer dynamically. The static
    scan sees the deferred ``import webview`` inside ``_run_webview``
    but the platform module (``webview.platforms.edgechromium``) is
    loaded by attribute lookup on the parent module. Without an
    explicit hidden import, the platform module is dropped from the
    frozen payload and ``import webview`` succeeds at import time
    but ``webview.start(gui="edgechromium")`` fails with
    ``ModuleNotFoundError`` for the platform module.
    """
    spec_text = GUI_SPEC_PATH.read_text(encoding="utf-8")
    assert '"webview"' in spec_text, (
        "GUI spec must list `\"webview\"` in HIDDENIMPORTS. "
        f"Edit {GUI_SPEC_PATH}."
    )
    assert '"webview.platforms.edgechromium"' in spec_text, (
        "GUI spec must list `\"webview.platforms.edgechromium\"` in "
        "HIDDENIMPORTS so the Microsoft Edge WebView2 backend is "
        "pinned in the import graph. "
        f"Edit {GUI_SPEC_PATH}."
    )


# ---------------------------------------------------------------------------
# Payload guard: inspect the most recent frozen GUI EXE and assert the
# PYZ archive contains the webview module and the edgechromium backend.
# The test is skipped if no built portable is on disk so the suite
# remains fast on dev machines that have not yet built.
# ---------------------------------------------------------------------------


def _find_frozen_exe() -> Path | None:
    for candidate in CANDIDATE_FROZEN_EXES:
        if candidate.is_file():
            return candidate
    return None


def _read_pyz(exe_path: Path) -> bytes | None:
    """Read the PYZ archive out of a frozen PyInstaller EXE.

    Returns the raw PYZ bytes (header + TOC + source area) or
    ``None`` if the EXE is not a PyInstaller CArchive (older
    onefile layouts embed the PYZ differently).
    """
    try:
        from PyInstaller.archive.readers import CArchiveReader
    except Exception:
        return None
    try:
        reader = CArchiveReader(str(exe_path))
    except Exception:
        return None
    for key in reader.toc:
        if key.upper() == "PYZ.PYZ":
            return reader.extract(key)
    return None


def _list_pyz_module_names(pyz_bytes: bytes) -> list[str]:
    """Return the module names declared in a PyInstaller PYZ TOC.

    The TOC is the marshalled list at the end of the PYZ
    archive; each entry is a ``(name, (is_pkg, offset, length))``
    tuple. Names are scanned to validate the frozen payload
    without deserialising every code object.
    """
    import marshal

    toc_offset = struct.unpack(">I", pyz_bytes[8:12])[0]
    try:
        # Reading the PyInstaller-generated PYZ TOC is the
        # documented way to inspect a frozen payload; the
        # ``S302`` warning is not applicable here because
        # the data is produced by PyInstaller itself, not
        # an untrusted source.
        toc = marshal.loads(pyz_bytes[toc_offset:])  # noqa: S302
    except Exception:
        return []
    names: list[str] = []
    for entry in toc:
        try:
            name = entry[0]
        except (TypeError, IndexError):
            continue
        if isinstance(name, str):
            names.append(name)
    return names


def test_frozen_gui_payload_contains_webview() -> None:
    """The most recent frozen ``Lockverity.exe`` must contain ``webview``.

    This is the v2.1.2 regression guard. The build artefact is
    optional in the test environment; the test skips cleanly when
    no built portable is on disk so the suite stays fast for a
    developer who has not yet run ``scripts/build_windows_portable.py``.
    Once a build is on disk, a missing ``webview`` module is a
    hard fail with a clear remediation message.
    """
    exe_path = _find_frozen_exe()
    if exe_path is None:
        pytest.skip(
            "No built Lockverity.exe found in any known packaging output "
            "directory; run `python backend/scripts/build_windows_portable.py` "
            "to populate the frozen payload before running this guard."
        )
    pyz_bytes = _read_pyz(exe_path)
    if pyz_bytes is None:
        pytest.skip(
            f"{exe_path} is not a PyInstaller CArchive with a PYZ; "
            "the regression guard cannot inspect the frozen payload."
        )
    names = _list_pyz_module_names(pyz_bytes)
    assert "webview" in names, (
        f"Frozen payload at {exe_path} does not contain the `webview` "
        "module. The v2.1.2 documented regression: install pywebview "
        "in the build environment and rebuild. PYZ modules: "
        f"{[n for n in names if 'webview' in n.lower() or 'pywebview' in n.lower()]}"
    )
    assert "webview.platforms.edgechromium" in names, (
        f"Frozen payload at {exe_path} does not contain the "
        "`webview.platforms.edgechromium` Microsoft Edge WebView2 "
        "backend. The platform module is loaded by attribute lookup "
        "and is missed by the static scan; the GUI spec's hidden "
        "import list must include it. PYZ modules: "
        f"{[n for n in names if 'webview' in n.lower()]}"
    )


# ---------------------------------------------------------------------------
# Payload guard: the frozen GUI must carry the WebView2 interop DLLs.
# These are collected by pywebview's own ``__pyinstaller`` hook and
# the regression guard checks the most recent portable's
# ``_internal/webview/lib`` directory exists.
# ---------------------------------------------------------------------------


def test_frozen_gui_payload_carries_webview2_interop_dlls() -> None:
    """The most recent frozen portable must carry the WebView2 interop DLLs.

    The pywebview ``__pyinstaller/hook-webview.py`` collects the
    ``webview/lib`` data files and the ``webview`` dynamic
    libraries. A portable missing the interop DLLs cannot create
    the WebView2 window on a real Windows desktop even if
    ``import webview`` succeeds.
    """
    portable_root = next(
        (root for root in CANDIDATE_PORTABLE_ROOTS if root.is_dir()), None
    )
    if portable_root is None:
        pytest.skip(
            "No built portable root found; run "
            "`python backend/scripts/build_windows_portable.py` to "
            "populate the frozen payload before running this guard."
        )
    webview2_dir = portable_root / "_internal" / "webview" / "lib"
    if not webview2_dir.is_dir():
        pytest.fail(
            f"Frozen portable at {portable_root} does not carry the "
            "pywebview WebView2 interop DLLs. The pywebview "
            "__pyinstaller hook must be discoverable; verify the "
            "build environment has pywebview installed and that the "
            "GUI spec's hidden-import list includes the package."
        )
    # At least the two canonical Microsoft WebView2 DLLs must be
    # bundled. The pywebview lib also includes the WinForms wrapper
    # and the WebBrowserInterop native shims.
    required = (
        "Microsoft.Web.WebView2.Core.dll",
        "Microsoft.Web.WebView2.WinForms.dll",
    )
    for dll_name in required:
        if not (webview2_dir / dll_name).is_file():
            pytest.fail(
                f"Frozen portable at {portable_root} is missing the "
                f"required WebView2 interop DLL {dll_name}. The "
                "pywebview __pyinstaller hook should collect this "
                "DLL; verify the build environment has pywebview "
                "installed and that the GUI spec's hidden-import "
                "list includes the package."
            )


# ---------------------------------------------------------------------------
# Bundle-size smoke: a frozen GUI with ``webview`` bundled is at least
# ~16 MB on Windows (pywebview + WebView2Loader + the Edge WebView2
# host DLLs). A frozen GUI under 12 MB is almost certainly missing
# pywebview and will fail at startup with ``ModuleNotFoundError``.
# This is a low-cost pre-flight the operator can use to triage a
# failed build before opening a debugger. It is a SECONDARY check;
# the primary correctness assertions are the semantic payload
# checks above.
# ---------------------------------------------------------------------------


_MIN_GUI_BYTES = 12 * 1024 * 1024


def test_frozen_gui_exe_size_meets_minimum() -> None:
    """The frozen ``Lockverity.exe`` is at least 12 MB (secondary sanity).

    This is a low-cost smoke that catches the
    "the hidden-import list dropped pywebview and we shipped an
    EXE that imports nothing useful" regression without
    requiring a Windows desktop. The primary correctness
    assertions live in the semantic tests above; this size
    guard is a secondary sanity check.
    """
    exe_path = _find_frozen_exe()
    if exe_path is None:
        pytest.skip(
            "No built Lockverity.exe found in any known packaging output "
            "directory."
        )
    size = exe_path.stat().st_size
    assert size >= _MIN_GUI_BYTES, (
        f"Frozen GUI at {exe_path} is {size} bytes, below the "
        f"{_MIN_GUI_BYTES}-byte minimum. The most likely cause is "
        "a PyInstaller hidden-import regression. Inspect the build "
        "log and the GUI spec."
    )
