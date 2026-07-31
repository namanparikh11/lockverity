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
    # ``sys._MEIPASS/alembic/alembic.ini`` and
    # ``sys._MEIPASS/alembic/versions``.
    #
    # ``alembic.ini`` is bundled at
    # ``<frozen_root>/alembic/alembic.ini`` because
    # PyInstaller's ``datas`` processing conflicts
    # between a directory entry and a file entry
    # whose name shares a prefix (``alembic`` and
    # ``alembic.ini``); bundling the file inside the
    # directory removes the prefix collision and the
    # runtime resolver reflects the layout.
    # The Alembic config is **not** bundled through
    # the ``datas`` tuple. PyInstaller's COLLECT
    # nests the file's dest inside a same-named
    # directory entry (a documented
    # ``alembic.ini/alembic.ini`` quirk when
    # ``alembic/`` is a sibling directory entry);
    # the build script copies the file to the
    # right place after PyInstaller has run.
    (str(BACKEND_ROOT / "alembic"), "alembic"),
    # The approved application icon (16/32/48 ICO).
    # The launcher exposes it under the bundle root
    # at launch so the web UI can serve the brand
    # favicon unchanged.
    (str(REPO_ROOT / "frontend" / "public" / "favicon.ico"), "favicon.ico"),
    # The packaging-derivative ICO (16/32/48/256)
    # is bundled alongside the approved ICO for
    # future Windows shell integrations. It is a
    # Lanczos downscale of the approved 1024x1024
    # source PNG; the original brand assets are not
    # modified. The PyInstaller ``icon=`` argument
    # below uses this derivative so the executable
    # resource has a 256x256 entry the Windows shell
    # can render at high DPI.
    (str(BACKEND_ROOT / "pyinstaller" / "favicon-exe.ico"), "favicon-exe.ico"),
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
    # ``alembic.config`` uses ``logging.config.fileConfig``
    # at module import time; the static scan only sees
    # the ``logging`` package import, not the
    # ``logging.config`` submodule, so we add it
    # explicitly. The in-process migration path uses
    # ``alembic.command.upgrade`` which also pulls in
    # the same module transitively.
    "logging.config",
    # The application configures the rotating file
    # handler in ``app.cli.logging_setup``; the
    # standard ``logging`` package is scanned, but
    # ``logging.handlers`` (which contains the
    # ``RotatingFileHandler`` and ``BaseRotatingHandler``
    # we use) is loaded via a string lookup at runtime.
    "logging.handlers",
    # ``alembic/env.py`` imports ``app.models`` to
    # bind ``Base.metadata``; the static scan only
    # follows the entry-point import graph
    # (``app.cli.main``), so the migration-time
    # import of ``app.models`` is not seen. The
    # hidden import ensures the metadata table is
    # registered before the migration runs.
    "app.models",
    # ``app.models`` re-exports the SQLAlchemy
    # ``Base`` and a number of domain tables; the
    # static scan follows the re-export but misses
    # the dynamic ``__getattr__`` style imports
    # some Alembic revisions use. ``app.db.base`` is
    # also referenced by ``alembic/env.py``; the
    # hidden import here documents both.
    "app.db.base",
    # The launcher's child-serve dispatch
    # (``--internal-serve``) imports ``app.cli._serve``
    # which runs Uvicorn against ``app.main:app``;
    # Uvicorn loads the ASGI module at runtime and
    # the static scan only sees the entry-point
    # import graph. The hidden import ensures the
    # FastAPI factory and its dependency graph are
    # bundled so the frozen server can serve HTTP.
    "app.main",
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
    # executable's icon resource. The derivative
    # ``favicon-exe.ico`` (16/32/48/256) is the
    # icon resource actually used here so the
    # Windows shell can render the executable at
    # high DPI; the approved web favicon (16/32/48)
    # is bundled at the frozen root for the
    # single-port UI to serve. The conversion is a
    # documented mechanical Lanczos downscale of
    # the approved 1024x1024 source PNG; see
    # ``scripts/generate_exe_icon.py`` and
    # ``tests/test_exe_icon.py``.
    icon=str(BACKEND_ROOT / "pyinstaller" / "favicon-exe.ico"),
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
