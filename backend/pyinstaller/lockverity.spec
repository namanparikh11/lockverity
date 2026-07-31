# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Lockverity graphical launcher.

This spec produces the v2.1 Part B3A ``Lockverity.exe``
graphical launcher. The launcher is a windowless
application that:

  * uses the approved ``favicon.ico`` for the
    executable icon resource;
  * resolves all resources via ``app.runtime_paths``;
  * delegates the runtime lifecycle to the accepted
    Part B2 ``app.cli`` functions and the Part B1
    ``app.main`` FastAPI app.

The spec is intentionally explicit: every ``datas``
entry, every ``hiddenimport``, and every binary is
declared in source so a maintainer can audit the
package contents without running a build.

The launcher build is one of two PyInstaller outputs
in the v2.1 Part B3A portable package. The other is
``cli.spec`` (the console CLI build). The two specs
share the same data files but differ in
``console=False`` vs ``console=True`` and the entry
point module.
"""

from pathlib import Path

import sys

# The spec is invoked from the backend root. The spec
# does not depend on the caller's current working
# directory.
BACKEND_ROOT = Path(SPECPATH).resolve().parent  # type: ignore[name-defined]  # noqa: F821
REPO_ROOT = BACKEND_ROOT.parent

# The frozen bundle root. Every ``datas`` entry is
# resolved relative to this root. PyInstaller unpacks
# the bundle at ``sys._MEIPASS`` at launch.
FROZEN_BUNDLE_DATA: list[tuple[str, str]] = [
    # The bundled frontend dist. The path is the same
    # in source and frozen modes; the runtime resolver
    # reads it under ``sys._MEIPASS/frontend/dist``.
    (str(REPO_ROOT / "frontend" / "dist"), "frontend/dist"),
    # The Alembic config and migration scripts. The
    # runtime resolver reads them under
    # ``sys._MEIPASS/alembic.ini`` and
    # ``sys._MEIPASS/alembic/versions``.
    (str(BACKEND_ROOT / "alembic.ini"), "alembic.ini"),
    (str(BACKEND_ROOT / "alembic"), "alembic"),
    # The approved application icon. The launcher
    # loads it from the bundle root at launch.
    (str(REPO_ROOT / "frontend" / "public" / "favicon.ico"), "favicon.ico"),
    # The brand PNG assets used by the launcher and
    # bundled for downstream components that need them.
    (str(REPO_ROOT / "frontend" / "public" / "brand"), "brand"),
    # The repository LICENSE (MIT) bundled at the
    # frozen root so a downstream operator can read
    # the licence without consulting an external
    # resource.
    (str(REPO_ROOT / "LICENSE"), "LICENSE"),
    # The portable README bundled at the frozen root.
    (str(REPO_ROOT / "docs" / "windows-portable.md"), "README-PORTABLE.txt"),
]

# Hidden imports. PyInstaller scans the entry point's
# import graph automatically; the list below covers
# modules that are imported dynamically (via
# ``importlib``) and so are missed by the static
# scan. Adding a module here is a deliberate action;
# every entry has a comment explaining why the static
# scan misses it.
HIDDENIMPORTS: list[str] = [
    # The Alembic ``script.py.mako`` template is
    # loaded by Alembic at runtime via
    # ``pkg_resources`` / ``importlib.resources``;
    # PyInstaller's static scan does not see the
    # template loader.
    "alembic.runtime.migration",
    # The Alembic op helpers are imported
    # dynamically in env.py.
    "alembic.operations.ops",
    # The launcher uses ``webbrowser``; the standard
    # library entry is normally scanned, but the
    # Windows backend is dynamically imported.
    "webbrowser",
    # ``app.cli.process`` uses ``psutil`` which has
    # platform-specific submodules.
    "psutil",
    "psutil._pswindows",
    "psutil._psutil_windows",
    # ``app.cli.runner`` builds a ``RotatingFileHandler``
    # from ``logging.handlers``; the standard library
    # entry is scanned but the rare Win32-only
    # ``NTEventLogHandler`` is not used here.
]


a = Analysis(  # type: ignore[name-defined]  # noqa: F821
    [str(BACKEND_ROOT / "app" / "launcher" / "__main__.py")],
    pathex=[str(BACKEND_ROOT)],
    binaries=[],
    datas=FROZEN_BUNDLE_DATA,
    hiddenimports=HIDDENIMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # The launcher does not embed a separate console
    # window. The Windows subsystem is set to
    # ``WINDOWS`` (windowless) by the ``console=False``
    # argument to ``PEX`` below.
    excludes=[
        # The standard-library ``tkinter`` is not used
        # by the launcher. Excluding it shrinks the
        # bundle and reduces antivirus surface area.
        "tkinter",
        "unittest",
        "pydoc",
        "doctest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure)  # type: ignore[name-defined]  # noqa: F821

exe = EXE(  # type: ignore[name-defined]  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Lockverity",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX is forbidden by the v2.1 Part B3A contract.
    console=False,  # Windowless launcher. The CLI spec uses ``console=True``.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # The approved application icon. The file is the
    # same ``favicon.ico`` the Part A brand board
    # shipped. PyInstaller embeds it as the Windows
    # executable's icon resource.
    icon=str(REPO_ROOT / "frontend" / "public" / "favicon.ico"),
)

coll = COLLECT(  # type: ignore[name-defined]  # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Lockverity",
)
